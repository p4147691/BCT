"""Opt-in RCC connection-change observer for durable chat stream checkpoints.

Uses only authenticated RCC state reads and exact existing Work-scoped
checkpoints. Never sends to a ChatGPT tab or replays an Operation.
"""
from __future__ import annotations

import hashlib
import re
import time
import uuid
from typing import Any

from .chat_stream_checkpoint import ChatStreamCheckpoint, _check_id
from .models import ConflictError, Work
from .store import Store
from bct.integrations.rcc import RelayClient, RelayEffectUnknown, RelayUnavailable, validate_instance_id

_UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")


class ChatStreamRccWatch:
    def __init__(self, store: Store, client: RelayClient):
        self.store = store
        self.client = client
        self.checkpoint = ChatStreamCheckpoint(store)

    def bind(self, *, work: Work, stream_id: str, instance_id: str,
             conversation_key: str) -> dict[str, Any]:
        stream_id = _check_id(stream_id)
        instance_id = validate_instance_id(instance_id)
        if not isinstance(conversation_key, str) or _UUID.fullmatch(conversation_key) is None:
            raise ValueError("STREAM_WATCH_CONVERSATION_INVALID")
        with self.store.transaction() as db:
            self.checkpoint._check_work(db, work)
            checkpoint = db.execute(
                "SELECT 1 FROM chat_stream_checkpoints WHERE work_id=? AND stream_id=? LIMIT 1",
                (work.work_id, stream_id),
            ).fetchone()
            if checkpoint is None:
                raise ConflictError("STREAM_WATCH_CHECKPOINT_REQUIRED")
            existing = db.execute(
                "SELECT * FROM chat_stream_rcc_watches WHERE work_id=? AND stream_id=?",
                (work.work_id, stream_id),
            ).fetchone()
            if existing is not None:
                if (existing["instance_id"], existing["conversation_key"],
                    existing["assignment_epoch"]) != (
                        instance_id, conversation_key, work.assignment_epoch):
                    raise ConflictError("STREAM_WATCH_BINDING_IMMUTABLE")
                return {"duplicate": True, "stream_id": stream_id,
                        "instance_id": instance_id, "conversation_key": conversation_key}
            db.execute(
                "INSERT INTO chat_stream_rcc_watches VALUES(?,?,?,?,?,?,?,?,?)",
                (work.work_id, stream_id, instance_id, conversation_key,
                 "UNOBSERVED", "", 0, "", work.assignment_epoch),
            )
        return {"duplicate": False, "stream_id": stream_id,
                "instance_id": instance_id, "conversation_key": conversation_key}

    def status(self, *, work: Work, stream_id: str) -> dict[str, Any]:
        stream_id = _check_id(stream_id)
        db = self.store._connect()
        try:
            self.checkpoint._check_work(db, work, require_active=False)
            row = db.execute(
                "SELECT * FROM chat_stream_rcc_watches WHERE work_id=? AND stream_id=?",
                (work.work_id, stream_id),
            ).fetchone()
            if row is None:
                raise KeyError("STREAM_WATCH_NOT_FOUND")
            result = {
                "stream_id": stream_id, "instance_id": row["instance_id"],
                "conversation_key": row["conversation_key"],
                "last_state": row["last_state"],
                "transition_counter": row["transition_counter"],
                "last_rcc_signal": row["last_signal"] or None,
                "will_execute": False, "will_resend": False,
            }
        finally:
            db.close()
        if result["last_rcc_signal"] == "CLIENT_RECONNECTED":
            result["resume_inspection"] = self.checkpoint.inspect(
                work=work, stream_id=stream_id)
        return result

    def poll_once(self) -> list[dict[str, Any]]:
        db = self.store._connect()
        try:
            rows = db.execute(
                "SELECT w.* FROM chat_stream_rcc_watches w JOIN works x "
                "ON x.work_id=w.work_id WHERE x.state='ACTIVE' "
                "AND x.assignment_epoch=w.assignment_epoch "
                "ORDER BY w.instance_id,w.work_id,w.stream_id",
            ).fetchall()
            watches = [dict(row) for row in rows]
        finally:
            db.close()
        if not watches:
            return []
        by_instance: dict[str, list[dict[str, Any]]] = {}
        for row in watches:
            by_instance.setdefault(row["instance_id"], []).append(row)
        events = []
        for instance_id, group in by_instance.items():
            try:
                reply = self.client.request(
                    instance_id=instance_id, command="state",
                    request_id="stream-observe-" + uuid.uuid4().hex[:24],
                    timeout_s=2.5,
                )
            except (RelayUnavailable, RelayEffectUnknown, OSError):
                continue  # RCC unavailable != ChatGPT reconnected or disconnected.
            state = reply.get("state") if isinstance(reply, dict) else None
            if (not isinstance(state, dict) or reply.get("ok") is not True
                    or state.get("instanceId") != instance_id
                    or not isinstance(state.get("sessionId"), str)
                    or not state.get("sessionId")
                    or not isinstance(state.get("endpoints"), list)):
                continue
            session_id = state["sessionId"]
            for row in group:
                exact = [
                    ep for ep in state["endpoints"]
                    if isinstance(ep, dict)
                    and ep.get("conversationKey") == row["conversation_key"]
                    and ep.get("presence") == "OPEN"
                    and isinstance(ep.get("connection"), dict)
                    and type(ep["connection"].get("disconnected")) is bool
                ]
                if len(exact) != 1:
                    continue  # Missing/ambiguous endpoints are not evidence.
                connected = not exact[0]["connection"]["disconnected"]
                event = self._observe(
                    work_id=row["work_id"], stream_id=row["stream_id"],
                    instance_id=instance_id, conversation_key=row["conversation_key"],
                    session_id=session_id, connected=connected,
                )
                if event is not None:
                    events.append(event)
        return events

    def _observe(self, *, work_id: str, stream_id: str, instance_id: str,
                 conversation_key: str, session_id: str, connected: bool
                 ) -> dict[str, Any] | None:
        observed = "CONNECTED" if connected else "DISCONNECTED"
        incident_id = None
        signal = None
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT w.*,x.state AS work_state,"
                "x.assignment_epoch AS current_epoch FROM chat_stream_rcc_watches w "
                "JOIN works x ON x.work_id=w.work_id WHERE w.work_id=? AND w.stream_id=?",
                (work_id, stream_id),
            ).fetchone()
            if (row is None or row["work_state"] != "ACTIVE"
                    or row["current_epoch"] != row["assignment_epoch"]
                    or row["instance_id"] != instance_id
                    or row["conversation_key"] != conversation_key):
                return None
            previous = row["last_state"]
            last_session = row["last_session_id"]
            # A restart/reload is not proof that ChatGPT repaired a connection.
            if last_session and last_session != session_id:
                previous = "UNOBSERVED"
            if previous == observed and last_session == session_id:
                return None
            counter = row["transition_counter"] + 1
            if observed == "DISCONNECTED":
                signal = "DISCONNECTED"
            elif previous == "DISCONNECTED":
                signal = "CLIENT_RECONNECTED"
            db.execute(
                "UPDATE chat_stream_rcc_watches SET last_state=?,last_session_id=?,"
                "transition_counter=?,last_signal=? WHERE work_id=? AND stream_id=?",
                (observed, session_id, counter, signal or "", work_id, stream_id),
            )
            if signal is not None:
                # Only a deterministic, scoped ID; no URL, prompt or raw banner.
                event_key = hashlib.sha256(
                    (work_id + "\0" + stream_id + "\0" + instance_id
                     + "\0" + conversation_key + "\0" + session_id
                     + "\0" + str(counter) + "\0" + signal
                    ).encode("utf-8")).hexdigest()[:24]
                incident_id = "rcc-" + event_key
                db.execute(
                    "INSERT INTO chat_stream_transport_reports VALUES(?,?,?,?,?)",
                    (work_id, stream_id, incident_id, signal, time.time()),
                )
        if signal is None:
            return None
        event = {"work_id": work_id, "stream_id": stream_id,
                 "signal": signal, "incident_id": incident_id,
                 "will_execute": False, "will_resend": False}
        if signal == "CLIENT_RECONNECTED":
            work = self.store.get_work(work_id)
            event["resume_inspection"] = self.checkpoint.inspect(
                work=work, stream_id=stream_id)
        return event
