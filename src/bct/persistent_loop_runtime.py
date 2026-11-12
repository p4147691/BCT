"""Loop-only runtime ports and external-effect coordinator.

The coordinator composes existing BCT browser operations without changing
their implementations.  Durable Loop state is always staged before Watch or
message effects.  A repeated continuation ID returns its existing state and
never replays either effect.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from bct.core.models import Principal
from bct.loop_recipe_contracts import LoopContractError
from bct.loop_recipe_flow import LinkKind
from bct.persistent_loop_commands import PersistentLoopCommands


CapabilityExecutor = Callable[..., Coroutine[Any, Any, dict[str, Any]]]

LOOP_OUTPUT_CONTRACT = (
    "[LOOP NEXT LINK]\n"
    "End with exactly one route: NEXT TASK — SELF: <one next instruction> "
    "or NEXT TASK — MANAGER: <return result>. In this Loop, MANAGER means the "
    "other bound endpoint (A to Supervisor, or Supervisor to A)."
)

_UUID = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}")


def loop_delivery_text(text: str) -> tuple[str, bool]:
    body = str(text or "").strip()
    if not body:
        raise LoopContractError("LOOP_HANDOFF_TEXT_REQUIRED")
    if "NEXT TASK — SELF:" in body and "NEXT TASK — MANAGER:" in body:
        return body, False
    return body + "\n\n" + LOOP_OUTPUT_CONTRACT, True


@dataclass(frozen=True)
class PersistentLoopRuntime:
    bct: Any
    principal: Principal
    status_provider: Callable[[], dict[str, Any]] | None
    make_executor: Callable[[str], CapabilityExecutor]


class PersistentLoopCoordinator:
    """Join the state-only Loop kernel to unchanged BCT Watch/transport."""

    _DELIVERED = {"SELF_SENT", "RETURNED_TO_MANAGER", "COLLECTED_BY_SUPERVISOR"}
    _NOT_APPLIED = {"MANAGER_DECISION_REQUIRED", "CANCELLED", "SUPERSEDED"}

    def __init__(self, runtime: PersistentLoopRuntime):
        self.runtime = runtime
        self.commands = PersistentLoopCommands(
            runtime.bct.store, principal_id=runtime.principal.principal_id,
        )

    def verify_topology_endpoints(self, manager_conversation_key: str,
                                  supervisor_conversation_key: str) -> dict[str, Any]:
        """Verify exact live A/S identities before a new Loop is recorded."""
        if self.runtime.status_provider is None:
            raise LoopContractError("LOOP_FRESH_STATUS_REQUIRED")
        from bct.node_recovery import observe_node
        from bct.status_views import status_view
        node_view = status_view(self.runtime.status_provider(), "node")
        manager = observe_node(node_view, manager_conversation_key)
        if manager.get("result") != "OK":
            raise LoopContractError("LOOP_MANAGER_IDENTITY_UNVERIFIED")
        supervisor = observe_node(node_view, supervisor_conversation_key)
        if supervisor.get("result") != "OK":
            raise LoopContractError("LOOP_SUPERVISOR_PREPARATION_REQUIRED")
        return {"manager": manager, "supervisor": supervisor,
                "effects": "NONE_READ_ONLY"}

    def _attachment(self, *, instance_id: str = "", tab_id: int = 0,
                    conversation_key: str = "") -> dict[str, Any] | None:
        """Resolve one fresh RCC attachment without choosing a fallback node."""
        if self.runtime.status_provider is None:
            raise LoopContractError("LOOP_FRESH_STATUS_REQUIRED")
        from bct.status_views import status_view
        rcc = status_view(self.runtime.status_provider(), "rcc").get("rcc", {})
        matches: list[dict[str, Any]] = []
        for instance in rcc.get("instances", []):
            if (instance.get("state") != "OPEN" or instance.get("cached") is True
                    or instance_id and instance.get("instance_id") != instance_id):
                continue
            session_id = str(instance.get("session_id") or "")
            if not re.fullmatch(r"[a-f0-9]{32}", session_id):
                continue
            for tab in instance.get("tabs", []):
                key = str(tab.get("conversation_key") or "").lower()
                if (tab_id and tab.get("tab_id") != tab_id
                        or conversation_key and key != conversation_key.lower()
                        or type(tab.get("window_id")) is not int):
                    continue
                matches.append({
                    "instance_id": str(instance.get("instance_id") or ""),
                    "session_id": session_id, "tab_id": int(tab["tab_id"]),
                    "window_id": int(tab["window_id"]), "conversation_key": key,
                })
        return matches[0] if len(matches) == 1 else None

    async def prepare_supervisor(
        self, *, work_id: str, manager_conversation_key: str,
        network_project_id: str, instance_id: str, create_operation_id: str,
        send_operation_id: str, watch_operation_id: str,
        register_operation_id: str, task_id: str, bootstrap_text: str,
        display_name: str, scope_name: str, create_command: str = "create-chat-tab",
        window_id: int = 0,
    ) -> dict[str, Any]:
        """Create and bind one missing Supervisor through existing BCT effects.

        Creation and the first send precede the bootstrap Watch because a new
        conversation UUID does not exist before that send.  The unchanged
        Delayed Send bootstrap fence then verifies the exact creation and send
        receipts and binds a zero-response baseline.  Reusing the same BCT
        operation IDs reads their receipts; it never creates or sends again.
        """
        self.commands._owned_work(work_id)
        if self.runtime.status_provider is None:
            raise LoopContractError("LOOP_FRESH_STATUS_REQUIRED")
        from bct.node_recovery import observe_node
        from bct.status_views import status_view
        manager = observe_node(
            status_view(self.runtime.status_provider(), "node"),
            manager_conversation_key,
        )
        manager_attachment = self._attachment(conversation_key=manager_conversation_key)
        if manager.get("result") != "OK" or manager_attachment is None:
            raise LoopContractError("LOOP_MANAGER_IDENTITY_UNVERIFIED")
        identifiers = (
            create_operation_id, send_operation_id, watch_operation_id,
            register_operation_id, task_id,
        )
        if (not all(identifiers) or len(set(identifiers)) != len(identifiers)
                or not all(re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value)
                           for value in identifiers)
                or not instance_id or not network_project_id
                or not bootstrap_text.strip() or not display_name.strip()
                or not scope_name.strip()):
            raise LoopContractError("LOOP_SUPERVISOR_PREPARATION_INPUT_REQUIRED")
        if create_command not in {"create-chat-tab", "create-chat-window"}:
            raise LoopContractError("LOOP_SUPERVISOR_CREATE_COMMAND_INVALID")
        if create_command == "create-chat-tab" and window_id <= 0:
            raise LoopContractError("LOOP_SUPERVISOR_WINDOW_REQUIRED")
        browser = self.runtime.make_executor("browser")
        create_args: dict[str, Any] = {
            "command": create_command, "instance_id": instance_id,
        }
        if create_command == "create-chat-tab":
            create_args["window_id"] = window_id
        try:
            created = await browser(work_id, create_operation_id, create_args)
        except Exception:
            return {"status": "SUPERVISOR_CREATION_UNKNOWN",
                    "operation_id": create_operation_id,
                    "warning": "RECONCILE_ORIGINAL_RECEIPT_NO_REPLAY"}
        if created.get("outcome") != "APPLIED":
            return {"status": "SUPERVISOR_CREATION_" + str(created.get("outcome") or "UNKNOWN"),
                    "creation": created, "warning": "NO_UNKNOWN_REPLAY"}
        creation_evidence = created.get("evidence") or {}
        created_tab_id = creation_evidence.get("created_tab_id")
        if type(created_tab_id) is not int or created_tab_id <= 0:
            return {"status": "SUPERVISOR_CREATION_RECEIPT_INVALID", "creation": created}
        attachment = self._attachment(instance_id=instance_id, tab_id=created_tab_id)
        if attachment is None:
            return {"status": "WAITING_FOR_SUPERVISOR_TAB", "creation": created,
                    "warning": "REUSE_SAME_OPERATION_IDS_NO_REPLAY"}
        outgoing, contract_appended = loop_delivery_text(bootstrap_text)
        try:
            sent = await browser(work_id, send_operation_id, {
                "command": "send-message", **attachment, "conversation_key": "",
                "create_operation_id": create_operation_id, "text": outgoing,
            })
        except Exception:
            return {"status": "SUPERVISOR_SEND_UNKNOWN", "creation": created,
                    "operation_id": send_operation_id,
                    "warning": "RECONCILE_ORIGINAL_RECEIPT_NO_REPLAY"}
        if sent.get("outcome") != "APPLIED":
            return {"status": "SUPERVISOR_SEND_" + str(sent.get("outcome") or "UNKNOWN"),
                    "creation": created, "send": sent, "warning": "NO_UNKNOWN_REPLAY"}
        supervisor_key = str((sent.get("evidence") or {}).get("conversation_key") or "").lower()
        if not _UUID.fullmatch(supervisor_key) or supervisor_key == manager_conversation_key:
            return {"status": "WAITING_FOR_SUPERVISOR_IDENTITY", "creation": created,
                    "send": sent, "warning": "REUSE_SAME_OPERATION_IDS_NO_REPLAY"}
        attachment = self._attachment(instance_id=instance_id, tab_id=created_tab_id)
        if attachment is None or attachment["conversation_key"] != supervisor_key:
            return {"status": "WAITING_FOR_SUPERVISOR_IDENTITY", "creation": created,
                    "send": sent, "supervisor_conversation_key": supervisor_key,
                    "warning": "REUSE_SAME_OPERATION_IDS_NO_REPLAY"}
        try:
            watched = await browser(work_id, watch_operation_id, {
                "command": "send-delayed-message", "task_id": task_id,
                "instance_id": instance_id, "conversation_key": supervisor_key,
                "manager_conversation_key": manager_conversation_key,
                "manager_instance_id": manager_attachment["instance_id"],
                "planned_send_operation_id": send_operation_id,
                "planned_send_text": outgoing,
                "bootstrap_create_operation_id": create_operation_id,
                "watched_session_id": attachment["session_id"],
                "watched_tab_id": attachment["tab_id"],
                "watched_window_id": attachment["window_id"],
            })
        except Exception:
            return {"status": "SUPERVISOR_WATCH_UNKNOWN", "creation": created,
                    "send": sent, "operation_id": watch_operation_id,
                    "warning": "RECONCILE_ORIGINAL_RECEIPT_NO_REPLAY"}
        if watched.get("outcome") != "APPLIED":
            return {"status": "SUPERVISOR_WATCH_" + str(watched.get("outcome") or "UNKNOWN"),
                    "creation": created, "send": sent, "watch": watched,
                    "warning": "NO_UNKNOWN_REPLAY"}
        from bct.conversation_network import role_tags_sha256
        network = self.runtime.make_executor("conversation_network_update")
        try:
            registered = await network(work_id, register_operation_id, {
                "operation": "set-node-info", "conversation_key": supervisor_key,
                "display_name": display_name.strip(), "scope_name": scope_name.strip(),
                "role_tags": ["Supervisor"], "expected_scope_id": "",
                "expected_role_tags_sha256": role_tags_sha256([]),
                "assigned_task": task_id,
            })
        except Exception:
            return {"status": "SUPERVISOR_REGISTRATION_UNKNOWN", "creation": created,
                    "send": sent, "watch": watched, "operation_id": register_operation_id,
                    "warning": "RECONCILE_ORIGINAL_RECEIPT_NO_REPLAY"}
        return {
            "status": "READY" if registered.get("outcome") == "APPLIED"
                      else "SUPERVISOR_REGISTRATION_" + str(registered.get("outcome") or "UNKNOWN"),
            "supervisor_conversation_key": supervisor_key,
            "network_project_id": network_project_id, "attachment": attachment,
            "manager_proof": manager, "creation": created, "send": sent,
            "watch": watched, "registration": registered,
            "contract_appended": contract_appended,
            "warning": "" if registered.get("outcome") == "APPLIED" else "NO_UNKNOWN_REPLAY",
        }

    async def configure_topology(
        self, *, loop_id: str, project_operation_id: str,
        manager_operation_id: str, supervisor_operation_id: str,
        display_name: str, expected_manager_scope_id: str = "",
        expected_supervisor_scope_id: str = "",
    ) -> dict[str, Any]:
        """Create the Loop-specific network and assign its exact A/S members."""
        run = self.commands.status(loop_id=loop_id)
        if run.get("status") != "OK" or not run.get("context"):
            raise LoopContractError("LOOP_CONTEXT_REQUIRED")
        if (not all((project_operation_id, manager_operation_id,
                     supervisor_operation_id, display_name))
                or len({project_operation_id, manager_operation_id,
                        supervisor_operation_id}) != 3):
            raise LoopContractError("LOOP_TOPOLOGY_OPERATION_IDS_REQUIRED")
        context = run["context"]
        execute = self.runtime.make_executor("conversation_network_update")
        work_id = run["run"]["work_id"]
        project = await execute(work_id, project_operation_id, {
            "operation": "project-upsert",
            "project_id": context["network_project_id"],
            "display_name": display_name,
        })
        if project.get("outcome") != "APPLIED":
            return {"status": "NETWORK_UNCONFIRMED", "project": project,
                    "warning": "NO_UNKNOWN_REPLAY"}
        manager = await execute(work_id, manager_operation_id, {
            "operation": "membership-assign", "project": context["network_project_id"],
            "conversation_key": context["manager_conversation_key"],
            "role_tags": ["Manager"], "expected_scope_id": expected_manager_scope_id,
        })
        if manager.get("outcome") != "APPLIED":
            return {"status": "MANAGER_MEMBERSHIP_UNCONFIRMED", "project": project,
                    "manager": manager, "warning": "NO_UNKNOWN_REPLAY"}
        supervisor = await execute(work_id, supervisor_operation_id, {
            "operation": "membership-assign", "project": context["network_project_id"],
            "conversation_key": context["supervisor_conversation_key"],
            "role_tags": ["Supervisor"], "expected_scope_id": expected_supervisor_scope_id,
        })
        return {
            "status": "READY" if supervisor.get("outcome") == "APPLIED"
                      else "SUPERVISOR_MEMBERSHIP_UNCONFIRMED",
            "project": project, "manager": manager, "supervisor": supervisor,
            "warning": "" if supervisor.get("outcome") == "APPLIED" else "NO_UNKNOWN_REPLAY",
        }

    async def connect(
        self, *, loop_id: str, block_id: str, link: str,
        continuation_id: str, watch_operation_id: str, task_id: str,
        instance_id: str, conversation_key: str,
        return_conversation_key: str, return_instance_id: str,
        send_operation_id: str = "", send_text: str = "",
        session_id: str = "", tab_id: int = 0, window_id: int = 0,
        required_capabilities: tuple[str, ...] = (),
        artifact_refs: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Stage, prearm, and conditionally deliver one exact boundary.

        WAIT watches the current conversation and sends nothing now. HANDOFF
        prearms the target response before one exact send. BLOCKED is state
        only. Existing continuation IDs are read-only replay fences.
        """
        try:
            kind = LinkKind(link)
        except ValueError as exc:
            raise LoopContractError("LOOP_LINK_INVALID") from exc
        contract_appended = False
        if kind in {LinkKind.WAIT, LinkKind.HANDOFF}:
            if not all((watch_operation_id, task_id, instance_id, conversation_key,
                        return_conversation_key, return_instance_id)):
                raise LoopContractError("LOOP_WATCH_IDENTITY_REQUIRED")
        if kind is LinkKind.HANDOFF:
            if not all((send_operation_id, send_text, session_id, tab_id, window_id)):
                raise LoopContractError("LOOP_HANDOFF_IDENTITY_REQUIRED")
            send_text, contract_appended = loop_delivery_text(send_text)
        connection_refs = tuple(artifact_refs) + (
            (("loop-target:" + conversation_key, "loop-return:" + return_conversation_key)
             if kind in {LinkKind.WAIT, LinkKind.HANDOFF} else ())
            + (("loop-payload-sha256:" + hashlib.sha256(send_text.encode("utf-8")).hexdigest(),)
               if kind is LinkKind.HANDOFF else ())
        )
        operation_id = send_operation_id or watch_operation_id
        existing = await asyncio.to_thread(
            self.commands.ledger.get_continuation, continuation_id,
        )
        if existing is not None:
            expected = (loop_id, block_id, operation_id, task_id, watch_operation_id, kind.value)
            actual = (
                existing["loop_id"], existing["source_block_id"],
                existing["operation_id"], existing["watch_id"],
                existing["receipt_ref"], existing["link_kind"],
            )
            if (actual != expected
                    or tuple(existing["artifact_refs"]) != connection_refs
                    or frozenset(existing["required_capabilities"])
                       != frozenset(required_capabilities)):
                raise LoopContractError("LOOP_CONTINUATION_ID_CONFLICT")
            return {"status": "PREPARED", "continuation": {**existing, "created": False},
                    "next_block_id": existing["next_block_id"],
                    "effects": "NONE_EXISTING_CONTINUATION"}
        prepared = await asyncio.to_thread(
            self.commands.transition,
            loop_id=loop_id, block_id=block_id, link=kind.value,
            required_capabilities=required_capabilities,
            artifact_refs=connection_refs, continuation_id=continuation_id,
            operation_id=operation_id, watch_id=task_id,
            receipt_ref=watch_operation_id,
        )
        if not prepared.get("continuation", {}).get("created", False):
            return {**prepared, "effects": "NONE_EXISTING_CONTINUATION"}
        if kind is LinkKind.BLOCKED:
            return {**prepared, "status": "BLOCKED", "effects": "STATE_ONLY"}
        if kind not in {LinkKind.WAIT, LinkKind.HANDOFF}:
            return prepared
        browser = self.runtime.make_executor("browser")
        try:
            watch = await browser(
                self.commands.status(loop_id=loop_id)["run"]["work_id"],
                watch_operation_id,
                {
                    "command": "send-delayed-message", "task_id": task_id,
                    "instance_id": instance_id, "conversation_key": conversation_key,
                    "manager_conversation_key": return_conversation_key,
                    "manager_instance_id": return_instance_id,
                    "planned_send_operation_id": send_operation_id if kind is LinkKind.HANDOFF else "",
                    "planned_send_text": send_text if kind is LinkKind.HANDOFF else "",
                    "bootstrap_create_operation_id": "",
                },
            )
        except Exception:
            await asyncio.to_thread(
                self.commands.ledger.observe_original_receipt,
                continuation_id=continuation_id, observation="UNKNOWN",
            )
            return {**prepared, "status": "WATCH_UNKNOWN",
                    "warning": "RECONCILE_ORIGINAL_RECEIPT_NO_REPLAY"}
        if watch.get("outcome") != "APPLIED":
            observation = "UNKNOWN" if watch.get("outcome") == "UNKNOWN" else "NOT_APPLIED"
            await asyncio.to_thread(
                self.commands.ledger.observe_original_receipt,
                continuation_id=continuation_id, observation=observation,
            )
            return {**prepared, "status": "WATCH_" + observation,
                    "watch": watch, "warning": "NO_UNKNOWN_REPLAY"}
        if kind is LinkKind.WAIT:
            return {**prepared, "status": "WATCHING", "watch": watch,
                    "effects": "WATCH_PREARMED_NO_INITIAL_SEND",
                    "response_output_contract": LOOP_OUTPUT_CONTRACT}
        try:
            sent = await browser(
                self.commands.status(loop_id=loop_id)["run"]["work_id"],
                send_operation_id,
                {
                    "command": "send-message", "instance_id": instance_id,
                    "session_id": session_id, "tab_id": tab_id,
                    "window_id": window_id, "conversation_key": conversation_key,
                    "text": send_text,
                },
            )
        except Exception:
            await asyncio.to_thread(
                self.commands.ledger.observe_original_receipt,
                continuation_id=continuation_id, observation="UNKNOWN",
            )
            return {**prepared, "status": "SEND_UNKNOWN", "watch": watch,
                    "warning": "RECONCILE_ORIGINAL_RECEIPT_NO_REPLAY"}
        if sent.get("outcome") != "APPLIED":
            observation = "UNKNOWN" if sent.get("outcome") == "UNKNOWN" else "NOT_APPLIED"
            await asyncio.to_thread(
                self.commands.ledger.observe_original_receipt,
                continuation_id=continuation_id, observation=observation,
            )
            return {**prepared, "status": "SEND_" + observation,
                    "watch": watch, "send": sent, "warning": "NO_UNKNOWN_REPLAY"}
        return {**prepared, "status": "WATCHING", "watch": watch, "send": sent,
                "effects": "WATCH_PREARMED_THEN_ONE_SEND",
                "contract_appended": contract_appended,
                "response_output_contract": LOOP_OUTPUT_CONTRACT}

    async def sync(self, *, continuation_id: str) -> dict[str, Any]:
        """Read the existing delayed Watch and resume without sending."""
        continuation = await asyncio.to_thread(
            self.commands.ledger.get_continuation, continuation_id,
        )
        if continuation is None:
            raise LoopContractError("LOOP_CONTINUATION_NOT_FOUND")
        if continuation["state"] == "CLAIMED":
            return {"status": "ALREADY_RESUMED", "continuation": continuation,
                    "effects": "NONE_READ_ONLY"}
        run = await asyncio.to_thread(
            self.commands.ledger.get_run, continuation["loop_id"],
        )
        self.commands._owned_work(run["work_id"])
        from bct.send_delayed_message import DurableWatchLedger
        DurableWatchLedger(self.runtime.bct.store)
        with self.runtime.bct.store._readonly() as db:
            row = db.execute(
                "SELECT * FROM delayed_send_watches WHERE task_id=? "
                "ORDER BY generation DESC LIMIT 1", (continuation["watch_id"],),
            ).fetchone()
        if row is None:
            return {"status": "WAITING_WATCH", "continuation": continuation}
        watch = dict(row)
        context = json.loads(watch.pop("context_json") or "{}")
        if (context.get("work_id") != run["work_id"]
                or context.get("principal_id") != self.runtime.principal.principal_id):
            raise LoopContractError("LOOP_WATCH_BINDING_MISMATCH")
        state = str(watch["state"])
        if state == "UNKNOWN":
            observed = await asyncio.to_thread(
                self.commands.ledger.observe_original_receipt,
                continuation_id=continuation_id, observation="UNKNOWN",
            )
            return {"status": "RECONCILE_ORIGINAL_RECEIPT", "continuation": observed,
                    "watch_state": state, "effects": "NONE_READ_ONLY"}
        if state in self._DELIVERED | self._NOT_APPLIED:
            observation = "DELIVERED" if state in self._DELIVERED else "NOT_APPLIED"
            await asyncio.to_thread(
                self.commands.ledger.observe_original_receipt,
                continuation_id=continuation_id, observation=observation,
            )
            claimed = await asyncio.to_thread(
                self.commands.ledger.claim_resume, continuation_id,
            )
            return {"status": "RESUMED" if claimed else "ALREADY_RESUMED",
                    "continuation": claimed or continuation, "watch_state": state,
                    "effects": "NONE_READ_ONLY"}
        return {"status": "WAITING_RESPONSE", "continuation": continuation,
                "watch_state": state, "effects": "NONE_READ_ONLY"}


async def persistent_loop_command(
    runtime: PersistentLoopRuntime, *, action: str = "outline",
    work_id: str = "", loop_id: str = "", block_id: str = "", link: str = "",
    continuation_id: str = "", watch_operation_id: str = "", task_id: str = "",
    instance_id: str = "", conversation_key: str = "",
    return_conversation_key: str = "", return_instance_id: str = "",
    send_operation_id: str = "", send_text: str = "", session_id: str = "",
    tab_id: int = 0, window_id: int = 0,
    required_capabilities: list[str] | None = None,
    artifact_refs: list[str] | None = None,
    receipt_observation: str = "", node_observation: str = "",
    unchanged_rechecks: int = 0,
    instruction_text: str = "", direction_text: str = "",
    manager_conversation_key: str = "", supervisor_conversation_key: str = "",
    network_project_id: str = "", project_operation_id: str = "",
    manager_operation_id: str = "", supervisor_operation_id: str = "",
    network_display_name: str = "", expected_manager_scope_id: str = "",
    expected_supervisor_scope_id: str = "",
    supervisor_instance_id: str = "", supervisor_create_operation_id: str = "",
    supervisor_send_operation_id: str = "", supervisor_watch_operation_id: str = "",
    supervisor_register_operation_id: str = "", supervisor_task_id: str = "",
    supervisor_bootstrap_text: str = "", supervisor_display_name: str = "",
    supervisor_scope_name: str = "", supervisor_create_command: str = "create-chat-tab",
    supervisor_window_id: int = 0,
    recovery_action: str = "", recovery_case_id: str = "",
    recovery_conversation_key: str = "", recovery_task_id: str = "",
    recovery_reason: str = "", successor_conversation_key: str = "",
    inheritance_task_id: str = "",
    loop_recipe_runtime: Any = None,
) -> dict[str, Any]:
    """Public action dispatcher kept separate from MCP registration."""
    coordinator = PersistentLoopCoordinator(runtime)
    commands = coordinator.commands
    try:
        if action == "outline":
            return commands.outline()
        if action == "prepare_supervisor":
            return await coordinator.prepare_supervisor(
                work_id=work_id, manager_conversation_key=manager_conversation_key,
                network_project_id=network_project_id, instance_id=supervisor_instance_id,
                create_operation_id=supervisor_create_operation_id,
                send_operation_id=supervisor_send_operation_id,
                watch_operation_id=supervisor_watch_operation_id,
                register_operation_id=supervisor_register_operation_id,
                task_id=supervisor_task_id, bootstrap_text=supervisor_bootstrap_text,
                display_name=supervisor_display_name, scope_name=supervisor_scope_name,
                create_command=supervisor_create_command, window_id=supervisor_window_id,
            )
        if action == "start":
            if not loop_id or not work_id:
                raise LoopContractError("LOOP_RUN_IDENTITY_REQUIRED")
            if not all((instruction_text, direction_text, manager_conversation_key,
                        supervisor_conversation_key, network_project_id)):
                raise LoopContractError("LOOP_CONTEXT_REQUIRED")
            topology_proof = await asyncio.to_thread(
                coordinator.verify_topology_endpoints,
                manager_conversation_key, supervisor_conversation_key,
            )
            started = await asyncio.to_thread(
                commands.start, loop_id=loop_id, work_id=work_id,
                instruction_text=instruction_text, direction_text=direction_text,
                manager_conversation_key=manager_conversation_key,
                supervisor_conversation_key=supervisor_conversation_key,
                network_project_id=network_project_id,
            )
            return {**started, "topology_proof": topology_proof}
        if action == "topology":
            return await coordinator.configure_topology(
                loop_id=loop_id, project_operation_id=project_operation_id,
                manager_operation_id=manager_operation_id,
                supervisor_operation_id=supervisor_operation_id,
                display_name=network_display_name,
                expected_manager_scope_id=expected_manager_scope_id,
                expected_supervisor_scope_id=expected_supervisor_scope_id,
            )
        if action == "node_recovery":
            from bct.persistent_loop_recovery import PersistentLoopRecovery
            return await PersistentLoopRecovery(runtime).run(
                action=recovery_action, work_id=work_id,
                conversation_key=recovery_conversation_key,
                task_id=recovery_task_id, case_id=recovery_case_id,
                reason=recovery_reason,
                successor_conversation_key=successor_conversation_key,
                inheritance_task_id=inheritance_task_id,
            )
        if action == "status":
            if not loop_id:
                raise LoopContractError("LOOP_ID_REQUIRED")
            return await asyncio.to_thread(commands.status, loop_id=loop_id)
        if action == "sync":
            if not continuation_id:
                raise LoopContractError("LOOP_CONTINUATION_ID_REQUIRED")
            return await coordinator.sync(continuation_id=continuation_id)
        if action == "recovery_plan":
            return await asyncio.to_thread(
                commands.recovery_plan, continuation_id=continuation_id,
                receipt_observation=receipt_observation,
                node_observation=node_observation,
                unchanged_rechecks=unchanged_rechecks,
            )
        if action != "transition":
            raise LoopContractError("LOOP_ACTION_INVALID")
        try:
            kind = LinkKind(link)
        except ValueError as exc:
            raise LoopContractError("LOOP_LINK_INVALID") from exc
        common = dict(
            loop_id=loop_id, block_id=block_id, link=link,
            required_capabilities=tuple(required_capabilities or ()),
            artifact_refs=tuple(artifact_refs or ()),
        )
        if kind in {LinkKind.CONTINUE, LinkKind.COMPLETE}:
            return await asyncio.to_thread(commands.transition, **common)
        return await coordinator.connect(
            **common, continuation_id=continuation_id,
            watch_operation_id=watch_operation_id, task_id=task_id,
            instance_id=instance_id, conversation_key=conversation_key,
            return_conversation_key=return_conversation_key,
            return_instance_id=return_instance_id,
            send_operation_id=send_operation_id, send_text=send_text,
            session_id=session_id, tab_id=tab_id, window_id=window_id,
        )
    except (LoopContractError, KeyError, ValueError) as exc:
        return {"status": "INVALID_REQUEST", "reason": str(exc), "effects": "NONE"}
