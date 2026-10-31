"""Reuse the durable GitHubRunInbox watcher when an exact PR creation succeeds."""
from __future__ import annotations

import hashlib

from .background_operations import launch_background_operation
from .core.models import Work


def schedule_pr_ci_inbox(bct, principal, source_work_id: str, evidence: dict) -> dict:
    """Start a detached watcher; missing manager bindings remain Work Inbox only."""
    repo = str(evidence.get("repository") or "").lower()
    sha = str(evidence.get("head_sha") or "").lower()
    number = evidence.get("number")
    if not repo or len(sha) != 40 or not isinstance(number, int):
        return {"status": "NO_EXACT_PR_EVIDENCE"}
    if repo != "p4147691/bct":
        return {"status": "NOT_BCT_REPOSITORY"}
    if "github_run_watch" not in principal.capabilities:
        return {"status": "WATCH_CAPABILITY_UNAVAILABLE"}
    work = bct.store.get_work(source_work_id)
    if work.owner_principal_id != principal.principal_id or work.state != "ACTIVE":
        return {"status": "WORK_NOT_ACTIVE"}
    with bct.store._readonly() as db:
        attached = db.execute(
            "SELECT DISTINCT s.manager_node_id FROM orchestration_sessions s "
            "JOIN orchestration_attachments a ON a.node_id=s.manager_node_id AND a.active=1 "
            "WHERE s.work_id=? AND s.work_assignment_epoch=? "
            "AND s.state='ACTIVE' AND s.manager_epoch>0 "
            "AND s.manager_node_id IS NOT NULL",
            (work.work_id, work.assignment_epoch),
        ).fetchall()
    managers = {str(row["manager_node_id"]) for row in attached}
    manager = next(iter(managers)) if len(managers) == 1 else ""
    # A Work Inbox recipient is not a fabricated conversation/manager identity.
    recipient = manager or ("work:" + hashlib.sha256(source_work_id.encode()).hexdigest()[:24])
    digest = hashlib.sha256(f"{source_work_id}|{repo}|{sha}".encode()).hexdigest()[:24]
    follow_work_id = "bct-ci-follow-" + digest
    follow_work = Work(follow_work_id, "Existing GitHub CI Inbox auto-follow",
                       work.roots, frozenset({"github_run_watch"}), principal.principal_id)
    try:
        bct.store.create_work(follow_work)
    except Exception:
        existing = bct.store.get_work(follow_work_id)
        if existing != follow_work:
            raise
    arguments = {
        "repository": repo, "head_sha": sha, "follow_head": True,
        "workflow": "BCT CI", "initiator_node_id": recipient,
        "inbox_work_id": source_work_id,
        "notify_user": True, "notify_manager": bool(manager),
        "manager_node_id": manager or None,
        "trigger": f"github-head:{sha}:terminal",
        "context": {"pr": number, "source_work_id": source_work_id},
    }
    receipt = launch_background_operation(
        bct, principal=principal, work_id=follow_work_id,
        operation_id="ci-follow-" + digest,
        capability="github_run_watch", arguments=arguments, approval_ref=None,
    )
    return {"status": "REGISTERED", "watch_work_id": follow_work_id,
            "operation_id": "ci-follow-" + digest,
            "recipient_kind": "MANAGER" if manager else "WORK",
            "receipt_state": receipt.state.value}
