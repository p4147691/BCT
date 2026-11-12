"""State R: current snapshot, stored networks, and read-only comparisons."""
from __future__ import annotations

import asyncio
import re

from typing import Any

from bct.conversation_network import ConversationNetworkError, conversation_scope_directory, project_view, resolve_project_id, scope_directory
from bct.core.models import Work
from bct.status_views import status_view

from .runtime import ChainRecipeRuntime

def compare_current_and_stored_networks_recipe(
    *, nodes: dict[str, Any], stored_scopes: list[dict[str, object]],
    stored_nodes: dict[str, dict[str, object]],
) -> dict[str, Any]:
    """Compare current Node Info with durable scope metadata; never decide a topology."""
    current_items = (
        nodes.get("current_nodes", {}).get("items", [])
        if isinstance(nodes.get("current_nodes"), dict) else []
    )
    node_cards: list[dict[str, Any]] = []
    observed_by_scope: dict[str, list[str]] = {}
    for node in current_items:
        if not isinstance(node, dict):
            continue
        key = str(node.get("conversation_uuid") or "").strip().lower()
        node_number = str(node.get("node_number") or "")
        if node.get("status") != "CONFIRMED" or not key:
            node_cards.append({
                "node_number": node_number, "conversation_key": key,
                "comparison": "UNCONFIRMED_CURRENT_NODE",
            })
            continue
        current_scope = str(node.get("network_id") or "")
        stored = stored_nodes.get(key)
        if stored is None:
            node_cards.append({
                "node_number": node_number, "conversation_key": key,
                "current_scope_id": current_scope,
                "comparison": "CURRENT_ONLY",
            })
            continue
        differences = []
        checks = (
            ("scope_id", current_scope, str(stored.get("scope_id") or "")),
            ("scope_name", str(node.get("network") or ""), str(stored.get("scope_name") or "")),
            ("roles", sorted(str(x).casefold() for x in node.get("roles", []) if str(x).strip()),
             sorted(str(x).casefold() for x in stored.get("role_tags", []) if str(x).strip())),
            ("node_memo", str(node.get("node_memo") or ""), str(stored.get("node_memo") or "")),
            ("assigned_task", str(node.get("assigned_task") or ""), str(stored.get("assigned_task") or "")),
        )
        for field, current, durable in checks:
            if current != durable:
                differences.append(field)
        scope_id = str(stored.get("scope_id") or current_scope)
        if scope_id:
            observed_by_scope.setdefault(scope_id, []).append(key)
        node_cards.append({
            "node_number": node_number, "conversation_key": key,
            "scope_id": scope_id,
            "comparison": "MATCH" if not differences else "MISMATCH",
            "different_fields": differences,
        })
    scope_cards = [
        {
            "scope_id": str(scope.get("scope_id") or ""),
            "scope_name": str(scope.get("scope_name") or ""),
            "stored_state": str(scope.get("state") or ""),
            "stored_member_count": int(scope.get("member_count") or 0),
            "open_member_keys": observed_by_scope.get(str(scope.get("scope_id") or ""), []),
            "current_presence": (
                "OPEN_OBSERVED" if observed_by_scope.get(str(scope.get("scope_id") or ""))
                else "NOT_OPEN"
            ),
        }
        for scope in stored_scopes
    ]
    return {"nodes": node_cards, "scopes": scope_cards}


def build_current_node_info_recipe(*, snapshot: dict[str, Any], sort_by: str = "number") -> dict[str, Any]:
    """Build current-only Node/RCC evidence from one already-read snapshot."""
    nodes = status_view(snapshot, "node", sort_by=sort_by)
    rcc = status_view(snapshot, "rcc", sort_by=sort_by)
    current_node_items = (
        nodes.get("current_nodes", {}).get("items", [])
        if isinstance(nodes.get("current_nodes"), dict) else []
    )
    candidates: dict[str, dict[str, Any]] = {}
    supervisor_candidates: list[dict[str, Any]] = []
    for node in current_node_items:
        if not isinstance(node, dict) or node.get("status") != "CONFIRMED":
            continue
        name = str(node.get("network") or "").strip()
        scope_id = str(node.get("network_id") or "").strip()
        if name:
            candidates.setdefault(scope_id or name.casefold(), {"title": name, "network_id": scope_id})
        roles = node.get("roles") if isinstance(node.get("roles"), list) else []
        if any(str(role).strip().casefold() == "supervisor" for role in roles):
            supervisor_candidates.append({
                "node_number": str(node.get("node_number") or ""),
                "name": str(node.get("name") or ""),
                "conversation_uuid": str(node.get("conversation_uuid") or ""),
                "network": name, "network_id": scope_id, "roles": list(roles),
                "active": node.get("active") is True,
            })
    return {
        "nodes": nodes, "rcc": rcc, "current_node_items": current_node_items,
        "candidates": candidates,
        "supervisor": {
            "status": ("MISSING" if not supervisor_candidates else
                       "PRESENT" if len(supervisor_candidates) == 1 else "MULTIPLE"),
            "role_tag": "supervisor", "candidates": supervisor_candidates,
            "scope": "CURRENT_CONFIRMED_NODES_ONLY",
        },
    }


async def read_stored_networks_recipe(runtime: ChainRecipeRuntime,
    *, current_node_items: list[dict[str, Any]], candidates: dict[str, dict[str, Any]],
    project: str = "", work_id: str = "", operation_id: str = "",
    stored_scope_directory: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    """Read durable network records and authorized historical context; no runtime observation."""
    scopes = (stored_scope_directory if stored_scope_directory is not None
              else await asyncio.to_thread(scope_directory, runtime.bct.store))
    network = None
    context = None
    context_status = "NOT_REQUESTED"
    historical_contexts: list[Any] = []
    historical_contexts_status = "AUTH_CONTEXT_REQUIRED"
    if not project and work_id and operation_id:
        try:
            directory = await runtime.make_executor("project_context")(
                work_id, operation_id, {"operation": "directory-get"},
            )
            if directory.get("outcome") == "APPLIED":
                payload = directory.get("output") or {}
                historical_contexts = payload.get("items", []) if isinstance(payload, dict) else []
                historical_contexts_status = "OK" if historical_contexts else "NO_CONTEXT"
                summaries = {str(item["project_id"]): item for item in historical_contexts
                             if isinstance(item, dict) and item.get("project_id")}
                with runtime.bct.store.transaction() as db:
                    rows = db.execute(
                        "SELECT project_id,display_name,active FROM conversation_network_projects "
                        "ORDER BY display_name,project_id LIMIT 200"
                    ).fetchall()
                for row in rows:
                    key = str(row["project_id"])
                    candidates[key] = {"title": str(row["display_name"]), "network_id": key,
                                       "active": bool(row["active"]),
                                       "context_summary": summaries.get(key)}
                for key, item in summaries.items():
                    if key not in candidates:
                        candidates[key] = {"title": str(item.get("title") or key),
                                           "network_id": key, "active": False,
                                           "context_summary": item}
            else:
                historical_contexts_status = "ACCESS_DENIED" if directory.get("error") and any(
                    marker in str(directory.get("error")).upper()
                    for marker in ("AUTH", "PERMISSION", "FORBIDDEN", "WORK_")
                ) else "QUERY_ERROR"
        except Exception as exc:
            historical_contexts_status = "ACCESS_DENIED" if any(
                marker in (type(exc).__name__ + ":" + str(exc)).upper()
                for marker in ("AUTH", "PERMISSION", "FORBIDDEN", "WORK_")
            ) else "QUERY_ERROR"
    elif project:
        historical_contexts_status = "NOT_REQUESTED"
    if project:
        try:
            project_id = await asyncio.to_thread(resolve_project_id, runtime.bct.store, project_reference=project)
            raw_network = await asyncio.to_thread(
                project_view, runtime.bct.store, project_id=project_id, include_internal_identity=True,
            )
            current_keys: dict[str, list[dict[str, Any]]] = {}
            for node in current_node_items:
                if not isinstance(node, dict) or node.get("status") != "CONFIRMED":
                    continue
                key = str(node.get("conversation_uuid") or "").strip()
                if key:
                    current_keys.setdefault(key, []).append(node)
            for member in raw_network.get("members", []):
                if not isinstance(member, dict):
                    continue
                key = str(member.pop("_conversation_key", ""))
                matches = current_keys.get(key, [])
                member["current_node_presence"] = (
                    "NOT_OPEN" if not matches else "CONFIRMED" if len(matches) == 1 else "AMBIGUOUS"
                )
                member["current_node"] = ({
                    "node_number": str(matches[0].get("node_number") or ""),
                    "active": matches[0].get("active") is True,
                    "generating": matches[0].get("generating") is True,
                } if len(matches) == 1 else None)
            network = {"status": "OK", **raw_network}
        except (ConversationNetworkError, ValueError) as exc:
            network = {"status": "NOT_FOUND", "reason": str(exc)}
        if not work_id or not operation_id:
            context_status = "AUTH_CONTEXT_REQUIRED"
        else:
            try:
                context = await runtime.make_executor("project_context")(
                    work_id, operation_id, {"operation": "overview-get", "project": project},
                )
                if context.get("outcome") == "APPLIED":
                    payload = context.get("output")
                    context_status = ("NO_CONTEXT" if not isinstance(payload, dict)
                                      or (payload.get("central") is None and not payload.get("worklogs"))
                                      else "OK")
                else:
                    reason = str(context.get("error") or "").upper()
                    context_status = "ACCESS_DENIED" if any(
                        marker in reason for marker in ("AUTH", "PERMISSION", "FORBIDDEN", "WORK_")
                    ) else "QUERY_ERROR"
            except Exception as exc:
                context_status = "ACCESS_DENIED" if any(
                    marker in (type(exc).__name__ + ":" + str(exc)).upper()
                    for marker in ("AUTH", "PERMISSION", "FORBIDDEN", "WORK_")
                ) else "QUERY_ERROR"
                context = {"status": "UNAVAILABLE", "reason_type": type(exc).__name__}
    return {
        "scope_directory": scopes, "network": network,
        "historical_contexts": historical_contexts,
        "historical_contexts_status": historical_contexts_status,
        "project_context": context, "context_status": context_status,
        "context_requires_work": bool(project and (not work_id or not operation_id)),
    }


async def check_conversation_network_recipe(runtime: ChainRecipeRuntime,
    *, snapshot: dict[str, Any], project: str = "", sort_by: str = "number",
    work_id: str = "", operation_id: str = "",
) -> dict[str, Any]:
    """Compatibility composition of current and stored network recipes."""
    current = build_current_node_info_recipe(snapshot=snapshot, sort_by=sort_by)
    stored = await read_stored_networks_recipe(runtime,
        current_node_items=current["current_node_items"], candidates=current["candidates"],
        project=project, work_id=work_id, operation_id=operation_id,
    )
    return {
        "status": "OK", "nodes": current["nodes"], "rcc": current["rcc"],
        "network": stored["network"], "network_candidates": list(current["candidates"].values()),
        "scope_directory": stored["scope_directory"], "supervisor": current["supervisor"],
        "candidates_scope": ("CURRENT_AND_HISTORICAL_AUTHORIZED"
                             if stored["historical_contexts_status"] in {"OK", "NO_CONTEXT"}
                             else "CURRENT_CONFIRMED_NODES_ONLY"),
        "historical_contexts": stored["historical_contexts"],
        "historical_contexts_status": stored["historical_contexts_status"],
        "project_context": stored["project_context"], "context_status": stored["context_status"],
        "context_requires_work": stored["context_requires_work"], "read_only": True,
    }


async def return_execute_plan_check_recipe(runtime: ChainRecipeRuntime,
    *, source_kind: str, work: Work | None, source_return: dict[str, Any] | None,
) -> dict[str, Any]:
    """Read plan evidence for this exact return; never create or repair it."""
    if source_kind != "MANAGER_RETURN":
        return {"status": "NOT_APPLICABLE"}
    binding = (source_return or {}).get("binding") or {}
    direction_id = str(binding.get("chain_direction_id") or "")
    task_id = str((source_return or {}).get("task_id") or "")
    generation = (source_return or {}).get("generation")
    if work is None or not direction_id or not task_id or type(generation) is not int:
        return {"status": "NOT_DECLARED"}
    if str(binding.get("work_id") or "") != work.work_id:
        return {"status": "UNAVAILABLE", "reason": "RETURN_WORK_BINDING_MISMATCH"}
    from bct.chain_execution_plan import ChainExecutionPlanLedger
    summary = await asyncio.to_thread(
        ChainExecutionPlanLedger.read_chain_return_summary,
        store=runtime.bct.store, work_id=work.work_id, direction_id=direction_id,
        task_id=task_id, generation=generation,
    )
    return {
        "chain": {
            "work_id": work.work_id, "direction_id": direction_id,
            "task_id": task_id, "generation": generation,
        },
        **summary,
    }


def chain_topology_preparation_recipe(*, current_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose a deterministic, read-only candidate order for a new chain.

    This deliberately does not repurpose an active role.  It tells the
    Manager which existing conversation can safely be reused and when a
    new conversation must be created through the existing browser recipe.
    """
    global_supervisors: list[dict[str, str]] = []
    reusable_workers: list[dict[str, str]] = []
    reserved: list[dict[str, str]] = []
    for node in current_items:
        if not isinstance(node, dict) or node.get("status") != "CONFIRMED":
            continue
        key = str(node.get("conversation_uuid") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", key):
            continue
        roles = {
            str(role).strip().casefold() for role in (node.get("roles") or [])
            if str(role).strip()
        }
        scope = str(node.get("network_id") or node.get("network") or "").strip()
        summary = {
            "conversation_key": key,
            "node_number": str(node.get("node_number") or ""),
        }
        # A global Supervisor is reusable only when it is not also an
        # operational Manager/Worker and is not tied to a project network.
        if roles == {"supervisor"} and not scope:
            global_supervisors.append(summary)
            continue
        # A Worker may be drawn only from a genuinely unassigned, idle
        # conversation.  A named task, active generation, role, or network
        # makes the node unavailable for implicit reassignment.
        if (not roles and not scope and not str(node.get("assigned_task") or "").strip()
                and node.get("generating") is not True):
            reusable_workers.append(summary)
            continue
        if roles or scope:
            reserved.append({
                **summary,
                "roles": sorted(roles),
                "scope": scope,
                "reason": "ROLE_OR_NETWORK_ALREADY_ASSIGNED",
            })
    return {
        "status": "READY",
        "read_only": True,
        "selection_order": [
            "reuse one existing global Supervisor",
            "otherwise create one new global Supervisor",
            "reuse one unassigned idle conversation as Worker and apply the Manager's network",
            "otherwise create one new Worker and apply the Manager's network",
        ],
        "global_supervisor_candidates": global_supervisors,
        "unassigned_worker_candidates": reusable_workers,
        "reserved_nodes": reserved,
        "required_creation": {
            "supervisor": not bool(global_supervisors),
            "worker": not bool(reusable_workers),
        },
        "prohibitions": [
            "Never reuse a Manager as Worker or Supervisor.",
            "Never take a node from another conversation network as an implicit Worker.",
            "Never use a network-bound Supervisor; Supervisor is global.",
        ],
    }


async def state_recipe(runtime: ChainRecipeRuntime,
    *, project: str = "", source_kind: str = "USER", work: Work | None = None,
    source_return: dict[str, Any] | None = None,
    report_target_conversation_key: str = "",
) -> dict[str, Any]:
    """Run State R with exactly one current runtime snapshot."""
    if runtime.status_provider is None:
        return {"status": "UNAVAILABLE", "reason": "STATUS_PROVIDER_NOT_CONFIGURED"}
    snapshot = await asyncio.to_thread(runtime.status_provider)
    current = build_current_node_info_recipe(snapshot=snapshot)
    nodes = current["nodes"]
    monitor = snapshot.get("monitor") if isinstance(snapshot.get("monitor"), dict) else {}
    current_items = (
        nodes.get("current_nodes", {}).get("items", [])
        if isinstance(nodes.get("current_nodes"), dict) else []
    )
    current_keys = [
        str(node.get("conversation_uuid") or "").strip().lower()
        for node in current_items
        if isinstance(node, dict) and node.get("status") == "CONFIRMED"
    ]
    stored_scopes, stored_nodes = await asyncio.gather(
        asyncio.to_thread(scope_directory, runtime.bct.store),
        asyncio.to_thread(conversation_scope_directory, runtime.bct.store, conversation_keys=current_keys),
    )
    stored = await read_stored_networks_recipe(runtime,
        current_node_items=current_items, candidates=current["candidates"], project=project,
        stored_scope_directory=stored_scopes,
    )
    return_plan_check = await return_execute_plan_check_recipe(runtime,
        source_kind=source_kind, work=work, source_return=source_return,
    )
    recovery_notices: dict[str, Any] = {"status": "NOT_REQUESTED", "notices": []}
    github_ci_notices: dict[str, Any] = {"status": "NOT_REQUESTED", "notices": []}
    if report_target_conversation_key:
        if not re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                report_target_conversation_key):
            return {"status": "INVALID_REQUEST", "reason": "STATE_REPORT_TARGET_ID_INVALID"}
        if work is None:
            recovery_notices = {"status": "WORK_UNAVAILABLE", "notices": []}
        else:
            from bct.send_delayed_message import DurableWatchLedger
            notices = await asyncio.to_thread(
                DurableWatchLedger(runtime.bct.store).recovery_notices,
                work_id=work.work_id,
                report_target_conversation_key=report_target_conversation_key,
            )
            recovery_notices = {
                "status": "OK", "report_target_conversation_key": report_target_conversation_key,
                "notices": notices,
                "next_action": "AUTHOR_RECOVER_NODE_DIRECTION" if notices else "NONE",
            }
            ci_notices = await asyncio.to_thread(
                runtime.bct.store.get_github_run_inbox,
                work_id=work.work_id,
                conversation_uuid=report_target_conversation_key,
                limit=20,
            )
            terminal_notices = [
                notice for notice in ci_notices
                if notice.get("state") != "WAITING_EXTERNAL"
            ]
            github_ci_notices = {
                "status": "OK",
                "report_target_conversation_key": report_target_conversation_key,
                "notices": ci_notices,
                "next_action": (
                    "REVIEW_CI_RESULT_AND_AUTHOR_NEXT_DIRECTION"
                    if terminal_notices else "NONE"
                ),
            }
    topology_preparation = chain_topology_preparation_recipe(current_items=current_items)
    # The Manager needs a compact, receipt-backed view of the work already
    # in motion before authoring another Direction.  It is information, not
    # an authorization or a request for BCT to choose a branch.  The
    # existing Direction/branch/watch ledgers remain the only durable
    # relationship records.
    chain_work_context: dict[str, Any] = {
        "status": "NOT_APPLICABLE",
        "root_work_id": "",
        "nodes": [],
        "branch_requests": [],
        "manager_attention": [],
        "effects": "NONE_READ_ONLY",
    }
    if work is not None:
        from bct.chain_direction import ChainBranchRequestLedger
        tree = await asyncio.to_thread(
            ChainBranchRequestLedger.tree, store=runtime.bct.store,
            root_work_id=work.work_id,
        )
        chain_work_context = {"status": "OK", **tree, "effects": "NONE_READ_ONLY"}
    return {
        "status": "OK",
        "observed_at": monitor.get("generated_at"),
        "current_nodes": nodes,
        "stored_networks": stored_scopes,
        "network_comparison": compare_current_and_stored_networks_recipe(
            nodes=nodes, stored_scopes=stored_scopes, stored_nodes=stored_nodes,
        ),
        "selected_network": stored["network"],
        "project_context": stored["project_context"],
        "context_status": stored["context_status"],
        "return_execute_plan_check": return_plan_check,
        "recovery_notices": recovery_notices,
        "github_ci_notices": github_ci_notices,
        "chain_work_context": chain_work_context,
        "chain_topology_preparation": topology_preparation,
        "read_only": True,
    }
