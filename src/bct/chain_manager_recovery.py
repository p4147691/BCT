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
        "DELIVERING",
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
            columns = {str(r["name"]) for r in db.execute(
                "PRAGMA table_info(chain_manager_return_checkpoints)"
            )}
            if "active_supervisor_conversation_key" not in columns:
                db.execute(
                    "ALTER TABLE chain_manager_return_checkpoints "
                    "ADD COLUMN active_supervisor_conversation_key TEXT NOT NULL DEFAULT ''"
                )
                # Historical recipient is immutable provenance. New active
                # routing starts at that recipient and may later be rebound.
                db.execute(
                    "UPDATE chain_manager_return_checkpoints "
                    "SET active_supervisor_conversation_key=supervisor_conversation_key"
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
                db.execute(
                    "UPDATE chain_manager_return_checkpoints "
                    "SET active_supervisor_conversation_key=? "
                    "WHERE task_id=? AND generation=?",
                    (supervisor_conversation_key, task_id, generation),
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

    def pending_manager_deliveries(
        self, *, after_task_id: str = "", after_generation: int = 0,
        limit: int = 8,
    ) -> list[dict]:
        """Read only exact saved Worker returns lacking a confirmed A delivery.

        The originating Watch must be MANAGER_RECOVERY_PENDING. Other pending
        checkpoints belong to normal delivery and must not be replayed here.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("CHAIN_RECOVERY_POLL_LIMIT_INVALID")
        if not self._table_exists():
            # Core may be polling before any Chain Manager return exists.
            # Do not create a new recovery table during an empty read.
            return []
        with self.store._readonly() as db:
            rows = db.execute(
                "SELECT c.*,w.context_json AS watch_context_json,"
                "w.conversation_key AS watched_conversation "
                "FROM chain_manager_return_checkpoints c "
                "JOIN delayed_send_watches w ON "
                "w.task_id=c.task_id AND w.generation=c.generation "
                "WHERE c.delivery_state IN ('PENDING','DELIVERING') "
                "AND c.acknowledged_at=0 "
                "AND w.state='MANAGER_RECOVERY_PENDING' "
                "AND (c.task_id>? OR (c.task_id=? AND c.generation>?)) "
                "ORDER BY c.task_id,c.generation LIMIT ?",
                (after_task_id, after_task_id, after_generation, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_pending_manager_delivery(
        self, *, work_id: str, task_id: str, generation: int,
        manager_conversation_key: str, operation_id: str,
    ) -> dict | None:
        """Store one exact destination/operation claim before RCC dispatch.

        A second caller may resume the same claim and Operation ID. It cannot
        choose a different A or replay under a new Operation ID.
        """
        now = time.time()
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM chain_manager_return_checkpoints "
                "WHERE work_id=? AND task_id=? AND generation=?",
                (work_id, task_id, generation),
            ).fetchone()
            if row is None or float(row["acknowledged_at"] or 0) != 0:
                return None
            if row["active_manager_conversation_key"] != manager_conversation_key:
                return None
            if row["delivery_state"] == "DELIVERING":
                if (row["destination_conversation_key"] != manager_conversation_key
                        or row["delivery_operation_id"] != operation_id):
                    return None
                return dict(row)
            if row["delivery_state"] != "PENDING":
                return None
            changed = db.execute(
                "UPDATE chain_manager_return_checkpoints "
                "SET delivery_state='DELIVERING',"
                "destination_conversation_key=?,delivery_operation_id=?,updated_at=? "
                "WHERE work_id=? AND task_id=? AND generation=? AND delivery_state='PENDING' "
                "AND active_manager_conversation_key=? AND acknowledged_at=0",
                (manager_conversation_key, operation_id, now,
                 work_id, task_id, generation, manager_conversation_key),
            ).rowcount
            if changed != 1:
                return None
            latest = db.execute(
                "SELECT * FROM chain_manager_return_checkpoints "
                "WHERE work_id=? AND task_id=? AND generation=?",
                (work_id, task_id, generation),
            ).fetchone()
            return dict(latest)

    def finish_pending_manager_delivery(
        self, *, work_id: str, task_id: str, generation: int,
        manager_conversation_key: str, operation_id: str,
        outcome: str,
    ) -> dict:
        """Finish only the previously claimed exact external operation."""
        if outcome not in {"RETURNED_TO_MANAGER","NOT_APPLIED","UNKNOWN"}:
            raise ValueError("CHAIN_MANAGER_AUTO_RETURN_OUTCOME_INVALID")
        with self.store.transaction() as db:
            changed = db.execute(
                "UPDATE chain_manager_return_checkpoints "
                "SET delivery_state=?,delivery_receipt=?,updated_at=? "
                "WHERE work_id=? AND task_id=? AND generation=? "
                "AND delivery_state='DELIVERING' "
                "AND active_manager_conversation_key=? "
                "AND destination_conversation_key=? AND delivery_operation_id=?",
                (outcome, operation_id if outcome=="RETURNED_TO_MANAGER" else "",
                 time.time(), work_id, task_id, generation,
                 manager_conversation_key, manager_conversation_key, operation_id),
            ).rowcount
            if changed != 1:
                raise ValueError("CHAIN_MANAGER_AUTO_RETURN_CLAIM_CONFLICT")
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

    def full_recovery_relations(self, *, work_id: str) -> dict:
        """Read every active Chain Watch and return before any Manager rebinding.

        No first-100 cap and no schema writes. The caller validates current RCC
        identity, network and role using the complete set.
        """
        with self.store._readonly() as db:
            # Read Watch and checkpoint relationships from one consistent
            # SQLite snapshot, not two observations that can race a writer.
            db.execute("BEGIN")
            active = [
                {
                    "conversation_key": str(row["conversation_key"]),
                    "context": json.loads(row["context_json"] or "{}"),
                }
                for row in db.execute(
                    "SELECT conversation_key,context_json FROM delayed_send_watches "
                    "WHERE state IN ('WATCHING','RESERVED','PAUSED','MANAGER_RECOVERY_PENDING') "
                    "AND json_extract(context_json,'$.work_id')=? "
                    "ORDER BY task_id,generation", (work_id,),
                )
            ]
            returns = [
                dict(row) for row in db.execute(
                    "SELECT * FROM chain_manager_return_checkpoints WHERE work_id=? "
                    "AND acknowledged_at=0 ORDER BY task_id,generation",
                    (work_id,),
                )
            ]
            unresolved = [
                dict(row) for row in db.execute(
                    "SELECT task_id,generation,state FROM delayed_send_watches "
                    "WHERE state IN ('DISPATCHING','UNKNOWN') "
                    "AND json_extract(context_json,'$.work_id')=? "
                    "ORDER BY task_id,generation", (work_id,),
                )
            ]
        return {
            "watches": active, "checkpoints": returns,
            "unresolved_watches": unresolved,
            "complete": not unresolved,
        }

    def rebind_active_manager_atomic(
        self, *, work_id: str, manager_conversation_key: str,
        manager_instance_id: str, succession_proofs: list[dict] | None = None,
        require_latest_transfer: bool = False,
    ) -> dict:
        """Rebind every active Watch and every unacknowledged return in one TX.

        No browser send/replay and no new authority. Proof validation completes
        for *all* predecessors before any Watch or checkpoint is modified.
        """
        proofs = succession_proofs or []
        when = time.time()
        with self.store.transaction() as db:
            watches = list(db.execute(
                "SELECT task_id,generation,context_json FROM delayed_send_watches "
                "WHERE state IN ('WATCHING','RESERVED','PAUSED','MANAGER_RECOVERY_PENDING') "
                "AND json_extract(context_json,'$.work_id')=? "
                "ORDER BY task_id,generation", (work_id,),
            ).fetchall())
            returns = list(db.execute(
                "SELECT task_id,generation,active_manager_conversation_key "
                "FROM chain_manager_return_checkpoints "
                "WHERE work_id=? AND acknowledged_at=0 "
                "AND delivery_state!='DELIVERING' "
                "ORDER BY task_id,generation", (work_id,),
            ).fetchall())
            unresolved_claims = list(db.execute(
                "SELECT task_id,generation,destination_conversation_key,"
                "delivery_operation_id FROM chain_manager_return_checkpoints "
                "WHERE work_id=? AND acknowledged_at=0 "
                "AND delivery_state='DELIVERING' "
                "ORDER BY task_id,generation", (work_id,),
            ).fetchall())
            unresolved = list(db.execute(
                "SELECT task_id,generation,state FROM delayed_send_watches "
                "WHERE state IN ('DISPATCHING','UNKNOWN') "
                "AND json_extract(context_json,'$.work_id')=? "
                "ORDER BY task_id,generation", (work_id,),
            ).fetchall())
            modified_watches = []
            modified_returns = []
            def proven(previous: str) -> bool:
                if previous == manager_conversation_key:
                    return True
                for proof in proofs:
                    if (proof.get("predecessor_conversation_key") != previous
                            or proof.get("successor_conversation_key")
                                != manager_conversation_key):
                        continue
                    if not require_latest_transfer:
                        return True
                    # The automatic Core path requires an actual, newest BCT
                    # role-transfer receipt and current unique Manager role.
                    # Validate within the SAME SQLite transaction as rebinding.
                    project_id = str(proof.get("project_id") or "")
                    transfer_id = str(proof.get("transfer_id") or "")
                    if not project_id or not transfer_id:
                        continue
                    latest = db.execute(
                        "SELECT transfer_id,predecessor_conversation_key,"
                        "successor_conversation_key "
                        "FROM conversation_network_manager_transfers "
                        "WHERE project_id=? ORDER BY transferred_at DESC,"
                        "transfer_id DESC LIMIT 1", (project_id,),
                    ).fetchone()
                    if (latest is None or latest["transfer_id"] != transfer_id
                            or latest["predecessor_conversation_key"] != previous
                            or latest["successor_conversation_key"]
                               != manager_conversation_key):
                        continue
                    active_manager = db.execute(
                        "SELECT conversation_key FROM conversation_network_membership_tags "
                        "WHERE project_id=? AND lower(tag)='manager'",
                        (project_id,),
                    ).fetchall()
                    if [str(item["conversation_key"]) for item in active_manager] != [
                            manager_conversation_key]:
                        continue
                    return True
                return False
            for row in watches:
                ctx = json.loads(row["context_json"] or "{}")
                old = str(ctx.get("manager_conversation_key") or "")
                if not proven(old):
                    raise ValueError("DELAYED_MANAGER_SUCCESSION_PROOF_REQUIRED")
                if (old == manager_conversation_key
                        and str(ctx.get("manager_instance_id") or "") == manager_instance_id):
                    continue
                history = ctx.get("manager_recovery_history")
                if not isinstance(history, list):
                    history = []
                history.append({
                    "from_manager_conversation_key": old,
                    "to_manager_conversation_key": manager_conversation_key,
                    "at": when, "succession_proofs": proofs,
                })
                ctx["manager_recovery_history"] = history[-8:]
                ctx["manager_conversation_key"] = manager_conversation_key
                ctx["manager_instance_id"] = manager_instance_id
                modified_watches.append((json.dumps(ctx, sort_keys=True),
                                         row["task_id"], row["generation"]))
            for row in returns:
                old = str(row["active_manager_conversation_key"])
                if not proven(old):
                    raise ValueError("CHAIN_MANAGER_SUCCESSION_PROOF_REQUIRED")
                if old != manager_conversation_key:
                    modified_returns.append((manager_conversation_key,
                                             json.dumps(proofs, sort_keys=True),
                                             row["task_id"], row["generation"]))
            for context, task, generation in modified_watches:
                db.execute(
                    "UPDATE delayed_send_watches SET context_json=? "
                    "WHERE task_id=? AND generation=? AND state IN ('WATCHING','RESERVED','PAUSED','MANAGER_RECOVERY_PENDING')",
                    (context, task, generation),
                )
            for destination, proof_json, task, generation in modified_returns:
                db.execute(
                    "UPDATE chain_manager_return_checkpoints "
                    "SET active_manager_conversation_key=?,"
                    "manager_succession_proof_json=?,updated_at=? "
                    "WHERE task_id=? AND generation=? AND acknowledged_at=0",
                    (destination, proof_json, when, task, generation),
                )
        return {
            "work_id": work_id,
            "manager_conversation_key": manager_conversation_key,
            "updated_watches": len(modified_watches),
            "rebound_checkpoints": len(modified_returns),
            "examined_watches": len(watches),
            "examined_checkpoints": len(returns),
            "unresolved_watches": [
                {"task_id": str(row["task_id"]),
                 "generation": int(row["generation"]),
                 "state": str(row["state"])} for row in unresolved
            ],
            "unresolved_return_claims": [
                {"task_id": str(row["task_id"]),
                 "generation": int(row["generation"]),
                 "destination_conversation_key": str(row["destination_conversation_key"]),
                 "operation_id": str(row["delivery_operation_id"])}
                for row in unresolved_claims
            ],
            "complete": len(unresolved) == 0 and len(unresolved_claims) == 0,
            "atomic": True,
            "effects": "DURABLE_BINDING_ONLY_NO_MESSAGE",
        }

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
