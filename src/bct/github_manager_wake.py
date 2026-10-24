"""GitHub Inbox manager wake coordinator (opt-in, existing relay only).

Never owns GitHub/Worker result payloads and never assumes a submission when
the transport result is ambiguous. The injected relay must enforce exact
manager identity and epoch again at submission time.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Any


@dataclass(frozen=True)
class WakePlan:
    manager_node_id: str
    manager_epoch: int
    conversation_uuid: str
    subscription_ids: tuple[str, ...]
    token: str
    message: str


class GithubManagerWake:
    def __init__(self, store: Any):
        self.store = store

    def plan(self, *, manager_node_id: str, manager_epoch: int,
             conversation_uuid: str, idle: bool, limit: int = 80) -> WakePlan | None:
        if not manager_node_id or not conversation_uuid or manager_epoch < 1:
            raise ValueError("MANAGER_WAKE_IDENTITY_INVALID")
        if not idle:
            return None
        db = self.store._connect()
        try:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute(
                "SELECT i.subscription_id FROM github_run_inbox i "
                "JOIN github_run_inbox_recipients r ON r.subscription_id=i.subscription_id "
                "WHERE r.node_id=? AND r.notify_manager=1 AND r.unread=1 "
                "AND i.state!='WAITING_EXTERNAL' "
                "ORDER BY i.updated_at,i.subscription_id LIMIT ?",
                (manager_node_id, max(1, min(limit, 80))),
            ).fetchall()
        finally:
            db.close()
        ids = tuple(sorted({str(r["subscription_id"]) for r in rows}))
        if not ids:
            return None
        # Stable generation-independent deduplication of a specific batch.
        payload = json.dumps([manager_node_id, manager_epoch, conversation_uuid, ids],
                             ensure_ascii=False, separators=(",", ":"))
        token = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        message = (
            "BCT GitHub Inbox에 확인할 완료 결과가 있습니다. "
            f"미확인 결과 {len(ids)}건, wake_ref={token}. "
            "권한이 있는 Work의 기존 bct_inbox_get에서 확인하고 판단하세요. "
            "이 알림은 작업 완료 또는 결과 ACK가 아닙니다."
        )
        return WakePlan(manager_node_id, manager_epoch, conversation_uuid, ids, token, message)

    def dispatch(self, plan: WakePlan, *, assert_manager_epoch: Callable[[str, int, str], None],
                 existing_relay: Callable[[str, str, str], dict[str, Any]]) -> str:
        """Submit only through an injected existing one-shot relay.

        Unknown is sticky: no automatic replay, no Inbox acknowledge.
        """
        assert_manager_epoch(plan.manager_node_id, plan.manager_epoch, plan.conversation_uuid)
        with self.store.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS github_manager_wake_attempts ("
                "token TEXT PRIMARY KEY, manager_node_id TEXT NOT NULL, "
                "manager_epoch INTEGER NOT NULL, state TEXT NOT NULL, "
                "message_sha256 TEXT NOT NULL)"
            )
            prior = db.execute("SELECT state FROM github_manager_wake_attempts WHERE token=?",
                               (plan.token,)).fetchone()
            if prior:
                return str(prior["state"])
            db.execute("INSERT INTO github_manager_wake_attempts VALUES(?,?,?,?,?)",
                       (plan.token, plan.manager_node_id, plan.manager_epoch,
                        "UNKNOWN", hashlib.sha256(plan.message.encode("utf-8")).hexdigest()))
        # Persist UNKNOWN before crossing the transport boundary. A lost ACK
        # leaves UNKNOWN rather than risking a duplicate submission.
        try:
            receipt = existing_relay(plan.conversation_uuid, plan.message, plan.token)
        except Exception:
            return "UNKNOWN"
        if not (isinstance(receipt, dict) and receipt.get("ok") is True
                and receipt.get("delivery_id") == plan.token
                and receipt.get("exact_turn_confirmed") is True):
            return "UNKNOWN"
        with self.store.transaction() as db:
            db.execute("UPDATE github_manager_wake_attempts SET state='SUBMITTED' "
                       "WHERE token=? AND state='UNKNOWN'", (plan.token,))
        return "SUBMITTED"

class GithubWakeRecoveryAdapter:
    """Recovery-cycle adapter. Disabled unless a trusted existing relay is injected.

    Identity and idle observation are supplied by the existing Manager owner;
    failure to observe them means no submission, never a guessed wake.
    """
    def __init__(self, store: Any, manager_candidates: Callable[[], list[dict[str, Any]]],
                 existing_relay: Callable[[str, str, str], dict[str, Any]] | None = None,
                 assert_manager_epoch: Callable[[str, int, str], None] | None = None):
        self.coordinator = GithubManagerWake(store)
        self.manager_candidates = manager_candidates
        self.existing_relay = existing_relay
        self.assert_manager_epoch = assert_manager_epoch

    def run_once(self) -> dict[str, Any]:
        result = {"plans": 0, "submitted": 0, "busy": 0, "unknown": 0}
        for candidate in self.manager_candidates():
            # Authority/epoch/idle must originate from a trusted current observation.
            if not candidate.get("idle", False):
                result["busy"] += 1
                continue
            if not (self.assert_manager_epoch and self.existing_relay):
                continue
            self.assert_manager_epoch(candidate["node_id"], candidate["epoch"],
                                      candidate["conversation_uuid"])
            plan = self.coordinator.plan(
                manager_node_id=candidate["node_id"],
                manager_epoch=candidate["epoch"],
                conversation_uuid=candidate["conversation_uuid"], idle=True)
            if plan is None:
                continue
            result["plans"] += 1
            outcome = self.coordinator.dispatch(plan,
                assert_manager_epoch=self.assert_manager_epoch,
                existing_relay=self.existing_relay)
            if outcome == "SUBMITTED":
                result["submitted"] += 1
            elif outcome == "UNKNOWN":
                result["unknown"] += 1
        return result
