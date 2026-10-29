"""Event-triggered, receipt-fenced N-number favicon notifications.

Only committed NODE_LABEL_ASSIGNED outbox rows may reach an exact RCC session.
No timer, CDP watcher, new MCP, synthetic reassign/unregister or page text.
"""
from __future__ import annotations

import queue
import re
import threading
from typing import Any

from bct.core.models import Principal, Work
from bct.integrations.rcc import NamedPipeRelayClient, discover_instance_ids

WORK_ID = "bct-node-label-notifications"
PRINCIPAL_ID = "bct-core-node-label-notifier"
_UUID = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\Z")
_ACTIVE = {"PENDING"}


def ensure_notification_work(bct: Any, runtime_root: Any) -> Principal:
    principal = Principal(PRINCIPAL_ID, "durable-committed-node-label", frozenset({"relay_browser"}))
    expected = Work(WORK_ID, "Committed display-label favicon notifications",
                    (str(runtime_root.resolve()),), frozenset({"relay_browser"}), principal.principal_id)
    try:
        existing = bct.store.get_work(WORK_ID)
    except KeyError:
        bct.store.create_work(expected)
    else:
        if existing != expected:
            raise RuntimeError("NODE_LABEL_NOTIFY_WORK_CONTRACT_MISMATCH")
    return principal


class NodeLabelNotifier:
    """Queue wakes only for committed events, startup, or an existing Monitor read."""

    def __init__(self, bct: Any, principal: Principal,
                 client: Any | None = None, discover: Any = None):
        self.bct = bct
        self.principal = principal
        self.client = client if client is not None else NamedPipeRelayClient()
        self.discover = discover if discover is not None else discover_instance_ids
        self.pending: queue.Queue[int | None] = queue.Queue(maxsize=2048)
        self.stop_flag = threading.Event()
        self.thread: threading.Thread | None = None

    def wake(self, event_id: int) -> None:
        try:
            self.pending.put_nowait(int(event_id))
        except queue.Full:
            # Durable PENDING record remains; never promote a dropped wake to ACK.
            pass

    def start(self) -> None:
        if self.thread is not None:
            return
        self.bct.store.set_node_label_notifier(self.wake)
        self.thread = threading.Thread(target=self._run, name="bct-node-label-event-queue", daemon=True)
        self.thread.start()
        for item in self.bct.store.pending_node_label_notifications(limit=2048):
            self.wake(item["event_id"])

    def stop(self) -> None:
        self.bct.store.set_node_label_notifier(None)
        self.stop_flag.set()
        try:
            self.pending.put_nowait(None)
        except queue.Full:
            pass
        if self.thread is not None:
            self.thread.join(timeout=3.0)

    def _run(self) -> None:
        while not self.stop_flag.is_set():
            try:
                event_id = self.pending.get(timeout=0.25)
            except queue.Empty:
                continue
            if event_id is None:
                break
            try:
                self.deliver(event_id)
            except Exception:
                # Original durable outbox and BCT Operation are authoritative.
                # Do not infer an unobserved success or retry a dispatched UNKNOWN.
                pass

    def deliver(self, event_id: int) -> str:
        record = self.bct.store.node_label_notification(event_id)
        if record is None or record["status"] not in _ACTIVE:
            return "NO_PENDING_EVENT"
        uuid = record["conversation_key"]
        if _UUID.fullmatch(uuid) is None:
            return "INVALID_UUID"
        candidates = []
        try:
            instances = self.discover()
        except Exception:
            return "RCC_NOT_AVAILABLE"
        for instance in instances:
            try:
                response = self.client.request(
                    instance_id=instance, request_id="node-label-snapshot." + str(event_id),
                    command="state", timeout_s=4,
                )
            except Exception:
                continue
            state = response.get("state") if isinstance(response, dict) else None
            if not isinstance(response, dict) or response.get("ok") is not True or not isinstance(state, dict):
                continue
            if str(state.get("instanceId") or "") != instance:
                continue
            session = str(state.get("sessionId") or "")
            endpoints = state.get("endpoints")
            if not session or not isinstance(endpoints, list):
                continue
            for endpoint in endpoints:
                if not isinstance(endpoint, dict) or endpoint.get("presence") != "OPEN":
                    continue
                if str(endpoint.get("conversationKey") or "").lower() != uuid:
                    continue
                tab_id = endpoint.get("tabId")
                window_id = endpoint.get("windowId")
                if (type(tab_id) is int and tab_id > 0 and type(window_id) is int and window_id > 0
                        and re.fullmatch(r"https://chatgpt\.com/c/" + re.escape(uuid)
                                         + r"(?:[/?#]|$)", str(endpoint.get("url") or ""), re.I)):
                    candidates.append((instance, session, tab_id, window_id))
        # Same UUID in multiple real tabs is ambiguous; no arbitrary target selection.
        if len(candidates) != 1:
            return "TARGET_ABSENT_OR_AMBIGUOUS"
        instance, session, tab_id, window_id = candidates[0]
        operation_id = "node-label." + str(event_id) + "." + str(tab_id)
        # Never use a new Operation ID to retry an UNKNOWN original.
        if not self.bct.store.claim_node_label_notification(event_id, operation_id):
            return "ALREADY_CLAIMED"
        try:
            receipt = self.bct.operations.run(
                principal=self.principal,
                work_id=WORK_ID,
                operation_id=operation_id,
                capability="relay_browser",
                arguments={
                    "command": "node-label-notify",
                    "instance_id": instance, "session_id": session,
                    "tab_id": tab_id, "window_id": window_id,
                    "conversation_key": uuid, "event_id": event_id,
                    "timeout_s": 8,
                },
            ).as_dict()
        except Exception:
            self.bct.store.finish_node_label_notification(event_id, "UNKNOWN")
            return "UNKNOWN"
        outcome = str(receipt.get("outcome") or "").upper()
        status = "ACKED" if outcome == "APPLIED" else (
            "NOT_APPLIED" if outcome == "NOT_APPLIED" else "UNKNOWN"
        )
        self.bct.store.finish_node_label_notification(event_id, status)
        return status
