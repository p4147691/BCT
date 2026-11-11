"""Prepare/Send Direction R and exact send/watch composition."""
from __future__ import annotations

import asyncio
import re

from typing import Any

from bct.chain_message_preflight import EXPLICIT_NEXT_TASK_SUFFIX, check_chain_work, prepare_chain_instruction
from bct.core.models import Work

from .direction import read_saved_direction
from .network import apply_conversation_network_recipe
from .outline import chain_recipe_progress
from .recovery import _assert_node_send_allowed
from .runtime import ChainRecipeRuntime

def prepare_derived_dispatch_recipe(
    *, assessment: dict[str, Any], targets: list[tuple[int, dict[str, Any]]],
) -> dict[str, Any]:
    """Select only Manager-declared, immediately independent targets.

    This is a Chain Recipe sub-recipe, not a public command and not an AI
    decision maker.  It turns the saved Direction assessment into either
    a target subset that may proceed to delivery or a durable deferred
    card.  It does not create a node, inspect a browser, or send anything.
    """
    from bct.chain_derived_tasks import dispatch_plan

    derived_dispatch = dispatch_plan(
        tasks=list(assessment.get("derived_tasks") or []),
        targets=[target for _, target in targets],
    )
    ready_targets = [
        (index, target) for index, target in targets
        if target["conversation_key"] in derived_dispatch["ready_target_keys"]
    ]
    dispatch_card = {
        "classification": derived_dispatch["classification"],
        "deferred": derived_dispatch["deferred"],
    }
    if not ready_targets:
        return {
            "status": "DEFERRED", "reason": "CHAIN_DERIVED_TASKS_NOT_READY",
            "derived_dispatch": dispatch_card, "authorizes_send": False,
        }
    return {
        "status": "READY", "targets": ready_targets,
        "derived_dispatch": dispatch_card,
    }


async def prepare_send_direction_recipe(runtime: ChainRecipeRuntime,
    *, direction: dict[str, Any], assessment: dict[str, Any], task_id: str,
    operation_id: str, target_conversation_key: str, max_generations: int,
) -> dict[str, Any]:
    """Validate a saved Direction and select targets before any network effect or send."""
    from bct.chain_direction import (
        ChainDirectionLedger, compose_target_direction, validate_direction_assessment,
        target_direction_id,
    )
    if runtime.status_provider is None:
        return {"status": "UNAVAILABLE", "reason": "STATUS_PROVIDER_NOT_CONFIGURED"}
    try:
        checked = validate_direction_assessment(assessment, decision=direction["decision"])
    except ValueError as exc:
        return {"status": "INVALID_REQUEST", "reason": str(exc)}
    if type(max_generations) is not int or not 0 <= max_generations <= 12:
        return {"status": "INVALID_REQUEST", "reason": "CHAIN_MESSAGE_MAX_GENERATIONS_INVALID"}
    targets = [(index, target) for index, target in enumerate(checked["targets"], 1)
               if not target_conversation_key or target["conversation_key"] == target_conversation_key]
    if not targets:
        return {"status": "INVALID_REQUEST", "reason": "DIRECTION_TARGET_NOT_DECLARED"}
    derived = prepare_derived_dispatch_recipe(assessment=checked, targets=targets)
    if derived["status"] != "READY":
        return derived
    targets = derived["targets"]
    if len(task_id) > 70 or len(operation_id) > 65:
        return {"status": "INVALID_REQUEST", "reason": "CHAIN_MESSAGE_OPERATION_TOO_LONG"}
    ledger = ChainDirectionLedger(runtime.bct.store)
    try:
        for index, target in targets:
            recorded = await asyncio.to_thread(
                ledger.get, direction_id=target_direction_id(direction, target),
            )
            compose_target_direction(
                direction=direction, target=target, task_id=f"{task_id}-{index}",
                recorded_direction=recorded,
            )
    except ValueError as exc:
        return {"status": "INVALID_REQUEST", "reason": str(exc)}
    return {
        "status": "READY", "assessment": checked, "targets": targets,
        "derived_dispatch": derived["derived_dispatch"],
    }


async def send_direction_recipe(runtime: ChainRecipeRuntime,
    *, direction: dict[str, Any], assessment: dict[str, Any], work: Work,
    targets: list[tuple[int, dict[str, Any]]], task_id: str, operation_id: str,
    network_results: list[dict[str, Any]], max_generations: int,
) -> dict[str, Any]:
    """Record each target Direction, recheck its live route, then send it."""
    from bct.chain_direction import (
        ChainDirectionLedger, resolve_direction_network,
        resolve_direction_target,
    )

    ledger = ChainDirectionLedger(runtime.bct.store)
    results = []
    for index, target in targets:
        child_task, child_op = f"{task_id}-{index}", f"{operation_id}-{index}"
        try:
            child = await asyncio.to_thread(
                ledger.target_direction, direction=direction, target=target, task_id=child_task,
            )
            if child["chain_state"] == "CHAIN_STARTED":
                results.append({"status": "ALREADY_STARTED", "target_conversation_key": target["conversation_key"],
                                "direction_id": child["direction_id"], "task_id": child["chain_task_id"],
                                "operation_id": child["chain_operation_id"], "resent": False})
                continue
            if child["chain_state"] != "NOT_PLANNED":
                results.append({"status": "RECEIPT_REVIEW_REQUIRED", "direction_id": child["direction_id"],
                                "task_id": child["chain_task_id"], "operation_id": child["chain_operation_id"]})
                continue
            fresh = await asyncio.to_thread(runtime.status_provider)
            origin, current_targets = resolve_direction_network(
                snapshot=fresh, assessment=assessment, targets=[(index, target)],
            )
            supervisor = resolve_direction_target(
                snapshot=fresh,
                conversation_key=assessment["supervisor_conversation_key"],
            )
            route = current_targets[0][2]
            if route["node_info"].get("generating") is True:
                results.append({"status": "TARGET_BUSY", "target_conversation_key": target["conversation_key"]})
                continue
            result = await send_chain_delivery(runtime,
                work_id=work.work_id, task_id=child_task, operation_id=child_op, action="start",
                chain_direction_id=child["direction_id"],
                instance_id=route["instance_id"], session_id=route["session_id"],
                target_tab_id=route["tab_id"], target_window_id=route["window_id"],
                target_conversation_key=target["conversation_key"],
                origin_conversation_key=assessment["manager_conversation_key"],
                origin_instance_id=origin["instance_id"],
                supervisor_conversation_key=assessment[
                    "supervisor_conversation_key"
                ],
                supervisor_instance_id=supervisor["instance_id"],
                continuation_output_contract="explicit-next-task-v1", max_generations=max_generations,
            )
            results.append({**result, "target_conversation_key": target["conversation_key"],
                            "direction_id": child["direction_id"]})
        except ValueError as exc:
            results.append({"status": "BLOCKED", "reason": str(exc),
                            "target_conversation_key": target["conversation_key"]})
    all_started = all(result["status"] in {"WATCHING", "ALREADY_STARTED"} for result in results)
    return {
        "status": "STARTED" if all_started else "PARTIAL", "stage": "TARGET_DISPATCH",
        "network_preparation_applied": bool(network_results), "all_targets_started": all_started,
        "direction_id": direction["direction_id"], "network_results": network_results,
        "targets": results,
    }


async def _run_direction_targets(runtime: ChainRecipeRuntime,
    *, direction: dict, assessment: dict, work: Work, task_id: str,
    operation_id: str, action: str, target_conversation_key: str,
    max_generations: int,
) -> dict[str, Any]:
    """Compose prepare, apply-conversation-network, and send-direction recipes."""
    prepared = await prepare_send_direction_recipe(runtime,
        direction=direction, assessment=assessment, task_id=task_id, operation_id=operation_id,
        target_conversation_key=target_conversation_key, max_generations=max_generations,
    )
    if prepared["status"] != "READY":
        return prepared
    network = await apply_conversation_network_recipe(runtime,
        direction=direction, assessment=prepared["assessment"], work=work,
        targets=prepared["targets"], action=action,
    )
    if network["status"] != "READY":
        return network
    if action == "preflight":
        from bct.chain_direction import resolve_direction_target
        target_routes = []
        for _, target in prepared["targets"]:
            try:
                route = resolve_direction_target(
                    snapshot=await asyncio.to_thread(runtime.status_provider),
                    conversation_key=target["conversation_key"],
                )
                target_routes.append({"conversation_key": target["conversation_key"], **route})
            except ValueError as exc:
                target_routes.append({"conversation_key": target["conversation_key"],
                                      "status": "UNAVAILABLE", "reason": str(exc)})
        return {"status": "READY", "direction_id": direction["direction_id"],
                "targets": target_routes,
                "network_updates": network["network_updates"],
                "effects": "NONE_READ_ONLY", "authorizes_send": False,
                "recipe_progress": chain_recipe_progress(completed_through=5, next_number=6)}
    sent = await send_direction_recipe(runtime,
        direction=direction, assessment=prepared["assessment"], work=work,
        targets=prepared["targets"], task_id=task_id, operation_id=operation_id,
        network_results=network["network_results"], max_generations=max_generations,
    )
    return {
        "derived_dispatch": prepared.get("derived_dispatch"),
        **sent,
        "recipe_progress": chain_recipe_progress(completed_through=5, next_number=6),
    }


async def check_chain_work_access(runtime: ChainRecipeRuntime, *, work_id: str, action: str) -> dict[str, Any]:
    """Read one Work as an advisory observation before chain preparation or sending."""
    if not hasattr(runtime.bct, "store"):
        return {
            "status": "OBSERVED", "work": None,
            "work_access": "UNAVAILABLE",
            "reason": "CHAIN_MESSAGE_WORK_STORE_UNAVAILABLE",
        }
    try:
        work = await asyncio.to_thread(runtime.bct.store.get_work, work_id)
    except (KeyError, ValueError):
        return {
            "status": "OBSERVED", "work": None,
            "work_access": "NOT_FOUND",
            "reason": "CHAIN_MESSAGE_WORK_NOT_FOUND",
        }
    observation = check_chain_work(work, principal_id=runtime.principal.principal_id)
    return {**observation, "work": work}


async def send_chain_delivery(runtime: ChainRecipeRuntime,
    work_id: str = "", task_id: str = "", operation_id: str = "",
    action: str = "start",
    instance_id: str = "", session_id: str = "",
    worker_tab_id: int = 0, worker_window_id: int = 0,
    worker_conversation_key: str = "",
    manager_conversation_key: str = "",
    instruction: str = "", manager_instance_id: str = "",
    generation: int = 1, chain_direction_id: str = "",
    target_tab_id: int = 0, target_window_id: int = 0,
    target_conversation_key: str = "", origin_conversation_key: str = "",
    origin_instance_id: str = "",
    supervisor_conversation_key: str = "",
    supervisor_instance_id: str = "",
    continuation_output_contract: str = "none",
    max_generations: int = 0,
    source_kind: str = "USER", source_task_id: str = "",
    source_generation: int = 0, project: str = "",
) -> dict[str, Any]:
    if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id)
            or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", operation_id)):
        return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_ID_INVALID"}
    if action == "status":
        from bct.send_delayed_message import (
            DurableWatchLedger, watch_diagnostic_for_status,
        )
        work=await asyncio.to_thread(runtime.bct.store.get_work,work_id)
        watch=await asyncio.to_thread(DurableWatchLedger(runtime.bct.store).get,task_id,generation)
        if watch is None:
            return {"status":"NOT_FOUND","task_id":task_id,"generation":generation}
        import json
        ctx=json.loads(watch.get("context_json") or "{}")
        if (ctx.get("work_id") != work.work_id
                or ctx.get("principal_id") != work.owner_principal_id
                or ctx.get("assignment_epoch") != work.assignment_epoch):
            return {"status":"NOT_FOUND","task_id":task_id,"generation":generation}
        planned_source = ctx.get("source_proof_kind") == "BCT_PLANNED_SOURCE_SEND"
        response_key = str(ctx.get("observed_response_turn_key") or "")
        manager_decision = watch["state"] == "MANAGER_DECISION_REQUIRED"
        return {"status":watch["state"],"task_id":task_id,
                "generation":generation,
                "response_turn_id":watch["response_turn_id"],
                "observed_response_turn_key":response_key,
                "source_send_operation_id":ctx.get("source_send_operation_id",""),
                "source_turn_key_state": (
                    "DEFERRED_TO_VERIFIED_SEND_RECEIPT" if planned_source
                    else "BOUND" if ctx.get("source_user_turn_key") else "UNAVAILABLE"),
                "response_turn_key_state": (
                    "BOUND" if response_key else
                    "AWAITING_VERIFIED_RESPONSE" if watch["state"] == "WATCHING"
                    else "UNAVAILABLE"),
                "terminal_reason":ctx.get("watch_terminal_reason", ""),
                "manager_action":ctx.get("manager_action", "") if manager_decision else "",
                "recipe":ctx.get("recipe", ""),
                "max_generations":ctx.get("max_generations", 0),
                "requested_continuation_route":ctx.get(
                    "requested_continuation_route", ""),
                "effective_continuation_route":ctx.get(
                    "effective_continuation_route", ""),
                "continuation_route_override_reason":ctx.get(
                    "continuation_route_override_reason", ""),
                "watch_diagnostic_reason": watch_diagnostic_for_status(
                    str(watch["state"]), ctx,
                ),
                "recovery_needed": ctx.get("recovery_needed"),
                "execution_path": ctx.get("execution_path") or "LEGACY_UNCLASSIFIED",
                "chain_direction_id": ctx.get("chain_direction_id", "")}
    if action == "cancel":
        return await runtime.make_executor("browser")(
            work_id,operation_id,{"command":"delayed-send-cancel",
             "task_id":task_id,"generation":generation})
    if action not in {"start", "preflight"}:
        return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_ACTION_INVALID"}
    def select_identity(canonical, legacy):
        if canonical and legacy and canonical != legacy:
            return None
        return canonical or legacy
    target_tab = select_identity(target_tab_id, worker_tab_id)
    target_window = select_identity(target_window_id, worker_window_id)
    target_conversation = select_identity(target_conversation_key, worker_conversation_key)
    origin_conversation = select_identity(origin_conversation_key, manager_conversation_key)
    origin_instance = select_identity(origin_instance_id, manager_instance_id)
    if None in {target_tab, target_window, target_conversation, origin_conversation, origin_instance}:
        return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_IDENTITY_CONFLICT"}
    send_id=operation_id+"-send"
    arm_id=operation_id+"-arm"
    if len(send_id)>80 or len(arm_id)>80:
        return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_OPERATION_TOO_LONG"}

    work_access = await check_chain_work_access(runtime, work_id=work_id, action=action)
    work = work_access["work"]

    direction = None
    execution_path = "DIRECTION_DECLARED" if chain_direction_id else "DIRECT_EXACT_TARGET"
    if chain_direction_id:
        loaded_direction = await read_saved_direction(runtime,
            work_id=work_id, direction_id=chain_direction_id,
        )
        if loaded_direction["status"] != "READY":
            return loaded_direction
        direction = loaded_direction["direction"]
        if direction.get("decision") != "NEW_TASK":
            return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_NOT_A_NEW_TASK"}
        if (direction.get("target_conversation_key")
                and direction["target_conversation_key"] != target_conversation):
            return {"status":"INVALID_REQUEST","reason":"DIRECTION_TARGET_IDENTITY_MISMATCH"}
        import json
        assessment = json.loads(direction.get("assessment_json") or "{}")
        if assessment:
            return {"status":"INVALID_REQUEST","reason":"DIRECTION_REQUIRES_TARGET_DELIVERY"}
        if instruction and instruction != direction.get("direction_text"):
            return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_TEXT_MISMATCH"}
        if (direction.get("chain_task_id",""), direction.get("chain_operation_id","")) not in {
                ("",""), (task_id,operation_id)}:
            return {"status":"INVALID_REQUEST","reason":"CHAIN_DIRECTION_CHAIN_CONFLICT"}
        instruction = str(direction["direction_text"])
    if (not re.fullmatch(r"[a-f0-9]{32}",str(session_id or "")) or
            not isinstance(target_tab, int) or target_tab <= 0 or
            not isinstance(target_window, int) or target_window <= 0):
        return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_INPUT_INVALID"}
    try:
        prepared_text = prepare_chain_instruction(
            instruction, output_contract=continuation_output_contract,
            execution_plan_context=(
                {
                    "work_id": work_id,
                    "direction_id": chain_direction_id,
                    "task_id": task_id,
                    "generation": generation,
                }
                if chain_direction_id else None
            ),
        )
    except ValueError as exc:
        return {"status":"INVALID_REQUEST","reason":str(exc)}
    if type(max_generations) is not int or not 0 <= max_generations <= 12:
        return {"status":"INVALID_REQUEST","reason":"CHAIN_MESSAGE_MAX_GENERATIONS_INVALID"}
    outgoing_instruction = prepared_text["instruction"]
    if action == "preflight":
        return {
            "status": "READY", "work_id": work_id, "task_id": task_id,
            "target_conversation_key": target_conversation,
            "required_action": "browser",
            "work_observation": {
                key: value for key, value in work_access.items() if key != "work"
            },
            "continuation_output_contract": continuation_output_contract,
            "contract_appended": prepared_text["output_contract_appended"],
            "execution_plan_contract_appended": prepared_text[
                "execution_plan_contract_appended"
            ],
            "contract_suffix": EXPLICIT_NEXT_TASK_SUFFIX
                if prepared_text["output_contract_appended"] else "",
            "outgoing_instruction_sha256": prepared_text["instruction_sha256"],
            "outgoing_instruction_characters": prepared_text["instruction_characters"],
            "max_generations": max_generations,
            "execution_path": execution_path,
            "chain_direction_id": chain_direction_id,
            "effects": "NONE_READ_ONLY", "authorizes_send": False,
        }
    if chain_direction_id:
        from bct.chain_direction import ChainDirectionLedger
        try:
            direction = await asyncio.to_thread(
                ChainDirectionLedger(runtime.bct.store).plan_chain,
                direction_id=chain_direction_id, work_id=work_id,
                task_id=task_id, operation_id=operation_id,
                instruction_text=instruction,
            )
        except ValueError as exc:
            return {"status":"INVALID_REQUEST","reason":str(exc)}
    try:
        await asyncio.to_thread(
            _assert_node_send_allowed, runtime, work_id, str(target_conversation),
        )
    except ValueError as exc:
        return {"status":"PAUSED","reason":str(exc)}
    armed=await runtime.make_executor("browser")(
        work_id,arm_id,{"command":"send-delayed-message",
         "task_id":task_id,"instance_id":instance_id,
         "conversation_key":target_conversation,
         "manager_conversation_key":origin_conversation,
         "manager_instance_id":origin_instance or instance_id,
         "supervisor_conversation_key":supervisor_conversation_key,
         "supervisor_instance_id":supervisor_instance_id,
         "planned_send_operation_id":send_id,
         "planned_send_text":outgoing_instruction,
         "execution_path":execution_path,
         "chain_direction_id":chain_direction_id,
         "exclusive_conversation_watch":True,
         "max_generations":max_generations,
         "watched_session_id":session_id,
         "watched_tab_id":target_tab,
         "watched_window_id":target_window})
    if armed.get("outcome") != "APPLIED":
        return {"status":"PREARM_FAILED","prearm":armed}
    sent=await runtime.make_executor("browser")(
        work_id,send_id,{"command":"send-message",
         "instance_id":instance_id,"session_id":session_id,
         "tab_id":target_tab,"window_id":target_window,
         "conversation_key":target_conversation,
         "text":outgoing_instruction})
    if sent.get("outcome") != "APPLIED":
        return {"status":"SEND_UNCONFIRMED","prearm":armed,
                "send":sent,"warning":"NO_UNKNOWN_REPLAY"}
    if chain_direction_id:
        from bct.chain_direction import ChainDirectionLedger
        direction = await asyncio.to_thread(
            ChainDirectionLedger(runtime.bct.store).mark_chain_started,
            direction_id=chain_direction_id, work_id=work_id,
            task_id=task_id, operation_id=operation_id,
        )
    return {"status":"WATCHING","task_id":task_id,"generation":generation,
            "max_generations":max_generations,
            "execution_path":execution_path,
            "chain_direction_id":chain_direction_id,
            "prearm":armed,"send":sent,
            **({"chain_direction": direction} if direction is not None else {})}
