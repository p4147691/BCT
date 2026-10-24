"""Durable, non-blocking ChatGPT reasoning-level changes through official CDP UI input.

The request is an absolute target, so recovery always reads the current value
before pressing a key.  Rows in this queue are never relay claims and cannot
block delivery or another BCT capability.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from bct.integrations.rcc import NamedPipeRelayClient, RelayEffectUnknown, RelayUnavailable


LEVELS = ("Instant", "Medium", "High", "Extra High", "Pro")
MAX_ATTEMPTS = 5
RETRY_BASE_SECONDS = 2.0
_UUID = re.compile(r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")
_PAGE = re.compile(r"^\s*(\d+): .* \((https://chatgpt\.com/c/([a-f0-9-]{36}))\)(?: \[selected\])?\s*$")


class ReasoningControlError(RuntimeError):
    pass


def _response_text(response: dict[str, Any]) -> str:
    content = response.get("content")
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block.get("text") or "") for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _json_result(response: dict[str, Any]) -> dict[str, Any]:
    text = _response_text(response)
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = match.group(1) if match else text.strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ReasoningControlError("CDP_REASONING_RESULT_UNPARSABLE") from exc
    if not isinstance(value, dict):
        raise ReasoningControlError("CDP_REASONING_RESULT_INVALID")
    return value


def build_prepare_function(conversation_key: str, target_level: str) -> str:
    if not _UUID.fullmatch(conversation_key) or target_level not in LEVELS:
        raise ValueError("CDP_REASONING_SCRIPT_ARGUMENT_INVALID")
    path = json.dumps("/c/" + conversation_key)
    target = json.dumps(target_level)
    return f"""async () => {{
 const path={path}, target={target};
 if(location.pathname!==path) return {{status:'TARGET_MISMATCH'}};
 if(document.querySelector('button[data-testid="stop-button"],button[data-testid="stop-generating-button"],button[aria-label="Stop generating"],button[aria-label="Stop"]')) return {{status:'BUSY'}};
 const button=[...document.querySelectorAll('button')].find(e=>e.getAttribute('aria-label')==='ChatGPT 모델 선택');
 if(!button) return {{status:'SELECTOR_MISSING'}};
 const current=(button.innerText||'').trim().split(/\\n/).at(-1)||'';
 if(current===target) return {{status:'ALREADY',current}};
 const deadline=Date.now()+1500;
 let power=document.querySelector('[role="menuitem"][aria-label="파워"]');
 let status=[...document.querySelectorAll('[role="status"]')].find(e=>/5개 중/.test(e.innerText||''));
 if(!power||!status) button.click();
 while(Date.now()<deadline) {{
   power=document.querySelector('[role="menuitem"][aria-label="파워"]');
   status=[...document.querySelectorAll('[role="status"]')].find(e=>/5개 중/.test(e.innerText||''));
   if(power&&status) break;
   await new Promise(r=>setTimeout(r,25));
 }}
 if(!power||!status) return {{status:'MENU_MISSING',current}};
 const match=(status.innerText||'').match(/^(.+), 5개 중 (\\d)번째/);
 if(!match||match[1]!==current) return {{status:'POSITION_UNPROVEN',current}};
 power.focus();
 if(document.activeElement!==power) return {{status:'FOCUS_UNPROVEN',current}};
 return {{status:'READY',current,index:Number(match[2])}};
}}"""


def build_verify_function(conversation_key: str, target_level: str) -> str:
    if not _UUID.fullmatch(conversation_key) or target_level not in LEVELS:
        raise ValueError("CDP_REASONING_SCRIPT_ARGUMENT_INVALID")
    path = json.dumps("/c/" + conversation_key)
    target = json.dumps(target_level)
    return f"""() => {{
 const path={path}, target={target};
 const button=[...document.querySelectorAll('button')].find(e=>e.getAttribute('aria-label')==='ChatGPT 모델 선택');
 const current=button?(button.innerText||'').trim().split(/\\n/).at(-1)||'':'';
 return {{status:location.pathname===path&&current===target?'VERIFIED':'NOT_VERIFIED',current}};
}}"""


def validate_reasoning_function(page_id: Any, function: Any) -> bool:
    if type(page_id) is not int or page_id < 1 or not isinstance(function, str):
        return False
    match = re.match(
        r'^(?:async )?\(\) => \{\n const path="/c/([a-f0-9-]{36})", '
        r'target="([A-Za-z ]+)";', function,
    )
    if not match:
        return False
    conversation, target = match.groups()
    if not _UUID.fullmatch(conversation) or target not in LEVELS:
        return False
    return function in {
        build_prepare_function(conversation, target),
        build_verify_function(conversation, target),
    }


class CDPReasoningController:
    def __init__(self, manager):
        self.manager = manager

    def _page_id(self, conversation_key: str) -> int:
        response = self.manager.request("tools/call", {
            "name": "list_pages", "arguments": {},
        })
        matches: list[int] = []
        for line in _response_text(response).splitlines():
            match = _PAGE.match(line)
            if match and match.group(3) == conversation_key:
                matches.append(int(match.group(1)))
        if len(matches) != 1:
            raise ReasoningControlError("CDP_REASONING_EXACT_PAGE_UNAVAILABLE")
        return matches[0]

    def apply(self, conversation_key: str, target_level: str) -> dict[str, Any]:
        page_id = self._page_id(conversation_key)
        prepared = _json_result(self.manager.request("tools/call", {
            "name": "evaluate_script", "arguments": {
                "pageId": page_id,
                "function": build_prepare_function(conversation_key, target_level),
                "waitForStableDom": False,
            },
        }))
        status = str(prepared.get("status") or "")
        before = str(prepared.get("current") or "")
        if status == "ALREADY":
            return {"page_id": page_id, "before": before, "after": before,
                    "changed": False}
        if status == "BUSY":
            raise ReasoningControlError("CDP_REASONING_TARGET_BUSY")
        if status != "READY" or before not in LEVELS:
            raise ReasoningControlError("CDP_REASONING_PREPARE_" + (status or "INVALID"))
        current_index = int(prepared.get("index") or 0)
        target_index = LEVELS.index(target_level) + 1
        if current_index != LEVELS.index(before) + 1:
            raise ReasoningControlError("CDP_REASONING_POSITION_MISMATCH")
        key = "ArrowRight" if target_index > current_index else "ArrowLeft"
        for _ in range(abs(target_index - current_index)):
            self.manager.request("tools/call", {
                "name": "press_key", "arguments": {
                    "pageId": page_id, "key": key, "includeSnapshot": False,
                },
            })
        # Close the menu before readback so no transient popup is left behind.
        self.manager.request("tools/call", {
            "name": "press_key", "arguments": {
                "pageId": page_id, "key": "Escape", "includeSnapshot": False,
            },
        })
        verified = _json_result(self.manager.request("tools/call", {
            "name": "evaluate_script", "arguments": {
                "pageId": page_id,
                "function": build_verify_function(conversation_key, target_level),
                "waitForStableDom": False,
            },
        }))
        after = str(verified.get("current") or "")
        if verified.get("status") != "VERIFIED" or after != target_level:
            raise ReasoningControlError("CDP_REASONING_READBACK_FAILED")
        return {"page_id": page_id, "before": before, "after": after,
                "changed": True}


class ReasoningChangeRecovery:
    def __init__(self, store, manager, relay: NamedPipeRelayClient):
        self.store = store
        self.controller = CDPReasoningController(manager)
        self.relay = relay

    def enqueue(self, *, request_id: str, work_id: str, instance_id: str,
                conversation_key: str, target_level: str) -> dict[str, Any]:
        now = time.time()
        with self.store.transaction() as db:
            existing = db.execute(
                "SELECT * FROM reasoning_change_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if existing is not None:
                if (existing["work_id"], existing["instance_id"],
                        existing["conversation_key"], existing["target_level"]) != (
                        work_id, instance_id, conversation_key, target_level):
                    raise ValueError("REASONING_CHANGE_REQUEST_ID_REUSE_MISMATCH")
                return dict(existing)
            db.execute(
                "UPDATE reasoning_change_requests SET state='SUPERSEDED',updated_at=? "
                "WHERE instance_id=? AND conversation_key=? AND state='PENDING'",
                (now, instance_id, conversation_key),
            )
            db.execute(
                "INSERT INTO reasoning_change_requests(" 
                "request_id,work_id,instance_id,conversation_key,target_level,state,"
                "attempts,next_attempt_at,created_at,updated_at) "
                "VALUES(?,?,?,?,?,'PENDING',0,0,?,?)",
                (request_id, work_id, instance_id, conversation_key,
                 target_level, now, now),
            )
        return self.get(request_id)

    def get(self, request_id: str) -> dict[str, Any]:
        db = self.store._connect()
        try:
            row = db.execute(
                "SELECT * FROM reasoning_change_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("REASONING_CHANGE_REQUEST_NOT_FOUND")
        return dict(row)

    def _rcc_observation(self, row: dict[str, Any]) -> tuple[bool, str]:
        digest = hashlib.sha256(row["request_id"].encode("utf-8")).hexdigest()[:24]
        reply = self.relay.request(
            instance_id=row["instance_id"], request_id="reasoning-state-" + digest,
            command="state", timeout_s=2.0,
        )
        state = reply.get("state") if isinstance(reply.get("state"), dict) else {}
        endpoints = state.get("endpoints") if isinstance(state.get("endpoints"), list) else []
        exact = [item for item in endpoints if isinstance(item, dict)
                 and str(item.get("conversationKey") or "").lower()
                 == row["conversation_key"]]
        if len(exact) != 1 or exact[0].get("presence") != "OPEN":
            raise ReasoningControlError("REASONING_TARGET_NOT_OPEN")
        endpoint = exact[0]
        reasoning = endpoint.get("reasoning") if isinstance(endpoint.get("reasoning"), dict) else {}
        current = str(reasoning.get("level") or "") if reasoning.get("status") == "OBSERVED" else ""
        return endpoint.get("generating") is True, current

    def run_once(self, *, limit: int = 4) -> dict[str, int]:
        started_at = time.time()
        db = self.store._connect()
        try:
            rows = [dict(row) for row in db.execute(
                "SELECT * FROM reasoning_change_requests WHERE state='PENDING' "
                "AND next_attempt_at<=? ORDER BY created_at LIMIT ?",
                (started_at, limit),
            ).fetchall()]
        finally:
            db.close()
        applied = deferred = 0
        for row in rows:
            now = time.time()
            try:
                busy, observed = self._rcc_observation(row)
                if busy:
                    with self.store.transaction() as db:
                        db.execute(
                            "UPDATE reasoning_change_requests SET error=?,"
                            "next_attempt_at=?,updated_at=? WHERE request_id=? "
                            "AND state='PENDING'",
                            ("CDP_REASONING_TARGET_BUSY",
                             now + RETRY_BASE_SECONDS, now, row["request_id"]),
                        )
                    deferred += 1
                    continue
                if observed == row["target_level"]:
                    result = {"before": observed, "after": observed}
                else:
                    result = self.controller.apply(
                        row["conversation_key"], row["target_level"])
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE reasoning_change_requests SET state='APPLIED',"
                        "observed_before=?,observed_after=?,attempts=attempts+1,error=NULL,"
                        "next_attempt_at=0,updated_at=? WHERE request_id=? "
                        "AND state='PENDING'",
                        (result.get("before") or observed, result.get("after") or "",
                         now, row["request_id"]),
                    )
                applied += 1
            except (ReasoningControlError, RelayUnavailable, RelayEffectUnknown,
                    OSError, RuntimeError, ValueError) as exc:
                error = (
                    type(exc).__name__ + ":" + str(exc)
                    if isinstance(exc, (ReasoningControlError, RelayUnavailable,
                                        RelayEffectUnknown))
                    else type(exc).__name__
                )[:180]
                transient = (
                    isinstance(exc, (RelayUnavailable, RelayEffectUnknown, OSError))
                    or (isinstance(exc, RuntimeError)
                        and not isinstance(exc, ReasoningControlError))
                ) or str(exc) in {
                    "CDP_REASONING_EXACT_PAGE_UNAVAILABLE",
                    "REASONING_TARGET_NOT_OPEN",
                    "CDP_REASONING_TARGET_BUSY",
                    "CDP_REASONING_READBACK_FAILED",
                }
                attempts = int(row.get("attempts") or 0) + 1
                state = "PENDING" if transient and attempts < MAX_ATTEMPTS else "FAILED"
                backoff = min(30.0, RETRY_BASE_SECONDS * (2 ** (attempts - 1)))
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE reasoning_change_requests SET state=?,"
                        "attempts=attempts+1,error=?,next_attempt_at=?,updated_at=? "
                        "WHERE request_id=? AND state='PENDING'",
                        (state, error, now + backoff if state == "PENDING" else 0,
                         now, row["request_id"]),
                    )
                deferred += 1
        return {"examined": len(rows), "applied": applied, "deferred": deferred}
