"""Exact RCC response proof and autonomous Loop SELF continuation.

The model's NEXT TASK -- SELF instruction is parsed using the existing BCT
continuation primitive. Only an exact terminal response to the original
delivery can queue a subsequent wake. No other conversation may be selected.
"""
from __future__ import annotations
import hashlib
import secrets

from bct.loop_self_dispatch import LoopSelfDispatcher
from bct.loop_self_outbox import LoopSelfOutbox
from bct.loop_store import LoopStateError
from bct.send_delayed_message import (
    _rcc_submitted_text_sha256, extract_next_instruction, NextTarget,
    InstructionError,
)


class LoopSelfContinuation:
    def __init__(self, store, browser_feature):
        self.store=store
        self.browser_feature=browser_feature
        self.outbox=LoopSelfOutbox(store)

    def observe_once(self, *, row: dict, snapshot: dict, now=None) -> dict:
        if row["state"]!="DELIVERED":
            raise LoopStateError("LOOP_RESPONSE_RECEIPT_REQUIRED")
        route=LoopSelfDispatcher.exact_route(snapshot,row["conversation_key"])
        observed=self.browser_feature.client.request(
            instance_id=route["instance_id"],
            request_id="loop-read-"+secrets.token_hex(12),
            command="read-latest-assistant",
            extra={"instanceId":route["instance_id"],
                   "sessionId":route["session_id"],
                   "tabId":route["tab_id"],
                   "windowId":route["window_id"],
                   "conversationKey":route["conversation_key"]},
            timeout_s=5.0,
        )
        source_sha=_rcc_submitted_text_sha256(row["message_text"])
        if (not isinstance(observed,dict)
                or observed.get("ok") is not True
                or observed.get("conversationKey")!=row["conversation_key"]
                or observed.get("terminal") is not True
                or observed.get("observationState")!="TERMINAL"
                or observed.get("generating") is not False
                or observed.get("inputReady") is not True
                or observed.get("latestUserSha256")!=source_sha
                or observed.get("responseSourceUserSha256")!=source_sha
                or not observed.get("responseSourceUserTurnKey")
                or observed.get("latestUserTurnKey")!=observed.get("responseSourceUserTurnKey")):
            return {"status":"RESPONSE_SOURCE_UNVERIFIED"}
        text=observed.get("responseText")
        response_sha=observed.get("responseSha256")
        turn_key=observed.get("responseTurnKey")
        if (not isinstance(text,str) or not isinstance(response_sha,str)
                or hashlib.sha256(text.encode("utf-8")).hexdigest()!=response_sha
                or not isinstance(turn_key,str) or not turn_key):
            return {"status":"RESPONSE_HASH_UNVERIFIED"}
        from bct.chain_execution_plan import ChainExecutionPlanLedger, check_execute_plan
        from bct.loop_store import LoopStore
        loop = LoopStore(self.store).get(row["work_id"])
        if loop:
            plans = ChainExecutionPlanLedger(self.store)
            plan = plans.get_for_chain(store=self.store, work_id=row["work_id"],
                direction_id=loop["direction_id"], task_id=loop["task_id"])
            plans.record_execute_plan_check(work_id=row["work_id"],
                direction_id=loop["direction_id"], task_id=loop["task_id"],
                generation=row["step"] + 1, response_sha256=response_sha,
                assessment=check_execute_plan(plan=plan, response_text=text))
        try:
            instruction=extract_next_instruction(text)
        except InstructionError:
            return {"status":"NEXT_TASK_NOT_VERIFIED"}
        if instruction.target!=NextTarget.SELF:
            return {"status":"NOT_SELF_CONTINUATION"}
        confirmed=self.outbox.record_terminal_response(
            work_id=row["work_id"],epoch=row["epoch"],step=row["step"],
            owner=row["conversation_key"],response_turn_key=turn_key,
            response_sha256=response_sha,next_message=instruction.text,
            now=now,
        )
        return {"status":"NEXT_SELF_QUEUED",
                "next_operation_id":confirmed["queued"]["operation_id"]}
