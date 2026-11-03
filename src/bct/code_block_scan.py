from __future__ import annotations

import ast
import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "bct.code-block-scan.v1"
DEFAULT_EXCLUDES = frozenset({
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", ".venv",
    "venv", "__pycache__", ".pytest_cache", ".mypy_cache", "dist", "build",
    "coverage", ".coverage", "vendor",
})
LANGUAGES = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript",
    ".cjs": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".ps1": "powershell", ".cs": "csharp",
    ".java": "java", ".go": "go", ".rs": "rust", ".c": "c",
    ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".rb": "ruby",
    ".php": "php", ".sh": "shell",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inside(path: Path, roots: Iterable[Path]) -> bool:
    target = os.path.normcase(str(path.resolve()))
    for root in roots:
        base = os.path.normcase(str(root.resolve()))
        try:
            if os.path.commonpath((target, base)) == base:
                return True
        except ValueError:
            continue
    return False


def resolve_scan_root(work: Any, requested_root: str = "") -> Path:
    if "read" not in set(work.actions):
        raise PermissionError("CODE_BLOCK_SCAN_READ_REQUIRED")
    roots = tuple(Path(value).resolve() for value in work.roots)
    if not roots:
        raise ValueError("CODE_BLOCK_SCAN_WORK_ROOT_REQUIRED")
    root = Path(requested_root).resolve() if requested_root.strip() else roots[0]
    if not _inside(root, roots):
        raise PermissionError("CODE_BLOCK_SCAN_ROOT_OUTSIDE_WORK")
    if not root.is_dir():
        raise ValueError("CODE_BLOCK_SCAN_ROOT_NOT_DIRECTORY")
    return root


@dataclass(frozen=True)
class SourceFile:
    path: Path
    relative: str
    language: str
    data: bytes
    text: str
    sha256: str


class CodeBlockParseError(ValueError):
    """Exact source-analysis failure that must not look like a complete scan."""

    def __init__(self, source: SourceFile, error: SyntaxError):
        self.issue = {
            "path": source.relative,
            "language": source.language,
            "code": "PYTHON_SYNTAX_ERROR",
            "line": int(error.lineno or 0),
            "offset": int(error.offset or 0),
            "message": str(error.msg or "invalid syntax")[:240],
        }
        super().__init__(
            "CODE_BLOCK_PYTHON_SYNTAX_ERROR:"
            f"{source.relative}:{self.issue['line']}:{self.issue['offset']}"
        )


def _source_files(root: Path, *, max_files: int, max_bytes_per_file: int) -> tuple[list[SourceFile], dict[str, Any]]:
    files: list[SourceFile] = []
    skipped_large = 0
    skipped_unreadable = 0
    truncated = False
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in DEFAULT_EXCLUDES)
        for name in sorted(names):
            path = Path(current, name)
            language = LANGUAGES.get(path.suffix.lower())
            if not language or path.is_symlink():
                continue
            if len(files) >= max_files:
                truncated = True
                break
            try:
                size = path.stat().st_size
                if size > max_bytes_per_file:
                    skipped_large += 1
                    continue
                data = path.read_bytes()
                text = data.decode("utf-8", errors="replace")
            except OSError:
                skipped_unreadable += 1
                continue
            files.append(SourceFile(
                path=path,
                relative=path.relative_to(root).as_posix(),
                language=language,
                data=data,
                text=text,
                sha256=_sha256(data),
            ))
        if truncated:
            break
    return files, {
        "complete": not truncated and skipped_large == 0 and skipped_unreadable == 0,
        "truncated": truncated,
        "skipped_large": skipped_large,
        "skipped_unreadable": skipped_unreadable,
    }


def _normalized_body(lines: list[str], start: int, end: int) -> str:
    body = "\n".join(lines[max(0, start - 1):max(start, end)])
    body = re.sub(r"(?m)^\s*(?://|#).*?$", "", body)
    body = re.sub(r"\s+", " ", body).strip()
    return body


def _exact_body(text: str, start: int, end: int) -> str:
    """Return the exact decoded source slice for one 1-based line range."""
    lines = text.splitlines(keepends=True)
    return "".join(lines[max(0, start - 1):max(start, end)])


def _effect_hints(body: str) -> list[str]:
    checks = (
        (r"\b(?:write|unlink|remove|delete|rename|replace|mkdir|rmdir)\b", "filesystem_write"),
        (r"\b(?:fetch|requests\.|httpx\.|urllib|axios|WebSocket)\b", "network"),
        (r"\b(?:subprocess|Popen|spawn|exec\(|system\()", "process"),
        (r"\b(?:INSERT|UPDATE|DELETE|CREATE TABLE|commit\()\b", "database_write"),
        (r"\b(?:chrome\.|browser\.)", "browser_api"),
    )
    return [label for pattern, label in checks if re.search(pattern, body, re.I)]


def _branch_count(body: str) -> int:
    return len(re.findall(r"\b(?:if|elif|else if|for|while|case|catch|except|match)\b|&&|\|\|", body))


def _python_blocks(source: SourceFile) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        tree = ast.parse(source.text)
    except SyntaxError as exc:
        raise CodeBlockParseError(source, exc) from exc
    lines = source.text.splitlines()
    blocks: list[dict[str, Any]] = []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif node.module:
                imports.append(node.module)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        decorators = getattr(node, "decorator_list", ())
        start = min(
            [int(node.lineno), *(int(item.lineno) for item in decorators)],
        )
        end = int(getattr(node, "end_lineno", node.lineno))
        body = _normalized_body(lines, start, end)
        params = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = [arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)]
            if node.args.vararg:
                params.append("*" + node.args.vararg.arg)
            if node.args.kwarg:
                params.append("**" + node.args.kwarg.arg)
        blocks.append({
            "name": node.name,
            "kind": "class" if isinstance(node, ast.ClassDef) else "function",
            "line_start": start, "line_end": end, "parameters": params,
            "normalized": body,
        })
    return blocks, sorted(set(imports))


def _cards_for_source(source: SourceFile, *, max_blocks: int) -> tuple[list[dict[str, Any]], bool]:
    blocks, _ = _python_blocks(source) if source.language == "python" else _generic_blocks(source)
    cards: list[dict[str, Any]] = []
    truncated = False
    for block in blocks:
        if len(cards) >= max_blocks:
            truncated = True
            break
        normalized = block.pop("normalized")
        lines = max(1, int(block["line_end"]) - int(block["line_start"]) + 1)
        exact = _exact_body(source.text, int(block["line_start"]), int(block["line_end"]))
        card = {
            "block_id": _sha256(
                f"{source.relative}:{block['line_start']}:{block['name']}".encode()
            )[:16],
            "path": source.relative,
            "language": source.language,
            **block,
            "metrics": {"lines": lines, "branches": _branch_count(normalized)},
            "inputs": block.get("parameters", []),
            "outputs": "STATIC_SCAN_UNKNOWN",
            "side_effect_hints": _effect_hints(normalized),
            "failure_conditions": ["STATIC_SCAN_NOT_RUNTIME_PROOF"],
            # body_sha256 remains the similarity hash used for duplicate detection.
            "body_sha256": _sha256(normalized.encode()) if normalized else "",
            # Exact hashes are the fail-closed boundary for partial replacement.
            "source_sha256": _sha256(exact.encode("utf-8")),
            "file_sha256": source.sha256,
        }
        card["candidate_kind"] = _candidate_kind(card)
        cards.append(card)
    return cards, truncated


def inspect_file(root: Path, relative_path: str, *, max_bytes: int = 5_000_000,
                 max_blocks: int = 10_000) -> dict[str, Any]:
    """Build the exact block index for one regular UTF-8 source file."""
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("CODE_BLOCK_PATH_INVALID")
    root = root.resolve()
    candidate = root / relative
    current = candidate
    while True:
        if current.exists() or current.is_symlink():
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise ValueError("CODE_BLOCK_REPARSE_PATH_FORBIDDEN")
        if current == root:
            break
        current = current.parent
    path = candidate.resolve()
    if not _inside(path, (root,)):
        raise ValueError("CODE_BLOCK_PATH_OUTSIDE_ROOT")
    language = LANGUAGES.get(path.suffix.lower())
    if not language:
        raise ValueError("CODE_BLOCK_LANGUAGE_UNSUPPORTED")
    if not path.is_file() or path.is_symlink():
        raise ValueError("CODE_BLOCK_SOURCE_NOT_REGULAR")
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise ValueError("CODE_BLOCK_SOURCE_TOO_LARGE")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("CODE_BLOCK_SOURCE_NOT_UTF8") from exc
    source = SourceFile(
        path=path,
        relative=path.relative_to(root).as_posix(),
        language=language,
        data=data,
        text=text,
        sha256=_sha256(data),
    )
    cards, truncated = _cards_for_source(source, max_blocks=max_blocks)
    if truncated:
        raise ValueError("CODE_BLOCK_INDEX_TRUNCATED")
    return {
        "path": source.relative,
        "language": source.language,
        "file_sha256": source.sha256,
        "bytes": len(source.data),
        "text": source.text,
        "blocks": cards,
    }


_DECLARATION = re.compile(
    r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"
    r"|^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>"
)


def _brace_end(lines: list[str], start_index: int) -> int:
    depth = 0
    opened = False
    for index in range(start_index, min(len(lines), start_index + 1200)):
        line = re.sub(r"(['\"]).*?\1", "", lines[index])
        for char in line:
            if char == "{":
                depth += 1
                opened = True
            elif char == "}" and opened:
                depth -= 1
                if depth <= 0:
                    return index + 1
    return min(len(lines), start_index + 1)


def _generic_blocks(source: SourceFile) -> tuple[list[dict[str, Any]], list[str]]:
    lines = source.text.splitlines()
    blocks: list[dict[str, Any]] = []
    for match in _DECLARATION.finditer(source.text):
        name = match.group(1) or match.group(3) or match.group(4) or "anonymous"
        params = match.group(2) or match.group(5) or ""
        start = source.text.count("\n", 0, match.start()) + 1
        end = _brace_end(lines, start - 1)
        blocks.append({
            "name": name,
            "kind": "class" if match.group(3) else "function",
            "line_start": start, "line_end": end,
            "parameters": [item.strip() for item in params.split(",") if item.strip()],
            "normalized": _normalized_body(lines, start, end),
        })
    imports = []
    for pattern in (r"\bfrom\s+['\"]([^'\"]+)['\"]", r"\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)", r"(?m)^\s*using\s+([\w.]+)"):
        imports.extend(re.findall(pattern, source.text))
    return blocks, sorted(set(imports))


def _candidate_kind(card: dict[str, Any]) -> str:
    lines = int(card["metrics"]["lines"])
    effects = len(card["side_effect_hints"])
    branches = int(card["metrics"]["branches"])
    if lines <= 24 and effects == 0:
        return "primitive"
    if lines <= 90 and branches <= 12:
        return "module"
    if lines <= 220:
        return "partial_recipe"
    return "full_recipe"


def scan(root: Path, *, max_files: int = 1000, max_bytes_per_file: int = 1_000_000,
         max_blocks: int = 4000) -> dict[str, Any]:
    max_files = max(1, min(int(max_files), 5000))
    max_bytes_per_file = max(4096, min(int(max_bytes_per_file), 5_000_000))
    max_blocks = max(1, min(int(max_blocks), 10000))
    files, limits = _source_files(root, max_files=max_files, max_bytes_per_file=max_bytes_per_file)
    cards: list[dict[str, Any]] = []
    file_rows: list[dict[str, Any]] = []
    dependencies: list[dict[str, str]] = []
    path_set = {source.relative for source in files}
    stem_index = {Path(path).stem: path for path in path_set}
    block_truncated = False
    parse_errors: list[dict[str, Any]] = []
    for source in files:
        parse_error = None
        try:
            blocks, imports = (
                _python_blocks(source)
                if source.language == "python"
                else _generic_blocks(source)
            )
            remaining = max_blocks - len(cards)
            source_cards, source_truncated = _cards_for_source(
                source, max_blocks=max(0, remaining),
            )
        except CodeBlockParseError as exc:
            # A project scan may continue so it can report every affected file,
            # but it must become PARTIAL and expose the exact parse failures.
            parse_error = exc.issue
            parse_errors.append(parse_error)
            blocks, imports, source_cards, source_truncated = [], [], [], False
        for imported in imports:
            target = stem_index.get(Path(imported.replace(".", "/")).name)
            dependencies.append({"from": source.relative, "to": target or imported, "resolved": str(bool(target)).lower()})
        file_rows.append({
            "path": source.relative, "language": source.language,
            "sha256": source.sha256, "bytes": len(source.data),
            "lines": source.text.count("\n") + (1 if source.text else 0),
            "imports": imports[:80],
            "analysis_status": "PARSE_ERROR" if parse_error else "OK",
        })
        cards.extend(source_cards)
        if source_truncated:
            block_truncated = True
        if block_truncated:
            break
    duplicate_groups: list[dict[str, Any]] = []
    by_body: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        if card["metrics"]["lines"] >= 4 and card["body_sha256"]:
            by_body.setdefault(card["body_sha256"], []).append(card)
    for digest, group in by_body.items():
        if len(group) > 1:
            duplicate_groups.append({
                "body_sha256": digest,
                "blocks": [{"block_id": item["block_id"], "path": item["path"], "name": item["name"]} for item in group],
            })
    refactor_targets: list[dict[str, Any]] = [
        {"priority": "high", "reason": "python_syntax_error", "evidence": issue}
        for issue in parse_errors
    ]
    for group in duplicate_groups:
        refactor_targets.append({"priority": "high", "reason": "exact_duplicate_block", "evidence": group})
    for card in cards:
        if card["metrics"]["lines"] >= 180 or card["metrics"]["branches"] >= 24:
            refactor_targets.append({
                "priority": "high" if card["metrics"]["lines"] >= 320 else "medium",
                "reason": "large_or_branch_dense_block",
                "evidence": {"block_id": card["block_id"], "path": card["path"], "name": card["name"], "metrics": card["metrics"]},
            })
    candidates = [{
        "block_id": card["block_id"], "kind": card["candidate_kind"],
        "path": card["path"], "name": card["name"],
        "reusability": "high" if not card["side_effect_hints"] and card["metrics"]["lines"] <= 90 else "review",
    } for card in cards]
    catalog = [item for item in candidates if item["reusability"] == "high"][:300]
    ordered = sorted(refactor_targets, key=lambda item: ({"high": 0, "medium": 1, "low": 2}.get(item["priority"], 3), item["reason"]))
    scan_fingerprint = _sha256("\n".join(f"{item['path']}\0{item['sha256']}" for item in file_rows).encode())
    complete = limits["complete"] and not block_truncated and not parse_errors
    warnings = ["STATIC_ANALYSIS_CANDIDATES_REQUIRE_HUMAN_OR_TEST_VALIDATION"]
    if parse_errors:
        warnings.append("PYTHON_PARSE_ERRORS_PRESENT")
    return {
        "schema": SCHEMA,
        "status": "OK" if complete else "PARTIAL",
        "read_only": True,
        "root": str(root),
        "scan": {
            "files": len(file_rows), "blocks": len(cards), "scan_fingerprint": scan_fingerprint,
            "complete": complete,
            "limits": {**limits, "block_truncated": block_truncated, "max_files": max_files,
                       "max_bytes_per_file": max_bytes_per_file, "max_blocks": max_blocks},
            "parse_errors": parse_errors,
            "incremental_index": [{"path": item["path"], "sha256": item["sha256"]} for item in file_rows],
        },
        "block_map": {"files": file_rows, "dependency_edges": dependencies},
        "block_candidates": candidates,
        "refactor_targets": ordered,
        "block_cards": cards,
        "block_index": [{
            "block_id": card["block_id"], "path": card["path"],
            "name": card["name"], "kind": card["kind"],
            "line_start": card["line_start"], "line_end": card["line_end"],
            "file_sha256": card["file_sha256"],
            "source_sha256": card["source_sha256"],
        } for card in cards],
        "component_catalog_candidates": catalog,
        "work_order": ordered[:100],
        "warnings": warnings,
    }
