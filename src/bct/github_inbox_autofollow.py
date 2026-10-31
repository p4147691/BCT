"""Route exact PR and main CI completions into the existing durable GitHub Inbox."""
from __future__ import annotations

import hashlib

from .background_operations import launch_background_operation
from .core.models import Work


def _schedule(bct, principal, source_work_id: str, *, repository: str,
              sha: str, event: str, context: dict) -> dict:
    repo = repository.lower()
    sha = sha.lower()
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
    recipient = manager or ("work:" + hashlib.sha256(source_work_id.encode()).hexdigest()[:24])
    digest = hashlib.sha256(f"{source_work_id}|{repo}|{sha}|{event}".encode()).hexdigest()[:24]
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
        "expected_event": event,
        "workflow": "BCT CI", "initiator_node_id": recipient,
        "inbox_work_id": source_work_id,
        "notify_user": True, "notify_manager": bool(manager),
        "manager_node_id": manager or None,
        "trigger": (f"github-head:{sha}:push:terminal" if event == "push"
                    else f"github-head:{sha}:terminal"),
        "context": {**context, "source_work_id": source_work_id},
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


def schedule_pr_ci_inbox(bct, principal, source_work_id: str, evidence: dict) -> dict:
    """Follow one exactly confirmed PR without another external mutation."""
    sha = str(evidence.get("head_sha") or "")
    repo = str(evidence.get("repository") or "")
    number = evidence.get("number")
    if len(sha) != 40 or not isinstance(number, int) or not repo:
        return {"status": "NO_EXACT_PR_EVIDENCE"}
    return _schedule(bct, principal, source_work_id, repository=repo,
                     sha=sha, event="pull_request", context={"pr": number})


def schedule_main_ci_inbox(bct, principal, source_work_id: str, evidence: dict) -> dict:
    """Follow exact main SHA only after GitHub confirms the push state."""
    repo = str(evidence.get("repository") or "")
    sha = str(evidence.get("local_sha") or "")
    if (evidence.get("branch") != "main" or len(sha) != 40
            or sha != evidence.get("remote_sha")
            or evidence.get("sync_state") != "IN_SYNC" or not repo):
        return {"status": "NO_EXACT_MAIN_PUSH_EVIDENCE"}
    return _schedule(bct, principal, source_work_id, repository=repo,
                     sha=sha, event="push", context={"branch": "main"})
