"""Mechanically connect a completed Worker reply to its fixed Manager.

This component never decides whether the task is complete and never creates a
new Delivery.  It only advances a Delivery whose Manager, Worker, return
contract and opt-in continuation mode were frozen before the Worker submit.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import threading
import uuid
from typing import Any

from bct.core.delivery_state import DeliveryState
from bct.core.store import Store


class DeliveryContinuationRecovery:
    """Poll opted-in active Deliveries and return one captured reply exactly once."""

    def __init__(self, store: Store, relay_feature: Any):
        self.store = store
        self.relay_feature = relay_feature
        self._run_lock = threading.Lock()

    def _candidates(self, *, limit: int) -> list[dict[str, Any]]:
        db = self.store._connect()
        try:
            rows = db.execute(
                "SELECT d.* FROM relay_deliveries d JOIN works w ON w.work_id=d.work_id "
                "WHERE w.state='ACTIVE' AND d.state IN "
                "('SENT_WAITING','REPLY_CAPTURED','NEEDS_REVIEW') "
                "ORDER BY d.updated_at,d.delivery_id",
            ).fetchall()
        finally:
            db.close()
        answer: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            try:
                observation = json.loads(value.get("observation_json") or "{}")
            except (TypeError, ValueError):
                continue
            return_unknown = (
                value.get("state") == DeliveryState.NEEDS_REVIEW.value
                and bool(value.get("response_sha256"))
                and observation.get("host_state") == DeliveryState.REPLY_CAPTURED.value
                and observation.get("error_code") == "RCC_DELIVERY_EFFECT_UNKNOWN"
            )
            if (isinstance(observation, dict)
                    and observation.get("continuation_mode") == "auto_return"
                    and (value.get("state") != DeliveryState.NEEDS_REVIEW.value
                         or return_unknown)):
                value["observation"] = observation
                answer.append(value)
                if len(answer) >= limit:
                    break
        return answer

    @staticmethod
    def _operation_id(kind: str, delivery_id: str) -> str:
        digest = hashlib.sha256(delivery_id.encode("utf-8")).hexdigest()[:20]
        return f"continuity-{kind}-{digest}-{uuid.uuid4().hex[:8]}"

    def _execute(self, *, work: Any, row: dict[str, Any], command: str):
        request = self.relay_feature.prepare(work=work, arguments={
            "command": command,
            "instance_id": row["instance_id"],
            "delivery_id": row["delivery_id"],
            "timeout_s": 5.0,
        })
        return self.relay_feature.execute(replace(
            request,
            operation_id=self._operation_id(command.removeprefix("delivery-"),
                                            row["delivery_id"]),
        ))

    def run_once(self, *, limit: int = 8) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "checked": 0, "captured": 0, "returned": 0, "queued": 0,
            "errors": [], "run_owned": False,
        }
        if not self._run_lock.acquire(blocking=False):
            return summary
        summary["run_owned"] = True
        try:
            for row in self._candidates(limit=max(1, min(int(limit), 32))):
                summary["checked"] += 1
                try:
                    work = self.store.get_work(str(row["work_id"]))
                    state = str(row["state"])
                    if state == DeliveryState.NEEDS_REVIEW.value:
                        reconciled = self._execute(
                            work=work, row=row, command="delivery-manager-status",
                        )
                        state = str(reconciled.evidence.get("delivery_state") or state)
                        if state == DeliveryState.RETURNED.value:
                            summary["returned"] += 1
                        continue
                    if state == DeliveryState.SENT_WAITING.value:
                        observed = self._execute(
                            work=work, row=row, command="delivery-status",
                        )
                        state = str(observed.evidence.get("delivery_state") or state)
                        if state == DeliveryState.REPLY_CAPTURED.value:
                            summary["captured"] += 1
                    if state != DeliveryState.REPLY_CAPTURED.value:
                        continue
                    returned = self._execute(
                        work=work, row=row, command="delivery-return",
                    )
                    state = str(returned.evidence.get("delivery_state") or state)
                    if state == DeliveryState.RETURNED.value:
                        summary["returned"] += 1
                    elif returned.evidence.get("pending") is True:
                        summary["queued"] += 1
                except Exception as exc:
                    summary["errors"].append({
                        "delivery_id": str(row.get("delivery_id") or ""),
                        "error": type(exc).__name__ + ":" + str(exc)[:160],
                    })
        finally:
            self._run_lock.release()
        return summary
