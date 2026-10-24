from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from bct.core.models import FeatureRequest, FeatureResult, Outcome, PreconditionError, Work
from bct.integrations.github import GitHubClient
from bct.trace_timing import trace_stage

_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SHA = re.compile(r"[0-9a-f]{40}")


def _settings(path: Path) -> tuple[float, float, float]:
    # Reload on registration: future subscriptions can be tuned without restart.
    import tomllib
    value = tomllib.loads(path.read_text(encoding="utf-8")).get("github_inbox", {})
    if not isinstance(value, dict): raise PreconditionError("GITHUB_INBOX_CONFIG_INVALID")
    initial, maximum, timeout = (float(value.get(k, d)) for k, d in (("initial_seconds", 5), ("max_seconds", 30), ("timeout_seconds", 300)))
    if not (5 <= initial <= maximum <= 30 and 30 <= timeout <= 86400): raise PreconditionError("GITHUB_INBOX_CONFIG_BOUNDS")
    return initial, maximum, timeout


class GitHubRunInboxFeature:
    capability = "github_run_watch"

    def __init__(self, store: Any, client: GitHubClient, policy_path: str | Path):
        self.store, self.client, self.policy_path = store, client, Path(policy_path)

    def prepare(self, *, work: Work, arguments: dict[str, Any]) -> FeatureRequest:
        repository = str(arguments.get("repository") or "").lower()
        head_sha = str(arguments.get("head_sha") or "").lower()
        raw_run_id = arguments.get("run_id")
        try: run_id = int(raw_run_id)
        except (TypeError, ValueError) as exc: raise PreconditionError("GITHUB_RUN_ID_INVALID") from exc
        node_id, workflow = str(arguments.get("initiator_node_id") or ""), str(arguments.get("workflow") or "")
        notify_nodes = arguments.get("notify_nodes", [])
        manager_node_id = arguments.get("manager_node_id")
        context = arguments.get("context", {})
        trigger = str(arguments.get("trigger") or "")
        try:
            context_size = len(json.dumps(context, sort_keys=True, separators=(",", ":")))
        except (TypeError, ValueError) as exc:
            raise PreconditionError("GITHUB_RUN_WATCH_CONTEXT_INVALID") from exc
        if (isinstance(raw_run_id, bool) or not _REPO.fullmatch(repository)
                or not _SHA.fullmatch(head_sha) or run_id < 1 or not node_id
                or len(node_id) > 128 or not workflow or len(workflow) > 200 or trigger != f"github-run:{run_id}:terminal"
                or not isinstance(context, dict) or len(context) > 24
                or context_size > 4096
                or not isinstance(notify_nodes, list) or len(notify_nodes) > 16
                or any(not isinstance(node, str) or not node or len(node) > 128 for node in notify_nodes)
                or (manager_node_id is not None and (not isinstance(manager_node_id, str) or not manager_node_id or len(manager_node_id) > 128))
                or (bool(arguments.get("notify_manager", False)) and not manager_node_id)):
            raise PreconditionError("GITHUB_RUN_WATCH_ARGUMENTS_INVALID")
        _settings(self.policy_path)
        return FeatureRequest(self.capability, f"{repository}/actions/runs/{run_id}", {
            "repository": repository, "run_id": run_id, "head_sha": head_sha, "work_id": work.work_id, "initiator_node_id": node_id,
            "initiator_conversation_uuid": str(arguments.get("initiator_conversation_uuid") or "") or None,
            "workflow": workflow, "context": context, "trigger": trigger,
            "notify_user": bool(arguments.get("notify_user", True)), "notify_manager": bool(arguments.get("notify_manager", False)),
            "notify_nodes": list(dict.fromkeys(notify_nodes)), "manager_node_id": manager_node_id,
            "next_step": str(arguments.get("next_step") or "Review this terminal CI result before any follow-up.")[:500],
        }, (f"github-inbox-registration:{work.work_id}:{node_id}:{run_id}:{head_sha}",),
           {"head_sha": head_sha, "advisory_only": True})

    def execute(self, request: FeatureRequest) -> FeatureResult:
        v = request.arguments
        return self._register_and_watch(v)

    def register(self, *, work_id: str, work: Work, arguments: dict[str, Any]) -> FeatureResult:
        request = self.prepare(work=work, arguments=arguments); v = request.arguments
        v["work_id"] = work_id
        return self._register_and_watch(v)

    def _register_and_watch(self, v: dict[str, Any]) -> FeatureResult:
        recipients = [v["initiator_node_id"], *v["notify_nodes"]]
        if v["notify_manager"]:
            recipients.append(v["manager_node_id"])
        record = None
        created = False
        for node_id in dict.fromkeys(recipients):
            record, new = self.store.register_github_run_inbox(
                subscription_id=uuid.uuid4().hex, repository=v["repository"], run_id=v["run_id"],
                head_sha=v["head_sha"], workflow=v["workflow"], context=v["context"],
                work_id=v["work_id"], node_id=node_id,
                conversation_uuid=v["initiator_conversation_uuid"] if node_id == v["initiator_node_id"] else None,
                notify_user=v["notify_user"], notify_manager=(v["notify_manager"] and node_id == v.get("manager_node_id")),
                next_step=v["next_step"], trigger=v["trigger"],
            )
            created = created or new
        assert record is not None
        if created:
            self._watch(record["subscription_id"], v)
        return FeatureResult(Outcome.APPLIED, {"subscription_id": record["subscription_id"], "state": record["state"], "watcher_started": created, "next_step_advisory_only": True})

    def _watch(self, subscription_id: str, v: dict[str, Any]) -> None:
        initial, maximum, timeout = _settings(self.policy_path); delay, deadline = initial, time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                try:
                    run = self.client.get_workflow_run(v["repository"], v["run_id"])
                    repo = str(run.get("repository", {}).get("full_name") or "").lower(); sha = str(run.get("head_sha") or "").lower()
                    if repo != v["repository"] or sha != v["head_sha"]:
                        self.store.finish_github_run_inbox(subscription_id=subscription_id, state="FAILED", conclusion=None, url=None, error_summary="GITHUB_RUN_IDENTITY_MISMATCH"); return
                    if str(run.get("status") or "") == "completed":
                        conclusion = str(run.get("conclusion") or "").lower(); state = "SUCCESS" if conclusion == "success" else "CANCELLED" if conclusion in {"cancelled", "skipped"} else "FAILED"
                        jobs = self.client.get_workflow_jobs(v["repository"], v["run_id"])
                        bad_job = next((j for j in jobs if str(j.get("conclusion") or "").lower() not in {"", "success", "skipped"}), None)
                        failed = None
                        if isinstance(bad_job, dict):
                            name = str(bad_job.get("name") or "unknown")[:120]
                            steps = bad_job.get("steps") if isinstance(bad_job.get("steps"), list) else []
                            step = next((str(k.get("name"))[:120] for k in steps if isinstance(k, dict) and str(k.get("conclusion") or "").lower() == "failure"), None)
                            failed = "failed job: " + name + ("; step: " + step if step else "")
                        self.store.finish_github_run_inbox(subscription_id=subscription_id, state=state, conclusion=conclusion, url=str(run.get("html_url") or "") or None, error_summary=failed); return
                except Exception:
                    # API errors are observational and retry only within this bounded watcher.
                    pass
                time.sleep(min(delay, max(0, deadline-time.monotonic()))); delay = min(maximum, delay * 2)
            self.store.finish_github_run_inbox(subscription_id=subscription_id, state="TIMED_OUT", conclusion=None, url=None, error_summary="GITHUB_RUN_WATCH_TIMEOUT")
        except Exception:
            self.store.finish_github_run_inbox(subscription_id=subscription_id, state="FAILED", conclusion=None, url=None, error_summary="GITHUB_RUN_WATCHER_CRASH")
        finally:
            trace_stage("github_inbox_terminal", tool_kind="github_run_watch")
