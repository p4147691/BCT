from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import ConflictError, OperationResult, OperationState, Outcome, Work


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def _initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT, group_name TEXT,
                    revision INTEGER NOT NULL, active INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS connections (
                    connection_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, kind TEXT NOT NULL,
                    instance TEXT NOT NULL, endpoint TEXT NOT NULL, generation INTEGER NOT NULL,
                    active INTEGER NOT NULL, FOREIGN KEY(node_id) REFERENCES nodes(node_id)
                );
                CREATE TABLE IF NOT EXISTS works (
                    work_id TEXT PRIMARY KEY, request_summary TEXT NOT NULL, roots_json TEXT NOT NULL,
                    actions_json TEXT NOT NULL, owner_principal_id TEXT NOT NULL,
                    assignment_epoch INTEGER NOT NULL, state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY, work_id TEXT NOT NULL, principal_id TEXT NOT NULL,
                    request_digest TEXT NOT NULL, capability TEXT NOT NULL, target TEXT NOT NULL,
                    state TEXT NOT NULL, outcome TEXT, evidence_json TEXT NOT NULL,
                    error TEXT, assignment_epoch INTEGER NOT NULL, policy_revision TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    FOREIGN KEY(work_id) REFERENCES works(work_id)
                );
                CREATE TABLE IF NOT EXISTS resource_claims (
                    resource_key TEXT PRIMARY KEY, operation_id TEXT NOT NULL, work_id TEXT NOT NULL,
                    assignment_epoch INTEGER NOT NULL, unresolved INTEGER NOT NULL,
                    FOREIGN KEY(operation_id) REFERENCES operations(operation_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                    subject_id TEXT NOT NULL, data_json TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operation_steps (
                    operation_id TEXT NOT NULL, step_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                    capability TEXT NOT NULL, request_digest TEXT NOT NULL,
                    state TEXT NOT NULL, outcome TEXT, evidence_json TEXT NOT NULL,
                    error TEXT, started_at REAL, finished_at REAL,
                    PRIMARY KEY(operation_id, step_id),
                    UNIQUE(operation_id, ordinal),
                    FOREIGN KEY(operation_id) REFERENCES operations(operation_id)
                );
                CREATE TABLE IF NOT EXISTS background_jobs (
                    operation_id TEXT PRIMARY KEY, job_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(operation_id) REFERENCES operations(operation_id)
                );
                CREATE TABLE IF NOT EXISTS background_job_executors (
                    operation_id TEXT PRIMARY KEY, pid INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL, claimed_at REAL NOT NULL,
                    FOREIGN KEY(operation_id) REFERENCES background_jobs(operation_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_sessions (
                    session_id TEXT PRIMARY KEY, work_id TEXT NOT NULL,
                    work_assignment_epoch INTEGER NOT NULL, objective TEXT NOT NULL,
                    roots_json TEXT NOT NULL, actions_json TEXT NOT NULL,
                    acceptance_json TEXT NOT NULL, plan_revision INTEGER NOT NULL,
                    manager_node_id TEXT, manager_epoch INTEGER NOT NULL,
                    state TEXT NOT NULL, terminal_summary_json TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    FOREIGN KEY(work_id) REFERENCES works(work_id),
                    FOREIGN KEY(manager_node_id) REFERENCES nodes(node_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_manager_epochs (
                    session_id TEXT NOT NULL, epoch INTEGER NOT NULL,
                    manager_node_id TEXT NOT NULL, reason TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, started_at REAL NOT NULL,
                    ended_at REAL,
                    PRIMARY KEY(session_id, epoch),
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id),
                    FOREIGN KEY(manager_node_id) REFERENCES nodes(node_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_session_nodes (
                    session_id TEXT NOT NULL, node_id TEXT NOT NULL,
                    session_role TEXT NOT NULL, active INTEGER NOT NULL,
                    PRIMARY KEY(session_id,node_id),
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id),
                    FOREIGN KEY(node_id) REFERENCES nodes(node_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_attachments (
                    attachment_id TEXT NOT NULL, generation INTEGER NOT NULL,
                    node_id TEXT NOT NULL, kind TEXT NOT NULL,
                    instance_id TEXT NOT NULL, external_session_id TEXT NOT NULL,
                    tab_id INTEGER NOT NULL, window_id INTEGER NOT NULL,
                    conversation_key TEXT NOT NULL, endpoint TEXT NOT NULL,
                    relay_role TEXT, binding_receipt_id TEXT,
                    active INTEGER NOT NULL, observed_at REAL NOT NULL,
                    PRIMARY KEY(attachment_id, generation),
                    FOREIGN KEY(node_id) REFERENCES nodes(node_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_assignments (
                    assignment_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    created_manager_epoch INTEGER NOT NULL,
                    request_digest TEXT NOT NULL, request_json TEXT NOT NULL,
                    roots_json TEXT NOT NULL, actions_json TEXT NOT NULL,
                    acceptance_json TEXT NOT NULL, state TEXT NOT NULL,
                    current_generation INTEGER NOT NULL,
                    terminal_result_json TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_dependencies (
                    assignment_id TEXT NOT NULL, depends_on_assignment_id TEXT NOT NULL,
                    PRIMARY KEY(assignment_id, depends_on_assignment_id),
                    FOREIGN KEY(assignment_id) REFERENCES orchestration_assignments(assignment_id),
                    FOREIGN KEY(depends_on_assignment_id) REFERENCES orchestration_assignments(assignment_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_assignment_attempts (
                    assignment_id TEXT NOT NULL, generation INTEGER NOT NULL,
                    manager_epoch INTEGER NOT NULL, worker_node_id TEXT NOT NULL,
                    attachment_id TEXT NOT NULL, attachment_generation INTEGER NOT NULL,
                    state TEXT NOT NULL, dispatch_message_id TEXT,
                    dispatch_operation_id TEXT, created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(assignment_id, generation),
                    FOREIGN KEY(assignment_id) REFERENCES orchestration_assignments(assignment_id),
                    FOREIGN KEY(worker_node_id) REFERENCES nodes(node_id),
                    FOREIGN KEY(attachment_id,attachment_generation)
                        REFERENCES orchestration_attachments(attachment_id,generation)
                );
                CREATE TABLE IF NOT EXISTS orchestration_mailbox (
                    message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    assignment_id TEXT, assignment_generation INTEGER,
                    kind TEXT NOT NULL, sender_node_id TEXT, recipient_node_id TEXT,
                    message_digest TEXT NOT NULL, payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL, delivered_at REAL, consumed_at REAL,
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id),
                    FOREIGN KEY(assignment_id) REFERENCES orchestration_assignments(assignment_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_reconciliations (
                    decision_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    assignment_id TEXT NOT NULL, generation INTEGER NOT NULL,
                    manager_epoch INTEGER NOT NULL, decision TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, created_at REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id),
                    FOREIGN KEY(assignment_id) REFERENCES orchestration_assignments(assignment_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS orchestration_attachment_active_role
                    ON orchestration_attachments(instance_id,relay_role)
                    WHERE active=1 AND relay_role IS NOT NULL AND relay_role!='';
                CREATE INDEX IF NOT EXISTS orchestration_attachment_conversation
                    ON orchestration_attachments(instance_id,conversation_key,active);
                CREATE UNIQUE INDEX IF NOT EXISTS orchestration_attachment_current_slot
                    ON orchestration_attachments(instance_id,tab_id)
                    WHERE active=1;
                CREATE UNIQUE INDEX IF NOT EXISTS orchestration_attempt_dispatch
                    ON orchestration_assignment_attempts(dispatch_operation_id)
                    WHERE dispatch_operation_id IS NOT NULL;
                """
            )

    @staticmethod
    def _event(db: sqlite3.Connection, kind: str, subject_id: str, data: dict[str, Any]) -> None:
        db.execute(
            "INSERT INTO events(kind,subject_id,data_json,created_at) VALUES(?,?,?,?)",
            (kind, subject_id, json.dumps(data, sort_keys=True), time.time()),
        )

    def create_node(self, *, node_id: str, name: str, role: str | None = None,
                    group: str | None = None) -> dict[str, Any]:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO nodes(node_id,name,role,group_name,revision,active) VALUES(?,?,?,?,1,1)",
                (node_id, name, role, group),
            )
            self._event(db, "NODE_CREATED", node_id, {"name": name, "role": role, "group": group})
        return self.get_node(node_id)

    def get_node(self, node_id: str) -> dict[str, Any]:
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("NODE_NOT_FOUND")
        return {"node_id": row["node_id"], "name": row["name"], "role": row["role"],
                "group": row["group_name"], "revision": row["revision"], "active": bool(row["active"])}

    def update_node(self, *, node_id: str, expected_revision: int,
                    name: str | None = None, role: str | None = None,
                    group: str | None = None, active: bool | None = None) -> dict[str, Any]:
        current = self.get_node(node_id)
        values = {
            "name": current["name"] if name is None else name,
            "role": current["role"] if role is None else role,
            "group": current["group"] if group is None else group,
            "active": current["active"] if active is None else active,
        }
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE nodes SET name=?,role=?,group_name=?,active=?,revision=revision+1 "
                "WHERE node_id=? AND revision=?",
                (values["name"], values["role"], values["group"], int(values["active"]), node_id, expected_revision),
            ).rowcount
            if changed != 1:
                raise ConflictError("NODE_REVISION_MISMATCH")
            self._event(db, "NODE_UPDATED", node_id, values)
        return self.get_node(node_id)

    def replace_connection(self, *, connection_id: str, node_id: str, kind: str,
                           instance: str, endpoint: str, expected_generation: int | None) -> dict[str, Any]:
        with self.transaction() as db:
            node = db.execute("SELECT active FROM nodes WHERE node_id=?", (node_id,)).fetchone()
            if node is None or not node["active"]:
                raise ConflictError("NODE_NOT_ACTIVE")
            current = db.execute("SELECT * FROM connections WHERE connection_id=?", (connection_id,)).fetchone()
            if current is None:
                if expected_generation not in {None, 0}:
                    raise ConflictError("CONNECTION_GENERATION_MISMATCH")
                generation = 1
                db.execute(
                    "INSERT INTO connections(connection_id,node_id,kind,instance,endpoint,generation,active) "
                    "VALUES(?,?,?,?,?,?,1)",
                    (connection_id, node_id, kind, instance, endpoint, generation),
                )
            else:
                if current["node_id"] != node_id or expected_generation != current["generation"]:
                    raise ConflictError("CONNECTION_GENERATION_MISMATCH")
                generation = current["generation"] + 1
                db.execute(
                    "UPDATE connections SET kind=?,instance=?,endpoint=?,generation=?,active=1 WHERE connection_id=?",
                    (kind, instance, endpoint, generation, connection_id),
                )
            self._event(db, "CONNECTION_REPLACED", connection_id, {"node_id": node_id, "generation": generation})
        return self.get_connection(connection_id)

    def get_connection(self, connection_id: str) -> dict[str, Any]:
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM connections WHERE connection_id=?", (connection_id,)).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("CONNECTION_NOT_FOUND")
        return dict(row)

    def create_work(self, work: Work) -> Work:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO works VALUES(?,?,?,?,?,?,?)",
                (work.work_id, work.request_summary, json.dumps(work.roots), json.dumps(sorted(work.actions)),
                 work.owner_principal_id, work.assignment_epoch, work.state),
            )
            self._event(db, "WORK_CREATED", work.work_id, {"owner": work.owner_principal_id})
        return work

    def get_work(self, work_id: str) -> Work:
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("WORK_NOT_FOUND")
        return Work(row["work_id"], row["request_summary"], tuple(json.loads(row["roots_json"])),
                    frozenset(json.loads(row["actions_json"])), row["owner_principal_id"],
                    row["assignment_epoch"], row["state"])

    def monitor_snapshot(self, *, event_limit: int = 50) -> dict[str, Any]:
        """Return a bounded, read-only projection for the local BCT monitor."""
        limit = max(1, min(int(event_limit), 200))
        db = self._connect()
        try:
            nodes = [dict(row) for row in db.execute(
                "SELECT node_id,name,role,group_name,revision,active FROM nodes ORDER BY node_id"
            ).fetchall()]
            connections = [dict(row) for row in db.execute(
                "SELECT connection_id,node_id,kind,instance,endpoint,generation,active "
                "FROM connections ORDER BY connection_id"
            ).fetchall()]
            works = [dict(row) for row in db.execute(
                "SELECT work_id,request_summary,owner_principal_id,assignment_epoch,state "
                "FROM works ORDER BY rowid DESC LIMIT 100"
            ).fetchall()]
            operations = [dict(row) for row in db.execute(
                "SELECT operation_id,work_id,capability,target,state,outcome,created_at,updated_at "
                "FROM operations ORDER BY updated_at DESC LIMIT 100"
            ).fetchall()]
            claims = [dict(row) for row in db.execute(
                "SELECT resource_key,operation_id,work_id,assignment_epoch "
                "FROM resource_claims WHERE unresolved=1 ORDER BY resource_key"
            ).fetchall()]
            events = [dict(row) for row in db.execute(
                "SELECT event_id,kind,subject_id,created_at FROM events "
                "ORDER BY event_id DESC LIMIT ?", (limit,)
            ).fetchall()]
            orchestration_sessions = [dict(row) for row in db.execute(
                "SELECT session_id,work_id,manager_node_id,manager_epoch,state,plan_revision,updated_at "
                "FROM orchestration_sessions ORDER BY updated_at DESC LIMIT 50"
            ).fetchall()]
            orchestration_assignments = [dict(row) for row in db.execute(
                "SELECT assignment_id,session_id,created_manager_epoch,state,current_generation,updated_at "
                "FROM orchestration_assignments ORDER BY updated_at DESC LIMIT 100"
            ).fetchall()]
        finally:
            db.close()
        for node in nodes:
            node["active"] = bool(node["active"])
            node["group"] = node.pop("group_name")
        for connection in connections:
            connection["active"] = bool(connection["active"])
        return {
            "nodes": nodes,
            "connections": connections,
            "works": works,
            "operations": operations,
            "unresolved_claims": claims,
            "events": events,
            "orchestration_sessions": orchestration_sessions,
            "orchestration_assignments": orchestration_assignments,
        }

    def handoff_work(self, *, work_id: str, old_principal_id: str, new_principal_id: str,
                     expected_epoch: int) -> Work:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
            if row is None:
                raise KeyError("WORK_NOT_FOUND")
            if row["owner_principal_id"] != old_principal_id or row["assignment_epoch"] != expected_epoch:
                raise ConflictError("WORK_HANDOFF_FENCE_MISMATCH")
            unresolved = db.execute(
                "SELECT COUNT(*) FROM resource_claims WHERE work_id=? AND unresolved=1", (work_id,)
            ).fetchone()[0]
            if unresolved:
                raise ConflictError("WORK_HAS_UNRESOLVED_OPERATION")
            running = db.execute(
                "SELECT COUNT(*) FROM operations WHERE work_id=? AND state!=?",
                (work_id, OperationState.FINISHED.value),
            ).fetchone()[0]
            if running:
                raise ConflictError("WORK_HAS_ACTIVE_OPERATION")
            db.execute(
                "UPDATE works SET owner_principal_id=?,assignment_epoch=assignment_epoch+1 WHERE work_id=?",
                (new_principal_id, work_id),
            )
            self._event(db, "WORK_HANDED_OFF", work_id, {"old": old_principal_id, "new": new_principal_id})
        return self.get_work(work_id)

    def begin_operation(self, *, operation_id: str, work: Work, principal_id: str,
                        request_digest: str, capability: str, target: str,
                        resources: tuple[str, ...], policy_revision: str,
                        background_job: dict[str, Any] | None = None,
                        ) -> tuple[bool, OperationResult]:
        now = time.time()
        with self.transaction() as db:
            current = db.execute("SELECT * FROM works WHERE work_id=?", (work.work_id,)).fetchone()
            if current is None or current["owner_principal_id"] != principal_id or current["assignment_epoch"] != work.assignment_epoch:
                raise ConflictError("WORK_ASSIGNMENT_CHANGED")
            existing = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            if existing is not None:
                if existing["work_id"] != work.work_id:
                    raise ConflictError("OPERATION_RESULT_ACCESS_DENIED")
                if existing["request_digest"] != request_digest:
                    raise ConflictError("OPERATION_ID_REQUEST_MISMATCH")
                if background_job is not None:
                    self._record_background_job(
                        db, operation_id=operation_id, job=background_job,
                        operation_created_at=float(existing["created_at"]),
                    )
                return False, self._row_result(existing, duplicate=True)
            db.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (operation_id, work.work_id, principal_id, request_digest, capability, target,
                 OperationState.RECORDED.value, None, "{}", None, work.assignment_epoch,
                 policy_revision, now, now),
            )
            for resource in sorted(set(resources)):
                row = db.execute("SELECT * FROM resource_claims WHERE resource_key=? AND unresolved=1", (resource,)).fetchone()
                if row is not None:
                    # Only the current work may see its own operation identity.
                    # Foreign claims remain opaque, including their resource key.
                    if row["work_id"] != work.work_id:
                        raise ConflictError("RESOURCE_ALREADY_CLAIMED:FOREIGN_WORK")
                    owner = db.execute(
                        "SELECT state,outcome FROM operations WHERE operation_id=? AND work_id=?",
                        (row["operation_id"], work.work_id),
                    ).fetchone()
                    if owner is None:
                        raise ConflictError("RESOURCE_ALREADY_CLAIMED:SAME_WORK_UNVERIFIED")
                    next_action = "WAIT_RECHECK" if owner["state"] != OperationState.FINISHED.value else "REVIEW_UNRESOLVED"
                    raise ConflictError(
                        "RESOURCE_ALREADY_CLAIMED:SAME_WORK:"
                        + row["operation_id"] + ":" + owner["state"] + ":"
                        + (owner["outcome"] or "NONE") + ":" + next_action
                    )
                db.execute(
                    "INSERT OR REPLACE INTO resource_claims VALUES(?,?,?,?,1)",
                    (resource, operation_id, work.work_id, work.assignment_epoch),
                )
            db.execute("UPDATE operations SET state=?,updated_at=? WHERE operation_id=?",
                       (OperationState.RUNNING.value, now, operation_id))
            if background_job is not None:
                self._record_background_job(
                    db, operation_id=operation_id, job=background_job,
                    operation_created_at=now,
                )
            self._event(db, "OPERATION_STARTED", operation_id, {"capability": capability, "resources": resources})
            row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            return True, self._row_result(row)

    def _record_background_job(
        self, db, *, operation_id: str, job: dict[str, Any],
        operation_created_at: float,
    ) -> None:
        value = dict(job)
        delay = float(value.pop("_not_before_delay", 0.0))
        value["created_at"] = operation_created_at
        value["not_before"] = operation_created_at + max(0.0, delay)
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
        existing = db.execute(
            "SELECT job_json FROM background_jobs WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            db.execute(
                "INSERT INTO background_jobs VALUES(?,?,?)",
                (operation_id, payload, operation_created_at),
            )
        else:
            prior = json.loads(existing["job_json"])
            for key in ("operation_id", "work_id", "capability"):
                if str(prior.get(key) or "") != str(value.get(key) or ""):
                    raise ConflictError("BACKGROUND_JOB_REQUEST_MISMATCH")
            if str((prior.get("principal") or {}).get("principal_id") or "") != str(
                (value.get("principal") or {}).get("principal_id") or ""
            ):
                raise ConflictError("BACKGROUND_JOB_REQUEST_MISMATCH")

    def acquire_background_executor(
        self, *, operation_id: str, pid: int, fingerprint: str,
    ) -> bool:
        with self.transaction() as db:
            operation = db.execute(
                "SELECT state FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            job = db.execute(
                "SELECT 1 FROM background_jobs WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if operation is None or job is None \
                    or operation["state"] != OperationState.RUNNING.value:
                return False
            current = db.execute(
                "SELECT * FROM background_job_executors WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if current is not None:
                return current["fingerprint"] == fingerprint and current["pid"] == pid
            db.execute(
                "INSERT INTO background_job_executors VALUES(?,?,?,?)",
                (operation_id, pid, fingerprint, time.time()),
            )
            return True

    def background_executor(self, operation_id: str) -> dict[str, Any] | None:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT * FROM background_job_executors WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            return None if row is None else dict(row)
        finally:
            db.close()

    def clear_background_executor(
        self, *, operation_id: str, fingerprint: str,
    ) -> bool:
        with self.transaction() as db:
            cursor = db.execute(
                "DELETE FROM background_job_executors WHERE operation_id=? "
                "AND fingerprint=?",
                (operation_id, fingerprint),
            )
            return cursor.rowcount == 1

    def running_background_jobs(self, *, capability: str | None = None) -> list[dict[str, Any]]:
        db = self._connect()
        try:
            query = (
                "SELECT b.job_json FROM background_jobs b JOIN operations o "
                "ON o.operation_id=b.operation_id WHERE o.state=?"
            )
            params: list[Any] = [OperationState.RUNNING.value]
            if capability is not None:
                query += " AND o.capability=?"
                params.append(capability)
            query += " ORDER BY b.created_at,b.operation_id"
            return [json.loads(row["job_json"]) for row in db.execute(
                query, tuple(params)
            ).fetchall()]
        finally:
            db.close()

    def background_job(self, operation_id: str) -> dict[str, Any] | None:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT job_json FROM background_jobs WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            return None if row is None else json.loads(row["job_json"])
        finally:
            db.close()

    def finish_operation(self, *, operation_id: str, outcome: Outcome,
                         evidence: dict[str, Any], error: str | None,
                         release_claims: bool,
                         reconciled_operation_ids: tuple[str, ...] = ()) -> OperationResult:
        with self.transaction() as db:
            resolver = db.execute(
                "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if resolver is None or resolver["state"] != OperationState.RUNNING.value:
                raise ConflictError("OPERATION_NOT_RUNNING")
            reconciled = tuple(sorted(set(reconciled_operation_ids)))
            running_reconciled: list[str] = []
            for original_id in reconciled:
                original = db.execute(
                    "SELECT * FROM operations WHERE operation_id=?", (original_id,)
                ).fetchone()
                if original is None or original["work_id"] != resolver["work_id"]:
                    raise ConflictError("RECONCILIATION_OPERATION_ACCESS_DENIED")
                finished_unknown = (
                    original["state"] == OperationState.FINISHED.value
                    and original["outcome"] == Outcome.UNKNOWN.value
                )
                recoverable_running = (
                    original["state"] == OperationState.RUNNING.value
                    and original["capability"] == "orchestrate"
                    and resolver["capability"] == "orchestrate"
                    and evidence.get("operation") in {
                        "reconcile", "chain-resume", "recover-not-dispatched"
                    }
                )
                if not finished_unknown and not recoverable_running:
                    raise ConflictError("RECONCILIATION_ORIGINAL_NOT_UNKNOWN")
                if recoverable_running:
                    running_reconciled.append(original_id)
                unresolved = db.execute(
                    "SELECT COUNT(*) FROM resource_claims WHERE operation_id=? AND unresolved=1",
                    (original_id,),
                ).fetchone()[0]
                if not unresolved:
                    raise ConflictError("RECONCILIATION_CLAIM_NOT_UNRESOLVED")
            changed = db.execute(
                "UPDATE operations SET state=?,outcome=?,evidence_json=?,error=?,updated_at=? "
                "WHERE operation_id=? AND state=?",
                (OperationState.FINISHED.value, outcome.value, json.dumps(evidence, sort_keys=True), error,
                 time.time(), operation_id, OperationState.RUNNING.value),
            ).rowcount
            if changed != 1:
                raise ConflictError("OPERATION_NOT_RUNNING")
            if release_claims:
                db.execute("UPDATE resource_claims SET unresolved=0 WHERE operation_id=?", (operation_id,))
            for original_id in reconciled:
                if original_id in running_reconciled:
                    recovered_outcome = (
                        Outcome.NOT_APPLIED
                        if evidence.get("operation") == "recover-not-dispatched"
                        else outcome
                    )
                    db.execute(
                        "UPDATE operations SET state=?,outcome=?,evidence_json=?,error=?,"
                        "updated_at=? WHERE operation_id=? AND state=?",
                        (
                            OperationState.FINISHED.value, recovered_outcome.value,
                            json.dumps({
                                "phase": "RECONCILED_RUNNING",
                                "resolver_operation_id": operation_id,
                                "recovered_outcome": recovered_outcome.value,
                            }, sort_keys=True),
                            None,
                            time.time(), original_id, OperationState.RUNNING.value,
                        ),
                    )
                db.execute(
                    "UPDATE resource_claims SET unresolved=0 WHERE operation_id=?",
                    (original_id,),
                )
                self._event(db, "OPERATION_RECONCILED", original_id, {
                    "resolver_operation_id": operation_id,
                    "original_outcome": (
                        (Outcome.NOT_APPLIED if evidence.get("operation")
                         == "recover-not-dispatched" else outcome).value
                        if original_id in running_reconciled
                        else Outcome.UNKNOWN.value
                    ),
                })
            self._event(db, "OPERATION_FINISHED", operation_id,
                        {"outcome": outcome.value, "claims_released": release_claims,
                         "reconciled_operation_ids": list(reconciled)})
            row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        return self._row_result(row)

    def finish_orchestration_recovery_in_transaction(
        self, db, *, resolver_operation_id: str, original_operation_id: str,
        resolver_outcome: Outcome, original_outcome: Outcome | None,
        evidence: dict[str, Any], release_original: bool,
    ) -> None:
        """Atomically close a result-only orchestration resolver and its original.

        The caller already owns ``db``'s IMMEDIATE transaction together with the
        assignment/session evidence that proves the outcome.  Keeping these writes
        together removes the crash window between durable reconciliation and the
        outer operation receipts.
        """
        resolver = db.execute(
            "SELECT * FROM operations WHERE operation_id=? AND capability='orchestrate'",
            (resolver_operation_id,),
        ).fetchone()
        original = db.execute(
            "SELECT * FROM operations WHERE operation_id=? AND capability='orchestrate'",
            (original_operation_id,),
        ).fetchone()
        if (
            resolver is None or resolver["state"] != OperationState.RUNNING.value
            or original is None or original["work_id"] != resolver["work_id"]
        ):
            raise ConflictError("ORCHESTRATION_RECOVERY_OPERATION_STATE_INVALID")
        now = time.time()
        db.execute(
            "UPDATE operations SET state=?,outcome=?,evidence_json=?,error=NULL,updated_at=? "
            "WHERE operation_id=? AND state=?",
            (
                OperationState.FINISHED.value, resolver_outcome.value,
                json.dumps(evidence, sort_keys=True), now, resolver_operation_id,
                OperationState.RUNNING.value,
            ),
        )
        db.execute(
            "UPDATE resource_claims SET unresolved=0 WHERE operation_id=?",
            (resolver_operation_id,),
        )
        original_persisted_outcome = str(original["outcome"] or "UNRESOLVED")
        takeover_unknown = (
            original["state"] == OperationState.FINISHED.value
            and original["outcome"] == Outcome.UNKNOWN.value
            and original["error"] == "ORCHESTRATION_RECOVERY_TAKEOVER"
        )
        if original_outcome is not None and (
            original["state"] == OperationState.RUNNING.value or takeover_unknown
        ):
            db.execute(
                "UPDATE operations SET state=?,outcome=?,evidence_json=?,error=NULL,updated_at=? "
                "WHERE operation_id=?",
                (
                    OperationState.FINISHED.value, original_outcome.value,
                    json.dumps({
                        "phase": "ORCHESTRATION_RECOVERED",
                        "resolver_operation_id": resolver_operation_id,
                        "recovered_outcome": original_outcome.value,
                    }, sort_keys=True),
                    now, original_operation_id,
                ),
            )
            original_persisted_outcome = original_outcome.value
        elif original["state"] != OperationState.FINISHED.value:
            raise ConflictError("ORCHESTRATION_RECOVERY_ORIGINAL_INVALID")
        if release_original:
            db.execute(
                "UPDATE resource_claims SET unresolved=0 WHERE operation_id=?",
                (original_operation_id,),
            )
        self._event(db, "OPERATION_FINISHED", resolver_operation_id, {
            "outcome": resolver_outcome.value,
            "claims_released": True,
            "atomic_orchestration_recovery": True,
        })
        self._event(db, "OPERATION_RECONCILED", original_operation_id, {
            "resolver_operation_id": resolver_operation_id,
            "original_outcome": original_persisted_outcome,
            "resolved_outcome": (
                original_outcome.value if original_outcome is not None else None
            ),
            "claims_released": release_original,
        })

    def initialize_operation_steps(self, *, operation_id: str,
                                   steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Persist one immutable ordered plan before the first child is dispatched."""
        with self.transaction() as db:
            operation = db.execute(
                "SELECT state FROM operations WHERE operation_id=?", (operation_id,),
            ).fetchone()
            if operation is None or operation["state"] != OperationState.RUNNING.value:
                raise ConflictError("OPERATION_NOT_RUNNING")
            existing = db.execute(
                "SELECT step_id,ordinal,capability,request_digest FROM operation_steps "
                "WHERE operation_id=? ORDER BY ordinal", (operation_id,),
            ).fetchall()
            expected = [
                (str(step["step_id"]), int(step["ordinal"]), str(step["capability"]),
                 str(step["request_digest"]))
                for step in steps
            ]
            if existing:
                actual = [
                    (row["step_id"], row["ordinal"], row["capability"], row["request_digest"])
                    for row in existing
                ]
                if actual != expected:
                    raise ConflictError("OPERATION_STEP_PLAN_MISMATCH")
            else:
                for step_id, ordinal, capability, request_digest in expected:
                    db.execute(
                        "INSERT INTO operation_steps VALUES(?,?,?,?,?,'PENDING',NULL,'{}',NULL,NULL,NULL)",
                        (operation_id, step_id, ordinal, capability, request_digest),
                    )
                self._event(db, "OPERATION_STEPS_INITIALIZED", operation_id, {
                    "count": len(expected),
                    "steps": [value[0] for value in expected],
                })
        return self.get_operation_steps(operation_id=operation_id)

    def start_operation_step(self, *, operation_id: str, step_id: str) -> dict[str, Any]:
        now = time.time()
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE operation_steps SET state='RUNNING',started_at=? "
                "WHERE operation_id=? AND step_id=? AND state='PENDING'",
                (now, operation_id, step_id),
            ).rowcount
            if changed != 1:
                raise ConflictError("OPERATION_STEP_NOT_PENDING")
            self._event(db, "OPERATION_STEP_STARTED", operation_id, {"step_id": step_id})
        return self.get_operation_step(operation_id=operation_id, step_id=step_id)

    def finish_operation_step(self, *, operation_id: str, step_id: str,
                              outcome: Outcome, evidence: dict[str, Any],
                              error: str | None = None) -> dict[str, Any]:
        now = time.time()
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE operation_steps SET state='FINISHED',outcome=?,evidence_json=?,"
                "error=?,finished_at=? WHERE operation_id=? AND step_id=? AND state='RUNNING'",
                (outcome.value, json.dumps(evidence, sort_keys=True), error, now,
                 operation_id, step_id),
            ).rowcount
            if changed != 1:
                raise ConflictError("OPERATION_STEP_NOT_RUNNING")
            self._event(db, "OPERATION_STEP_FINISHED", operation_id, {
                "step_id": step_id, "outcome": outcome.value,
            })
        return self.get_operation_step(operation_id=operation_id, step_id=step_id)

    def skip_pending_operation_steps(self, *, operation_id: str,
                                     after_ordinal: int, reason: str) -> None:
        now = time.time()
        with self.transaction() as db:
            rows = db.execute(
                "SELECT step_id FROM operation_steps WHERE operation_id=? AND ordinal>? "
                "AND state='PENDING' ORDER BY ordinal", (operation_id, after_ordinal),
            ).fetchall()
            for row in rows:
                db.execute(
                    "UPDATE operation_steps SET state='SKIPPED',outcome=?,evidence_json=?,"
                    "finished_at=? WHERE operation_id=? AND step_id=? AND state='PENDING'",
                    (Outcome.NOT_APPLIED.value, json.dumps({"code": reason}, sort_keys=True),
                     now, operation_id, row["step_id"]),
                )
                self._event(db, "OPERATION_STEP_SKIPPED", operation_id, {
                    "step_id": row["step_id"], "reason": reason,
                })

    def get_operation_step(self, *, operation_id: str, step_id: str) -> dict[str, Any]:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT * FROM operation_steps WHERE operation_id=? AND step_id=?",
                (operation_id, step_id),
            ).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("OPERATION_STEP_NOT_FOUND")
        return self._step_row(row)

    def get_operation_steps(self, *, operation_id: str) -> list[dict[str, Any]]:
        db = self._connect()
        try:
            rows = db.execute(
                "SELECT * FROM operation_steps WHERE operation_id=? ORDER BY ordinal",
                (operation_id,),
            ).fetchall()
        finally:
            db.close()
        return [self._step_row(row) for row in rows]

    def get_operation_steps_for(self, *, operation_id: str, work_id: str,
                                principal_id: str) -> list[dict[str, Any]]:
        self.get_operation_for(
            operation_id=operation_id, work_id=work_id, principal_id=principal_id,
        )
        return self.get_operation_steps(operation_id=operation_id)

    def get_operation_for(self, *, operation_id: str, work_id: str, principal_id: str) -> OperationResult:
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("OPERATION_NOT_FOUND")
        if row["work_id"] != work_id:
            raise ConflictError("OPERATION_RESULT_ACCESS_DENIED")
        work = self.get_work(work_id)
        if row["principal_id"] != principal_id and work.owner_principal_id != principal_id:
            raise ConflictError("OPERATION_RESULT_ACCESS_DENIED")
        return self._row_result(row)

    def get_operation_target_for(self, *, operation_id: str, work_id: str, principal_id: str) -> str:
        # Reuse the exact work/principal authorization check before revealing target.
        self.get_operation_for(operation_id=operation_id, work_id=work_id, principal_id=principal_id)
        db = self._connect()
        try:
            row = db.execute(
                "SELECT target FROM operations WHERE operation_id=? AND work_id=?",
                (operation_id, work_id),
            ).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("OPERATION_NOT_FOUND")
        return str(row["target"])

    @staticmethod
    def _row_result(row: sqlite3.Row, *, duplicate: bool = False) -> OperationResult:
        return OperationResult(
            row["operation_id"], OperationState(row["state"]),
            Outcome(row["outcome"]) if row["outcome"] else None,
            json.loads(row["evidence_json"]), duplicate, row["error"],
        )

    @staticmethod
    def _step_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "step_id": row["step_id"],
            "ordinal": row["ordinal"],
            "capability": row["capability"],
            "request_digest": row["request_digest"],
            "state": row["state"],
            "outcome": row["outcome"],
            "evidence": json.loads(row["evidence_json"]),
            "error": row["error"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }
