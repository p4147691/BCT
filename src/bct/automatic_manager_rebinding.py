"""Automatic reconciliation after a formally recorded Manager role transfer.

Only existing, exact successor Chat UUIDs with durable BCT transfer receipts
are eligible. No standby election, guessed new Chat or browser delivery occurs.
"""
from __future__ import annotations

import json
from typing import Any

from .chain_manager_recovery import ChainManagerRecoveryLedger
from .chain_direction import resolve_direction_target
from .conversation_network import manager_role_transfer_receipt


class AutomaticManagerRebinding:
    def __init__(self, *, store: Any, status_provider):
        self.store = store
        self.status_provider = status_provider
        self._cursor = ""

    def _work_ids(self) -> list[str]:
        with self.store._readonly() as db:
            tables = {
                str(r["name"]) for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            queries = []
            if "delayed_send_watches" in tables:
                queries.append(
                    "SELECT DISTINCT json_extract(d.context_json,'$.work_id') AS work_id "
                    "FROM delayed_send_watches d JOIN works w "
                    "ON w.work_id=json_extract(d.context_json,'$.work_id') "
                    "WHERE w.state='ACTIVE' AND d.state IN "
                    "('WATCHING','RESERVED','PAUSED','MANAGER_RECOVERY_PENDING')"
                )
            if "chain_manager_return_checkpoints" in tables:
                queries.append(
                    "SELECT DISTINCT c.work_id AS work_id "
                    "FROM chain_manager_return_checkpoints c JOIN works w "
                    "ON w.work_id=c.work_id WHERE w.state='ACTIVE' "
                    "AND c.acknowledged_at=0"
                )
            if not queries:
                return []
            rows = db.execute(
                " UNION ".join(queries) + " ORDER BY work_id"
            ).fetchall()
        return [str(row["work_id"]) for row in rows if row["work_id"]]

    def _latest_transfer(self, predecessor: str) -> dict | None:
        with self.store._readonly() as db:
            row = db.execute(
                "SELECT project_id,predecessor_conversation_key,"
                "successor_conversation_key,transfer_id,transferred_at "
                "FROM conversation_network_manager_transfers "
                "WHERE predecessor_conversation_key=? "
                "ORDER BY transferred_at DESC,transfer_id DESC LIMIT 1",
                (predecessor,),
            ).fetchone()
        if row is None:
            return None
        proof = dict(row)
        return manager_role_transfer_receipt(
            self.store, project_id=proof["project_id"],
            predecessor_conversation_key=predecessor,
            successor_conversation_key=proof["successor_conversation_key"],
        )

    def run_once(self, *, limit: int = 8) -> dict:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("AUTO_MANAGER_REBIND_LIMIT_INVALID")
        work_ids = self._work_ids()
        selected = [wid for wid in work_ids if wid > self._cursor][:limit]
        if not selected and self._cursor:
            self._cursor = ""
            selected = work_ids[:limit]
        if selected:
            self._cursor = selected[-1]
        if not selected:
            return {"status": "IDLE", "examined": 0, "work_count": len(work_ids),
                    "events": []}
        try:
            snapshot = self.status_provider()
        except Exception as exc:
            return {"status": "SENSOR_UNKNOWN", "examined": 0,
                    "work_count": len(work_ids), "reason": type(exc).__name__,
                    "events": []}
        # Existing Watches may predate the first Manager return. Only after
        # a linked Work is found, initialize the old return ledger if needed.
        ledger = ChainManagerRecoveryLedger(self.store)
        events = []
        for work_id in selected:
            try:
                relations = ledger.full_recovery_relations(work_id=work_id)
                olds = sorted(({
                    str(row["context"].get("manager_conversation_key") or "")
                    for row in relations["watches"]
                } | {
                    str(row["active_manager_conversation_key"] or "")
                    for row in relations["checkpoints"]
                }) - {""})
                if not olds:
                    continue
                candidates: dict[str, list[dict]] = {}
                for old in olds:
                    proof = self._latest_transfer(old)
                    if proof is None:
                        continue
                    candidate = str(proof["successor_conversation_key"])
                    candidates.setdefault(candidate, []).append(proof)
                # An explicit transfer for each old Manager must converge to
                # exactly one current successor. Never guess among candidates.
                if len(candidates) != 1:
                    continue
                successor, proofs = next(iter(candidates.items()))
                if any(old != successor and not any(
                        proof.get("predecessor_conversation_key") == old
                        for proof in proofs) for old in olds):
                    continue
                target = resolve_direction_target(
                    snapshot=snapshot, conversation_key=successor,
                )
                roles = {str(x).casefold() for x in target["node_info"].get("roles", [])}
                if "manager" not in roles or roles & {"worker", "supervisor"}:
                    continue
                scope = str(target["node_info"].get("network_id") or "")
                if not scope or any(str(proof["project_id"]) != scope for proof in proofs):
                    continue
                if target["node_info"].get("generating") is True:
                    # Do not interrupt an unfinished successor response.
                    continue
                connection = target["node_info"].get("connection")
                if (not isinstance(connection, dict)
                        or connection.get("disconnected") is not False):
                    # The successor must be positively connected. Missing
                    # telemetry is not proof of a usable Manager.
                    continue
                result = ledger.rebind_active_manager_atomic(
                    work_id=work_id,
                    manager_conversation_key=successor,
                    manager_instance_id=str(target["instance_id"]),
                    succession_proofs=proofs,
                    require_latest_transfer=True,
                )
                if result["updated_watches"] or result["rebound_checkpoints"]:
                    events.append({
                        "work_id": work_id, "status": "MANAGER_AUTO_REBOUND",
                        "successor_conversation_key": successor,
                        "updated_watches": result["updated_watches"],
                        "rebound_checkpoints": result["rebound_checkpoints"],
                        "complete": result["complete"],
                        "unresolved_watches": len(result["unresolved_watches"]),
                        "unresolved_return_claims":
                            len(result["unresolved_return_claims"]),
                    })
            except (KeyError, ValueError) as exc:
                events.append({
                    "work_id": work_id, "status": "RECONCILE_REQUIRED",
                    "reason": type(exc).__name__,
                })
        return {"status": "OBSERVED", "examined": len(selected),
                "work_count": len(work_ids), "events": events,
                "effects": "DURABLE_REBIND_ONLY_NO_MESSAGE"}
