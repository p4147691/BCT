"""Loop-specific adapter over the unchanged BCT Node Recovery ledger."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from bct.loop_recipe_contracts import LoopContractError
from bct.node_recovery import NodeRecoveryLedger, observe_node
from bct.status_views import status_view


class PersistentLoopRecovery:
    def __init__(self, runtime: Any):
        self.runtime = runtime

    def _work(self, work_id: str):
        try:
            work = self.runtime.bct.store.get_work(work_id)
        except KeyError as exc:
            raise LoopContractError("LOOP_WORK_NOT_FOUND") from exc
        if (work.owner_principal_id != self.runtime.principal.principal_id
                or work.state != "ACTIVE"):
            raise LoopContractError("LOOP_WORK_NOT_OWNED")
        return work

    def _evidence(self, conversation_key: str) -> dict[str, Any]:
        if self.runtime.status_provider is None:
            raise LoopContractError("LOOP_FRESH_STATUS_REQUIRED")
        return observe_node(
            status_view(self.runtime.status_provider(), "node"), conversation_key,
        )

    async def run(self, *, action: str, work_id: str, conversation_key: str = "",
                  task_id: str = "", case_id: str = "", reason: str = "",
                  successor_conversation_key: str = "",
                  inheritance_task_id: str = "") -> dict[str, Any]:
        work = await asyncio.to_thread(self._work, work_id)
        ledger = NodeRecoveryLedger(self.runtime.bct.store)
        case_id = case_id or ("loop-node-" + uuid.uuid4().hex[:24])
        if action == "check":
            result = await asyncio.to_thread(
                ledger.check, work=work, case_id=case_id, task_id=task_id,
                conversation_key=conversation_key,
                evidence=self._evidence(conversation_key), kind="CHECK",
            )
        elif action == "recheck":
            current = await asyncio.to_thread(ledger.get, work=work, case_id=case_id)
            if current is None:
                raise LoopContractError("LOOP_RECOVERY_CASE_NOT_FOUND")
            result = await asyncio.to_thread(
                ledger.check, work=work, case_id=case_id,
                task_id=str(current["task_id"]),
                conversation_key=str(current["conversation_key"]),
                evidence=self._evidence(str(current["conversation_key"])), kind="RECHECK",
            )
        elif action == "pause":
            result = await asyncio.to_thread(
                ledger.pause, work=work, case_id=case_id, reason=reason,
            )
        elif action == "prepare_replace":
            result = await asyncio.to_thread(
                ledger.prepare_replace, work=work, case_id=case_id,
                successor_conversation_key=successor_conversation_key,
                inheritance_task_id=inheritance_task_id,
                successor_evidence=self._evidence(successor_conversation_key),
            )
        elif action == "commit_replace":
            result = await asyncio.to_thread(
                ledger.commit_replace, work=work, case_id=case_id,
                successor_evidence=self._evidence(successor_conversation_key),
            )
        elif action == "status":
            result = await asyncio.to_thread(ledger.get, work=work, case_id=case_id)
            if result is None:
                return {"status": "NOT_FOUND", "case_id": case_id,
                        "effects": "NONE_READ_ONLY"}
        else:
            raise LoopContractError("LOOP_RECOVERY_ACTION_INVALID")
        return {"status": "OK", "node_recovery": result,
                "effects": "NONE_READ_ONLY" if action in {"status", "check", "recheck"}
                           else "RECOVERY_STATE_ONLY"}
