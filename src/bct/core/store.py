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
                        resources: tuple[str, ...], policy_revision: str) -> tuple[bool, OperationResult]:
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
                    raise ConflictError("RESOURCE_ALREADY_CLAIMED:" + resource)
                db.execute(
                    "INSERT OR REPLACE INTO resource_claims VALUES(?,?,?,?,1)",
                    (resource, operation_id, work.work_id, work.assignment_epoch),
                )
            db.execute("UPDATE operations SET state=?,updated_at=? WHERE operation_id=?",
                       (OperationState.RUNNING.value, now, operation_id))
            self._event(db, "OPERATION_STARTED", operation_id, {"capability": capability, "resources": resources})
            row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            return True, self._row_result(row)

    def finish_operation(self, *, operation_id: str, outcome: Outcome,
                         evidence: dict[str, Any], error: str | None,
                         release_claims: bool) -> OperationResult:
        with self.transaction() as db:
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
            self._event(db, "OPERATION_FINISHED", operation_id,
                        {"outcome": outcome.value, "claims_released": release_claims})
            row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        return self._row_result(row)

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

    @staticmethod
    def _row_result(row: sqlite3.Row, *, duplicate: bool = False) -> OperationResult:
        return OperationResult(
            row["operation_id"], OperationState(row["state"]),
            Outcome(row["outcome"]) if row["outcome"] else None,
            json.loads(row["evidence_json"]), duplicate, row["error"],
        )
