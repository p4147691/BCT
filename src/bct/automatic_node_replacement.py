"""Receipt-driven automatic Chat replacement for positively confirmed NEW_CHAT_REQUIRED.

This is a lower-level Core partial recipe, not a new user approval or Manager.
A single BCT/RCC create-and-send Operation does first submit + UUID + persisted
reply. UNKNOWN and in-flight claims are observed, NEVER reissued.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from typing import Any

from .automatic_chain_recovery import _targets
from .automatic_prepared_replacement import _exact_successor_attachment
from .conversation_network import configure_conversation_scope, conversation_scope_directory
from .core.models import Outcome, Principal
from .node_recovery import NodeRecoveryLedger, observe_node
from .status_views import status_view

_UUID = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\Z")


def _op_id(case_id: str) -> str:
    return "auto-replace-" + hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:32]


class AutomaticNodeReplacement:
    """One bounded, restart-safe step from the existing Core recovery ledger."""

    def __init__(self, *, bct, status_provider):
        self.bct = bct
        self.store = bct.store
        self.status_provider = status_provider
        self.ledger = NodeRecoveryLedger(self.store)
        self._cursor = ""

    def _cases(self) -> list[dict]:
        with self.store._readonly() as db:
            rows = db.execute(
                "SELECT c.case_id,c.work_id,c.conversation_key,c.state,"
                "c.context_json,c.assignment_epoch "
                "FROM node_recovery_cases c JOIN works w ON w.work_id=c.work_id "
                "WHERE c.case_id LIKE 'auto-node-%' "
                "AND c.state IN ('RECOVERY_NEEDED','PAUSED','REPLACEMENT_PREPARED') "
                "AND w.state='ACTIVE' AND w.assignment_epoch=c.assignment_epoch "
                "ORDER BY c.case_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def _original_connection(
        self, key: str, snapshot: dict, *, work=None,
    ) -> dict | None:
        node = status_view(snapshot, "node")
        current = node.get("current_nodes") or {}
        if (node.get("status") != "OK"
                or (current.get("observation") or {}).get("state") != "FRESH"):
            return None
        evidence = observe_node(node, key)
        if (evidence["reason"] != "NODE_NEW_CHAT_REQUIRED"
                or evidence["result"] != "CHECK"):
            # A previously exact NEW_CHAT_REQUIRED node may disappear before
            # its saved replacement intent is reserved. Never guess a window.
            # Find ONE fresh, explicitly same-network live peer as a window
            # anchor, while the original Work/RECHECK proof remains required
            # by _process before any external create-and-send.
            if evidence["reason"] == "NODE_NOT_OBSERVED" and work is not None:
                return self._unique_network_peer_window(
                    original=key, work=work, snapshot=snapshot,
                )
            return None
        ident = evidence["node"] or {}
        if ident.get("generating") is True:
            return None
        rcc = status_view(snapshot, "rcc").get("rcc") or {}
        matches = []
        for instance in rcc.get("instances") or []:
            if (not isinstance(instance, dict)
                    or instance.get("state") != "OPEN" or instance.get("cached") is True):
                continue
            for tab in instance.get("tabs") or []:
                if (tab.get("conversation_key") == key
                        and tab.get("presence") == "OPEN"
                        and tab.get("tab_id") == ident.get("tab_id")
                        and tab.get("window_id") == ident.get("window_id")):
                    matches.append({
                        "instance_id":str(instance.get("instance_id") or ""),
                        "window_id":int(tab["window_id"]),
                    })
        return matches[0] if len(matches) == 1 and matches[0]["instance_id"] else None

    def _unique_network_peer_window(
        self, *, original: str, work, snapshot: dict,
    ) -> dict | None:
        """Use one exact live network window if the old Chat tab vanished.

        Requires an existing recorded Work recovery case with a recent
        positive NEW_CHAT_REQUIRED RECHECK. This helper only resolves an
        existing RCC instance/window; it does not create or send anything.
        A global S with multiple scopes, a stale observer or two possible
        windows fail closed rather than guessing a user's destination.
        """
        node = status_view(snapshot, "node")
        current = node.get("current_nodes") or {}
        if (node.get("status") != "OK"
                or (current.get("observation") or {}).get("state") != "FRESH"):
            return None
        if observe_node(node, original)["reason"] != "NODE_NOT_OBSERVED":
            return None
        with self.store._readonly() as db:
            memberships = db.execute(
                "SELECT project_id FROM conversation_network_memberships "
                "WHERE conversation_key=? AND activity='ACTIVE'",
                (original,),
            ).fetchall()
            if len(memberships) != 1:
                return None
            project_id = str(memberships[0]["project_id"])
            peers = {
                str(row["conversation_key"]).lower() for row in db.execute(
                    "SELECT conversation_key FROM conversation_network_memberships "
                    "WHERE project_id=? AND activity='ACTIVE' "
                    "AND conversation_key!=?",
                    (project_id, original),
                )
            }
        # A shared project can contain other Works. A peer must also be
        # already linked to THIS original Work through its durable Chain
        # Direction, Watch or pending return. Project membership by itself
        # never authorizes using a different conversation's window.
        work_peers = {
            str(item["conversation_key"]).lower() for item in _targets(self.store)
            if item["work_id"] == work.work_id
            and item["conversation_key"] != original
        }
        peers &= work_peers
        if not peers:
            return None
        fresh: dict[str, tuple[int,int]] = {}
        for item in current.get("items") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("conversation_uuid") or "").lower()
            connection = item.get("connection")
            if (key not in peers or item.get("status") != "CONFIRMED"
                    or item.get("generating") is not False
                    or not isinstance(connection, dict)
                    or connection.get("disconnected") is not False
                    or str(item.get("network_id") or "") != project_id
                    or type(item.get("tab_id")) is not int
                    or type(item.get("window_id")) is not int):
                continue
            fresh[key] = (item["tab_id"], item["window_id"])
        rcc = status_view(snapshot, "rcc").get("rcc") or {}
        windows: dict[tuple[str,int], dict[str,Any]] = {}
        for instance in rcc.get("instances") or []:
            if (not isinstance(instance, dict)
                    or instance.get("state") != "OPEN"
                    or instance.get("cached") is True):
                continue
            instance_id = str(instance.get("instance_id") or "")
            session_id = str(instance.get("session_id") or "")
            if not instance_id or not re.fullmatch("[a-f0-9]{32}", session_id):
                continue
            for tab in instance.get("tabs") or []:
                if not isinstance(tab, dict):
                    continue
                key = str(tab.get("conversation_key") or "").lower()
                connection = tab.get("connection")
                if (key not in fresh or tab.get("presence") != "OPEN"
                        or (tab.get("tab_id"),tab.get("window_id")) != fresh[key]
                        or (isinstance(connection,dict)
                            and connection.get("disconnected") is True)):
                    continue
                window = tab["window_id"]
                windows[(instance_id,window)] = {
                    "instance_id":instance_id,
                    "window_id":window,
                    "peer_conversation_key":key,
                    "peer_session_id":session_id,
                    "network_id":project_id,
                }
        return next(iter(windows.values())) if len(windows) == 1 else None

    def _instruction(self, *, work, case: dict, role: str, task_id: str) -> str:
        # Read the newest exact original Work/Task generation instead of
        # guessing that a recovered Worker should restart Generation 1.
        generation = ""
        direction_id = ""
        if task_id:
            with self.store._readonly() as db:
                source = db.execute(
                    "SELECT generation,context_json FROM delayed_send_watches "
                    "WHERE task_id=? AND conversation_key=? "
                    "AND json_extract(context_json,'$.work_id')=? "
                    "ORDER BY generation DESC LIMIT 1",
                    (task_id, case["conversation_key"], work.work_id),
                ).fetchone()
                if source is not None:
                    generation = str(source["generation"])
                    try:
                        direction_id = str(json.loads(
                            source["context_json"] or "{}"
                        ).get("chain_direction_id") or "")
                    except (ValueError, TypeError):
                        direction_id = ""
        # Work/Direction/Task/Generation are internal continuity identities.
        # The user must never have to type them; the successor must not replay.
        text = (
            "[BCT AUTOMATIC NODE RECOVERY]\n"
            "You are the verified successor of an unavailable Chat node. "
            "No separate Manager is created by receiving this instruction.\n"
            "Restore the existing Chain Recipe 8-step flow and Watch·Alarm "
            "Continuation R, not a legacy Chain Message.\n"
            "Original work_id=" + work.work_id + "\n"
            "Original node UUID=" + case["conversation_key"] + "\n"
            "Original role=" + role + "\n"
            "Original task_id=" + (task_id or "(read original Work)") + "\n"
            "Original direction_id=" + (direction_id or "(read saved Direction)") + "\n"
            "Original generation=" + (generation or "(read persisted generation)") + "\n"
            "Read exact saved Work, Direction, Task, Generation, Execute Plan, "
            "Watch, Alarm, return/checkpoints, Operation receipts, and Epoch "
            "using BCT. Continue only the next uncompleted step. NEVER resend "
            "an UNKNOWN external effect or create a new Work/Manager. "
            "Report original Task and successful restoration to the same "
            "conversation network. Use SELF continuation for remaining work "
            "and MANAGER return only under the original Chain Recipe contract."
        )
        if len(text) > 6000:
            raise ValueError("AUTO_REPLACE_INHERITANCE_INSTRUCTION_TOO_LONG")
        return text

    def _unknown_effect_in_original_task(self, work, conversation_key: str) -> bool:
        """The original Worker/Manager's uncertain external effects stay fenced."""
        with self.store._readonly() as db:
            watches = list(db.execute(
                "SELECT state,context_json FROM delayed_send_watches "
                "WHERE json_extract(context_json,'$.work_id')=? "
                "AND conversation_key=?",
                (work.work_id,conversation_key),
            ))
            for row in watches:
                if row["state"] in {"UNKNOWN","DISPATCHING"}:
                    return True
                context = json.loads(row["context_json"] or "{}")
                source_id = str(context.get("source_send_operation_id") or "")
                if not source_id:
                    continue
                operation = db.execute(
                    "SELECT state,outcome FROM operations WHERE work_id=? AND operation_id=?",
                    (work.work_id,source_id),
                ).fetchone()
                if operation is not None and (
                    operation["outcome"] == "UNKNOWN"
                    or (operation["state"] == "RUNNING"
                        and operation["outcome"] is None)
                ):
                    return True
        return False

    def _principal(self, work):
        if "browser" not in work.actions:
            raise ValueError("AUTO_REPLACE_WORK_BROWSER_NOT_ALLOWED")
        return Principal(work.owner_principal_id,
                         "core-original-work-recovery",
                         frozenset({"browser"}))

    def _discover_window(self, *, work, principal, source: dict) -> str | None:
        result = self.bct.operations.run(
            principal=principal, work_id=work.work_id,
            operation_id="auto-recovery-discover-" + secrets.token_hex(16),
            capability="browser",
            arguments={"command":"target-discover",
                       "instance_id":source["instance_id"]},
        )
        if result.outcome != Outcome.APPLIED:
            return None
        matches = [
            item for item in result.output.get("targets", [])
            if (item.get("target_kind") == "window"
                and item.get("window_id") == source["window_id"])
        ]
        return str(matches[0]["target_ref"]) if len(matches) == 1 else None

    def _old_uuid_is_ready(self, key: str) -> dict | None:
        try:
            node = status_view(self.status_provider(),"node")
            evidence = observe_node(node,key)
            if (evidence["result"]=="OK"
                    and evidence["observation_state"]=="FRESH"
                    and evidence["conversation_key"]==key):
                return evidence
        except (ValueError,KeyError,RuntimeError):
            pass
        return None

    def _execute_original_operation(self, *, work, principal, intent: dict):
        operation_id = intent["operation_id"]
        try:
            previous = self.store.get_operation_for(
                operation_id=operation_id, work_id=work.work_id,
                principal_id=work.owner_principal_id,
            )
        except KeyError:
            previous = None
        # A running claim may have reached the browser before Core died.
        # Even a cached APPLIED receipt must be checked, not replayed.
        if previous is not None:
            if previous.state.value != "FINISHED":
                return "IN_FLIGHT_UNKNOWN", None
            return (previous.outcome.value if previous.outcome else "IN_FLIGHT_UNKNOWN",
                    previous)
        result = self.bct.operations.run(
            principal=principal, work_id=work.work_id,
            operation_id=operation_id, capability="browser",
            arguments={
                "command":"create-and-send", "instance_id":intent["instance_id"],
                "mode":"tab", "target_ref":intent["target_ref"],
                "timeout_s":180.0, "text":intent["instruction"],
            },
        )
        return (result.outcome.value if result.outcome else "IN_FLIGHT_UNKNOWN",
                result)

    def _verified_successor(self, *, snapshot, intent, operation) -> dict | None:
        ev = operation.evidence
        key = str(ev.get("conversation_key") or "").lower()
        if not (_UUID.fullmatch(key)
                and ev.get("operation_id") == intent["operation_id"]
                and ev.get("rcc_command") == "new-chat-send"
                and ev.get("result_state") == "RESULT_PERSISTED"
                and re.fullmatch(r"[a-f0-9]{64}", str(ev.get("result_hash") or ""))
                and ev.get("instance_id") == intent["instance_id"]
                and type(ev.get("tab_id")) is int and type(ev.get("window_id")) is int):
            return None
        node = status_view(snapshot,"node")
        if (node.get("status") != "OK"
                or ((node.get("current_nodes") or {}).get("observation") or {})
                    .get("state") != "FRESH"):
            return None
        matching = []
        for instance in (status_view(snapshot,"rcc").get("rcc") or {}).get("instances",[]):
            if (instance.get("instance_id") != intent["instance_id"]
                    or instance.get("state") != "OPEN" or instance.get("cached") is True):
                continue
            for tab in instance.get("tabs",[]):
                if (tab.get("presence") == "OPEN" and tab.get("conversation_key") == key
                        and tab.get("tab_id") == ev["tab_id"]
                        and tab.get("window_id") == ev["window_id"]):
                    matching.append(tab)
        return {"conversation_key": key, "tab": matching[0], "evidence":ev} if len(matching)==1 else None

    def _process(self, case: dict) -> dict:
        work = self.store.get_work(case["work_id"])
        current = self.ledger.get(work=work, case_id=case["case_id"])
        if current is None:
            return {"status":"STALE_WORK_OR_CASE"}
        original = str(case["conversation_key"])
        role_candidates = {
            item["role"] for item in _targets(self.store)
            if item["work_id"] == work.work_id
            and item["conversation_key"] == original
        }
        if len(role_candidates) != 1:
            return {"status":"ROLE_AMBIGUOUS"}
        role = next(iter(role_candidates))
        if role not in {"manager","worker","supervisor"}:
            return {"status":"ROLE_UNSUPPORTED"}
        if role == "manager":
            # An active orchestration Manager uses a separate fenced Epoch/
            # lease owner. Creating an independent Manager without transferring
            # that epoch could cause two leaders. Never silently skip that.
            with self.store._readonly() as db:
                active = db.execute(
                    "SELECT 1 FROM orchestration_sessions "
                    "WHERE work_id=? AND state IN ('ACTIVE','PARTIAL') LIMIT 1",
                    (work.work_id,),
                ).fetchone()
            if active:
                return {"status":"MANAGER_EPOCH_RECONCILIATION_REQUIRED"}
        intent = (current.get("context") or {}).get("automatic_new_chat_intent")
        principal = self._principal(work)
        if (intent is None
                and self._unknown_effect_in_original_task(work,original)):
            return {"status":"ORIGINAL_EXTERNAL_EFFECT_UNKNOWN"}
        if intent and current["state"] == "PAUSED":
            original_evidence = self._old_uuid_is_ready(original)
            if original_evidence is not None:
                # The old Chat recovered while a replacement was planned.
                # A missing or confirmed NOT_APPLIED bootstrap can be safely
                # cancelled; a submitted or UNKNOWN new Chat cannot.
                try:
                    resumed = self.ledger.restore_automatic_predecessor(
                        work=work,case_id=case["case_id"],
                        evidence=original_evidence,
                    )
                except ValueError:
                    return {"status":"DUAL_NODE_EFFECT_RECONCILE_REQUIRED"}
                return {"status":"RECOVERED_ORIGINAL",
                        "restored_watches":resumed["restored_watches"]}
        if intent is None:
            if current["state"] != "RECOVERY_NEEDED":
                return {"status":"NO_AUTOMATIC_INTENT"}
            last = (current.get("latest_check") or {})
            observed = last.get("evidence") or {}
            if not (last.get("kind") == "RECHECK"
                    and last.get("result") == "CHECK"
                    and observed.get("reason") == "NODE_NEW_CHAT_REQUIRED"
                    and observed.get("observation_state") == "FRESH"):
                return {"status":"EXACT_NEW_CHAT_NOT_CONFIRMED"}
            snapshot = self.status_provider()
            source = self._original_connection(original, snapshot, work=work)
            if source is None:
                return {"status":"WAIT_ORIGINAL_RCC_IDENTITY"}
            target_ref = self._discover_window(
                work=work, principal=principal, source=source,
            )
            if target_ref is None:
                return {"status":"WAIT_EXACT_WINDOW_REFERENCE"}
            intent = {
                "operation_id":_op_id(case["case_id"]),
                "instance_id":source["instance_id"],
                "window_id":source["window_id"],
                "target_ref":target_ref,
                "original_role":role,
                "instruction":self._instruction(
                    work=work, case=case, role=role,
                    task_id=str(current.get("task_id") or ""),
                ),
            }
            self.ledger.pause(
                work=work, case_id=case["case_id"],
                reason="CONFIRMED_NEW_CHAT_REQUIRED",
                automatic_intent=intent,
            )
            current = self.ledger.get(work=work, case_id=case["case_id"])
        else:
            if current["state"] not in {"PAUSED","REPLACEMENT_PREPARED"}:
                return {"status":"INTENT_STATE_MISMATCH"}
        # Recheck one final time after durable PAUSE and just before the
        # irreversible RCC new-chat call. An old node can become usable
        # between target-discover and this point.
        if current["state"] == "PAUSED":
            positive = self._old_uuid_is_ready(original)
            if positive is not None:
                try:
                    resumed = self.ledger.restore_automatic_predecessor(
                        work=work,case_id=case["case_id"],evidence=positive,
                    )
                except ValueError:
                    return {"status":"DUAL_NODE_EFFECT_RECONCILE_REQUIRED"}
                return {"status":"RECOVERED_ORIGINAL",
                        "restored_watches":resumed["restored_watches"]}
        outcome, operation = self._execute_original_operation(
            work=work,principal=principal,intent=intent,
        )
        if outcome != "APPLIED" or operation is None:
            return {"status":"NEW_CHAT_" + outcome,
                    "operation_id":intent["operation_id"]}
        verified = self._verified_successor(
            snapshot=self.status_provider(),intent=intent,operation=operation,
        )
        if verified is None or verified["conversation_key"] == original:
            return {"status":"WAIT_VERIFIED_CREATED_UUID",
                    "operation_id":intent["operation_id"]}
        successor = verified["conversation_key"]
        # Register only the observed new UUID, with no new privileged role.
        # Existing predecessor roles and task metadata move atomically below.
        known = conversation_scope_directory(
            self.store,conversation_keys=[successor],
        ).get(successor) or {}
        if (known.get("scope_id") or known.get("role_tags")):
            # Another Work/user already claimed this node.
            return {"status":"SUCCESSOR_NODEINFO_CONFLICT"}
        if not known.get("display_name"):
            configure_conversation_scope(
                self.store,conversation_key=successor,
                display_name="BCT Recovery Candidate",
                scope_name="",role_tags=[],
            )
        fresh = self.status_provider()
        evidence = observe_node(status_view(fresh,"node"),successor)
        if evidence.get("result") != "OK":
            return {"status":"WAIT_SUCCESSOR_NODEINFO"}
        attachment = _exact_successor_attachment(fresh, successor)
        if (attachment is None
                or any(str(attachment[field]) != str(verified["evidence"][field])
                       for field in ("instance_id","session_id","tab_id","window_id"))):
            return {"status":"WAIT_EXACT_SUCCESSOR_RCC_BINDING"}
        evidence["verified_rcc_attachment"] = attachment
        inherit = "auto-inherit-" + hashlib.sha256(
            case["case_id"].encode("utf-8")
        ).hexdigest()[:24]
        if current["state"] == "PAUSED":
            self.ledger.prepare_replace(
                work=work,case_id=case["case_id"],
                successor_conversation_key=successor,
                inheritance_task_id=inherit,
                successor_evidence=evidence,
                atomic_inheritance_operation_id=intent["operation_id"],
            )
        result = self.ledger.commit_replace(
            work=work,case_id=case["case_id"],successor_evidence=evidence,
        )
        return {
            "status":"REPLACED" if result["state"]=="REPLACED" else "RECONCILE_REQUIRED",
            "successor_conversation_key":successor,
            "work_id":work.work_id,
            "manager_binding_recovery":result.get("manager_binding_recovery"),
            "supervisor_binding_recovery":result.get("supervisor_binding_recovery"),
            "original_task_resumption":"REQUIRES_SUCCESSOR_WORK_RECEIPT",
        }

    def run_once(self, *, limit: int = 2) -> dict:
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("AUTO_REPLACE_LIMIT_INVALID")
        items = self._cases()
        after = [r for r in items if r["case_id"] > self._cursor]
        if not after and self._cursor:
            self._cursor = ""
            after = items
        selected = after[:limit]
        if selected:
            self._cursor = selected[-1]["case_id"]
        events=[]
        for item in selected:
            try:
                result=self._process(item)
                events.append({"case_id":item["case_id"],
                               "work_id":item["work_id"],**result})
            except Exception as exc:
                # Side effect state remains in the ORIGINAL Operation ledger.
                # Do not silently reissue under a different id.
                events.append({"case_id":item["case_id"],
                               "work_id":item["work_id"],
                               "status":"RECONCILE_REQUIRED",
                               "reason":type(exc).__name__})
        return {"status":"OBSERVED","examined":len(selected),
                "known_cases":len(items),"events":events,
                "effects":"EXACT_RECEIPT_DRIVEN_SINGLE_BOOTSTRAP"}
