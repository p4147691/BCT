"""Node Recovery command coordination without MCP registration."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Awaitable, Callable

from .node_recovery import NodeRecoveryLedger
from .recipes.delivery import send_chain_delivery
from .recipes.recovery import _current_node_evidence

BrowserExecutor = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]]


class NodeRecoveryCommands:
    """Preserve Node Recovery transitions while keeping transport outside this module."""

    def __init__(self, *, store: Any, principal_id: str, runtime: Any,
                 browser_execute: BrowserExecutor) -> None:
        self.store = store
        self.principal_id = principal_id
        self.runtime = runtime
        self.browser_execute = browser_execute

    async def _work(self, work_id: str) -> Any:
        try:
            work = await asyncio.to_thread(self.store.get_work, work_id)
        except KeyError as exc:
            raise ValueError("WORK_NOT_FOUND") from exc
        if work.owner_principal_id != self.principal_id:
            raise ValueError("WORK_NOT_FOUND")
        return work

    def _evidence(self, conversation_key: str) -> dict[str, Any]:
        return _current_node_evidence(self.runtime, conversation_key)

    async def check(self, *, work_id: str, conversation_key: str, task_id: str = "",
                    case_id: str = "") -> dict[str, Any]:
        work = await self._work(work_id)
        case_id = case_id or ("node-recovery-" + uuid.uuid4().hex[:24])
        try:
            result = await asyncio.to_thread(
                NodeRecoveryLedger(self.store).check, work=work, case_id=case_id,
                task_id=task_id, conversation_key=conversation_key,
                evidence=self._evidence(conversation_key), kind="CHECK",
            )
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        return {"status": "OK", "check_node": result}

    async def recheck(self, *, work_id: str, case_id: str) -> dict[str, Any]:
        work = await self._work(work_id)
        ledger = NodeRecoveryLedger(self.store)
        case = await asyncio.to_thread(ledger.get, work=work, case_id=case_id)
        if case is None:
            return {"status": "NOT_FOUND", "case_id": case_id}
        try:
            result = await asyncio.to_thread(
                ledger.check, work=work, case_id=case_id, task_id=str(case["task_id"]),
                conversation_key=str(case["conversation_key"]),
                evidence=self._evidence(str(case["conversation_key"])), kind="RECHECK",
            )
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        return {"status": "OK", "recheck_node": result}

    async def pause(self, *, work_id: str, case_id: str, reason: str) -> dict[str, Any]:
        work = await self._work(work_id)
        try:
            result = await asyncio.to_thread(
                NodeRecoveryLedger(self.store).pause, work=work, case_id=case_id, reason=reason,
            )
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        return {"status": "OK", "pause_node": result}

    async def replace(self, *, work_id: str, case_id: str,
                      successor_conversation_key: str = "", inheritance_task_id: str = "",
                      action: str = "status", operation_id: str = "", instance_id: str = "",
                      session_id: str = "", target_tab_id: int = 0, target_window_id: int = 0,
                      origin_conversation_key: str = "", origin_instance_id: str = "") -> dict[str, Any]:
        work = await self._work(work_id)
        ledger = NodeRecoveryLedger(self.store)
        if action == "status":
            case = await asyncio.to_thread(ledger.get, work=work, case_id=case_id)
            return ({"status": "NOT_FOUND", "case_id": case_id} if case is None
                    else {"status": "OK", "replace_node": case})
        if action not in {"prepare", "start", "commit"}:
            return {"status": "INVALID_REQUEST", "reason": "NODE_REPLACEMENT_ACTION_INVALID"}
        if action == "start" and not operation_id:
            return {"status": "INVALID_REQUEST", "reason": "NODE_REPLACEMENT_OPERATION_REQUIRED"}
        try:
            if action in {"prepare", "start"}:
                prepared = await asyncio.to_thread(
                    ledger.prepare_replace, work=work, case_id=case_id,
                    successor_conversation_key=successor_conversation_key,
                    inheritance_task_id=inheritance_task_id,
                    successor_evidence=self._evidence(successor_conversation_key),
                )
                if action == "prepare":
                    return {"status": "OK", "replace_node": prepared}
                sent = await send_chain_delivery(
                    self.runtime, work_id=work_id, task_id=inheritance_task_id,
                    operation_id=operation_id, action="start", instance_id=instance_id,
                    session_id=session_id, target_tab_id=target_tab_id,
                    target_window_id=target_window_id,
                    target_conversation_key=successor_conversation_key,
                    origin_conversation_key=origin_conversation_key,
                    origin_instance_id=origin_instance_id,
                    instruction=str(prepared["inheritance_instruction"]),
                )
                return {"status": "INHERITANCE_SENT" if sent.get("status") == "WATCHING"
                        else "INHERITANCE_UNCONFIRMED", "replace_node": prepared, "delivery": sent}
            current_case = await asyncio.to_thread(ledger.get, work=work, case_id=case_id)
            successor_key = successor_conversation_key or str(
                (current_case or {}).get("replacement_conversation_key") or "")
            result = await asyncio.to_thread(
                ledger.commit_replace, work=work, case_id=case_id,
                successor_evidence=self._evidence(successor_key),
            )
            return {"status": "OK", "replace_node": result}
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}

    async def reset(self, *, work_id: str, case_id: str, action: str = "status",
                    operation_id: str = "", instance_id: str = "", session_id: str = "",
                    tab_id: int = 0, window_id: int = 0, conversation_key: str = "") -> dict[str, Any]:
        work = await self._work(work_id)
        ledger = NodeRecoveryLedger(self.store)
        case = await asyncio.to_thread(ledger.get, work=work, case_id=case_id)
        if case is None:
            return {"status": "NOT_FOUND", "case_id": case_id}
        if action == "status":
            return {"status": "OK", "reset_node": case}
        if action not in {"plan", "apply"}:
            return {"status": "INVALID_REQUEST", "reason": "NODE_RESET_ACTION_INVALID"}
        if action == "apply" and not operation_id:
            return {"status": "INVALID_REQUEST", "reason": "NODE_RESET_OPERATION_REQUIRED"}
        key = str(case["conversation_key"])
        if conversation_key and conversation_key.lower() != key:
            return {"status": "INVALID_REQUEST", "reason": "NODE_RESET_CONVERSATION_CONFLICT"}
        try:
            planned = await asyncio.to_thread(
                ledger.prepare_reset, work=work, case_id=case_id, node_evidence=self._evidence(key),
            )
            if action == "plan":
                return {"status": "OK", "reset_node": planned}
            closed = await self.browser_execute(work_id, operation_id, {
                "command": "close-conversation-tab", "instance_id": instance_id,
                "session_id": session_id, "tab_id": tab_id, "window_id": window_id,
                "conversation_key": key,
            })
            outcome = str(closed.get("outcome") or "UNKNOWN")
            finished = await asyncio.to_thread(
                ledger.finish_reset, work=work, case_id=case_id,
                close_outcome=outcome, operation_id=operation_id,
            )
            return {"status": "OK" if outcome == "APPLIED" else "CLOSE_" + outcome,
                    "reset_node": finished, "close": closed}
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
