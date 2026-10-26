from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "source-parts"
DOMAINS = ROOT / "domains"
EXTENSION = ROOT / "extension"

FUNCTION_BLOCK = re.compile(
    r"^//@@FN_START:([A-Za-z_$][\w$]*)\n(.*?)\n//@@FN_END:\1\n",
    re.S | re.M,
)
IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_$])([A-Za-z_$][\w$]*)(?![A-Za-z0-9_$])")
TOP_LEVEL_DECLARATION = re.compile(
    r"^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\b", re.M
)
FUNCTION_MARKER = re.compile(r"/\*@@MONITOR_FUNCTION:[A-Za-z_$][\w$]*@@\*/")


def load_sources():
    part_manifest = json.loads((PARTS / "manifest.json").read_text(encoding="utf-8"))
    domain_manifest = json.loads((DOMAINS / "manifest.json").read_text(encoding="utf-8"))

    functions: dict[str, str] = {}
    owners: dict[str, str] = {}
    domain_text: dict[str, str] = {}
    for entry in domain_manifest["domains"]:
        domain = entry["domain"]
        text = (DOMAINS / entry["file"]).read_text(encoding="utf-8")
        domain_text[domain] = text
        for match in FUNCTION_BLOCK.finditer(text):
            name = match.group(1)
            functions[name] = match.group(2)
            owners[name] = domain

    globals_by_name: dict[str, str] = {}
    part_text: dict[str, str] = {}
    for part in part_manifest["parts"]:
        text = (PARTS / part).read_text(encoding="utf-8")
        part_text[part] = text
        for match in TOP_LEVEL_DECLARATION.finditer(text):
            globals_by_name.setdefault(match.group(1), part)

    return functions, owners, globals_by_name, domain_text, part_text


def token_set(text: str) -> set[str]:
    # This is intentionally conservative. It finds identifier coupling without
    # pretending to be a JavaScript parser; candidates still require source review.
    return set(IDENTIFIER.findall(text))


def render_report() -> str:
    functions, owners, globals_by_name, domain_text, part_text = load_sources()
    runtime = (EXTENSION / "monitor.js").read_text(encoding="utf-8")
    function_names = set(functions)
    global_names = set(globals_by_name)

    definition_only = []
    reference_counts = {}
    for name in sorted(function_names):
        count = len(re.findall(rf"(?<![A-Za-z0-9_$]){re.escape(name)}(?![A-Za-z0-9_$])", runtime))
        reference_counts[name] = count
        if count == 1:
            definition_only.append(name)

    definition_only_globals = []
    for name in sorted(global_names):
        count = len(re.findall(rf"(?<![A-Za-z0-9_$]){re.escape(name)}(?![A-Za-z0-9_$])", runtime))
        if count == 1:
            definition_only_globals.append(name)

    cross_edges: Counter[tuple[str, str]] = Counter()
    incoming_functions: defaultdict[str, set[str]] = defaultdict(set)
    outgoing_functions: defaultdict[str, set[str]] = defaultdict(set)
    globals_used: defaultdict[str, set[str]] = defaultdict(set)
    for function_name, body in functions.items():
        source_domain = owners[function_name]
        tokens = token_set(body)
        for target in tokens & function_names:
            if target == function_name:
                continue
            target_domain = owners[target]
            if target_domain != source_domain:
                cross_edges[(source_domain, target_domain)] += 1
                outgoing_functions[source_domain].add(target)
                incoming_functions[target_domain].add(function_name)
        globals_used[source_domain].update(tokens & global_names)

    boundary_patterns = {
        "native_control": r"\bmonitorNative\b",
        "native_capture": r"\bmonitorCoreNative\b",
        "act_transport": r"\bactFetch\b",
        "chrome_api": r"\bchrome\.",
        "local_storage": r"\blocalStorage\b",
        "session_storage": r"\bsessionStorage\b",
        "dom_access": r"\b(?:document|window)\.",
    }
    boundary_counts: dict[str, dict[str, int]] = {}
    for domain, text in domain_text.items():
        boundary_counts[domain] = {
            key: len(re.findall(pattern, text)) for key, pattern in boundary_patterns.items()
        }

    scripts = re.findall(
        r"<script\s+[^>]*src=[\"']([^\"']+)[\"']", (EXTENSION / "desktop.html").read_text(encoding="utf-8")
    )
    roots_text = "\n".join(FUNCTION_MARKER.sub("", text) for text in part_text.values())
    for script in scripts:
        path = EXTENSION / script
        if script != "monitor.js" and path.is_file():
            roots_text += "\n" + path.read_text(encoding="utf-8")
    roots = token_set(roots_text) & function_names
    call_graph = {
        name: (token_set(body) & function_names) - {name}
        for name, body in functions.items()
    }
    reachable = set(roots)
    pending = list(roots)
    while pending:
        source = pending.pop()
        for target in call_graph[source] - reachable:
            reachable.add(target)
            pending.append(target)
    unreachable = sorted(function_names - reachable)

    lines = [
        "# Monitor dependency audit",
        "",
        "Generated by `tools/analyze_monitor_dependencies.py`. This is a conservative identifier-level map, not proof that a function is safe to delete.",
        "",
        "## Inventory",
        "",
        f"- Generated `monitor.js`: {len(runtime.splitlines()):,} lines, {len(runtime):,} characters",
        f"- Owned functions: {len(functions):,}",
        f"- Top-level declarations in ordered source parts: {len(globals_by_name):,}",
        f"- Loaded scripts: {len(scripts):,}",
        f"- Definition-only function candidates: {len(definition_only):,}",
        f"- Definition-only global candidates: {len(definition_only_globals):,}",
        f"- Conservative unreachable function candidates: {len(unreachable):,}",
        "",
        "## Domain coupling",
        "",
        "| Domain | Functions | Shared globals read | Cross-domain callees | Cross-domain callers | Native control | Native capture | ACT | Chrome | DOM |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    function_counts = Counter(owners.values())
    for domain in sorted(domain_text):
        counts = boundary_counts[domain]
        lines.append(
            "| " + " | ".join([
                domain,
                str(function_counts[domain]),
                str(len(globals_used[domain])),
                str(len(outgoing_functions[domain])),
                str(len(incoming_functions[domain])),
                str(counts["native_control"]),
                str(counts["native_capture"]),
                str(counts["act_transport"]),
                str(counts["chrome_api"]),
                str(counts["dom_access"]),
            ]) + " |"
        )

    lines += ["", "## Cross-domain references", "", "| From | To | Identifier references |", "| --- | --- | ---: |"]
    for (source, target), count in sorted(cross_edges.items()):
        lines.append(f"| {source} | {target} | {count} |")

    lines += [
        "",
        "## Definition-only candidates",
        "",
        "These names occur only at their declaration in the generated runtime. Check dynamic entry points and focused tests before removal.",
        "",
    ]
    for name in definition_only:
        lines.append(f"- `{name}` ({owners[name]})")

    lines += [
        "",
        "## Definition-only global candidates",
        "",
    ]
    for name in definition_only_globals:
        lines.append(f"- `{name}` (`{globals_by_name[name]}`)")

    lines += [
        "",
        "## Conservative unreachable function candidates",
        "",
        "Roots include ordered bootstrap statements and every separately loaded script. Identifier references in comments and strings are intentionally retained, so this list favors keeping code over deleting it.",
        "",
    ]
    for name in unreachable:
        lines.append(f"- `{name}` ({owners[name]})")

    lines += ["", "## Loaded script order", ""]
    for index, script in enumerate(scripts, 1):
        lines.append(f"{index}. `{script}`")

    lines += ["", "## Ordered source-part global ownership", ""]
    globals_by_part: defaultdict[str, list[str]] = defaultdict(list)
    for name, part in globals_by_name.items():
        globals_by_part[part].append(name)
    for part in part_text:
        names = sorted(globals_by_part[part])
        lines.append(f"### `{part}` ({len(names)} declarations)")
        lines.append("")
        lines.append(", ".join(f"`{name}`" for name in names) if names else "None.")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = render_report()
    target = ROOT / "MONITOR_DEPENDENCY_AUDIT.md"
    if args.check:
        if not target.is_file() or target.read_text(encoding="utf-8") != report:
            raise SystemExit("MONITOR_DEPENDENCY_AUDIT_OUT_OF_DATE")
        print("MONITOR_DEPENDENCY_AUDIT_PASS")
        return
    if args.write:
        target.write_text(report, encoding="utf-8", newline="")
        print(f"MONITOR_DEPENDENCY_AUDIT_WRITTEN {target}")
        return
    print(report, end="")


if __name__ == "__main__":
    main()
