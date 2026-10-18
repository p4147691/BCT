"""BCT-owned stale chat recovery without replaying an UNKNOWN operation.

A browser tab is replaceable. The original BCT work receipt is not.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Literal

from bct.core.models import ConflictError
from bct.core.store import Store


Decision = Literal[
    "ACCEPT_RESULT", "PROTECT_USER_CHAT", "KEEP_WORKING",
    "CHECK_AGAIN", "RECREATE_CHAT",
]


@dataclass(frozen=True)
class ChatObservation:
    bct_owned: bool
    user_active: bool
    checks: int
    no_progress_seconds: float
    progress_seen: bool = False
    response_confirmed: bool = False


def decide(observation: ChatObservation) -> Decision:
    """Checks are independent UI/state/receipt reads, not repeat sends."""
    if observation.response_confirmed:
        return "ACCEPT_RESULT"
    if observation.user_active or not observation.bct_owned:
        return "PROTECT_USER_CHAT"
    if observation.progress_seen:
        return "KEEP_WORKING"
    if observation.checks >= 2 and observation.no_progress_seconds >= 90:
        return "RECREATE_CHAT"
    return "CHECK_AGAIN"


def abandon_unknown_instance_claim(
    store: Store, *, original_work_id: str, original_operation_id: str,
    instance_id: str, observation: ChatObservation, reason: str,
) -> dict[str, object]:
    """Retire ONE stale broad RCC Claim; preserve original UNKNOWN forever.

    ABANDONED_UNVERIFIED does not mean NOT_APPLIED. The next send must
    belong to a new, independent chat and operation ID.
    """
    if decide(observation) != "RECREATE_CHAT":
        raise ConflictError("CHAT_CONTINUITY_NOT_STALE_OR_USER_ACTIVE")
    if not reason.strip() or len(reason) > 300:
        raise ConflictError("CHAT_CONTINUITY_REASON_REQUIRED")
    if not instance_id or any(ch in instance_id for ch in ": \n\t"):
        raise ConflictError("CHAT_CONTINUITY_INSTANCE_INVALID")
    resource = "rcc-instance:" + instance_id
    with store.transaction() as db:
        op = db.execute(
            "SELECT operation_id,work_id,capability,target,state,outcome "
            "FROM operations WHERE operation_id=?", (original_operation_id,),
        ).fetchone()
        if (op is None or op["work_id"] != original_work_id
                or op["capability"] != "relay_browser"
                or op["target"] != instance_id
                or op["state"] != "FINISHED" or op["outcome"] != "UNKNOWN"):
            raise ConflictError("CHAT_CONTINUITY_EXACT_UNKNOWN_REQUIRED")
        claim = db.execute(
            "SELECT operation_id,work_id,unresolved FROM resource_claims "
            "WHERE resource_key=?", (resource,),
        ).fetchone()
        if (claim is None or claim["operation_id"] != original_operation_id
                or claim["work_id"] != original_work_id):
            raise ConflictError("CHAT_CONTINUITY_ORIGINAL_CLAIM_MISMATCH")
        if claim["unresolved"] == 0:
            return {"action": "ALREADY_ABANDONED", "original_outcome": "UNKNOWN",
                    "original_operation_id": original_operation_id,
                    "resource_key": resource}
        changed = db.execute(
            "UPDATE resource_claims SET unresolved=0 "
            "WHERE resource_key=? AND operation_id=? AND work_id=? AND unresolved=1",
            (resource, original_operation_id, original_work_id),
        ).rowcount
        if changed != 1:
            raise ConflictError("CHAT_CONTINUITY_RACE")
        store._event(db, "OPERATION_CLAIM_ABANDONED_UNVERIFIED",
                     original_operation_id, {
            "original_work_id": original_work_id,
            "original_operation_id": original_operation_id,
            "resource_key": resource,
            "original_outcome": "UNKNOWN",
            "mode": "BCT_OWNED_STALE_CHAT_REPLACEMENT",
            "observations": observation.checks,
            "no_progress_seconds": observation.no_progress_seconds,
            "user_active": False,
            "no_resend_original": True,
            "reason": reason.strip(),
        })
    return {"action": "ABANDONED_UNVERIFIED", "original_outcome": "UNKNOWN",
            "original_operation_id": original_operation_id,
            "resource_key": resource, "next": "NEW_CHAT_NEW_OPERATION_ID"}


def main() -> int:
    parser = argparse.ArgumentParser(description="BCT stale dedicated-chat handoff")
    parser.add_argument("--db", required=True)
    parser.add_argument("--original-work", required=True)
    parser.add_argument("--original-operation", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--checks", type=int, required=True)
    parser.add_argument("--no-progress-seconds", type=float, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--bct-owned", action="store_true")
    parser.add_argument("--user-active", action="store_true")
    parser.add_argument("--progress-seen", action="store_true")
    parser.add_argument("--response-confirmed", action="store_true")
    parser.add_argument("--apply", action="store_true",
                        help="Without this option, assess only; do not change claims")
    args = parser.parse_args()
    observation = ChatObservation(
        bct_owned=args.bct_owned, user_active=args.user_active,
        checks=args.checks, no_progress_seconds=args.no_progress_seconds,
        progress_seen=args.progress_seen, response_confirmed=args.response_confirmed,
    )
    decision = decide(observation)
    if not args.apply:
        print(json.dumps({"decision": decision, "applied": False}))
        return 0
    if decision != "RECREATE_CHAT":
        print(json.dumps({"decision": decision, "applied": False}))
        return 2
    result = abandon_unknown_instance_claim(
        Store(args.db), original_work_id=args.original_work,
        original_operation_id=args.original_operation, instance_id=args.instance_id,
        observation=observation, reason=args.reason,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
