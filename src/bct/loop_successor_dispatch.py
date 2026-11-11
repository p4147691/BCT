"""Exact one-shot BCT browser operations for Loop successor bootstrap.

No effect is retried after a durable reservation; reconcile original receipts.
The predecessor must be proven disconnected twice before this adapter is called.
"""
from __future__ import annotations

from bct.core.models import Principal
from bct.core.capabilities import capability_matches
from bct.loop_store import LoopStateError
from bct.loop_successor import LoopSuccessorLedger
from bct.chain_worker_provision import _attachment
from bct.send_delayed_message import _rcc_submitted_text_sha256


class LoopSuccessorDispatch:
    def __init__(self,store,operations):
        self.store=store
        self.operations=operations
        self.ledger=LoopSuccessorLedger(store)

    def _principal(self,work_id):
        work=self.store.get_work(work_id)
        if work.state!="ACTIVE" or not any(
            capability_matches(x,"browser") for x in work.actions
        ):
            raise LoopStateError("LOOP_SUCCESSOR_BROWSER_NOT_AUTHORIZED")
        return Principal(work.owner_principal_id,"loop-successor-existing-work",
                         frozenset({"browser"}))

    def create_once(self,*,work_id):
        principal=self._principal(work_id)
        case=self.ledger.reserve_effect(work_id=work_id,kind="create")
        # The persisted CREATE_DISPATCHING state prevents any repeated create
        # even if this process crashes between reservation and send.
        receipt=self.operations.run(
            principal=principal,work_id=work_id,
            operation_id=case["create_op"],capability="browser",
            arguments={"command":"create-chat-tab",
                       "instance_id":case["instance_id"],
                       "window_id":case["window_id"]},
        )
        return {"operation_id":case["create_op"],
                "outcome":receipt.outcome.value if receipt.outcome else "UNKNOWN"}

    def send_initial_once(self,*,work_id,snapshot,instruction):
        principal=self._principal(work_id)
        row=self.ledger.get(work_id)
        if not row or row["state"]!="CREATED":
            raise LoopStateError("LOOP_SUCCESSOR_CREATE_NOT_CONFIRMED")
        if not isinstance(instruction,str) or not instruction.strip() or len(instruction)>12000:
            raise LoopStateError("LOOP_SUCCESSOR_INSTRUCTION_INVALID")
        attached=_attachment(snapshot,instance_id=row["instance_id"],
                             tab_id=row["created_tab_id"])
        if not attached or attached["window_id"]!=row["window_id"]:
            raise LoopStateError("LOOP_SUCCESSOR_ATTACHMENT_UNKNOWN")
        if attached["conversation_key"]:
            # An existing/bound conversation is never a new blank tab.
            raise LoopStateError("LOOP_SUCCESSOR_NOT_BLANK_TAB")
        reserved=self.ledger.reserve_effect(
            work_id=work_id,kind="send",
            handoff_text_sha=_rcc_submitted_text_sha256(instruction),
        )
        receipt=self.operations.run(
            principal=principal,work_id=work_id,
            operation_id=reserved["send_op"],capability="browser",
            arguments={"command":"send-message",**attached,
                       "conversation_key":"",
                       "create_operation_id":reserved["create_op"],
                       "text":instruction},
        )
        return {"operation_id":reserved["send_op"],
                "outcome":receipt.outcome.value if receipt.outcome else "UNKNOWN"}
