"""Durable node-recovery building blocks for one Chain delivery flow.

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
        connection = row.get("connection") if isinstance(row.get("connection"), dict) else {}
        telemetry = row.get("telemetry") if isinstance(row.get("telemetry"), dict) else {}
        attention = telemetry.get("user_attention") \
            if isinstance(telemetry.get("user_attention"), dict) else {}
        attention_kind = str(attention.get("kind") or "").strip().upper()
        if observation_state != "FRESH" or row.get("status") != "CONFIRMED":
            result, reason = "CHECK", "NODE_NOT_FRESH_CONFIRMED"
        elif connection.get("disconnected") is True:
            result, reason = "CHECK", "NODE_CONNECTION_DISCONNECTED"
        elif attention_kind == "RETRY_REQUIRED":
            result, reason = "CHECK", "NODE_RETRY_REQUIRED"
        elif attention_kind == "NEW_CHAT_REQUIRED":
            result, reason = "CHECK", "NODE_NEW_CHAT_REQUIRED"
        elif attention_kind == "RECOVERY_REQUIRED":
            result, reason = "CHECK", "NODE_RECOVERY_REQUIRED"
        elif row.get("generating") is True:
            result, reason = "WAIT", "NODE_GENERATING"
        else:
            result, reason = "OK", "NODE_READY"
    connection = row.get("connection") if isinstance(row.get("connection"), dict) else {}
    telemetry = row.get("telemetry") if isinstance(row.get("telemetry"), dict) else {}
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
        "activity": {
            "connection": {
                "disconnected": connection.get("disconnected")
                if type(connection.get("disconnected")) is bool else None,
                "reason": str(connection.get("reason") or "")[:160],
            },
            "generating": row.get("generating") is True if row else False,
            "generation_state": str(telemetry.get("generation_state") or "")[:32],
            "readiness": str(telemetry.get("readiness") or "")[:32],
            "last_activity_at": telemetry.get("last_activity_at"),
            "generation_started_at": telemetry.get("generation_started_at"),
            "generation_finished_at": telemetry.get("generation_finished_at"),
            "rendered_chars": telemetry.get("rendered_chars"),
            "turns": telemetry.get("turns"),
            "user_attention": telemetry.get("user_attention")
            if isinstance(telemetry.get("user_attention"), dict) else None,
            "signal_source": str(telemetry.get("signal_source") or "")[:32],
        },
    }
    evidence["state_sha256"] = _digest({
        key: evidence[key] for key in (
            "conversation_key", "result", "reason", "observation_state", "node", "activity"
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
        from .send_delayed_message import DurableWatchLedger
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

    @staticmethod
    def _attach_existing_task_activity(
        db, *, evidence: dict[str, Any], work_id: str, task_id: str,
        conversation_key: str,
    ) -> None:
        """Join existing task/operation progress without creating another receipt."""
        activity: dict[str, Any] | None = None
        if task_id:
            watch = db.execute(
                "SELECT generation,state,conversation_key,context_json "
                "FROM delayed_send_watches WHERE task_id=? "
                "ORDER BY generation DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if watch is not None and str(watch["conversation_key"]) == conversation_key:
                context = json.loads(watch["context_json"] or "{}")
                if context.get("work_id") in {None, "", work_id}:
                    activity = {
                        "generation": int(watch["generation"]),
                        "state": str(watch["state"]),
                        "response_observed": bool(
                            context.get("observed_response_turn_key")
                            or context.get("observed_response_sha")
                        ),
                    }
                    operation_id = str(context.get("source_send_operation_id") or "")
                    if operation_id:
                        operation = db.execute(
                            "SELECT operation_id,capability,state,outcome,updated_at "
                            "FROM operations WHERE operation_id=? AND work_id=?",
                            (operation_id, work_id),
                        ).fetchone()
                        if operation is not None:
                            activity["source_operation"] = {
                                "operation_id": str(operation["operation_id"]),
                                "capability": str(operation["capability"]),
                                "state": str(operation["state"]),
                                "outcome": str(operation["outcome"] or ""),
                                "updated_at": operation["updated_at"],
                            }
        evidence["task_activity"] = activity
        evidence["state_sha256"] = _digest({
            key: evidence.get(key) for key in (
                "conversation_key", "result", "reason", "observation_state",
                "node", "activity", "task_activity",
            )
        })
        evidence["evidence_sha256"] = _digest({
            key: value for key, value in evidence.items() if key != "evidence_sha256"
        })

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
            self._attach_existing_task_activity(
                db, evidence=evidence, work_id=work.work_id, task_id=task_id,
                conversation_key=conversation_key,
            )
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
        elif not unchanged:
            next_action = "RECHECK"
        else:
            next_action = "RESTART"
        return {
            "case_id": case_id, "sequence": sequence, "kind": kind,
            "result": evidence["result"], "reason": evidence["reason"],
            "unchanged": unchanged, "progress_changed": bool(previous and not unchanged),
            "next_action": next_action,
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

    def mark_automatic_observation(
        self, *, work, case_id: str, state: str, reason: str,
    ) -> bool:
        """Persist a Core observation result, not an external recovery effect.

        Only the auto-node-* cases are advanced. A manual Pause/Replace/Reset
        case cannot be cleared by a routine background observation.
        """
        if not str(case_id).startswith("auto-node-"):
            raise ValueError("NODE_AUTOMATIC_CASE_REQUIRED")
        if state not in {"RECOVERY_NEEDED", "RECOVERED"}:
            raise ValueError("NODE_AUTOMATIC_STATE_INVALID")
        with self.store.transaction() as db:
            row = self._case(db, case_id)
            if not self._owned(row, work):
                return False
            if str(row["state"]) in {
                "PAUSED", "REPLACEMENT_PREPARED", "REPLACED",
                "RESETTING", "RESET_UNKNOWN", "RESET",
            }:
                return False
            context = json.loads(row["context_json"] or "{}")
            context["automatic_node_observation"] = {
                "state": state, "reason": reason, "at": time.time(),
            }
            return db.execute(
                "UPDATE node_recovery_cases SET state=?,context_json=?,updated_at=? "
                "WHERE case_id=? AND work_id=? AND assignment_epoch=?",
                (state, _canonical(context), time.time(), case_id,
                 work.work_id, work.assignment_epoch),
            ).rowcount == 1

    def pause(self, *, work, case_id: str, reason: str,
              automatic_intent: dict[str, Any] | None = None) -> dict[str, Any]:
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
            if automatic_intent is not None:
                if (not str(case_id).startswith("auto-node-")
                        or row["state"] not in {"RECOVERY_NEEDED", "CHECKED"}
                        or context.get("automatic_new_chat_intent")):
                    raise ValueError("NODE_AUTO_BOOTSTRAP_INTENT_CONFLICT")
                if not (isinstance(automatic_intent, dict)
                        and automatic_intent.get("operation_id")
                        and automatic_intent.get("instruction")
                        and automatic_intent.get("instance_id")
                        and automatic_intent.get("target_ref")
                        and automatic_intent.get("window_id")):
                    raise ValueError("NODE_AUTO_BOOTSTRAP_INTENT_INVALID")
                context["automatic_new_chat_intent"] = automatic_intent
            # A Core-initiated pause must be reversible when the SAME exact
            # conversation UUID recovers. Store original Watch state before
            # the mutation, without duplicating message content or receipts.
            if str(case_id).startswith("auto-node-"):
                original = [
                    {"task_id": str(item["task_id"]),
                     "generation": int(item["generation"]),
                     "state": str(item["state"])}
                    for item in db.execute(
                        "SELECT task_id,generation,state FROM delayed_send_watches "
                        "WHERE state IN ('WATCHING','RESERVED') "
                        "AND json_extract(context_json,'$.work_id')=? "
                        "AND conversation_key=? ORDER BY task_id,generation",
                        (work.work_id, row["conversation_key"]),
                    )
                ]
                context["automatic_watch_restore"] = original
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

    def restore_automatic_predecessor(
        self, *, work, case_id: str, evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """Restore original Watch states only after the exact old UUID recovers.

        Never clears a manual pause, prepared replacement or UNKNOWN effect;
        all changes and case closure occur inside one SQLite transaction.
        """
        if not str(case_id).startswith("auto-node-"):
            raise ValueError("NODE_AUTOMATIC_CASE_REQUIRED")
        if (evidence.get("result") != "OK"
                or evidence.get("observation_state") != "FRESH"):
            raise ValueError("NODE_RECOVERY_POSITIVE_IDENTITY_REQUIRED")
        when = time.time()
        with self.store.transaction() as db:
            row = self._case(db, case_id)
            if not self._owned(row, work) or row["state"] != "PAUSED":
                raise ValueError("NODE_AUTO_RESTORE_PAUSED_REQUIRED")
            if evidence.get("conversation_key") != row["conversation_key"]:
                raise ValueError("NODE_AUTO_RESTORE_IDENTITY_CHANGED")
            context = json.loads(row["context_json"] or "{}")
            intent = context.get("automatic_new_chat_intent")
            if intent:
                # Core may cancel its own pending bootstrap only when the
                # original external create/send was conclusively never sent.
                opid = str(intent.get("operation_id") or "")
                if not opid:
                    raise ValueError("NODE_AUTO_RESTORE_INTENT_INVALID")
                operation = db.execute(
                    "SELECT state,outcome FROM operations "
                    "WHERE operation_id=? AND work_id=?",
                    (opid, work.work_id),
                ).fetchone()
                if operation is not None and not (
                    operation["state"] == "FINISHED"
                    and operation["outcome"] == "NOT_APPLIED"
                ):
                    raise ValueError("NODE_AUTO_RESTORE_EXTERNAL_EFFECT_UNCERTAIN")
                context.pop("automatic_new_chat_intent", None)
                context["automatic_bootstrap_cancelled"] = opid
            restore = context.get("automatic_watch_restore")
            if not isinstance(restore, list):
                raise ValueError("NODE_AUTO_RESTORE_HISTORY_MISSING")
            # Never partially unpause if another recovery step changed one
            # of the original generation states while we were offline.
            for item in restore:
                if item["state"] not in {"WATCHING", "RESERVED"}:
                    raise ValueError("NODE_AUTO_RESTORE_STATE_INVALID")
                actual = db.execute(
                    "SELECT state,conversation_key,context_json FROM delayed_send_watches "
                    "WHERE task_id=? AND generation=?",
                    (item["task_id"],item["generation"]),
                ).fetchone()
                if actual is None or actual["state"] != "PAUSED" or (
                        actual["conversation_key"] != row["conversation_key"]):
                    raise ValueError("NODE_AUTO_RESTORE_WATCH_CHANGED")
                if json.loads(actual["context_json"] or "{}").get("work_id") != work.work_id:
                    raise ValueError("NODE_AUTO_RESTORE_FOREIGN_WORK")
            for item in restore:
                db.execute(
                    "UPDATE delayed_send_watches SET state=? "
                    "WHERE task_id=? AND generation=? AND state='PAUSED'",
                    (item["state"],item["task_id"],item["generation"]),
                )
            context["automatic_resumed_at"] = when
            db.execute(
                "UPDATE node_recovery_cases SET state='RECOVERED',context_json=?,updated_at=? "
                "WHERE case_id=? AND work_id=? AND assignment_epoch=?",
                (_canonical(context),when,case_id,work.work_id,work.assignment_epoch),
            )
        return {"case_id":case_id,"state":"RECOVERED",
                "restored_watches":len(restore),
                "effects":"DURABLE_WATCH_STATE_ONLY_NO_EXTERNAL_SEND"}

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

    @staticmethod
    def _verified_atomic_bootstrap(db, *, work, operation_id: str,
                                   successor_conversation_key: str) -> dict[str, Any]:
        """Verify one existing BCT+RCC atomic new-chat send/reply receipt.

        Never infer a UUID or trust a caller's result: every field derives
        from the ORIGINAL Work's durable Operation, not a new message.
        """
        result = db.execute(
            "SELECT state,outcome,capability,assignment_epoch,principal_id,evidence_json "
            "FROM operations WHERE work_id=? AND operation_id=?",
            (work.work_id, operation_id),
        ).fetchone()
        if result is None or not (
            result["state"] == "FINISHED" and result["outcome"] == "APPLIED"
            and result["capability"] == "browser"
            and int(result["assignment_epoch"]) == work.assignment_epoch
            and result["principal_id"] == work.owner_principal_id
        ):
            raise ValueError("NODE_REPLACEMENT_ATOMIC_RECEIPT_NOT_APPLIED")
        proof = json.loads(result["evidence_json"] or "{}")
        if not (
            proof.get("command") in {"create-and-send", "new-chat-send"}
            and proof.get("rcc_command") == "new-chat-send"
            and proof.get("result_state") == "RESULT_PERSISTED"
            and proof.get("conversation_key") == successor_conversation_key
            and isinstance(proof.get("result_hash"), str)
            and re.fullmatch(r"[a-f0-9]{64}", proof["result_hash"])
            and str(proof.get("session_id") or "")
            and str(proof.get("instance_id") or "")
            and type(proof.get("tab_id")) is int and proof["tab_id"] > 0
            and type(proof.get("window_id")) is int and proof["window_id"] > 0
        ):
            raise ValueError("NODE_REPLACEMENT_ATOMIC_RECEIPT_IDENTITY_INVALID")
        return proof

    def prepare_replace(self, *, work, case_id: str, successor_conversation_key: str,
                        inheritance_task_id: str, successor_evidence: dict[str, Any],
                        atomic_inheritance_operation_id: str = "") -> dict[str, Any]:
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
            if atomic_inheritance_operation_id:
                if successor_evidence.get("conversation_key") != successor:
                    raise ValueError("NODE_REPLACEMENT_SUCCESSOR_EVIDENCE_IDENTITY_INVALID")
                self._verified_atomic_bootstrap(
                    db, work=work, operation_id=atomic_inheritance_operation_id,
                    successor_conversation_key=successor,
                )
            context["replacement"] = {
                "successor_conversation_key": successor,
                "inheritance_task_id": inheritance,
                "successor_evidence_sha256": successor_evidence["evidence_sha256"],
                "atomic_inheritance_operation_id": atomic_inheritance_operation_id,
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
        # Additive schema initialization occurs outside the replacement TX.
        # Auto-new-chat first-submit evidence itself is stored by Operations.
        from .chain_manager_recovery import ChainManagerRecoveryLedger
        recovery_ledger = ChainManagerRecoveryLedger(self.store)
        with self.store.transaction() as db:
            row = self._case(db, case_id)
            if not self._owned(row, work):
                raise ValueError("NODE_RECOVERY_CASE_NOT_FOUND")
            if row["state"] == "REPLACED":
                return {"case_id": case_id, "state": "REPLACED", "duplicate": True,
                        "successor_conversation_key": row["replacement_conversation_key"]}
            if row["state"] != "REPLACEMENT_PREPARED" or successor_evidence.get("result") != "OK":
                raise ValueError("NODE_REPLACEMENT_NOT_READY")
            context = json.loads(row["context_json"] or "{}")
            atomic_id = str((context.get("replacement") or {}).get(
                "atomic_inheritance_operation_id") or "")
            if atomic_id:
                # A verified atomic RCC new-chat operation already contains
                # first submit, actual UUID and a persisted first AI answer.
                # Do not fabricate a Watch retroactively or replay its first
                # instruction. Its reply hash stays in the source Operation.
                self._verified_atomic_bootstrap(
                    db, work=work, operation_id=atomic_id,
                    successor_conversation_key=row["replacement_conversation_key"],
                )
            else:
                watch = db.execute(
                    "SELECT state,conversation_key,context_json FROM delayed_send_watches "
                    "WHERE task_id=? ORDER BY generation DESC LIMIT 1",
                    (row["inheritance_task_id"],),
                ).fetchone()
                if watch is None or watch["conversation_key"] != row["replacement_conversation_key"]:
                    raise ValueError("NODE_REPLACEMENT_INHERITANCE_NOT_SENT")
                binding = json.loads(watch["context_json"] or "{}")
                if binding.get("work_id") != work.work_id or watch["state"] not in {
                        "WATCHING", "SELF_SENT", "RETURNED_TO_MANAGER",
                        "MANAGER_DECISION_REQUIRED"}:
                    raise ValueError("NODE_REPLACEMENT_INHERITANCE_NOT_READY")
            # Keep inheritance proof, advisory role/scope transfer, old-watch
            # retirement and recovery-case completion in one transaction.  A
            # role uniqueness failure therefore leaves the predecessor PAUSED
            # and does not partially promote the successor.
            from .conversation_network import _transfer_conversation_state
            old_key = str(row["conversation_key"])
            new_key = str(row["replacement_conversation_key"])
            roles = [str(r["tag"]).casefold() for r in db.execute(
                "SELECT tag FROM conversation_network_membership_tags "
                "WHERE conversation_key=?", (old_key,),
            )]
            unassigned = db.execute(
                "SELECT unassigned_role_tags FROM conversation_network_conversations "
                "WHERE conversation_key=?", (old_key,),
            ).fetchone()
            if unassigned is not None:
                try:
                    roles.extend(str(t).casefold() for t in
                                 json.loads(unassigned["unassigned_role_tags"] or "[]"))
                except (TypeError, ValueError):
                    pass
            is_supervisor = "supervisor" in roles
            supervisor_binding_recovery = None
            # A global S can have watches from unrelated Work. Every binding
            # must move in the SAME transaction as the role transfer, and
            # ambiguous external sends cannot be silently retargeted.
            if is_supervisor:
                attachment = successor_evidence.get("verified_rcc_attachment")
                if (not isinstance(attachment, dict)
                        or not str(attachment.get("instance_id") or "")
                        or not str(attachment.get("session_id") or "")):
                    raise ValueError("NODE_SUPERVISOR_EXACT_RCC_BINDING_REQUIRED")
                pending = db.execute(
                    "SELECT 1 FROM delayed_send_watches "
                    "WHERE json_extract(context_json,'$.supervisor_conversation_key')=? "
                    "AND state IN ('UNKNOWN','DISPATCHING') LIMIT 1",
                    (old_key,),
                ).fetchone()
                if pending:
                    raise ValueError("NODE_SUPERVISOR_UNCERTAIN_WATCH_RECONCILIATION_REQUIRED")
                table = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='chain_manager_return_checkpoints'",
                ).fetchone()
                if table is not None:
                    inflight = db.execute(
                        "SELECT 1 FROM chain_manager_return_checkpoints "
                        "WHERE supervisor_conversation_key=? AND acknowledged_at=0 "
                        "AND (delivery_state IN ('UNKNOWN','DELIVERING') "
                        "OR (destination_conversation_key=? AND delivery_state='PENDING')) "
                        "LIMIT 1", (old_key, old_key),
                    ).fetchone()
                    if inflight:
                        raise ValueError("NODE_SUPERVISOR_UNCERTAIN_RETURN_RECONCILIATION_REQUIRED")
                # Global S may span several independently owned Works. The
                # original Work's principal cannot claim another owner's
                # Watch/return by a local automatic replacement.
                affected = {
                    str(item["work_id"]): str(item["owner_principal_id"])
                    for item in db.execute(
                        "SELECT DISTINCT w.work_id,w.owner_principal_id "
                        "FROM works w WHERE w.state='ACTIVE' AND ("
                        "EXISTS (SELECT 1 FROM delayed_send_watches d "
                        "WHERE json_extract(d.context_json,'$.work_id')=w.work_id "
                        "AND json_extract(d.context_json,'$.supervisor_conversation_key')=?) "
                        "OR EXISTS (SELECT 1 FROM chain_manager_return_checkpoints c "
                        "WHERE c.work_id=w.work_id "
                        "AND c.supervisor_conversation_key=? AND c.acknowledged_at=0))",
                        (old_key, old_key),
                    )
                }
                if any(owner != work.owner_principal_id
                       for owner in affected.values()):
                    raise ValueError("NODE_SUPERVISOR_GLOBAL_WORK_OWNER_CONFLICT")
                open_watches = list(db.execute(
                    "SELECT task_id,generation,context_json FROM delayed_send_watches "
                    "WHERE json_extract(context_json,'$.supervisor_conversation_key')=? "
                    "AND state IN ('WATCHING','RESERVED','PAUSED',"
                    "'MANAGER_RECOVERY_PENDING') ORDER BY task_id,generation",
                    (old_key,),
                ).fetchall())
                changed_contexts = []
                for watcher in open_watches:
                    ctx = json.loads(watcher["context_json"] or "{}")
                    history = ctx.get("supervisor_recovery_history")
                    if not isinstance(history, list):
                        history = []
                    history.append({
                        "from_supervisor_conversation_key": old_key,
                        "to_supervisor_conversation_key": new_key,
                        "recovery_case_id": case_id,
                        "old_supervisor_instance_id":
                            str(ctx.get("supervisor_instance_id") or ""),
                    })
                    ctx["supervisor_recovery_history"] = history[-8:]
                    ctx["supervisor_conversation_key"] = new_key
                    ctx["supervisor_instance_id"] = str(attachment["instance_id"])
                    changed_contexts.append((
                        _canonical(ctx), watcher["task_id"], watcher["generation"],
                    ))
                for context, task, generation in changed_contexts:
                    db.execute(
                        "UPDATE delayed_send_watches SET context_json=? "
                        "WHERE task_id=? AND generation=?",
                        (context, task, generation),
                    )
                # The original Supervisor recipient is immutable provenance.
                # The active routing alias is a separate field, updated for
                # every unacknowledged Work in this SAME role/Watch transaction.
                if table is not None:
                    existing_columns = {
                        str(column["name"]) for column in db.execute(
                            "PRAGMA table_info(chain_manager_return_checkpoints)"
                        )
                    }
                    if "active_supervisor_conversation_key" not in existing_columns:
                        db.execute(
                            "ALTER TABLE chain_manager_return_checkpoints "
                            "ADD COLUMN active_supervisor_conversation_key "
                            "TEXT NOT NULL DEFAULT ''"
                        )
                        db.execute(
                            "UPDATE chain_manager_return_checkpoints SET "
                            "active_supervisor_conversation_key=supervisor_conversation_key"
                        )
                    updated_returns = db.execute(
                        "UPDATE chain_manager_return_checkpoints SET "
                        "active_supervisor_conversation_key=?,updated_at=? "
                        "WHERE acknowledged_at=0 "
                        "AND active_supervisor_conversation_key=?",
                        (new_key, when, old_key),
                    ).rowcount
                else:
                    updated_returns = 0
                supervisor_binding_recovery = {
                    "affected_works": sorted(affected),
                    "updated_watches": len(changed_contexts),
                    "updated_returns": updated_returns,
                    "unresolved_delivery_claims": 0,
                    "complete": True,
                    "atomic": True,
                }
            transferred = _transfer_conversation_state(
                db,
                predecessor=str(row["conversation_key"]),
                successor=str(row["replacement_conversation_key"]),
                when=when,
            )
            binding_recovery = None
            if (atomic_id and any(
                    str(tag).casefold() == "manager"
                    for tag in transferred.get("role_tags", []))):
                proof = self._verified_atomic_bootstrap(
                    db, work=work, operation_id=atomic_id,
                    successor_conversation_key=row["replacement_conversation_key"],
                )
                binding_recovery = recovery_ledger.rebind_active_manager_atomic(
                    work_id=work.work_id,
                    manager_conversation_key=row["replacement_conversation_key"],
                    manager_instance_id=str(proof["instance_id"]),
                    succession_proofs=[{
                        "predecessor_conversation_key": row["conversation_key"],
                        "successor_conversation_key": row["replacement_conversation_key"],
                        "bootstrap_operation_id": atomic_id,
                    }],
                    transaction=db,
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
                "conversation_state": transferred,
                "manager_binding_recovery": binding_recovery,
                "supervisor_binding_recovery": supervisor_binding_recovery}

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
