"""Read-only discovery: deployed manuals, curated parts, and actual MCP schemas.

This module never selects a role, grants a capability or executes a tool.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


BUNDLE_PATH = Path(__file__).with_name("data") / "component-library.json"
DISCOVERY_GUIDE = {
    "tool": "bct_capabilities",
    "examples": [
        {"query": "코드 블럭"}, {"query": "데스크탑"},
        {"tool_name": "scan_code_blocks"}, {"include_manual": True},
    ],
    "instructions": (
        "필요한 기능을 검색하고 tool_name으로 현재 입력 계약을 확인한다. "
        "전체 도구를 의무적으로 실행하지 않는다. 선택 이유와 기대 결과는 A의 resources 답 또는 B의 실행계획에, "
        "실제 결과와 영수증은 기존 작업 보고에 남긴다. 도구 존재는 Work 권한이나 실행 성공의 증거가 아니다."
    ),
}
_SEARCH_WORDS = {
    "블럭": "block", "블록": "block", "코드": "code scan", "데스크탑": "desktop",
    "브라우저": "browser", "노드": "node", "대화망": "conversation network",
    "방향": "direction", "계획": "plan", "감시": "watch delayed", "배포": "deploy",
    "부품": "component", "창": "window", "탭": "tab", "큐": "queue",
}


def load_library(path: Path | None = None) -> dict[str, Any]:
    try:
        value = json.loads((path or BUNDLE_PATH).read_text(encoding="utf-8"))
        if value["schema"] != "bct.component-library.bundle.v1":
            raise ValueError("schema")
        manual = value["manual"]
        if hashlib.sha256(manual["text"].encode("utf-8")).hexdigest() != manual["sha256"]:
            raise ValueError("manual digest")
        if not isinstance(value["catalogue"]["components"], list):
            raise ValueError("components")
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "UNAVAILABLE", "reason": "COMPONENT_LIBRARY_BUNDLE_UNAVAILABLE"}


def _terms(query: str) -> set[str]:
    words = set(re.findall(r"[\w.-]+", query.casefold()))
    for korean, english in _SEARCH_WORDS.items():
        if korean in query:
            words.update(english.split())
    return words


def get_manual_guidance(bundle: dict | None = None) -> dict:
    """Read the bounded onboarding section from the same shipped manual."""
    bundle = load_library() if bundle is None else bundle
    manual = bundle.get("manual", {})
    heading = "## 바로 시작하는 노드 안내\n"
    section = str(manual.get("text", "")).partition(heading)[2].split("\n## ", 1)[0].strip()
    result = {
        "status": "AVAILABLE" if section and len(section) <= 3000 else "UNAVAILABLE",
        "read_only": True, "authorizes_execution": False,
        "path": manual.get("path"), "manual_sha256": manual.get("sha256"),
        "source_fingerprint": bundle.get("source_fingerprint"),
        "read_more": {"tool": "bct_capabilities", "arguments": {"include_manual": True}},
    }
    if result["status"] == "AVAILABLE":
        result["text"] = section
    else:
        result["reason"] = "MANUAL_GUIDANCE_UNAVAILABLE"
    return result


def _matches(value: Any, terms: set[str]) -> bool:
    text = json.dumps(value, ensure_ascii=False).casefold()
    return not terms or any(term in text for term in terms)


def discover(*, tools: list[dict], capabilities: tuple[str, ...], usage: dict[str, str],
             query: str = "", tool_name: str = "", component_id: str = "",
             include_manual: bool = False, limit: int = 8, offset: int = 0) -> dict:
    if (not 1 <= limit <= 20 or not 0 <= offset <= 10000 or len(query) > 300
            or len(tool_name) > 150 or len(component_id) > 150):
        return {"status": "INVALID_REQUEST", "reason": "LIBRARY_QUERY_INVALID", "read_only": True}
    actual = {tool["name"]: tool for tool in tools}
    bundle = load_library()
    parts = bundle.get("catalogue", {}).get("components", [])
    # Only explicit MCP implementation symbols are direct tool connections.
    # A Python/JS internal part remains discoverable, never advertised as callable.
    cards = []
    for part in parts:
        symbols = " ".join(entry["symbol"] for entry in part["implementation"]
                           if entry["path"] == "src/bct/mcp_server.py")
        linked = set(re.findall(r"\b(?:bct_\w+|scan_code_blocks|organize_code_blocks|queue_message)\b", symbols))
        linked.update(part.get("public_tools", []))
        cards.append({**part, "available_tools": sorted(linked & actual.keys()),
                      "availability": "TOOL_EXPOSED" if linked & actual.keys() else "SOURCE_COMPONENT_ONLY"})
    terms = _terms(query)
    matches = [card for card in cards if (not component_id or card["id"] == component_id)
               and _matches(card, terms)]
    result: dict[str, Any] = {
        "status": "OK", "read_only": True, "authorizes_execution": False,
        "discovery": DISCOVERY_GUIDE, "library_status": bundle.get("status", "AVAILABLE"),
        "manual_guidance": get_manual_guidance(bundle),
        "coverage": bundle.get("catalogue", {}).get("coverage", "UNAVAILABLE"),
        "source_fingerprint": bundle.get("source_fingerprint"),
        "components": matches[offset:offset + limit] if query or component_id else [],
        "component_total": len(matches) if query or component_id else len(cards),
    }
    if tool_name:
        tool = actual.get(tool_name)
        result["tool"] = tool  # Actual server metadata, including inputSchema, not a copied signature.
        if tool is None:
            result.update(status="NOT_FOUND", reason="TOOL_NOT_EXPOSED_BY_THIS_RUNTIME")
        result["related_components"] = [c["id"] for c in cards if tool_name in c["available_tools"]]
    if component_id and not matches:
        result.update(status="NOT_FOUND", reason="COMPONENT_NOT_FOUND")
    if query:
        found = [t for t in tools if _matches({"name": t["name"], "description": t.get("description", "")}, terms)]
        result["matching_tools"] = [{"name": t["name"], "description": t.get("description", "")}
                                    for t in found[offset:offset + limit]]
        result["tool_total"] = len(found)
        routes = []
        for capability in capabilities:
            if not _matches({"capability": capability, "usage": usage.get(capability, "")}, terms):
                continue
            direct = "bct_" + capability
            route = direct if direct in actual else "bct_dispatch" if "bct_dispatch" in actual else None
            routes.append({"capability": capability, "tool": route,
                           "routing_arguments": {"capability": capability} if route == "bct_dispatch" else {},
                           "usage": usage.get(capability, ""), "requires_work_authorization": True})
        result["capability_routes"] = routes[offset:offset + limit]
        result["capability_total"] = len(routes)
    if include_manual or tool_name == "bct_chain_message":
        result["manual"] = bundle.get("manual", {"status": "UNAVAILABLE"})
        result["manual_scope"] = "Packaged source description; check bct_status and receipts for LIVE acceptance."
    totals = [result.get(key, 0) for key in ("component_total", "tool_total", "capability_total")]
    result["next_offset"] = offset + limit if (query or component_id) and max(totals) > offset + limit else None
    return result
