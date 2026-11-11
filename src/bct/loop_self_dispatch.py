"""Fail-closed transport adapter for durable Loop SELF sends.

Only an already queued, exact SELF intent can be sent. Browser routing is
revalidated against one fresh RCC snapshot and Node Info before reservation.
The original BCT Operation ID is the only permissible delivery ID; uncertain
outcomes remain UNKNOWN and are never sent twice.
"""
from __future__ import annotations

import re

from bct.core.models import Principal
from bct.core.capabilities import capability_matches
from bct.loop_self_outbox import LoopSelfOutbox
from bct.loop_store import LoopStateError
from bct.node_recovery import NodeRecoveryLedger
from bct.status_views import status_view


class LoopSelfDispatcher:
    def __init__(self, store, operations):
        self.store = store
        self.operations = operations
        self.outbox = LoopSelfOutbox(store)

    @staticmethod
    def exact_route(snapshot: dict, owner: str, *, require_idle: bool = True):
        # Core recovery supplies the full status envelope; direct callers
        # supply its Monitor view. Never fall back to outer identity fields
        # when an envelope is present, even if its Monitor view is invalid.
        if "monitor" in snapshot:
            snapshot = snapshot["monitor"]
            if not isinstance(snapshot, dict):
                raise LoopStateError("LOOP_NODE_OBSERVATION_STALE")
        # The production classifier intentionally has no connection/telemetry.
        # Reuse the status projection's exact UUID/tab/window join against the
        # same fresh RCC observation, rather than treating absent fields as idle.
        nodes = status_view({"monitor": snapshot}, "node").get("current_nodes", {})
        if nodes.get("observation", {}).get("state") != "FRESH":
            raise LoopStateError("LOOP_NODE_OBSERVATION_STALE")
        matching = [n for n in nodes.get("items", [])
                    if n.get("status") == "CONFIRMED"
                    and n.get("conversation_uuid") == owner
                    and n.get("source") == "RCC_FRESH"
                    and (n.get("generating") is False or
                         (not require_idle and n.get("generating") is True))
                    and not n.get("connection", {}).get("disconnected", True)
                    and n.get("telemetry", {}).get("readiness") in
                        ({"IDLE"} if require_idle else {"IDLE", "BUSY"})]
        if len(matching) != 1:
            raise LoopStateError("LOOP_NODE_NOT_EXACT_IDLE")
        candidates=[]
        for instance in snapshot.get("rcc", {}).get("instances", []):
            if instance.get("state") != "OPEN" or instance.get("cached") is True:
                continue
            for tab in instance.get("tabs", []):
                if (tab.get("conversation_key") == owner
                        and tab.get("presence") == "OPEN"
                        and (tab.get("generating") is False or
                             (not require_idle and tab.get("generating") is True))
                        and not tab.get("connection",{}).get("disconnected",True)
                        and tab.get("telemetry",{}).get("readiness") in
                            ({"IDLE"} if require_idle else {"IDLE", "BUSY"})):
                    candidates.append((instance,tab))
        if len(candidates) != 1:
            raise LoopStateError("LOOP_RCC_TARGET_NOT_UNIQUE")
        instance, tab = candidates[0]
        if (matching[0].get("window_id") != tab.get("window_id")
                or matching[0].get("tab_id") != tab.get("tab_id")):
            raise LoopStateError("LOOP_RCC_ATTACHMENT_MISMATCH")
        for item in (instance.get("instance_id"),instance.get("session_id")):
            if not isinstance(item,str) or re.fullmatch(r"[a-f0-9]{32}",item) is None:
                raise LoopStateError("LOOP_RCC_ID_INVALID")
        if not all(isinstance(tab.get(name),int) and tab[name] > 0
                   for name in ("tab_id","window_id")):
            raise LoopStateError("LOOP_RCC_TAB_INVALID")
        return {"instance_id":instance["instance_id"],
                "session_id":instance["session_id"],
                "tab_id":tab["tab_id"],"window_id":tab["window_id"],
                "conversation_key":owner}

    def send_once(self, *, work_id: str, epoch: int, step: int,
                  owner: str, snapshot: dict, now=None):
        """Reserve the exact operation BEFORE transport; never retry UNKNOWN."""
        row=self.outbox.get(work_id=work_id,epoch=epoch,step=step)
        if row is None:
            raise LoopStateError("LOOP_SELF_NOT_FOUND")
        if row["conversation_key"] != owner:
            raise LoopStateError("LOOP_SELF_OWNER_MISMATCH")
        if row["state"] != "PENDING":
            raise LoopStateError("LOOP_SELF_ALREADY_DISPATCHED")
        work=self.store.get_work(work_id)
        if (work.state != "ACTIVE" or
                not any(capability_matches(x,"browser") for x in work.actions)):
            raise LoopStateError("LOOP_SELF_WORK_NOT_AUTHORIZED")
        NodeRecoveryLedger(self.store).assert_send_allowed(
            work_id=work_id, conversation_key=owner,
        )
        route=self.exact_route(snapshot,owner)
        reserved=self.outbox.reserve(
            work_id=work_id,epoch=epoch,step=step,owner=owner,now=now,
        )
        # An exception, process termination, or UNKNOWN after reservation is
        # intentionally NOT retried. The next Core pass reads the old receipt.
        principal=Principal(work.owner_principal_id,"loop-self-existing-work",
                            frozenset({"browser"}))
        receipt=self.operations.run(
            principal=principal,work_id=work_id,
            operation_id=reserved["operation_id"],capability="browser",
            arguments={"command":"send-message",**route,"text":reserved["message_text"]},
        )
        settled=self.outbox.reconcile(
            work_id=work_id,epoch=epoch,step=step,
            principal_id=work.owner_principal_id,now=now,
        )
        return {"operation_id":reserved["operation_id"],
                "status":settled["state"],
                "outcome":receipt.outcome.value if receipt.outcome else None}
