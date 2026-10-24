from __future__ import annotations

import json
import re
import time
from typing import Any

from .delivery_state import DeliveryEvent, DeliveryState, advance_delivery_state
from .models import ConflictError
from .store import Store


_DELIVERY_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_UUID = re.compile(
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
)
_SHA256 = re.compile(r"[a-f0-9]{64}")
_OBSERVATION_KEYS = frozenset({
    "rcc_session_id", "worker_tab_id", "worker_window_id",
    "manager_tab_id", "manager_window_id", "host_state", "error_code",
    "manager_return_sha256", "manager_return_length", "settings_sha256",
    "continuation_mode",
})


def _validate_identity(delivery_id: str, manager_key: str, worker_key: str,
                       request_sha256: str) -> None:
    if not _DELIVERY_ID.fullmatch(delivery_id):
        raise ValueError("DELIVERY_ID_INVALID")
    if (not _UUID.fullmatch(manager_key) or not _UUID.fullmatch(worker_key)
            or manager_key == worker_key):
        raise ValueError("DELIVERY_CONVERSATION_IDENTITY_INVALID")
    if not _SHA256.fullmatch(request_sha256):
        raise ValueError("DELIVERY_REQUEST_HASH_INVALID")


def _safe_observation(value: dict[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {}
    return {
        key: item for key, item in value.items()
        if key in _OBSERVATION_KEYS
        and (item is None or isinstance(item, (str, int, float, bool)))
    }


class DeliveryLedger:
    """Authoritative, minimal state for one exact relay roundtrip."""

    def __init__(self, store: Store):
        self.store = store

    def create_or_get(self, *, delivery_id: str, work_id: str, instance_id: str,
                      manager_conversation_key: str,
                      worker_conversation_key: str,
                      request_sha256: str, scope_id: str = "",
                      original_task: str = "", continuation_mode: str = "manual",
                      ) -> tuple[bool, dict[str, Any]]:
        _validate_identity(delivery_id, manager_conversation_key,
                           worker_conversation_key, request_sha256)
        if (scope_id and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", scope_id)) or len(original_task) > 8000:
            raise ValueError("DELIVERY_SCOPE_OR_TASK_INVALID")
        if continuation_mode not in {"manual", "auto_return"}:
            raise ValueError("DELIVERY_CONTINUATION_MODE_INVALID")
        now = time.time()
        with self.store.transaction() as db:
            existing = db.execute(
                "SELECT * FROM relay_deliveries WHERE delivery_id=?", (delivery_id,),
            ).fetchone()
            if existing is not None:
                expected = (
                    work_id, instance_id, manager_conversation_key,
                    worker_conversation_key, request_sha256,
                )
                actual = tuple(existing[key] for key in (
                    "work_id", "instance_id", "manager_conversation_key",
                    "worker_conversation_key", "request_sha256",
                ))
                if actual != expected:
                    raise ConflictError("DELIVERY_ID_REUSE_MISMATCH")
                return False, self._row(existing)
            db.execute(
                "INSERT INTO relay_deliveries VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (delivery_id, work_id, instance_id, manager_conversation_key,
                 worker_conversation_key, request_sha256,
                 DeliveryState.NOT_SENT.value, None, None,
                 (json.dumps({"scope_id": scope_id, "original_task": original_task,
                              "continuation_mode": continuation_mode},
                             ensure_ascii=False, sort_keys=True) if scope_id else "{}"),
                 now, now),
            )
            row = db.execute(
                "SELECT * FROM relay_deliveries WHERE delivery_id=?", (delivery_id,),
            ).fetchone()
        return True, self._row(row)

    def get_for_work(self, *, delivery_id: str, work_id: str) -> dict[str, Any]:
        db = self.store._connect()
        try:
            row = db.execute(
                "SELECT * FROM relay_deliveries WHERE delivery_id=?", (delivery_id,),
            ).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("DELIVERY_NOT_FOUND")
        if row["work_id"] != work_id:
            raise ConflictError("DELIVERY_ACCESS_DENIED")
        return self._row(row)

    def observe(self, *, delivery_id: str, work_id: str,
                event: DeliveryEvent | str,
                response_sha256: str | None = None,
                response_length: int | None = None,
                observation: dict[str, Any] | None = None) -> dict[str, Any]:
        if response_sha256 is not None and not _SHA256.fullmatch(response_sha256):
            raise ValueError("DELIVERY_RESPONSE_HASH_INVALID")
        if response_length is not None and response_length < 0:
            raise ValueError("DELIVERY_RESPONSE_LENGTH_INVALID")
        now = time.time()
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM relay_deliveries WHERE delivery_id=?", (delivery_id,),
            ).fetchone()
            if row is None:
                raise KeyError("DELIVERY_NOT_FOUND")
            if row["work_id"] != work_id:
                raise ConflictError("DELIVERY_ACCESS_DENIED")
            next_state = advance_delivery_state(row["state"], event)
            current_observation = json.loads(row["observation_json"] or "{}")
            current_observation.update(_safe_observation(observation))
            db.execute(
                "UPDATE relay_deliveries SET state=?,response_sha256=?,"
                "response_length=?,observation_json=?,updated_at=? WHERE delivery_id=?",
                (next_state.value,
                 response_sha256 if response_sha256 is not None else row["response_sha256"],
                 response_length if response_length is not None else row["response_length"],
                 json.dumps(current_observation, sort_keys=True, separators=(",", ":")),
                 now, delivery_id),
            )
            updated = db.execute(
                "SELECT * FROM relay_deliveries WHERE delivery_id=?", (delivery_id,),
            ).fetchone()
        return self._row(updated)

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        value = dict(row)
        value["observation"] = json.loads(value.pop("observation_json") or "{}")
        return value
