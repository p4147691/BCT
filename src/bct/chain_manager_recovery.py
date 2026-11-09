"""Durable Manager-return checkpoints for Chain Recipe recovery.

The Supervisor recorded by a Direction is a recovery collector, not an
acting Manager.  This ledger preserves a Worker's completed MANAGER return
before any browser delivery so a recovered or successor Manager can read the
exact state without replaying the Worker task.
"""
from __future__ import annotations

import json
import time


class ChainManagerRecoveryLedger:
    """Persist and read exact Chain Recipe hand-off records."""

    _DELIVERY_STATES = {
        "PENDING",
        "RETURNED_TO_MANAGER",
        "COLLECTED_BY_SUPERVISOR",
        "NOT_APPLIED",
        "UNKNOWN",
    }

    def __init__(self, store, *, initialize: bool = True):
        self.store = store
        if initialize:
            self._initialize()

    def _initialize(self) -> None:
        with self.store.transaction() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS chain_manager_return_checkpoints (
                    task_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    work_id TEXT NOT NULL,
                    direction_id TEXT NOT NULL,
                    worker_conversation_key TEXT NOT NULL,
                    manager_conversation_key TEXT NOT NULL,
                    active_manager_conversation_key TEXT NOT NULL,
                    supervisor_conversation_key TEXT NOT NULL,
                    response_turn_key TEXT NOT NULL,
                    response_sha256 TEXT NOT NULL,
                    return_payload TEXT NOT NULL,
                    delivery_state TEXT NOT NULL,
                    destination_conversation_key TEXT NOT NULL DEFAULT '',
                    delivery_operation_id TEXT NOT NULL DEFAULT '',
                    delivery_receipt TEXT NOT NULL DEFAULT '',
                    acknowledged_by TEXT NOT NULL DEFAULT '',
                    acknowledged_at REAL NOT NULL DEFAULT 0,
                    manager_succession_proof_json TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(task_id, generation)
                )
                """
            )

    def _table_exists(self) -> bool:
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='chain_manager_return_checkpoints'"
            ).fetchone()
        return row is not None

    def record_pending(
        self, *, task_id: str, generation: int, work_id: str,
        direction_id: str, worker_conversation_key: str,
        manager_conversation_key: str, supervisor_conversation_key: str,
        response_turn_key: str, response_sha256: str, return_payload: str,
    ) -> dict:
        """Record the completed Worker return before any external send."""
        now = time.time()
        values = (
            task_id, generation, work_id, direction_id,
            worker_conversation_key, manager_conversation_key,
            supervisor_conversation_key, response_turn_key,
            response_sha256, return_payload,
        )
        with self.store.transaction() as db:
            existing = db.execute(
                "SELECT * FROM chain_manager_return_checkpoints "
                "WHERE task_id=? AND generation=?",
                (task_id, generation),
            ).fetchone()
            if existing is None:
                db.execute(
                    "INSERT INTO chain_manager_return_checkpoints("
                    "task_id,generation,work_id,direction_id,"
                    "worker_conversation_key,manager_conversation_key,"
                    "active_manager_conversation_key,"
                    "supervisor_conversation_key,response_turn_key,"
                    "response_sha256,return_payload,delivery_state,created_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?, ?,?)",
                    (*values[:6], manager_conversation_key, *values[6:],
                     "PENDING", now, now),
                )
            else:
                immutable = tuple(existing[key] for key in (
                    "task_id", "generation", "work_id", "direction_id",
                    "worker_conversation_key", "manager_conversation_key",
                    "supervisor_conversation_key", "response_turn_key",
                    "response_sha256", "return_payload",
                ))
                if immutable != values:
                    raise ValueError("CHAIN_MANAGER_RETURN_CONFLICT")
        return self.get(task_id=task_id, generation=generation)

    def mark_delivery(
        self, *, task_id: str, generation: int, state: str,
        destination_conversation_key: str = "", operation_id: str = "",
        receipt: str = "",
    ) -> dict:
        if state not in self._DELIVERY_STATES - {"PENDING"}:
            raise ValueError("CHAIN_MANAGER_RETURN_STATE_INVALID")
        with self.store.transaction() as db:
            changed = db.execute(
                "UPDATE chain_manager_return_checkpoints SET delivery_state=?,"
                "destination_conversation_key=?,delivery_operation_id=?,"
                "delivery_receipt=?,updated_at=? WHERE task_id=? AND generation=?",
                (state, destination_conversation_key, operation_id, receipt,
                 time.time(), task_id, generation),
            )
            if changed.rowcount != 1:
                raise ValueError("CHAIN_MANAGER_RETURN_NOT_FOUND")
        return self.get(task_id=task_id, generation=generation)

    def get(self, *, task_id: str, generation: int) -> dict:
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT * FROM chain_manager_return_checkpoints "
                "WHERE task_id=? AND generation=?",
                (task_id, generation),
            ).fetchone()
        if row is None:
            raise ValueError("CHAIN_MANAGER_RETURN_NOT_FOUND")
        return dict(row)

    def inbox(
        self, *, work_id: str, report_target_conversation_key: str,
        limit: int = 50,
    ) -> list[dict]:
        """Read records visible to the bound Manager or Supervisor; no effects."""
        if not self._table_exists():
            return []
        with self.store._readonly() as db:
            rows = db.execute(
                "SELECT * FROM chain_manager_return_checkpoints WHERE work_id=? "
                "AND (manager_conversation_key=? OR active_manager_conversation_key=? "
                "OR supervisor_conversation_key=?) "
                "ORDER BY created_at,task_id,generation LIMIT ?",
                (work_id, report_target_conversation_key,
                 report_target_conversation_key,
                 report_target_conversation_key, max(1, min(int(limit), 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def for_work(self, *, work_id: str, limit: int = 100) -> list[dict]:
        """Internal recovery validation read; public callers use scoped inbox."""
        with self.store._readonly() as db:
            rows = db.execute(
                "SELECT * FROM chain_manager_return_checkpoints WHERE work_id=? "
                "ORDER BY created_at,task_id,generation LIMIT ?",
                (work_id, max(1, min(int(limit), 200))),
            ).fetchall()
        return [dict(row) for row in rows]

    def rebind_active_manager(self, *, work_id: str,
                              manager_conversation_key: str,
                              succession_proofs: list[dict] | None = None) -> int:
        """Point unacknowledged checkpoints at an already-verified successor A."""
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT task_id,generation,active_manager_conversation_key "
                "FROM chain_manager_return_checkpoints "
                "WHERE work_id=? AND acknowledged_at=0",
                (work_id,),
            ).fetchall()
            changed = 0
            for row in rows:
                previous = str(row["active_manager_conversation_key"])
                if previous == manager_conversation_key:
                    continue
                if not any(
                        str(proof.get("predecessor_conversation_key") or "") == previous
                        and str(proof.get("successor_conversation_key") or "")
                            == manager_conversation_key
                        for proof in (succession_proofs or [])):
                    raise ValueError("CHAIN_MANAGER_SUCCESSION_PROOF_REQUIRED")
                db.execute(
                    "UPDATE chain_manager_return_checkpoints "
                    "SET active_manager_conversation_key=?,"
                    "manager_succession_proof_json=?,updated_at=? "
                    "WHERE task_id=? AND generation=?",
                    (manager_conversation_key,
                     json.dumps(succession_proofs or [], sort_keys=True),
                     time.time(), row["task_id"], row["generation"]),
                )
                changed += 1
        return changed

    def acknowledge(self, *, work_id: str, task_id: str, generation: int,
                    manager_conversation_key: str) -> dict:
        """Record that the active A read the checkpoint before deciding next work."""
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM chain_manager_return_checkpoints "
                "WHERE work_id=? AND task_id=? AND generation=?",
                (work_id, task_id, generation),
            ).fetchone()
            if row is None:
                raise ValueError("CHAIN_MANAGER_RETURN_NOT_FOUND")
            if row["active_manager_conversation_key"] != manager_conversation_key:
                raise ValueError("CHAIN_MANAGER_RETURN_ACK_MANAGER_MISMATCH")
            if float(row["acknowledged_at"] or 0) == 0:
                db.execute(
                    "UPDATE chain_manager_return_checkpoints SET acknowledged_by=?,"
                    "acknowledged_at=?,updated_at=? WHERE task_id=? AND generation=?",
                    (manager_conversation_key, time.time(), time.time(),
                     task_id, generation),
                )
        return self.get(task_id=task_id, generation=generation)


def supervisor_collection_message(*, task_id: str, generation: int,
                                  worker_conversation_key: str,
                                  manager_conversation_key: str,
                                  payload: str) -> str:
    """Make the Supervisor's non-manager boundary explicit in the prompt."""
    return (
        "[CHAIN RECOVERY COLLECTION — DO NOT ACT AS MANAGER]\n"
        "A의 장애 중 Worker 반환을 인계용으로 보관합니다. 이 메시지로 작업을 판단·완료·"
        "재지시하거나 원 작업을 재실행하지 마세요. 복구된 A 또는 정식 후임 A에게 아래 "
        "식별값과 반환 원문을 전달하세요.\n"
        f"task_id={task_id}\n"
        f"generation={generation}\n"
        f"worker_conversation_key={worker_conversation_key}\n"
        f"manager_conversation_key={manager_conversation_key}\n\n"
        "[WORKER MANAGER RETURN]\n"
        f"{payload}\n"
        "[/WORKER MANAGER RETURN]"
    )
