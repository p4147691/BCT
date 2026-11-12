"""Public-command service for the new persistent Loop kernel.

The MCP adapter will be a thin forwarding entry.  This service owns validation
and durable state transitions but no browser/network effect.
"""
from __future__ import annotations

from bct.loop_recipe_assembly import persistent_loop_assembly, persistent_loop_outline
from bct.loop_recipe_contracts import LoopContractError
from bct.loop_recipe_flow import BlockResult, LinkKind, LoopFlowEngine
from bct.loop_recipe_ledger import LoopRecipeLedger
from bct.loop_recipe_recovery import RecoveryEvidence, plan_recovery


class PersistentLoopCommands:
    def __init__(self, store, *, principal_id: str):
        self.store = store
        self.principal_id = principal_id
        self.ledger = LoopRecipeLedger(store)
        self.engine = LoopFlowEngine(persistent_loop_assembly())

    def _owned_work(self, work_id: str):
        work = self.store.get_work(work_id)
        if work.owner_principal_id != self.principal_id:
            raise LoopContractError("LOOP_WORK_NOT_OWNED")
        if work.state != "ACTIVE":
            raise LoopContractError("LOOP_WORK_NOT_ACTIVE")
        return work

    def outline(self) -> dict:
        return {"status": "OK", "assembly": persistent_loop_outline(),
                "effects": "NONE_READ_ONLY"}

    def start(self, *, loop_id: str, work_id: str) -> dict:
        self._owned_work(work_id)
        run = self.ledger.start(loop_id=loop_id, work_id=work_id)
        if run["work_id"] != work_id:
            raise LoopContractError("LOOP_RUN_ID_CONFLICT")
        return {"status": "OK", "run": run, "effects": "STATE_ONLY"}

    def status(self, *, loop_id: str) -> dict:
        run = self.ledger.get_run(loop_id)
        if run is None:
            return {"status": "NOT_FOUND"}
        self._owned_work(run["work_id"])
        return {"status": "OK", "run": run}

    def transition(self, *, loop_id: str, block_id: str, link: str,
                   required_capabilities: tuple[str, ...] = (),
                   artifact_refs: tuple[str, ...] = (), continuation_id: str = "",
                   operation_id: str = "", watch_id: str = "", receipt_ref: str = "") -> dict:
        run = self.ledger.get_run(loop_id)
        if run is None:
            raise LoopContractError("LOOP_RUN_NOT_FOUND")
        self._owned_work(run["work_id"])
        try:
            kind = LinkKind(link)
        except ValueError as exc:
            raise LoopContractError("LOOP_LINK_INVALID") from exc
        result = BlockResult(block_id, kind, tuple(artifact_refs), frozenset(required_capabilities))
        advance = self.engine.advance(result)
        if run["current_block_id"] != block_id:
            raise LoopContractError("LOOP_RUN_SOURCE_BLOCK_STALE")
        if not advance.requires_continuation:
            updated = self.ledger.advance_immediate(
                loop_id=loop_id, expected_revision=run["revision"], source_block_id=block_id,
                next_block_id=advance.next_block_id, complete=kind is LinkKind.COMPLETE,
            )
            return {"status": "COMPLETED" if kind is LinkKind.COMPLETE else "NEXT_BLOCK",
                    "run": updated, "next_block_id": advance.next_block_id}
        if not all((continuation_id, operation_id, watch_id, receipt_ref)):
            raise LoopContractError("LOOP_CONTINUATION_IDENTITY_REQUIRED")
        continuation = self.engine.continuation(
            advance=advance, result=result, continuation_id=continuation_id,
            loop_id=loop_id, revision=run["revision"], operation_id=operation_id,
            watch_id=watch_id, receipt_ref=receipt_ref,
        )
        staged = self.ledger.stage(continuation=continuation, link=kind)
        return {"status": "PREPARED", "continuation": staged,
                "next_block_id": advance.next_block_id, "effects": "STATE_ONLY"}

    def recovery_plan(self, *, continuation_id: str, receipt_observation: str,
                      node_observation: str, unchanged_rechecks: int = 0) -> dict:
        continuation = self.ledger.get_continuation(continuation_id)
        if continuation is None:
            raise LoopContractError("LOOP_CONTINUATION_NOT_FOUND")
        run = self.ledger.get_run(continuation["loop_id"])
        self._owned_work(run["work_id"])
        action = plan_recovery(RecoveryEvidence(
            receipt_observation, node_observation, unchanged_rechecks,
        ))
        return {"status": "OK", "action": action.value,
                "continuation_id": continuation_id, "effects": "NONE_READ_ONLY"}
