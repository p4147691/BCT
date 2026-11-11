"""Full Chain Recipe coordinator; the MCP server only adapts its public entry."""
from __future__ import annotations

import asyncio
import hmac
import re

from typing import Any



from .delivery import _run_direction_targets, check_chain_work_access, prepare_send_direction_recipe
from .direction import prepare_direction_recipe, read_saved_direction, save_direction_recipe, write_direction_recipe
from .input import manager_return_save_context
from .network import apply_conversation_network_recipe
from .outline import chain_recipe_outline, chain_recipe_progress
from .recovery import recover_node_recipe
from .runtime import ChainRecipeRuntime, work_dict as _work_dict

async def chain_recipe(runtime: ChainRecipeRuntime,
    source_text: str = "", source_kind: str = "USER", work_id: str = "",
    source_task_id: str = "", source_generation: int = 0, project: str = "",
    action: str = "prepare", direction_text: str = "", decision: str = "",
    direction_id: str = "", assessment: dict[str, Any] | None = None,
    task_id: str = "", operation_id: str = "", target_conversation_key: str = "",
    max_generations: int = 0, report_target_conversation_key: str = "",
    generation: int = 0,
    entry_context_id: str = "",
    worker_preparation_id: str = "",
    parent_direction_id: str = "", parent_step_id: str = "",
    branch_kind: str = "PRIMARY", branch_reason: str = "", branch_request_id: str = "",
) -> dict[str, Any]:
    """Run one explicit boundary of the Chain Recipe."""
    if action not in {"prepare", "save", "recover_node", "prepare_send", "apply_network", "send", "preflight", "provision_worker", "recovery_inbox", "bind_recovery_collector", "resume_manager", "ack_recovery"}:
        return {"status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_ACTION_INVALID"}
    if action == "recovery_inbox":
        if not report_target_conversation_key:
            return {"status": "INVALID_REQUEST",
                    "reason": "CHAIN_RECOVERY_REPORT_TARGET_REQUIRED"}
        try:
            work = await asyncio.to_thread(runtime.bct.store.get_work, work_id)
        except KeyError:
            return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
        if work.owner_principal_id != runtime.principal.principal_id:
            return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
        from bct.chain_manager_recovery import ChainManagerRecoveryLedger
        from bct.send_delayed_message import DurableWatchLedger
        records = await asyncio.to_thread(
            ChainManagerRecoveryLedger(runtime.bct.store, initialize=False).inbox,
            work_id=work.work_id,
            report_target_conversation_key=report_target_conversation_key.lower(),
        )
        items = []
        for record in records:
            execution = await asyncio.to_thread(
                DurableWatchLedger(runtime.bct.store).read_execution_context,
                task_id=record["task_id"], generation=record["generation"],
            )
            operation = None
            if record.get("delivery_operation_id"):
                try:
                    receipt = await asyncio.to_thread(
                        runtime.bct.store.get_operation_for,
                        operation_id=record["delivery_operation_id"],
                        work_id=work.work_id,
                        principal_id=work.owner_principal_id,
                    )
                    operation = receipt.as_dict()
                except (KeyError, ValueError):
                    operation = None
            items.append({
                "checkpoint": record,
                "last_execution_result": execution,
                "delivery_receipt": operation,
            })
        return {
            "status": "OK", "effects": "NONE_READ_ONLY",
            "collector_role": "HANDOFF_INFORMATION_ONLY",
            "does_not": ["act_as_manager", "send_message", "replay_unknown"],
            "items": items,
        }
    if action == "ack_recovery":
        if (not report_target_conversation_key
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id)
                or generation < 1):
            return {"status": "INVALID_REQUEST",
                    "reason": "CHAIN_RECOVERY_ACK_INPUT_REQUIRED"}
        try:
            work = await asyncio.to_thread(runtime.bct.store.get_work, work_id)
            if work.owner_principal_id != runtime.principal.principal_id:
                raise KeyError(work_id)
            from bct.chain_manager_recovery import ChainManagerRecoveryLedger
            checkpoint = await asyncio.to_thread(
                ChainManagerRecoveryLedger(runtime.bct.store).acknowledge,
                work_id=work.work_id, task_id=task_id,
                generation=generation,
                manager_conversation_key=report_target_conversation_key.lower(),
            )
        except KeyError:
            return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        return {
            "status": "ACKNOWLEDGED", "checkpoint": checkpoint,
            "next_safe_step": "STATE_R_THEN_MANAGER_DECIDES_NEXT_DIRECTION",
            "does_not": ["send_message", "replay_worker_task"],
        }
    if action == "resume_manager":
        if not report_target_conversation_key:
            return {"status": "INVALID_REQUEST",
                    "reason": "CHAIN_RECOVERY_MANAGER_REQUIRED"}
        try:
            work = await asyncio.to_thread(runtime.bct.store.get_work, work_id)
            if work.owner_principal_id != runtime.principal.principal_id:
                raise KeyError(work_id)
            from bct.chain_direction import resolve_direction_target
            snapshot = await asyncio.to_thread(runtime.status_provider)
            manager = resolve_direction_target(
                snapshot=snapshot,
                conversation_key=report_target_conversation_key.lower(),
            )
            roles = {
                str(value).strip().casefold()
                for value in manager["node_info"].get("roles", [])
            }
            if "manager" not in roles or roles & {"worker", "supervisor"}:
                raise ValueError("CHAIN_RECOVERY_MANAGER_ROLE_NOT_CONFIRMED")
            from bct.send_delayed_message import DurableWatchLedger
            watch_ledger = DurableWatchLedger(runtime.bct.store)
            active = [row for row in watch_ledger.watching(limit=100)
                      if row["context"].get("work_id") == work.work_id]
            from bct.chain_manager_recovery import ChainManagerRecoveryLedger
            recovery_ledger = ChainManagerRecoveryLedger(runtime.bct.store)
            checkpoints = await asyncio.to_thread(
                recovery_ledger.for_work, work_id=work.work_id,
            )
            manager_scope = str(
                manager["node_info"].get("network_id")
                or manager["node_info"].get("network") or ""
            ).strip()
            predecessor_keys = {
                str(row["context"].get("manager_conversation_key") or "")
                for row in active
            }
            predecessor_keys.update(
                str(row["active_manager_conversation_key"])
                for row in checkpoints
            )
            worker_keys = {row["conversation_key"] for row in active}
            worker_keys.update(str(row["worker_conversation_key"])
                               for row in checkpoints)
            supervisor_keys = {
                str(row["context"].get("supervisor_conversation_key") or "")
                for row in active
            }
            supervisor_keys.update(str(row["supervisor_conversation_key"])
                                   for row in checkpoints)
            if report_target_conversation_key.lower() in supervisor_keys:
                raise ValueError("CHAIN_RECOVERY_MANAGER_IS_SUPERVISOR")
            for worker_key in worker_keys:
                worker = resolve_direction_target(
                    snapshot=snapshot, conversation_key=worker_key,
                )
                worker_scope = str(
                    worker["node_info"].get("network_id")
                    or worker["node_info"].get("network") or ""
                ).strip()
                if not manager_scope or manager_scope != worker_scope:
                    raise ValueError("CHAIN_RECOVERY_MANAGER_WORKER_NETWORK_MISMATCH")
            succession_proofs = []
            from bct.conversation_network import manager_role_transfer_receipt
            for predecessor in sorted(predecessor_keys - {
                    "", report_target_conversation_key.lower()}):
                proof = await asyncio.to_thread(
                    manager_role_transfer_receipt, runtime.bct.store,
                    project_id=manager_scope,
                    predecessor_conversation_key=predecessor,
                    successor_conversation_key=report_target_conversation_key.lower(),
                )
                if proof is None:
                    raise ValueError(
                        "CHAIN_RECOVERY_MANAGER_SUCCESSION_PROOF_REQUIRED"
                    )
                succession_proofs.append(proof)
            binding = await asyncio.to_thread(
                watch_ledger.resume_manager,
                work_id=work.work_id,
                manager_conversation_key=report_target_conversation_key.lower(),
                manager_instance_id=manager["instance_id"],
                succession_proofs=succession_proofs,
            )
            rebound = await asyncio.to_thread(
                recovery_ledger.rebind_active_manager,
                work_id=work.work_id,
                manager_conversation_key=report_target_conversation_key.lower(),
                succession_proofs=succession_proofs,
            )
        except KeyError:
            return {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"}
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        return {
            "status": "MANAGER_RESUMED", "binding": binding,
            "rebound_checkpoints": rebound,
            "next_safe_step": "READ_RECOVERY_INBOX_THEN_ACK_EACH_CHECKPOINT",
            "does_not": ["send_message", "replay_unknown", "act_as_supervisor"],
        }
    if action == "bind_recovery_collector":
        loaded_direction = await read_saved_direction(runtime,
            work_id=work_id, direction_id=direction_id,
        )
        if loaded_direction["status"] != "READY":
            return loaded_direction
        import json
        saved_assessment = json.loads(
            loaded_direction["direction"].get("assessment_json") or "{}"
        )
        if not saved_assessment:
            return {"status": "INVALID_REQUEST",
                    "reason": "CHAIN_RECOVERY_DIRECTION_ASSESSMENT_REQUIRED"}
        from bct.chain_direction import (
            resolve_direction_network, resolve_direction_target,
        )
        try:
            snapshot = await asyncio.to_thread(runtime.status_provider)
            resolve_direction_network(
                snapshot=snapshot, assessment=saved_assessment, targets=[],
            )
            supervisor = resolve_direction_target(
                snapshot=snapshot,
                conversation_key=saved_assessment[
                    "supervisor_conversation_key"
                ],
            )
            from bct.send_delayed_message import DurableWatchLedger
            binding = await asyncio.to_thread(
                DurableWatchLedger(runtime.bct.store).bind_recovery_collector,
                work_id=work_id, direction_id=direction_id,
                manager_conversation_key=saved_assessment[
                    "manager_conversation_key"
                ],
                supervisor_conversation_key=saved_assessment[
                    "supervisor_conversation_key"
                ],
                supervisor_instance_id=supervisor["instance_id"],
            )
        except (KeyError, ValueError) as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
        return {
            "status": "OK", "binding": binding,
            "does_not": ["send_message", "replay_unknown", "act_as_manager"],
        }
    if action == "provision_worker":
        if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,60}", worker_preparation_id)):
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_WORKER_PREPARATION_REQUIRED"}
        loaded_direction = await read_saved_direction(runtime,
            work_id=work_id, direction_id=direction_id,
        )
        if loaded_direction["status"] != "READY":
            return loaded_direction
        direction = loaded_direction["direction"]
        if direction.get("decision") != "NEW_TASK":
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_NOT_A_NEW_TASK"}
        import json
        saved_assessment = json.loads(direction.get("assessment_json") or "{}")
        matches = [item for item in saved_assessment.get("worker_preparations", [])
                   if item.get("preparation_id") == worker_preparation_id]
        if len(matches) != 1:
            return {"status": "INVALID_REQUEST",
                    "reason": "CHAIN_WORKER_PREPARATION_NOT_DECLARED"}
        work_access = await check_chain_work_access(runtime, work_id=work_id, action="start")
        work = work_access["work"]
        if work is None:
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_WORK_REQUIRED"}
        from bct.chain_worker_provision import ChainWorkerProvisionRecipe
        try:
            return await asyncio.to_thread(
                ChainWorkerProvisionRecipe(
                    bct=runtime.bct, principal=runtime.principal, status_provider=runtime.status_provider,
                ).run,
                direction=direction, assessment=saved_assessment, work=work,
                task_id=task_id, worker_preparation=matches[0],
                max_generations=max_generations,
            )
        except ValueError as exc:
            return {"status": "INVALID_REQUEST", "reason": str(exc)}
    if action == "save":
        # Saving a Direction is not an independent ingress.  Re-run the
        # mandatory current-state read and require the continuity handle
        # returned by the same Chain Recipe entry.  No record is created
        # here when the Manager did not enter (or the relevant work tree
        # changed) first.
        if not isinstance(entry_context_id, str) or not re.fullmatch(r"entry-[0-9a-f]{24}", entry_context_id):
            return {
                "status": "CHAIN_RECIPE_REENTER_REQUIRED",
                "reason": "CHAIN_RECIPE_ENTRY_CONTEXT_REQUIRED",
                "next_safe_step": "REENTER_CHAIN_RECIPE_PREPARE",
                "does_not": ["save_direction", "send_message", "create_operation"],
            }
        prepared = await prepare_direction_recipe(runtime,
            source_text=source_text, source_kind=source_kind, work_id=work_id,
            source_task_id=source_task_id, source_generation=source_generation,
            project=project,
            report_target_conversation_key=report_target_conversation_key,
        )
        if prepared["status"] != "PREPARED":
            return prepared
        confirmed_input = prepared["confirmed_input"]
        expected_entry_context_id = prepared["entry_context_id"]
        if not hmac.compare_digest(entry_context_id, expected_entry_context_id):
            return {
                "status": "CHAIN_RECIPE_REENTER_REQUIRED",
                "reason": "CHAIN_RECIPE_ENTRY_CONTEXT_CHANGED",
                "next_safe_step": "REVIEW_CURRENT_STATE_THEN_AUTHOR_DIRECTION",
                "entry_context_id": expected_entry_context_id,
                "input": {
                    "source_kind": source_kind,
                    "source_result_sha256": confirmed_input["source_result_sha256"],
                    "work": _work_dict(confirmed_input["work"]),
                },
                "state": prepared["state"],
                "does_not": ["save_direction", "send_message", "create_operation"],
            }
        resolved_parent = manager_return_save_context(
            return_chain_link=prepared["return_chain_link"],
            parent_direction_id=parent_direction_id, parent_step_id=parent_step_id,
            branch_kind=branch_kind, branch_reason=branch_reason,
            branch_request_id=branch_request_id,
        )
        if resolved_parent["status"] != "OK":
            return resolved_parent
        saved = await save_direction_recipe(runtime,
            work=confirmed_input["work"], direction_id=direction_id, source_kind=source_kind,
            source_task_id=source_task_id, source_generation=source_generation,
            source_result_sha256=str(confirmed_input["source_result_sha256"]),
            decision=decision, direction_text=direction_text, assessment=assessment,
            source_text=source_text, parent_direction_id=resolved_parent["parent_direction_id"],
            parent_step_id=resolved_parent["parent_step_id"], branch_kind=resolved_parent["branch_kind"],
            branch_reason=resolved_parent["branch_reason"], branch_request_id=branch_request_id,
        )
        if saved.get("status") != "OK":
            return saved
        has_recovery = bool((saved["chain_direction"].get("assessment") or {}).get("node_recovery"))
        next_number = 4 if has_recovery else 5 if decision == "NEW_TASK" else None
        return {
            **saved,
            "recipe_progress": chain_recipe_progress(
                completed_through=3,
                next_number=next_number,
            ),
        }
    if action == "recover_node":
        loaded_direction = await read_saved_direction(runtime, work_id=work_id, direction_id=direction_id)
        if loaded_direction["status"] != "READY":
            return loaded_direction
        direction = loaded_direction["direction"]
        import json
        saved_assessment = json.loads(direction.get("assessment_json") or "{}")
        if not saved_assessment.get("node_recovery"):
            return {"status": "NOT_APPLICABLE", "reason": "NODE_RECOVERY_NOT_DECLARED"}
        work_access = await check_chain_work_access(runtime, work_id=work_id, action="start")
        work = work_access["work"]
        if work is None:
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_RECOVERY_WORK_REQUIRED"}
        recovered = await recover_node_recipe(runtime,
            direction=direction, assessment=saved_assessment, work=work,
        )
        return {
            **recovered,
            "direction_id": direction_id,
            "recipe_progress": chain_recipe_progress(completed_through=4, next_number=5),
        }
    if action == "prepare_send":
        if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", operation_id)):
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_ID_INVALID"}
        loaded_direction = await read_saved_direction(runtime,
            work_id=work_id, direction_id=direction_id,
        )
        if loaded_direction["status"] != "READY":
            return loaded_direction
        direction = loaded_direction["direction"]
        if direction.get("decision") != "NEW_TASK":
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_NOT_A_NEW_TASK"}
        import json
        saved_assessment = json.loads(direction.get("assessment_json") or "{}")
        if not saved_assessment:
            return {"status": "NOT_APPLICABLE", "reason": "CHAIN_RECIPE_DIRECTION_HAS_NO_TARGETS"}
        prepared_send = await prepare_send_direction_recipe(runtime,
            direction=direction, assessment=saved_assessment, task_id=task_id,
            operation_id=operation_id, target_conversation_key=target_conversation_key,
            max_generations=max_generations,
        )
        if prepared_send["status"] != "READY":
            return prepared_send
        return {
            "status": "READY", "direction_id": direction_id,
            "targets": [target for _, target in prepared_send["targets"]],
            "derived_dispatch": prepared_send.get("derived_dispatch"),
            "effects": "NONE_READ_ONLY", "authorizes_send": False,
            "recipe_progress": chain_recipe_progress(completed_through=5, next_number=6),
        }
    if action == "apply_network":
        if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", operation_id)):
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_ID_INVALID"}
        loaded_direction = await read_saved_direction(runtime,
            work_id=work_id, direction_id=direction_id,
        )
        if loaded_direction["status"] != "READY":
            return loaded_direction
        direction = loaded_direction["direction"]
        if direction.get("decision") != "NEW_TASK":
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_NOT_A_NEW_TASK"}
        import json
        saved_assessment = json.loads(direction.get("assessment_json") or "{}")
        if not saved_assessment:
            return {"status": "NOT_APPLICABLE", "reason": "CHAIN_RECIPE_DIRECTION_HAS_NO_TARGETS"}
        prepared_send = await prepare_send_direction_recipe(runtime,
            direction=direction, assessment=saved_assessment, task_id=task_id,
            operation_id=operation_id, target_conversation_key=target_conversation_key,
            max_generations=max_generations,
        )
        if prepared_send["status"] != "READY":
            return prepared_send
        work_access = await check_chain_work_access(runtime, work_id=work_id, action="start")
        work = work_access["work"]
        if work is None:
            return {
                "status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_NETWORK_WORK_REQUIRED",
                "work_observation": {key: value for key, value in work_access.items() if key != "work"},
            }
        network = await apply_conversation_network_recipe(runtime,
            direction=direction, assessment=prepared_send["assessment"], work=work,
            targets=prepared_send["targets"], action="start",
        )
        if network["status"] != "READY":
            return network
        return {
            "status": "READY", "direction_id": direction_id,
            "targets": [{"conversation_key": target["conversation_key"], **route}
                        for _, target, route in network["resolved"]],
            "network_updates": network["network_updates"],
            "network_results": network["network_results"],
            "effects": network["effects"],
            "recipe_progress": chain_recipe_progress(completed_through=6, next_number=7),
        }
    if action in {"send", "preflight"}:
        if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", task_id)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", operation_id)):
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_ID_INVALID"}
        loaded_direction = await read_saved_direction(runtime,
            work_id=work_id, direction_id=direction_id,
        )
        if loaded_direction["status"] != "READY":
            return loaded_direction
        direction = loaded_direction["direction"]
        if direction.get("decision") != "NEW_TASK":
            return {"status": "INVALID_REQUEST", "reason": "CHAIN_DIRECTION_NOT_A_NEW_TASK"}
        import json
        saved_assessment = json.loads(direction.get("assessment_json") or "{}")
        if not saved_assessment:
            return {"status": "NOT_APPLICABLE", "reason": "CHAIN_RECIPE_DIRECTION_HAS_NO_TARGETS"}
        work_access = await check_chain_work_access(runtime, work_id=work_id, action="start")
        work = work_access["work"]
        if work is None:
            return {
                "status": "INVALID_REQUEST", "reason": "CHAIN_RECIPE_SEND_WORK_REQUIRED",
                "work_observation": {key: value for key, value in work_access.items() if key != "work"},
            }
        recovered = {"status": "SKIPPED", "reason": "PREFLIGHT_READ_ONLY"}
        if action == "send":
            recovered = await recover_node_recipe(runtime,
                direction=direction, assessment=saved_assessment, work=work,
            )
            if recovered["status"] not in {"CHECKED", "SKIPPED"}:
                return recovered
        sent = await _run_direction_targets(runtime,
            direction=direction, assessment=saved_assessment, work=work,
            task_id=task_id, operation_id=operation_id, action=action,
            target_conversation_key=target_conversation_key,
            max_generations=max_generations,
        )
        return {
            **sent,
            "recover_node": recovered,
            "recipe_progress": chain_recipe_progress(completed_through=7, next_number=None),
        }
    prepared = await prepare_direction_recipe(runtime,
        source_text=source_text, source_kind=source_kind, work_id=work_id,
        source_task_id=source_task_id, source_generation=source_generation, project=project,
        report_target_conversation_key=report_target_conversation_key,
    )
    if prepared["status"] != "PREPARED":
        return prepared
    confirmed = prepared["confirmed_input"]
    state = prepared["state"]
    work = confirmed["work"]
    direction = write_direction_recipe(source_kind=source_kind, work=work)
    return {
        "status": "RECIPE_READY",
        "recipe": {"name": "chain_recipe", "kind": "full_recipe"},
        "recipe_outline": chain_recipe_outline(),
        "completed_stages": [
            {"number": 0, "name": "Input R"},
            {"number": 1, "name": "State R"},
            {"number": 2, "name": "Write Direction R", "status": "A_REQUIRED"},
        ],
        "next_stage": {"number": 2, "name": "Write Direction R", "status": "A_REQUIRED"},
        "input": {
            "source_kind": source_kind,
            "source_evidence": (
                "VERIFIED_MANAGER_RETURN" if source_kind == "MANAGER_RETURN"
                else "CALLER_PROVIDED_TEXT"
            ),
            "source_text": source_text if source_kind == "USER" else "",
            "source_return": confirmed["source_return"],
            "source_result_sha256": confirmed["source_result_sha256"],
            "work": _work_dict(work) if work is not None else None,
            "connection": "EXACT_RETURN_BOUND" if source_kind == "MANAGER_RETURN"
                          else ("WORK_BOUND" if work is not None else "UNCONNECTED"),
        },
        "state": state,
        "return_chain_link": prepared["return_chain_link"],
        "entry_context_id": prepared["entry_context_id"],
        "direction": direction,
        "read_only": True,
        "authorizes_send": False,
    }
