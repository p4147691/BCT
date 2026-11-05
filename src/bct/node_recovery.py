"""Durable node-recovery building blocks for one Chain Message flow.

The ledger records observations and fences continuation delivery.  It never
decides that an AI node should be replaced, invents a successor, or replays an
UNKNOWN browser effect.  Replace and Reset are staged recipes so the caller can
inspect every boundary before an external message or tab close is attempted.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,96}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _valid_id(value: str, error: str) -> str:
    text = str(value or "").strip()
    if not _ID.fullmatch(text):
        raise ValueError(error)
    return text


def _valid_conversation(value: str, error: str = "NODE_RECOVERY_CONVERSATION_INVALID") -> str:
    text = str(value or "").strip().lower()
    if not _UUID.fullmatch(text):
        raise ValueError(error)
    return text


def observe_node(node_view: dict[str, Any], conversation_key: str) -> dict[str, Any]:
    """Normalize the current read-only node view into recovery evidence."""
    key = _valid_conversation(conversation_key)
    current = node_view.get("current_nodes") if isinstance(node_view, dict) else None
    items = current.get("items", []) if isinstance(current, dict) else []
    matches = [row for row in items if isinstance(row, dict)
               and str(row.get("conversation_uuid") or "").lower() == key]
    observation_state = ((current or {}).get("observation") or {}).get("state") \
        if isinstance(current, dict) else None
    observed_at = (current or {}).get("observed_at") if isinstance(current, dict) else None
    if len(matches) != 1:
        result = "CHECK"
        reason = "NODE_NOT_OBSERVED" if not matches else "NODE_IDENTITY_CONFLICT"
        row: dict[str, Any] = {}
    else:
        row = matches[0]
        if observation_state != "FRESH" or row.get("status") != "CONFIRMED":
            result, reason = "CHECK", "NODE_NOT_FRESH_CONFIRMED"
        elif row.get("generating") is True:
            result, reason = "WAIT", "NODE_GENERATING"
        else:
            result, reason = "OK", "NODE_READY"
    evidence = {
        "conversation_key": key,
        "result": result,
        "reason": reason,
        "observation_state": observation_state or "UNAVAILABLE",
        "observed_at": observed_at,
        "node": {
            field: row.get(field) for field in (
                "status", "node_number", "window_id", "tab_id", "generating",
                "name", "network", "network_id", "roles", "assigned_task",
            )
        } if row else None,
    }
    evidence["state_sha256"] = _digest({
        key: evidence[key] for key in (
            "conversation_key", "result", "reason", "observation_state", "node"
        )
    })
    evidence["evidence_sha256"] = _digest(evidence)
    return evidence


class NodeRecoveryLedger:
    """Small durable ledger shared by Check/Recheck/Pause/Replace/Reset."""

    ACTIVE_FENCE_STATES = frozenset({"PAUSED", "REPLACEMENT_PREPARED", "RESETTING", "RESET_UNKNOWN"})

    def __init__(self, store):
        self.store = store
        # Pause/Replace operate on the existing Delayed Send ledger. Some
        # read-only recovery tests create this ledger before any chain has run.
        from .delayed_send_message import DurableWatchLedger
        DurableWatchLedger(store)
        with self.store.transaction() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS node_recovery_cases (
                    case_id TEXT PRIMARY KEY, work_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL, assignment_epoch INTEGER NOT NULL,
                    task_id TEXT NOT NULL, conversation_key TEXT NOT NULL,
                    state TEXT NOT NULL, replacement_conversation_key TEXT NOT NULL DEFAULT '',
                    inheritance_task_id TEXT NOT NULL DEFAULT '', context_json TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS node_recovery_checks (
                    case_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    kind TEXT NOT NULL, result TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL, evidence_json TEXT NOT NULL,
                    created_at REAL NOT NULL, PRIMARY KEY(case_id,sequence),
                    FOREIGN KEY(case_id) REFERENCES node_recovery_cases(case_id)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_node_recovery_active "
                       "ON node_recovery_cases(work_id,conversation_key,state)")

    @staticmethod
    def _owned(row, work) -> bool:
        return (row is not None and row["work_id"] == work.work_id
                and row["principal_id"] == work.owner_principal_id
                and int(row["assignment_epoch"]) == work.assignment_epoch)

    def _case(self, db, case_id: str):
        return db.execute("SELECT * FROM node_recovery_cases WHERE case_id=?", (case_id,)).fetchone()

    def check(self, *, work, case_id: str, task_id: str,
              conversation_key: str, evidence: dict[str, Any], kind: str) -> dict[str, Any]:
        case_id = _valid_id(case_id, "NODE_RECOVERY_CASE_ID_INVALID")
        task_id = _valid_id(task_id, "NODE_RECOVERY_TASK_ID_INVALID") if task_id else ""
        conversation_key = _valid_conversation(conversation_key)
        if kind not in {"CHECK", "RECHECK"}:
            raise ValueError("NODE_RECOVERY_CHECK_KIND_INVALID")
        when = time.time()
        with self.store.transaction() as db:
            row = self._case(db, case_id)
            if row is None:
                if kind != "CHECK":
                    raise ValueError("NODE_RECOVERY_CASE_NOT_FOUND")
                db.execute(
                    "INSERT INTO node_recovery_cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (case_id, work.work_id, work.owner_principal_id, work.assignment_epoch,
                     task_id, conversation_key, "CHECKED", "", "", "{}", when, when),
                )
                row = self._case(db, case_id)
            if not self._owned(row, work):
                raise ValueError("NODE_RECOVERY_CASE_NOT_FOUND")
            if row["conversation_key"] != conversation_key or row["task_id"] != task_id:
                raise ValueError("NODE_RECOVERY_CASE_CONFLICT")
            sequence = int(db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM node_recovery_checks WHERE case_id=?",
                (case_id,),
            ).fetchone()[0])
            previous = db.execute(
                "SELECT result,evidence_sha256,evidence_json FROM node_recovery_checks WHERE case_id=? "
                "ORDER BY sequence DESC LIMIT 1", (case_id,),
            ).fetchone()
            encoded = _canonical(evidence)
            db.execute(
                "INSERT INTO node_recovery_checks VALUES(?,?,?,?,?,?,?)",
                (case_id, sequence, kind, evidence["result"], evidence["evidence_sha256"], encoded, when),
            )
            db.execute("UPDATE node_recovery_cases SET updated_at=? WHERE case_id=?", (when, case_id))
        previous_evidence = json.loads(previous["evidence_json"]) if previous else {}
        unchanged = bool(previous and previous_evidence.get("state_sha256") == evidence["state_sha256"])
        if evidence["result"] == "OK":
            next_action = "CONTINUE"
        elif evidence["result"] == "WAIT":
            next_action = "RECHECK"
        elif kind == "CHECK":
            next_action = "RECHECK"
        else:
            next_action = "PAUSE_REVIEW"
        return {
            "case_id": case_id, "sequence": sequence, "kind": kind,
            "result": evidence["result"], "reason": evidence["reason"],
            "unchanged": unchanged, "next_action": next_action,
            "evidence": evidence,
        }

    def get(self, *, work, case_id: str) -> dict[str, Any] | None:
        case_id = _valid_id(case_id, "NODE_RECOVERY_CASE_ID_INVALID")
        with self.store._readonly() as db:
            row = self._case(db, case_id)
            if not self._owned(row, work):
                return None
            latest = db.execute(
                "SELECT * FROM node_recovery_checks WHERE case_id=? ORDER BY sequence DESC LIMIT 1",
                (case_id,),
            ).fetchone()
        value = dict(row)
        value["context"] = json.loads(value.pop("context_json") or "{}")
        if latest is not None:
            value["latest_check"] = {**dict(latest), "evidence": json.loads(latest["evidence_json"])}
            value["latest_check"].pop("evidence_json", None)
        return value

    def pause(self, *, work, case_id: str, reason: str) -> dict[str, Any]:
        reason = str(reason or "").strip()
        if not reason or len(reason) > 500:
            raise ValueError("NODE_RECOVERY_PAUSE_REASON_INVALID")
        when = time.time()
        with self.store.transaction() as db:
            row = self._case(db, case_id)
            if not self._owned(row, work):
                raise ValueError("NODE_RECOVERY_CASE_NOT_FOUND")
            if row["state"] in {"REPLACED", "RESET", "RESET_UNKNOWN"}:
                raise ValueError("NODE_RECOVERY_CASE_TERMINAL")
            context = json.loads(row["context_json"] or "{}")
            context.setdefault("pause", {"reason": reason, "at": when})
            paused = db.execute(
                "UPDATE delayed_send_watches SET state='PAUSED' "
                "WHERE state IN ('WATCHING','RESERVED') "
                "AND json_extract(context_json,'$.work_id')=? "
                "AND conversation_key=?",
                (work.work_id, row["conversation_key"]),
            ).rowcount
            context["pause"]["delayed_send_count"] = paused
            db.execute("UPDATE node_recovery_cases SET state='PAUSED',context_json=?,updated_at=? "
                       "WHERE case_id=?", (_canonical(context), when, case_id))
        return {"case_id": case_id, "state": "PAUSED", "delayed_sends_paused": paused,
                "warning": "UNKNOWN_EFFECTS_ARE_NOT_REPLAYED"}

    def assert_send_allowed(self, *, work_id: str, conversation_key: str) -> None:
        key = _valid_conversation(conversation_key)
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT case_id,state FROM node_recovery_cases WHERE work_id=? AND conversation_key=? "
                "AND state IN ('PAUSED','REPLACEMENT_PREPARED','RESETTING','RESET_UNKNOWN') "
                "ORDER BY updated_at DESC LIMIT 1", (work_id, key),
            ).fetchone()
        if row is not None:
            raise ValueError("NODE_RECOVERY_SEND_FENCED:" + str(row["case_id"]))

    def assert_task_send_allowed(self, *, work_id: str, task_id: str) -> None:
        task = _valid_id(task_id, "NODE_RECOVERY_TASK_ID_INVALID")
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT c.case_id FROM node_recovery_cases c "
                "JOIN delayed_send_watches d ON d.conversation_key=c.conversation_key "
                "WHERE c.work_id=? AND d.task_id=? "
                "AND c.state IN ('PAUSED','REPLACEMENT_PREPARED','RESETTING','RESET_UNKNOWN') "
                "AND json_extract(d.context_json,'$.work_id')=c.work_id "
                "ORDER BY c.updated_at DESC LIMIT 1", (work_id, task),
            ).fetchone()
        if row is not None:
            raise ValueError("NODE_RECOVERY_SEND_FENCED:" + str(row["case_id"]))

    def prepare_replace(self, *, work, case_id: str, successor_conversation_key: str,
                        inheritance_task_id: str, successor_evidence: dict[str, Any]) -> dict[str, Any]:
        successor = _valid_conversation(successor_conversation_key, "NODE_REPLACEMENT_SUCCESSOR_INVALID")
        inheritance = _valid_id(inheritance_task_id, "NODE_REPLACEMENT_TASK_ID_INVALID")
        if successor_evidence.get("result") != "OK":
            raise ValueError("NODE_REPLACEMENT_SUCCESSOR_NOT_READY")
        when = time.time()
        with self.store.transaction() as db:
            row = self._case(db, case_id)
            if not self._owned(row, work):
                raise ValueError("NODE_RECOVERY_CASE_NOT_FOUND")
            if row["state"] not in {"PAUSED", "REPLACEMENT_PREPARED"}:
                raise ValueError("NODE_REPLACEMENT_REQUIRES_PAUSE")
            if row["conversation_key"] == successor:
                raise ValueError("NODE_REPLACEMENT_SUCCESSOR_SAME")
            if row["state"] == "REPLACEMENT_PREPARED" and (
                    row["replacement_conversation_key"] != successor
                    or row["inheritance_task_id"] != inheritance):
                raise ValueError("NODE_REPLACEMENT_CONFLICT")
            context = json.loads(row["context_json"] or "{}")
            context["replacement"] = {
                "successor_conversation_key": successor,
                "inheritance_task_id": inheritance,
                "successor_evidence_sha256": successor_evidence["evidence_sha256"],
                "prepared_at": when,
            }
            db.execute(
                "UPDATE node_recovery_cases SET state='REPLACEMENT_PREPARED',"
                "replacement_conversation_key=?,inheritance_task_id=?,context_json=?,updated_at=? "
                "WHERE case_id=?",
                (successor, inheritance, _canonical(context), when, case_id),
            )
        instruction = (
            "[BCT NODE REPLACEMENT]\n"
            f"Recovery case: {case_id}\nPrior task: {row['task_id'] or '(none)'}\n"
            "Continue only from the next incomplete step. Read exact BCT receipts first. "
            "Never replay an UNKNOWN external effect. Create a new execution plan for your own turn."
        )
        return {"case_id": case_id, "state": "REPLACEMENT_PREPARED",
                "successor_conversation_key": successor,
                "inheritance_task_id": inheritance, "inheritance_instruction": instruction}

    def commit_replace(self, *, work, case_id: str, successor_evidence: dict[str, Any]) -> dict[str, Any]:
        when = time.time()
        with self.store.transaction() as db:
            row = self._case(db, case_id)
            if not self._owned(row, work):
                raise ValueError("NODE_RECOVERY_CASE_NOT_FOUND")
            if row["state"] == "REPLACED":
                return {"case_id": case_id, "state": "REPLACED", "duplicate": True,
                        "successor_conversation_key": row["replacement_conversation_key"]}
            if row["state"] != "REPLACEMENT_PREPARED" or successor_evidence.get("result") != "OK":
                raise ValueError("NODE_REPLACEMENT_NOT_READY")
            watch = db.execute(
                "SELECT state,conversation_key,context_json FROM delayed_send_watches "
                "WHERE task_id=? ORDER BY generation DESC LIMIT 1",
                (row["inheritance_task_id"],),
            ).fetchone()
            if watch is None or watch["conversation_key"] != row["replacement_conversation_key"]:
                raise ValueError("NODE_REPLACEMENT_INHERITANCE_NOT_SENT")
            binding = json.loads(watch["context_json"] or "{}")
            # A successor can finish its first inheritance response before a
            # Manager authors a next instruction.  That is still a confirmed
            # inheritance delivery, not a failed or unknown send.  Keep the
            # evidence requirement: only this explicit terminal state may
            # join the existing watched/returned states.
            if binding.get("work_id") != work.work_id or watch["state"] not in {
                    "WATCHING", "SELF_SENT", "RETURNED_TO_MANAGER",
                    "MANAGER_DECISION_REQUIRED"}:
                raise ValueError("NODE_REPLACEMENT_INHERITANCE_NOT_READY")
            # Keep inheritance proof, advisory role/scope transfer, old-watch
            # retirement and recovery-case completion in one transaction.  A
            # role uniqueness failure therefore leaves the predecessor PAUSED
            # and does not partially promote the successor.
            from .conversation_network import _transfer_conversation_state
            transferred = _transfer_conversation_state(
                db,
                predecessor=str(row["conversation_key"]),
                successor=str(row["replacement_conversation_key"]),
                when=when,
            )
            db.execute(
                "UPDATE delayed_send_watches SET state='CANCELLED' WHERE state='PAUSED' "
                "AND json_extract(context_json,'$.work_id')=? AND conversation_key=?",
                (work.work_id, row["conversation_key"]),
            )
            db.execute("UPDATE node_recovery_cases SET state='REPLACED',updated_at=? WHERE case_id=?",
                       (when, case_id))
        return {"case_id": case_id, "state": "REPLACED", "duplicate": False,
                "successor_conversation_key": row["replacement_conversation_key"],
                "inheritance_task_id": row["inheritance_task_id"],
                "conversation_state": transferred}

    def prepare_reset(self, *, work, case_id: str, node_evidence: dict[str, Any]) -> dict[str, Any]:
        when = time.time()
        with self.store.transaction() as db:
            row = self._case(db, case_id)
            if not self._owned(row, work):
                raise ValueError("NODE_RECOVERY_CASE_NOT_FOUND")
            if row["state"] not in {"PAUSED", "REPLACED", "RESETTING", "RESET_UNKNOWN"}:
                raise ValueError("NODE_RESET_REQUIRES_PAUSE_OR_REPLACEMENT")
            context = json.loads(row["context_json"] or "{}")
            context.setdefault("reset_snapshot", {
                "captured_at": when, "node_evidence": node_evidence,
                "historical_node_number": ((node_evidence.get("node") or {}).get("node_number")),
            })
            db.execute("UPDATE node_recovery_cases SET state='RESETTING',context_json=?,updated_at=? "
                       "WHERE case_id=?", (_canonical(context), when, case_id))
        return {"case_id": case_id, "state": "RESETTING",
                "snapshot_sha256": _digest(context["reset_snapshot"]),
                "node_number_policy": "HISTORICAL_ONLY_NEW_NUMBER_ON_RESTORE"}

    def finish_reset(self, *, work, case_id: str, close_outcome: str,
                     operation_id: str) -> dict[str, Any]:
        if close_outcome not in {"APPLIED", "NOT_APPLIED", "UNKNOWN"}:
            raise ValueError("NODE_RESET_CLOSE_OUTCOME_INVALID")
        when = time.time()
        state = {"APPLIED": "RESET", "NOT_APPLIED": "RESET_FAILED", "UNKNOWN": "RESET_UNKNOWN"}[close_outcome]
        with self.store.transaction() as db:
            row = self._case(db, case_id)
            if not self._owned(row, work):
                raise ValueError("NODE_RECOVERY_CASE_NOT_FOUND")
            context = json.loads(row["context_json"] or "{}")
            context["reset_close"] = {"operation_id": operation_id, "outcome": close_outcome, "at": when}
            if close_outcome == "APPLIED":
                db.execute(
                    "UPDATE delayed_send_watches SET state='CANCELLED' WHERE state='PAUSED' "
                    "AND json_extract(context_json,'$.work_id')=? AND conversation_key=?",
                    (work.work_id, row["conversation_key"]),
                )
            db.execute("UPDATE node_recovery_cases SET state=?,context_json=?,updated_at=? WHERE case_id=?",
                       (state, _canonical(context), when, case_id))
        return {"case_id": case_id, "state": state, "close_outcome": close_outcome,
                "warning": "DO_NOT_RETRY_UNKNOWN" if close_outcome == "UNKNOWN" else ""}
