"""Bounded Loop successor stage progression; fail-closed, exact BCT receipts.

No arbitrary tab selection, UUID guessing, or replay. A predecessor must be
confirmed disconnected on two independent RCC observations before create.
"""
from __future__ import annotations

import hashlib
import secrets
import time

from bct.chain_worker_provision import _attachment
from bct.loop_recovery import LoopRecoveryScanner
from bct.loop_successor import LoopSuccessorLedger
from bct.loop_successor_dispatch import LoopSuccessorDispatch
from bct.loop_self_outbox import LoopSelfOutbox
from bct.loop_store import LoopStore, LoopStateError
from bct.status_views import status_view


class LoopSuccessorSupervisor:
    def __init__(self,store,operations,browser_feature,*,principal_id):
        self.store=store
        self.operations=operations
        self.browser=browser_feature
        self.principal_id=principal_id
        self.ledger=LoopSuccessorLedger(store)
        self.dispatcher=LoopSuccessorDispatch(store,operations)
        self.loops=LoopStore(store)

    @staticmethod
    def _origin_route(snapshot,owner):
        matches=[]
        for instance in status_view(snapshot,"rcc").get("rcc",{}).get("instances",[]):
            if instance.get("state")!="OPEN" or instance.get("cached") is True:
                continue
            for tab in instance.get("tabs",[]):
                if (tab.get("conversation_key")==owner and
                    tab.get("presence")=="OPEN" and
                    type(tab.get("window_id")) is int and tab["window_id"]>0):
                    matches.append((instance["instance_id"],tab["window_id"]))
        if len(matches)!=1:
            raise LoopStateError("LOOP_SUCCESSOR_ORIGIN_WINDOW_UNVERIFIED")
        return matches[0]

    @staticmethod
    def _same_owner_still_disconnected(snapshot,owner):
        return LoopSuccessorLedger._unavailable(snapshot,owner)

    @staticmethod
    def _inheritance_instruction(run,case):
        # No new independent Work, Task or Direction: only exact durable IDs.
        return (
            "[BCT LOOP SUCCESSOR — EXISTING WORK]\n"
            f"Work ID: {run['work_id']}\n"
            f"Direction ID: {run['direction_id']}\n"
            f"Task ID: {run['task_id']}\n"
            f"Predecessor UUID: {case['predecessor']}\n"
            f"Predecessor Epoch: {case['predecessor_epoch']}\n"
            f"Create Operation ID: {case['create_op']}\n"
            f"Handoff Operation ID: {case['send_op']}\n"
            f"Next incomplete step: {run['next_step']}\n"
            f"Plan SHA256: {run['plan_sha256']}\n"
            "Read the exact saved plan and original receipts. Do not execute"
            " external effects until the handoff and Epoch are verified."
            " Reply on one line: LOOP_SUCCESSOR_READY"
        )

    def _handoff_response(self,row,snapshot):
        attached=_attachment(snapshot,instance_id=row["instance_id"],
                             tab_id=row["created_tab_id"])
        if (not attached or attached["conversation_key"]!=row["successor"] or
            attached["window_id"]!=row["window_id"]):
            raise LoopStateError("LOOP_SUCCESSOR_ATTACHMENT_CHANGED")
        response=self.browser.client.request(
            instance_id=attached["instance_id"],
            request_id="loop-inherit-read-"+secrets.token_hex(12),
            command="read-latest-assistant",
            extra={"instanceId":attached["instance_id"],
                   "sessionId":attached["session_id"],
                   "tabId":attached["tab_id"],
                   "windowId":attached["window_id"],
                   "conversationKey":row["successor"]},
            timeout_s=5.0,
        )
        if not isinstance(response,dict) or response.get("ok") is not True:
            raise LoopStateError("LOOP_SUCCESSOR_RESPONSE_UNAVAILABLE")
        body=response.get("responseText")
        if not isinstance(body,str):
            raise LoopStateError("LOOP_SUCCESSOR_RESPONSE_UNAVAILABLE")
        sha=hashlib.sha256(body.encode("utf-8")).hexdigest()
        return response,sha

    def run_once(self,*,snapshot,prior_snapshot=None,now=None,limit=8):
        now=time.time() if now is None else now
        due=LoopRecoveryScanner(self.store).scan(now=now,limit=limit)
        outcomes=[]
        for candidate in due:
            work_id=candidate["work_id"]
            run=self.loops.get(work_id)
            if run is None:
                continue
            old=run["owner"]
            case=self.ledger.get(work_id)
            if not self._same_owner_still_disconnected(snapshot,old):
                outcomes.append({"work_id":work_id,"status":"PREFER_ORIGINAL_NODE"})
                continue
            try:
                if case is None or (case["state"] == "TAKEN_OVER"
                                    and case["predecessor_epoch"] < run["epoch"]):
                    if prior_snapshot is None:
                        raise LoopStateError("LOOP_SUCCESSOR_RECHECK_REQUIRED")
                    instance,window=self._origin_route(snapshot,old)
                    case=self.ledger.prepare(
                        work_id=work_id,snapshot_a=prior_snapshot,
                        snapshot_b=snapshot,instance_id=instance,
                        window_id=window,now=now,
                    )
                state=case["state"]
                if state=="CREATE_INTENT":
                    value=self.dispatcher.create_once(work_id=work_id)
                    result={"status":"CREATE_RESERVED","operation_id":value["operation_id"]}
                elif state=="CREATE_DISPATCHING":
                    value=self.ledger.confirm_create(
                        work_id=work_id,principal_id=self.principal_id,
                        snapshot=snapshot,now=now,
                    )
                    result={"status":"CREATE_CONFIRMED","tab_id":value["created_tab_id"]}
                elif state=="CREATED":
                    msg=self._inheritance_instruction(run,case)
                    value=self.dispatcher.send_initial_once(
                        work_id=work_id,snapshot=snapshot,instruction=msg,
                    )
                    result={"status":"HANDOFF_RESERVED","operation_id":value["operation_id"]}
                elif state=="SEND_DISPATCHING":
                    value=self.ledger.bind_successor(
                        work_id=work_id,principal_id=self.principal_id,
                        snapshot=snapshot,now=now,
                    )
                    result={"status":"UUID_CONFIRMED","successor":value["successor"]}
                elif state=="IDENTIFIED":
                    response,sha=self._handoff_response(case,snapshot)
                    value=self.ledger.verify_handoff(
                        work_id=work_id,principal_id=self.principal_id,
                        successor_response=response,expected_response_sha=sha,now=now,
                    )
                    result={"status":"HANDOFF_ACK","response_turn_key":value["response_turn_key"]}
                elif state=="HANDOFF_ACK":
                    # Existing NodeRecovery pause blocks old-node sends and
                    # retires its watched deliveries before Loop Epoch transfer.
                    from bct.node_recovery import NodeRecoveryLedger, observe_node
                    recovery=NodeRecoveryLedger(self.store)
                    work=self.store.get_work(work_id)
                    case_id="loop-fence-"+hashlib.sha256(
                        f"{work_id}:{case['predecessor_epoch']}".encode()
                    ).hexdigest()[:24]
                    if recovery.get(work=work,case_id=case_id) is None:
                        evidence=observe_node(
                            status_view(snapshot,"node"),
                            conversation_key=case["predecessor"],
                        )
                        if evidence["result"]!="CHECK" or (
                                evidence["reason"]!="NODE_CONNECTION_DISCONNECTED"):
                            raise LoopStateError("LOOP_SUCCESSOR_PREDECESSOR_NOT_DISCONNECTED")
                        recovery.check(
                            work=work,case_id=case_id,
                            task_id=run["task_id"],
                            conversation_key=case["predecessor"],
                            evidence=evidence,kind="CHECK",
                        )
                    existing=recovery.get(work=work,case_id=case_id)
                    if existing["state"]!="PAUSED":
                        recovery.pause(
                            work=work,case_id=case_id,
                            reason="Exact Loop successor handoff ACKed; fence predecessor",
                        )
                    takeover=self.ledger.finish(work_id=work_id,now=now)
                    result={"status":"EPOCH_SUCCEEDED","epoch":takeover["epoch"],
                            "successor":takeover["owner"]}
                else:
                    result={"status":"HELD","reason":"LOOP_SUCCESSOR_STATE_"+state}
                outcomes.append({"work_id":work_id,**result})
            except Exception as exc:
                outcomes.append({"work_id":work_id,"status":"HELD",
                                 "reason":str(exc)[:180]})
        return {"checked":len(due),"outcomes":outcomes}
