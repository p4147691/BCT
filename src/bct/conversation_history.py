"""On-demand BCT conversation evidence cache, using the existing Project Memory IO contracts.

Only an explicitly selected BCT Work and ChatGPT conversation may be captured.
This does not navigate ChatGPT, send messages, fetch private APIs or judge Work completion.
The browser reader supplies whatever is actually loaded; missing turns stay UNKNOWN.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit

from bct.core.project_memory import (
    ProjectMemoryCorrupt, ProjectMemoryError, _assert_no_redirect,
    _atomic_replace, _canonical, _digest, _parse_json,
    _publish_revision, _writer_lock,
)

SNAPSHOT_SCHEMA = "BCT_CONVERSATION_SNAPSHOT_V1"
POINTER_SCHEMA = "BCT_CONVERSATION_POINTER_V1"
COVERAGE = "LOADED_PAGE_ONLY"
MAX_CAPTURE_BYTES = 256 * 1024
MAX_SUMMARY_CHARS = 4000
MAX_HISTORY_REVISIONS = 512
_WORK_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_CONVERSATION_PATH = re.compile(
    r"/(?:g/[A-Za-z0-9_-]+/)?c/([a-f0-9]{8}-[a-f0-9]{4}-"
    r"[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})/?\Z", re.I
)


class ConversationEvidenceError(ProjectMemoryError):
    """Incomplete or invalid evidence; never infer that history was fully read."""


def normalize_conversation_url(value: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ConversationEvidenceError("CONVERSATION_URL_REQUIRED")
    try:
        uri = urlsplit(value)
    except ValueError as exc:
        raise ConversationEvidenceError("CONVERSATION_URL_INVALID") from exc
    if (uri.scheme != "https" or uri.hostname not in
            {"chatgpt.com", "chat.openai.com"} or uri.username or uri.password
            or uri.port is not None):
        raise ConversationEvidenceError("CONVERSATION_URL_INVALID")
    match = _CONVERSATION_PATH.fullmatch(uri.path)
    if not match:
        raise ConversationEvidenceError("CONVERSATION_ID_MISSING")
    conversation_id = match.group(1).lower()
    return conversation_id, "https://chatgpt.com/c/" + conversation_id


def _work_id(value: str) -> str:
    if not isinstance(value, str) or not _WORK_ID.fullmatch(value):
        raise ConversationEvidenceError("CONVERSATION_WORK_ID_INVALID")
    return value


def browser_context_text(payload: Any) -> str:
    """Unwrap the documented Browser.get_tab_context text container only.

    This is deliberately not a generic HTML scraper. Content may include
    navigation, collapsed turns and loading indicators. It is partial evidence.
    """
    current = payload
    for _ in range(3):
        if isinstance(current, dict):
            if type(current.get("text")) is not str:
                break
            current = current["text"]
            continue
        if isinstance(current, str):
            stripped = current.strip()
            if stripped.startswith("{"):
                try:
                    item = json.loads(stripped)
                except (ValueError, UnicodeError):
                    break
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    current = item["text"]
                    continue
        break
    if not isinstance(current, str):
        raise ConversationEvidenceError("CONVERSATION_BROWSER_TEXT_UNAVAILABLE")
    return current


def _validate_text(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ConversationEvidenceError("CONVERSATION_TEXT_INVALID")
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    # Browser page identity can race with SPA navigation. A newly opened
    # ChatGPT composer must not be archived as an existing conversation.
    home = ("무엇을 도와드릴까요?", "무엇을 도와드릴까요",
            "What can I help with?", "What can I help you with?")
    turns = ("내가 한 말:", "ChatGPT 답변:", "You said:", "ChatGPT said:")
    if any(marker in text for marker in home) and not any(
            marker in text for marker in turns):
        raise ConversationEvidenceError("CONVERSATION_PAGE_NOT_LOADED")
    if len(text.encode("utf-8")) > MAX_CAPTURE_BYTES:
        raise ConversationEvidenceError("CONVERSATION_CAPTURE_OVERSIZE")
    return text


class ConversationEvidenceCache:
    """Append-only immutable snapshots, scoped to a BCT Work + conversation.

    Reuses Project Memory's already-tested atomic file and locking primitives.
    No SQLite changes, new service, extra AI calls or recurrent polling.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).absolute()
        _assert_no_redirect(self.root)

    def _folder(self, work_id: str, conversation_url: str, *, create: bool
                ) -> tuple[Path, str, str]:
        work = _work_id(work_id)
        conversation, normalized_url = normalize_conversation_url(conversation_url)
        scope = hashlib.sha256(work.encode("utf-8")).hexdigest()
        folder = self.root / scope / conversation
        _assert_no_redirect(folder)
        if create:
            folder.mkdir(parents=True, exist_ok=True)
            _assert_no_redirect(folder)
        if folder.exists() and not folder.is_dir():
            raise ConversationEvidenceError("CONVERSATION_PATH_INVALID")
        return folder, conversation, normalized_url

    def _latest_at(self, folder: Path, work_id: str,
                   conversation_id: str) -> dict[str, Any] | None:
        pointer_file = folder / "current.json"
        _assert_no_redirect(pointer_file)
        if not pointer_file.exists():
            return None
        pointer = _parse_json(pointer_file.read_bytes())
        revision = pointer.get("revision")
        digest = pointer.get("sha256")
        if (set(pointer) != {"schema", "revision", "sha256", "revision_file"}
                or pointer["schema"] != POINTER_SCHEMA
                or type(revision) is not int or revision <= 0
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or pointer["revision_file"] != f"{revision:08d}-{digest}.json"):
            raise ProjectMemoryCorrupt("CONVERSATION_POINTER_INVALID")
        return self._read_revision(folder, revision, digest, work_id, conversation_id)

    @staticmethod
    def _read_revision(folder: Path, revision: int, digest: str,
                       work_id: str, conversation_id: str) -> dict[str, Any]:
        file = folder / "snapshots" / f"{revision:08d}-{digest}.json"
        _assert_no_redirect(file)
        if not file.is_file():
            raise ProjectMemoryCorrupt("CONVERSATION_REVISION_MISSING")
        raw = file.read_bytes()
        if _digest(raw) != digest:
            raise ProjectMemoryCorrupt("CONVERSATION_REVISION_HASH_MISMATCH")
        row = _parse_json(raw)
        if (row.get("schema") != SNAPSHOT_SCHEMA
                or row.get("revision") != revision
                or row.get("work_id") != work_id
                or row.get("conversation_id") != conversation_id
                or row.get("coverage") != COVERAGE
                or row.get("source") != "BROWSER_TAB_CONTEXT"
                or row.get("text_sha256") != hashlib.sha256(
                    _validate_text(row.get("page_text")).encode("utf-8")
                ).hexdigest()):
            raise ProjectMemoryCorrupt("CONVERSATION_REVISION_CONTENT_INVALID")
        return {**row, "sha256": digest}

    def latest(self, *, work_id: str, conversation_url: str
               ) -> dict[str, Any] | None:
        folder, cid, _ = self._folder(work_id, conversation_url, create=False)
        return self._latest_at(folder, work_id, cid) if folder.is_dir() else None

    def capture(self, *, work_id: str, conversation_url: str, title: str,
                page_text: str, summary: str | None = None,
                tab_id: str | None = None, now: datetime | None = None
                ) -> dict[str, Any]:
        work = _work_id(work_id)
        cid, normalized_url = normalize_conversation_url(conversation_url)
        page_text = _validate_text(page_text)
        if not isinstance(title, str) or not title.strip() or len(title) > 256:
            raise ConversationEvidenceError("CONVERSATION_TITLE_INVALID")
        if (summary is not None and (
                not isinstance(summary, str) or len(summary) > MAX_SUMMARY_CHARS)):
            raise ConversationEvidenceError("CONVERSATION_SUMMARY_INVALID")
        if tab_id is not None and (not isinstance(tab_id, str)
                                    or not re.fullmatch(r"[0-9]{1,20}", tab_id)):
            raise ConversationEvidenceError("CONVERSATION_TAB_ID_INVALID")
        when = now or datetime.now(timezone.utc)
        if when.tzinfo is None:
            raise ConversationEvidenceError("CONVERSATION_CAPTURE_TIME_INVALID")
        observed = when.astimezone(timezone.utc).isoformat(timespec="milliseconds")
        text_sha = hashlib.sha256(page_text.encode("utf-8")).hexdigest()

        folder, _, _ = self._folder(work, normalized_url, create=True)
        lock = folder / ".capture.lock"
        _assert_no_redirect(lock)
        with _writer_lock(lock):
            current = self._latest_at(folder, work, cid)
            if (current and current["text_sha256"] == text_sha
                    and (summary is None or current.get("summary") == summary)
                    and current["title"] == title):
                return {**self._public(current), "duplicate": True}
            rev = (current["revision"] if current else 0) + 1
            row = {
                "schema": SNAPSHOT_SCHEMA,
                "revision": rev,
                "previous_sha256": current["sha256"] if current else None,
                "work_id": work,
                "conversation_id": cid,
                "conversation_url": normalized_url,
                "title": title,
                "observed_at": observed,
                "source": "BROWSER_TAB_CONTEXT",
                "coverage": COVERAGE,
                "full_history_verified": False,
                "source_tab_id": tab_id,
                "text_sha256": text_sha,
                "page_text": page_text,
                "summary": summary,
                "summary_status": "AI_CURATED" if summary else "NOT_SUMMARIZED",
            }
            encoded = _canonical(row)
            digest = _digest(encoded)
            revisions = folder / "snapshots"
            _assert_no_redirect(revisions)
            revisions.mkdir(exist_ok=True)
            _assert_no_redirect(revisions)
            target = revisions / f"{rev:08d}-{digest}.json"
            _publish_revision(target, encoded)
            _atomic_replace(folder / "current.json", _canonical({
                "schema": POINTER_SCHEMA, "revision": rev,
                "sha256": digest, "revision_file": target.name,
            }))
        return {**self._public({**row, "sha256": digest}), "duplicate": False}

    @staticmethod
    def _public(row: dict[str, Any], *, tail: int = 0) -> dict[str, Any]:
        keys = ("revision", "sha256", "previous_sha256", "work_id",
                "conversation_id", "conversation_url", "title", "observed_at",
                "source", "coverage", "full_history_verified", "source_tab_id",
                "text_sha256", "summary", "summary_status")
        result = {k: row.get(k) for k in keys}
        if tail:
            result["loaded_text_tail"] = row["page_text"][-tail:]
        return result

    def history(self, *, work_id: str, conversation_url: str,
                max_revisions: int = MAX_HISTORY_REVISIONS
                ) -> list[dict[str, Any]]:
        if type(max_revisions) is not int or not 1 <= max_revisions <= MAX_HISTORY_REVISIONS:
            raise ConversationEvidenceError("CONVERSATION_HISTORY_LIMIT_INVALID")
        folder, cid, _ = self._folder(work_id, conversation_url, create=False)
        latest = self._latest_at(folder, work_id, cid) if folder.is_dir() else None
        if latest is None:
            return []
        results = []
        row = latest
        for _ in range(max_revisions):
            results.append(row)
            previous = row["previous_sha256"]
            if row["revision"] == 1:
                if previous is not None:
                    raise ProjectMemoryCorrupt("CONVERSATION_BAD_GENESIS")
                break
            if not isinstance(previous, str) or not re.fullmatch(r"[0-9a-f]{64}", previous):
                raise ProjectMemoryCorrupt("CONVERSATION_PARENT_INVALID")
            row = self._read_revision(folder, row["revision"] - 1, previous,
                                      work_id, cid)
        return results

    def search(self, *, work_id: str, conversation_url: str, query: str,
               limit: int = 10) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip() or len(query) > 256:
            raise ConversationEvidenceError("CONVERSATION_SEARCH_QUERY_INVALID")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ConversationEvidenceError("CONVERSATION_SEARCH_LIMIT_INVALID")
        results: list[dict[str, Any]] = []
        query_lower = query.casefold()
        for row in self.history(work_id=work_id, conversation_url=conversation_url):
            text = row["page_text"]
            pos = text.casefold().find(query_lower)
            if pos < 0:
                continue
            results.append({
                **self._public(row),
                "match_excerpt": text[max(0, pos - 160):pos + len(query) + 200],
                "coverage": COVERAGE,
            })
            if len(results) >= limit:
                break
        return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BCT selected conversation evidence cache")
    parser.add_argument("--root", default=r"D:\BCT\data\conversation-history")
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("capture", "latest", "search"):
        sub = actions.add_parser(action)
        sub.add_argument("--work-id", required=True)
        sub.add_argument("--url", required=True)
        if action == "capture":
            sub.add_argument("--title", required=True)
            sub.add_argument("--input", help="UTF-8 browser tool output file; otherwise stdin")
            sub.add_argument("--summary", default=None, help="Only an AI-curated summary")
            sub.add_argument("--tab-id", default=None)
        elif action == "latest":
            sub.add_argument("--tail", type=int, default=1200)
        else:
            sub.add_argument("--query", required=True)
            sub.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    cache = ConversationEvidenceCache(args.root)
    if args.action == "capture":
        payload = (Path(args.input).read_text(encoding="utf-8-sig")
                   if args.input else sys.stdin.read())
        record = cache.capture(
            work_id=args.work_id, conversation_url=args.url, title=args.title,
            page_text=browser_context_text(payload), summary=args.summary,
            tab_id=args.tab_id,
        )
        print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    elif args.action == "latest":
        if type(args.tail) is not int or not 0 <= args.tail <= 5000:
            parser.error("--tail must be 0..5000")
        row = cache.latest(work_id=args.work_id, conversation_url=args.url)
        print(json.dumps(None if row is None else cache._public(row, tail=args.tail),
                         ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(cache.search(work_id=args.work_id,
            conversation_url=args.url, query=args.query, limit=args.limit),
            ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
