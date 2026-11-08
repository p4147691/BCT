"""Receipt-driven Chain sub-recipe for one explicitly requested new Worker."""
from __future__ import annotations

import re
from typing import Any, Callable

from .chain_direction import ChainDirectionLedger, compose_prepared_worker_direction
from .chain_message_preflight import prepare_chain_instruction
from .chain_worker_preparation import (
    validate_worker_preparation, worker_preparation_operation_id,
)
from .conversation_network import role_tags_sha256
from .status_views import status_view


_UUID = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}")


def _attachment(snapshot: dict[str, Any], *, instance_id: str,
                tab_id: int) -> dict[str, Any] | None:
    matches = []
    for instance in status_view(snapshot, "rcc").get("rcc", {}).get("instances", []):
        if (instance.get("instance_id") != instance_id
                or instance.get("state") != "OPEN" or instance.get("cached") is True):
            continue
        session_id = str(instance.get("session_id") or "")
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            continue
        for tab in instance.get("tabs", []):
            if tab.get("tab_id") == tab_id and type(tab.get("window_id")) is int:
                matches.append({
                    "instance_id": instance_id, "session_id": session_id,
                    "tab_id": tab_id, "window_id": tab["window_id"],
                    "conversation_key": str(tab.get("conversation_key") or "").lower(),
                })
    return matches[0] if len(matches) == 1 else None


class ChainWorkerProvisionRecipe:
    """Compose existing create/move/send/watch/node-info operations."""

    def __init__(self, *, bct, principal, status_provider: Callable[[], dict[str, Any]]):
        self.bct = bct
        self.principal = principal
        self.status_provider = status_provider

    def _run(self, work_id: str, operation_id: str, capability: str,
             arguments: dict[str, Any]) -> dict[str, Any]:
        return self.bct.operations.run(
            principal=self.principal, work_id=work_id, operation_id=operation_id,
            capability=capability, arguments=arguments, approval_ref=None,
        ).as_dict()

    def _receipt(self, *, work, operation_id: str) -> dict[str, Any] | None:
        from .core.models import ConflictError
        try:
            return self.bct.store.get_operation_for(
                operation_id=operation_id, work_id=work.work_id,
                principal_id=work.owner_principal_id,
            ).as_dict()
        except KeyError:
            return None
        except ConflictError as exc:
            raise ValueError("CHAIN_WORKER_PREPARATION_RECEIPT_FOREIGN") from exc

    def run(self, *, direction: dict[str, Any], assessment: dict[str, Any], work,
            task_id: str, worker_preparation: dict[str, Any],
            max_generations: int = 0) -> dict[str, Any]:
        prepared = validate_worker_preparation(worker_preparation)
        ids = {stage: worker_preparation_operation_id(
            direction_id=direction["direction_id"],
            preparation_id=prepared["preparation_id"], stage=stage,
        ) for stage in ("create", "arrange", "send", "watch", "register")}
        create_arguments = {
            "command": prepared["command"], "instance_id": prepared["instance_id"],
        }
        if prepared["command"] == "create-chat-tab":
            create_arguments["window_id"] = prepared["window_id"]
        created = self._receipt(work=work, operation_id=ids["create"]) or self._run(
            work.work_id, ids["create"], "browser", create_arguments,
        )
        if created.get("outcome") != "APPLIED":
            return {"status": "CREATION_INCOMPLETE", "stage": "CREATE",
                    "creation_receipt": created, "operation_ids": ids}
        creation_evidence = created.get("evidence") or {}
        tab_id = creation_evidence.get("created_tab_id")
        if type(tab_id) is not int or tab_id <= 0:
            return {"status": "CREATION_RECEIPT_INVALID", "stage": "CREATE",
                    "creation_receipt": created, "operation_ids": ids}
        attachment = _attachment(
            self.status_provider(), instance_id=prepared["instance_id"], tab_id=tab_id,
        )
        if attachment is None:
            return {"status": "WAITING_FOR_CREATED_TAB", "stage": "OBSERVE_CREATED_TAB",
                    "creation_receipt": created, "operation_ids": ids,
                    "authorizes_send": False}
        arrangement = {"status": "SKIPPED", "reason": "ARRANGEMENT_NOT_DECLARED"}
        ledger = ChainDirectionLedger(self.bct.store)
        child_id, direction_text = compose_prepared_worker_direction(
            direction=direction, preparation_id=prepared["preparation_id"],
            conversation_key="00000000-0000-0000-0000-000000000000",
            role="worker", instruction=prepared["instruction"], task_id=task_id,
        )
        outgoing = prepare_chain_instruction(
            direction_text, output_contract="explicit-next-task-v1",
        )["instruction"]
        sent = self._receipt(work=work, operation_id=ids["send"]) or self._run(
            work.work_id, ids["send"], "browser", {
            "command": "send-message", **attachment, "conversation_key": "",
            "create_operation_id": ids["create"], "text": outgoing,
        })
        if sent.get("outcome") != "APPLIED":
            return {"status": "DELIVERY_INCOMPLETE", "stage": "SEND",
                    "creation_receipt": created, "arrangement_receipt": arrangement,
                    "send_receipt": sent, "operation_ids": ids}
        conversation_key = str((sent.get("evidence") or {}).get("conversation_key") or "").lower()
        if not _UUID.fullmatch(conversation_key):
            return {"status": "WAITING_FOR_CONVERSATION_UUID", "stage": "IDENTIFY",
                    "creation_receipt": created, "arrangement_receipt": arrangement,
                    "send_receipt": sent, "operation_ids": ids,
                    "authorizes_resend": False}
        current = _attachment(
            self.status_provider(), instance_id=prepared["instance_id"], tab_id=tab_id,
        )
        if current is None or current["conversation_key"] != conversation_key:
            return {"status": "WAITING_FOR_CONVERSATION_UUID", "stage": "IDENTIFY",
                    "conversation_key": conversation_key, "operation_ids": ids,
                    "authorizes_resend": False}
        recorded = ledger.get(direction_id=child_id)
        child_id, direction_text = compose_prepared_worker_direction(
            direction=direction, preparation_id=prepared["preparation_id"],
            conversation_key=conversation_key, role="worker",
            instruction=prepared["instruction"], task_id=task_id,
            recorded_direction=recorded,
        )
        if recorded is None:
            ledger.save(
                direction_id=child_id, work_id=work.work_id,
                source_kind=direction["source_kind"],
                source_task_id=direction["source_task_id"],
                source_generation=direction["source_generation"],
                source_result_sha256=direction["source_result_sha256"],
                decision="NEW_TASK", direction_text=direction_text,
                parent_direction_id=direction["direction_id"],
                target_conversation_key=conversation_key,
            )
        chain_operation_id = ids["send"][:-5]
        ledger.plan_chain(
            direction_id=child_id, work_id=work.work_id, task_id=task_id,
            operation_id=chain_operation_id, instruction_text=direction_text,
        )
        origin_key = str(assessment.get("manager_conversation_key") or "")
        if not _UUID.fullmatch(origin_key):
            return {"status": "MANAGER_IDENTITY_REQUIRED", "stage": "WATCH",
                    "conversation_key": conversation_key, "operation_ids": ids}
        origin_matches = []
        snapshot = self.status_provider()
        rcc = status_view(snapshot, "rcc").get("rcc", {})
        for instance in rcc.get("instances", []):
            if instance.get("state") != "OPEN" or instance.get("cached") is True:
                continue
            for tab in instance.get("tabs", []):
                if tab.get("conversation_key") == origin_key:
                    origin_matches.append(str(instance.get("instance_id") or ""))
        if len(origin_matches) != 1:
            return {"status": "MANAGER_ATTACHMENT_NOT_UNIQUE", "stage": "WATCH",
                    "conversation_key": conversation_key, "operation_ids": ids}
        watched = self._receipt(work=work, operation_id=ids["watch"]) or self._run(
            work.work_id, ids["watch"], "browser", {
            "command": "send-delayed-message", "task_id": task_id,
            "instance_id": current["instance_id"], "conversation_key": conversation_key,
            "manager_conversation_key": origin_key,
            "manager_instance_id": origin_matches[0],
            "planned_send_operation_id": ids["send"], "planned_send_text": outgoing,
            "bootstrap_create_operation_id": ids["create"],
            "max_generations": max_generations,
            "execution_path": "DIRECTION_DECLARED", "chain_direction_id": child_id,
            "watched_session_id": current["session_id"],
            "watched_tab_id": current["tab_id"],
            "watched_window_id": current["window_id"],
        })
        if watched.get("outcome") != "APPLIED":
            return {"status": "WATCH_INCOMPLETE", "stage": "WATCH",
                    "conversation_key": conversation_key, "watch_receipt": watched,
                    "operation_ids": ids}
        ledger.mark_chain_started(
            direction_id=child_id, work_id=work.work_id, task_id=task_id,
            operation_id=chain_operation_id,
        )
        # The bootstrap watch validates the original creation window. Arrange
        # only after it is durable, then reacquire the same UUID. Arrangement
        # failure never redirects or repeats the already submitted task.
        if prepared["arrange"] is not None:
            arrangement = self._receipt(
                work=work, operation_id=ids["arrange"],
            ) or self._run(work.work_id, ids["arrange"], "browser", {
                "command": "move-tab", **current,
                "target_window_id": prepared["arrange"]["target_window_id"],
                "index": prepared["arrange"]["index"],
                "conversation_key": conversation_key, "create_operation_id": "",
            })
            refreshed = _attachment(
                self.status_provider(), instance_id=prepared["instance_id"], tab_id=tab_id,
            )
            if refreshed is not None and refreshed["conversation_key"] == conversation_key:
                current = refreshed
        registered = self._receipt(
            work=work, operation_id=ids["register"],
        ) or self._run(work.work_id, ids["register"], "conversation_network_update", {
            "operation": "set-node-info", "conversation_key": conversation_key,
            "display_name": prepared["display_name"],
            "scope_name": prepared["scope_name"], "role_tags": prepared["role_tags"],
            "expected_scope_id": "",
            "expected_role_tags_sha256": role_tags_sha256([]),
            "assigned_task": task_id,
        })
        return {
            "status": "STARTED" if registered.get("outcome") == "APPLIED" else "PARTIAL",
            "stage": "WORKER_READY", "conversation_key": conversation_key,
            "direction_id": child_id, "task_id": task_id,
            "attachment": current, "operation_ids": ids,
            "creation_receipt": created, "arrangement_receipt": arrangement,
            "send_receipt": sent, "watch_receipt": watched,
            "registration_receipt": registered,
        }
