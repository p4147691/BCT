"""Durable, non-executing checkpoint/continuation planning for UI stream outages.

A client-reported stream failure is NOT evidence of a BCT effect. Never
retransmit, release claims, or mutate the original operation here.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from .models import ConflictError, Work
from .store import Store

_ID = re.compile(r"[A-Za-z0-9_.:-]{1,96}")
_SHA = re.compile(r"[a-f0-9]{40}|[a-f0-9]{64}")
_SIGNALS = frozenset({
    "CONNECTED", "DISCONNECTED", "STREAM_TIMEOUT", "WAITING_FOR_REPLY",
    "CLIENT_RECONNECTED", "CLIENT_UNOBSERVED",
})


def _check_id(value: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError("STREAM_CHECKPOINT_ID_INVALID")
    return value


def _receipt_digest(row: Any) -> str:
    raw = json.dumps(
        [row["operation_id"], row["work_id"], row["principal_id"],
         row["request_digest"], row["state"], row["outcome"], row["evidence_json"],
         row["error"], row["assignment_epoch"]],
        ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ChatStreamCheckpoint:
    def __init__(self, store: Store):
        self.store = store

    @staticmethod
    def _check_work(db: Any, work: Work, *, require_active: bool = True) -> None:
        row = db.execute(
            "SELECT owner_principal_id,assignment_epoch,state FROM works WHERE work_id=?",
            (work.work_id,),
        ).fetchone()
        if (row is None or row["owner_principal_id"] != work.owner_principal_id
                or row["assignment_epoch"] != work.assignment_epoch
                or (require_active and row["state"] != "ACTIVE")):
            raise ConflictError("STREAM_WORK_FENCE_CHANGED")

    @staticmethod
    def _source_row(db: Any, work: Work, operation_id: str) -> Any:
        row = db.execute(
            "SELECT * FROM operations WHERE operation_id=? AND work_id=?",
            (operation_id, work.work_id),
        ).fetchone()
        if row is None or row["principal_id"] != work.owner_principal_id:
            raise ConflictError("STREAM_SOURCE_RECEIPT_NOT_OWNED")
        return row

    @staticmethod
    def _snapshot(row: Any) -> dict[str, Any]:
        return {
            "sequence": row["sequence"], "step_id": row["step_id"],
            "source_operation_id": row["source_operation_id"],
            "source_state": row["source_state"],
            "source_outcome": row["source_outcome"],
            "source_receipt_sha256": row["source_receipt_sha256"],
            "source_release_sha": row["source_release_sha"],
            "next_step": row["next_step"],
            "created_at": row["created_at"],
        }

    def save(self, *, work: Work, stream_id: str, sequence: int, step_id: str,
             source_operation_id: str, source_release_sha: str,
             next_step: str) -> dict[str, Any]:
        stream_id = _check_id(stream_id)
        step_id = _check_id(step_id)
        source_operation_id = _check_id(source_operation_id)
        if type(sequence) is not int or not 0 <= sequence <= 100000:
            raise ValueError("STREAM_SEQUENCE_INVALID")
        if not isinstance(source_release_sha, str) or _SHA.fullmatch(source_release_sha) is None:
            raise ValueError("STREAM_SOURCE_SHA_INVALID")
        if (not isinstance(next_step, str) or not next_step.strip()
                or len(next_step) > 300):
            raise ValueError("STREAM_NEXT_STEP_INVALID")
        with self.store.transaction() as db:
            self._check_work(db, work)
            source = self._source_row(db, work, source_operation_id)
            existing = db.execute(
                "SELECT * FROM chat_stream_checkpoints WHERE work_id=? AND stream_id=? AND sequence=?",
                (work.work_id, stream_id, sequence),
            ).fetchone()
            receipt_sha = _receipt_digest(source)
            expected = (step_id, source_operation_id, source["state"],
                        source["outcome"], receipt_sha, source_release_sha, next_step)
            if existing:
                actual = tuple(existing[k] for k in (
                    "step_id", "source_operation_id", "source_state",
                    "source_outcome", "source_receipt_sha256", "source_release_sha",
                    "next_step",
                ))
                if actual != expected:
                    raise ConflictError("STREAM_CHECKPOINT_IMMUTABLE")
                return {**self._snapshot(existing), "duplicate": True}
            last = db.execute(
                "SELECT * FROM chat_stream_checkpoints WHERE work_id=? AND stream_id=? "
                "ORDER BY sequence DESC LIMIT 1",
                (work.work_id, stream_id),
            ).fetchone()
            if sequence != (last["sequence"] + 1 if last else 0):
                raise ConflictError("STREAM_CHECKPOINT_SEQUENCE_GAP")
            if last is not None:
                prev = self._source_row(db, work, last["source_operation_id"])
                if (_receipt_digest(prev) != last["source_receipt_sha256"]
                        or prev["state"] != "FINISHED" or prev["outcome"] != "APPLIED"):
                    raise ConflictError("STREAM_PREVIOUS_EFFECT_NOT_ACCEPTED")
            db.execute(
                "INSERT INTO chat_stream_checkpoints VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (work.work_id, stream_id, sequence, step_id, source_operation_id,
                 source["state"], source["outcome"], receipt_sha,
                 source_release_sha, next_step, time.time()),
            )
            row = db.execute(
                "SELECT * FROM chat_stream_checkpoints WHERE work_id=? AND stream_id=? AND sequence=?",
                (work.work_id, stream_id, sequence),
            ).fetchone()
            return {**self._snapshot(row), "duplicate": False}

    def report_transport(self, *, work: Work, stream_id: str, incident_id: str,
                         signal: str) -> dict[str, Any]:
        stream_id = _check_id(stream_id)
        incident_id = _check_id(incident_id)
        if signal not in _SIGNALS:
            raise ValueError("STREAM_SIGNAL_INVALID")
        with self.store.transaction() as db:
            self._check_work(db, work)
            old = db.execute(
                "SELECT * FROM chat_stream_transport_reports WHERE work_id=? AND stream_id=? AND incident_id=?",
                (work.work_id, stream_id, incident_id),
            ).fetchone()
            if old:
                if old["signal"] != signal:
                    raise ConflictError("STREAM_SIGNAL_IMMUTABLE")
                return {"incident_id": incident_id, "signal": signal,
                        "unverified_client_report": True, "duplicate": True}
            db.execute(
                "INSERT INTO chat_stream_transport_reports VALUES(?,?,?,?,?)",
                (work.work_id, stream_id, incident_id, signal, time.time()),
            )
        return {"incident_id": incident_id, "signal": signal,
                "unverified_client_report": True, "duplicate": False}

    def inspect(self, *, work: Work, stream_id: str) -> dict[str, Any]:
        stream_id = _check_id(stream_id)
        db = self.store._connect()
        try:
            self._check_work(db, work, require_active=False)
            rows = db.execute(
                "SELECT * FROM chat_stream_checkpoints WHERE work_id=? AND stream_id=? "
                "ORDER BY sequence",
                (work.work_id, stream_id),
            ).fetchall()
            reports = db.execute(
                "SELECT incident_id,signal,created_at FROM chat_stream_transport_reports "
                "WHERE work_id=? AND stream_id=? ORDER BY created_at,incident_id",
                (work.work_id, stream_id),
            ).fetchall()
            steps = []
            blocked = None
            for row in rows:
                try:
                    original = self._source_row(db, work, row["source_operation_id"])
                    same = (_receipt_digest(original) == row["source_receipt_sha256"]
                            and row["source_state"] == original["state"]
                            and row["source_outcome"] == original["outcome"])
                    state = original["state"]
                    outcome = original["outcome"]
                except ConflictError:
                    same, state, outcome = False, None, None
                decision = ("RECEIPT_CHANGED_OR_UNAVAILABLE" if not same else
                            "STOP_UNKNOWN_NO_RESEND" if outcome == "UNKNOWN" else
                            "WAIT_ORIGINAL_EXECUTION" if state != "FINISHED" else
                            "READY_TO_PROPOSE_NEXT_STEP" if outcome == "APPLIED" else
                            "REVIEW_NOT_APPLIED_OR_FAILED")
                steps.append({**self._snapshot(row), "receipt_verified": same,
                              "decision": decision})
                if blocked is None and decision != "READY_TO_PROPOSE_NEXT_STEP":
                    blocked = decision
        finally:
            db.close()
        if not steps:
            decision = "NO_DURABLE_CHECKPOINT"
            next_step = None
        else:
            decision = blocked or "READY_TO_PROPOSE_NEXT_STEP"
            next_step = steps[-1]["next_step"] if blocked is None else None
        return {
            "stream_id": stream_id, "work_id": work.work_id,
            "decision": decision, "next_step_proposal": next_step,
            "will_execute": False, "will_resend": False,
            "steps": steps,
            "client_transport_reports": [
                {"incident_id": r["incident_id"], "signal": r["signal"],
                 "unverified_client_report": True} for r in reports
            ],
            "message": "ChatGPT stream continuity cannot be proved from BCT receipts."
        }
