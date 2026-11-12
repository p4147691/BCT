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

from bct.core.models import PreconditionError, Principal
from bct.loop_recipe_contracts import LoopContractError
from bct.loop_recipe_flow import LinkKind
from bct.loop_self_dispatch import LoopSelfDispatcher
from bct.loop_store import LoopStateError
from bct.persistent_loop_commands import PersistentLoopCommands
from bct.loop_turns import LoopTurns
from bct.send_delayed_message import SendDelayedMessageService, _rcc_submitted_text_sha256


CapabilityExecutor = Callable[..., Coroutine[Any, Any, dict[str, Any]]]

LOOP_OUTPUT_CONTRACT = (
    "[LOOP NEXT LINK]\n"
    "End with exactly one route: NEXT TASK — SELF: <one next instruction> "
    "or NEXT TASK — MANAGER: <return result>. In this Loop, MANAGER means the "
    "other bound endpoint (A to Supervisor, or Supervisor to A)."
)

# The existing conversation-network contract reserves the exact ``Supervisor``
# tag for one unassigned global Chain supervisor.  A persistent Loop owns a
# separate, scoped endpoint, so its advisory Node Info tag must also be
# separate.  This keeps the existing Chain role rules unchanged while allowing
# each Loop network to contain its own supervisor endpoint.
LOOP_SUPERVISOR_ROLE = "Loop Supervisor"

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

    def _receipt(self, *, work: Any, operation_id: str,
                 capability: str) -> dict[str, Any] | None:
        """Read one exact owned receipt before considering an external effect."""
        from bct.core.models import ConflictError
        try:
            metadata = self.runtime.bct.store.get_operation_metadata_for(
                operation_id=operation_id, work_id=work.work_id,
                principal_id=work.owner_principal_id,
            )
            if metadata.get("capability") != capability:
                raise LoopContractError("LOOP_SUPERVISOR_RECEIPT_CAPABILITY_MISMATCH")
            value = self.runtime.bct.store.get_operation_for(
                operation_id=operation_id, work_id=work.work_id,
                principal_id=work.owner_principal_id,
            ).as_dict()
            value["duplicate"] = True
            return value
        except KeyError:
            return None
        except ConflictError as exc:
            raise LoopContractError("LOOP_SUPERVISOR_RECEIPT_FOREIGN") from exc

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

    async def resolve_start_manager(self, instruction: str) -> tuple[dict, str, str]:
        """Bind one live RCC user turn by exact text, independent of tab focus."""
        from bct.integrations.rcc import RelayEffectUnknown, RelayUnavailable
        from bct.status_views import status_view

        if not self.runtime.status_provider:
            raise LoopContractError("LOOP_FRESH_STATUS_REQUIRED")
        snapshot = await asyncio.to_thread(self.runtime.status_provider)
        roster = status_view(snapshot, "node").get("current_nodes", {})
        if (roster.get("observation", {}).get("state") != "FRESH"
                or roster.get("unavailable_instances", 0)):
            raise LoopContractError("LOOP_START_SOURCE_UNAVAILABLE")
        keys = {node.get("conversation_uuid") for node in roster.get("items", [])
                if node.get("status") == "CONFIRMED" and node.get("source") == "RCC_FRESH"
                and not node.get("connection", {}).get("disconnected", True)
                and _UUID.fullmatch(node.get("conversation_uuid") or "")}
        if len(keys) > 24:
            raise LoopContractError("LOOP_START_SOURCE_TOO_MANY_CHATS")
        operations = self.runtime.bct.operations
        service = SendDelayedMessageService(
            store=self.runtime.bct.store, operations=operations,
            browser_feature=operations._features["browser"],
        )
        texts = {_rcc_submitted_text_sha256(instruction): instruction}
        if not instruction.startswith("BCT Control "):
            rendered = "BCT Control " + instruction
            texts[_rcc_submitted_text_sha256(rendered)] = rendered

        def read(key):
            try:
                target = LoopSelfDispatcher.exact_route(snapshot, key, require_idle=False)
                observed = service.latest(
                    instance_id=target["instance_id"], conversation_key=key,
                    expected_attachment=(target["session_id"], target["tab_id"], target["window_id"]),
                )
            except (LoopStateError, PreconditionError, RelayUnavailable, RelayEffectUnknown, ValueError):
                raise LoopContractError("LOOP_START_SOURCE_UNAVAILABLE") from None
            if observed.get("ok") is not True or observed.get("conversationKey") != key:
                raise LoopContractError("LOOP_START_SOURCE_UNAVAILABLE")
            source = texts.get(observed.get("latestUserSha256"))
            if (source and observed.get("latestUserTurnKey")
                    and observed.get("latestUserTextOccurrenceCount") == 1
                    and not observed.get("completedLatestUserTurnKey")):
                return target, source, observed["latestUserTurnKey"]
            return None

        def read_candidates():
            # The native RCC host serves one pipe request at a time.
            return [match for key in sorted(keys) if (match := read(key))]

        matches = await asyncio.to_thread(read_candidates)
        if len(matches) != 1:
            reason = "LOOP_START_SOURCE_AMBIGUOUS" if matches else "LOOP_START_SOURCE_NOT_FOUND"
            raise LoopContractError(reason)
        return matches[0]

    async def start_from_chat(self, *, work_id, instruction, direction, overall_plan, conditions):
        work = self.commands._owned_work(work_id)
        if not all((instruction.strip(), direction.strip(), overall_plan.strip(), conditions)):
            raise LoopContractError("LOOP_START_PLAN_REQUIRED")
        if max(len(instruction.strip()), len(direction.strip())) > 12000:
            raise LoopContractError("LOOP_CONTEXT_TOO_LONG")
        LoopTurns.validate_plan(overall_plan, conditions)
        manager, source, turn_key = await self.resolve_start_manager(instruction.strip())
        if len(source) > 12000:
            raise LoopContractError("LOOP_CONTEXT_TOO_LONG")
        manager_key = manager["conversation_key"]
        suffix = hashlib.sha256(json.dumps(
            [work_id, manager_key, turn_key, _rcc_submitted_text_sha256(source)]
        ).encode()).hexdigest()[:32]
        loop_id, task_id, project_id = (f"loop-{kind}-{suffix}" for kind in ("run", "task", "project"))
        turns = LoopTurns(self.runtime.bct.store)
        saved = await asyncio.to_thread(self.commands.status, loop_id=loop_id)
        if saved.get("context"):
            supervisor_key = saved["context"]["supervisor_conversation_key"]
        else:
            with self.runtime.bct.store._readonly() as db:
                pending = db.execute("""SELECT 1 FROM loop_recipe_supervisor_preparations
                    WHERE work_id=? AND network_project_id=?""", (work_id, project_id)).fetchone()
            discovery = None
            if not pending:
                discovery = await asyncio.to_thread(
                    self.discover_supervisor, manager_key, verified_active_manager=True,
                )
            if pending or discovery["status"] == "SUPERVISOR_NOT_FOUND":
                discovery = await self.prepare_supervisor(
                    work_id=work_id, manager_conversation_key=manager_key,
                    network_project_id=project_id, instance_id=manager["instance_id"],
                    create_operation_id=f"loop-s-create-{suffix}",
                    send_operation_id=f"loop-s-send-{suffix}",
                    watch_operation_id=f"loop-s-watch-{suffix}",
                    register_operation_id=f"loop-s-register-{suffix}",
                    task_id=f"loop-s-task-{suffix}",
                    bootstrap_text="You are the BCT LOOP Supervisor. Verify the Manager's work "
                                   "against its stored completion conditions when asked. Reply READY.",
                    display_name="LOOP Supervisor", scope_name="LOOP",
                    window_id=manager["window_id"], verified_active_manager=True,
                )
            if discovery["status"] != "READY":
                return discovery
            supervisor_key = discovery["supervisor_conversation_key"]
        context = self.commands.ledger.context_values(
            source, direction, manager_key, supervisor_key, project_id,
        )
        started = await asyncio.to_thread(
            turns.start, work=work, loop_id=loop_id, task_id=task_id, context=context,
            overall_plan=overall_plan, conditions=conditions,
        )
        if started["turn"] is not None:
            return started
        topology = await self.configure_topology(
            loop_id=loop_id, project_operation_id=f"loop-project-op-{suffix}",
            manager_operation_id=f"loop-manager-op-{suffix}", supervisor_operation_id="",
            display_name="LOOP " + suffix[:8],
        )
        if topology["status"] != "READY":
            return {**topology, "loop_id": loop_id}
        return await asyncio.to_thread(turns.arm, loop_id, manager_key)

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

    def discover_supervisor(
        self, manager_conversation_key: str, *, verified_active_manager: bool = False,
    ) -> dict[str, Any]:
        from bct.node_recovery import observe_node
        from bct.status_views import status_view

        if not self.runtime.status_provider:
            raise LoopContractError("LOOP_FRESH_STATUS_REQUIRED")
        view = status_view(self.runtime.status_provider(), "node")
        roster = view.get("current_nodes", {})
        manager = observe_node(view, manager_conversation_key)
        manager_ready = (manager.get("result") == "OK" or
                         verified_active_manager and manager.get("reason") == "NODE_GENERATING")
        if not manager_ready or roster.get("observation", {}).get("state") != "FRESH":
            raise LoopContractError("LOOP_MANAGER_IDENTITY_UNVERIFIED")
        if roster.get("unavailable_instances", 0):
            raise LoopContractError("LOOP_SUPERVISOR_AVAILABILITY_UNVERIFIED")
        with self.runtime.bct.store._readonly() as db:
            assigned = {row[0] for row in db.execute(
                "SELECT conversation_key FROM conversation_network_memberships WHERE activity='ACTIVE'")}
        candidates = []
        for node in roster.get("items", []):
            key = node.get("conversation_uuid", "")
            if (key != manager_conversation_key and key not in assigned
                    and {"Supervisor", LOOP_SUPERVISOR_ROLE}.intersection(node.get("roles") or ())
                    and observe_node(view, key).get("result") == "OK"
                    and node.get("generating") is False):
                candidates.append(key)
        if len(candidates) == 1:
            return {"status": "READY", "supervisor_conversation_key": candidates[0],
                    "effects": "NONE_READ_ONLY"}
        if candidates:
            return {"status": "SUPERVISOR_SELECTION_REQUIRED", "candidates": candidates,
                    "effects": "NONE_READ_ONLY"}
        return {"status": "SUPERVISOR_NOT_FOUND", "effects": "NONE_READ_ONLY"}

    async def prepare_supervisor(
        self, *, work_id: str, manager_conversation_key: str,
        network_project_id: str, instance_id: str, create_operation_id: str,
        send_operation_id: str, watch_operation_id: str,
        register_operation_id: str, task_id: str, bootstrap_text: str,
        display_name: str, scope_name: str, create_command: str = "create-chat-tab",
        window_id: int = 0,
        verified_active_manager: bool = False,
    ) -> dict[str, Any]:
        """Create and bind one missing Supervisor through existing BCT effects.

        Creation and the first send precede the bootstrap Watch because a new
        conversation UUID does not exist before that send.  The unchanged
        Delayed Send bootstrap fence then verifies the exact creation and send
        receipts and binds a zero-response baseline.  Reusing the same BCT
        operation IDs reads their receipts; it never creates or sends again.
        """
        work = self.commands._owned_work(work_id)
        if self.runtime.status_provider is None:
            raise LoopContractError("LOOP_FRESH_STATUS_REQUIRED")
        from bct.node_recovery import observe_node
        from bct.status_views import status_view
        manager = observe_node(
            status_view(self.runtime.status_provider(), "node"),
            manager_conversation_key,
        )
        manager_attachment = self._attachment(conversation_key=manager_conversation_key)
        manager_ready = (manager.get("result") == "OK" or
                         verified_active_manager and manager.get("reason") == "NODE_GENERATING")
        if not manager_ready or manager_attachment is None:
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
        preparation_key = (work_id, network_project_id)
        request_sha = hashlib.sha256(json.dumps((
            manager_conversation_key, instance_id, identifiers, bootstrap_text, display_name,
            scope_name, create_command, window_id,
        )).encode()).hexdigest()
        store = self.runtime.bct.store
        with store._readonly() as db:
            existing = db.execute("""SELECT request_sha256 FROM loop_recipe_supervisor_preparations
                                      WHERE work_id=? AND network_project_id=?""", preparation_key).fetchone()
        if not existing:
            discovery = await asyncio.to_thread(
                self.discover_supervisor, manager_conversation_key,
                verified_active_manager=verified_active_manager,
            )
            if discovery["status"] != "SUPERVISOR_NOT_FOUND":
                return discovery
        with store.transaction() as db:
            db.execute("INSERT OR IGNORE INTO loop_recipe_supervisor_preparations VALUES(?,?,?,?)",
                       (*preparation_key, manager_conversation_key, request_sha))
            saved = db.execute("""SELECT request_sha256 FROM loop_recipe_supervisor_preparations
                                  WHERE work_id=? AND network_project_id=?""", preparation_key).fetchone()
            if saved[0] != request_sha:
                raise LoopContractError("LOOP_SUPERVISOR_PREPARATION_CONFLICT")
        browser = self.runtime.make_executor("browser")
        create_args: dict[str, Any] = {
            "command": create_command, "instance_id": instance_id,
        }
        if create_command == "create-chat-tab":
            create_args["window_id"] = window_id
        created = self._receipt(
            work=work, operation_id=create_operation_id, capability="browser",
        )
        if created is None:
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
        sent = self._receipt(
            work=work, operation_id=send_operation_id, capability="browser",
        )
        if sent is None:
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
        watched = self._receipt(
            work=work, operation_id=watch_operation_id, capability="browser",
        )
        if watched is None:
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
        registered = self._receipt(
            work=work, operation_id=register_operation_id,
            capability="conversation_network_update",
        )
        if registered is None:
            try:
                registered = await network(work_id, register_operation_id, {
                    "operation": "set-node-info", "conversation_key": supervisor_key,
                    # Registration deliberately stays unassigned.  The later
                    # topology action creates the exact requested Loop project and
                    # moves both endpoints into it using explicit CAS values.
                    "display_name": display_name.strip(), "scope_name": "",
                    "role_tags": [LOOP_SUPERVISOR_ROLE], "expected_scope_id": "",
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
            "network_project_id": network_project_id,
            "planned_scope_name": scope_name.strip(), "attachment": attachment,
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
        """Create the Loop network for A and keep the verified Supervisor unassigned."""
        run = self.commands.status(loop_id=loop_id)
        if run.get("status") != "OK" or not run.get("context"):
            raise LoopContractError("LOOP_CONTEXT_REQUIRED")
        if (not all((project_operation_id, manager_operation_id, display_name))
                or project_operation_id == manager_operation_id):
            raise LoopContractError("LOOP_TOPOLOGY_OPERATION_IDS_REQUIRED")
        context = run["context"]
        execute = self.runtime.make_executor("conversation_network_update")
        work_id = run["run"]["work_id"]
        work = self.commands._owned_work(work_id)
        with self.runtime.bct.store._readonly() as db:
            supervisor = db.execute("""SELECT 1 FROM conversation_network_memberships
                WHERE conversation_key=? AND activity='ACTIVE'""",
                (context["supervisor_conversation_key"],)).fetchone()
            existing = db.execute("SELECT 1 FROM conversation_network_projects WHERE project_id=?",
                                  (context["network_project_id"],)).fetchone()
        if supervisor:
            raise LoopContractError("LOOP_SUPERVISOR_MUST_BE_UNASSIGNED")
        if existing and self._receipt(work=work, operation_id=project_operation_id,
                                      capability="conversation_network_update") is None:
            raise LoopContractError("LOOP_NETWORK_ALREADY_EXISTS")
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
        return {"status": "READY", "project": project, "manager": manager,
                "supervisor_conversation_key": context["supervisor_conversation_key"]}

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
    overall_plan: str = "", completion_conditions: dict[str, str] | None = None,
    turn: int = 0, plan_id: str = "", expected_revision: int = 0,
    plan: dict[str, str] | None = None, turn_decision: dict[str, Any] | None = None,
    progress: dict[str, Any] | None = None,
    loop_recipe_runtime: Any = None,
) -> dict[str, Any]:
    """Public action dispatcher kept separate from MCP registration."""
    coordinator = PersistentLoopCoordinator(runtime)
    commands = coordinator.commands
    turns = LoopTurns(runtime.bct.store)
    try:
        if action == "outline":
            return {
                "status": "OK", "effects": "NONE_READ_ONLY",
                "actions": [
                    "discover_supervisor", "prepare_supervisor", "start", "topology",
                    "arm", "status", "save_plan", "record_progress", "decide", "resume",
                ],
                "manager_decisions": ["continue", "wait", "handoff", "blocked", "complete"],
                "supervisor_decisions": ["continue", "wait", "return", "blocked"],
                "sequence": [
                    "In a general chat, call start with work_id, the exact current user message, Direction, plan and conditions. Omit identity and topology IDs to verify the current RCC turn, prepare topology and arm automatically.",
                    "Save original instruction, Direction, overall plan and conditions.",
                    "Place only the Manager in the new project. Keep the Supervisor unassigned.",
                    "Arm the Manager response to the exact original user message. Wait for WATCHING before working.",
                    "Read status, save the detail plan, execute, verify and save the decision.",
                    "The exact response releases the next prearmed turn or completion receipt.",
                ],
            }
        if action == "discover_supervisor":
            return await asyncio.to_thread(coordinator.discover_supervisor, manager_conversation_key)
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
            if work_id and not any((manager_conversation_key, supervisor_conversation_key,
                                    network_project_id, loop_id, task_id)):
                return await coordinator.start_from_chat(
                    work_id=work_id, instruction=instruction_text, direction=direction_text,
                    overall_plan=overall_plan, conditions=completion_conditions,
                )
            if not loop_id or not work_id:
                raise LoopContractError("LOOP_RUN_IDENTITY_REQUIRED")
            if not all((instruction_text, direction_text, manager_conversation_key,
                        supervisor_conversation_key, network_project_id)):
                raise LoopContractError("LOOP_CONTEXT_REQUIRED")
            topology_proof = await asyncio.to_thread(
                coordinator.verify_topology_endpoints,
                manager_conversation_key, supervisor_conversation_key,
            )
            work = await asyncio.to_thread(commands._owned_work, work_id)
            context = commands.ledger.context_values(
                instruction_text, direction_text, manager_conversation_key,
                supervisor_conversation_key, network_project_id,
            )
            started = await asyncio.to_thread(
                turns.start, work=work, loop_id=loop_id, task_id=task_id, context=context,
                overall_plan=overall_plan, conditions=completion_conditions or {},
            )
            return {**started, "topology_proof": topology_proof}
        if action in {"arm", "save_plan", "record_progress", "decide", "resume"}:
            saved = await asyncio.to_thread(commands.status, loop_id=loop_id)
            if saved["status"] != "OK":
                return saved
            if action == "arm":
                return await asyncio.to_thread(turns.arm, loop_id, conversation_key)
            if action == "resume":
                return await asyncio.to_thread(turns.resume, loop_id, turn, conversation_key, send_text)
            if action == "record_progress":
                return await asyncio.to_thread(
                    turns.record_progress, loop_id, turn, conversation_key,
                    plan_id=plan_id, revision=expected_revision, progress=progress or {},
                )
            if action == "save_plan":
                return await asyncio.to_thread(
                    turns.save_plan, loop_id, turn, conversation_key,
                    plan_id=plan_id, expected_revision=expected_revision, plan=plan,
                )
            return await asyncio.to_thread(
                turns.decide, loop_id, turn, conversation_key, decision=turn_decision or {},
            )
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
            saved = await asyncio.to_thread(commands.status, loop_id=loop_id)
            if saved["status"] != "OK":
                return saved
            try:
                workflow = await asyncio.to_thread(turns.status, loop_id)
            except LoopContractError as exc:
                if str(exc) != "LOOP_PERSISTENT_OBJECTIVE_REQUIRED":
                    raise
                return saved
            return {**saved, **workflow}
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
        if action == "transition":
            raise LoopContractError("LOOP_USE_ARM_SAVE_PLAN_AND_DECIDE")
        raise LoopContractError("LOOP_ACTION_INVALID")
    except (LoopContractError, KeyError, ValueError) as exc:
        return {"status": "INVALID_REQUEST", "reason": str(exc), "effects": "NONE"}
