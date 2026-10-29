from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import ConflictError, OperationResult, OperationState, Outcome, Work


# Read-only cause hints. These describe where evidence was lost, never whether
# a remote effect occurred or whether a resource claim may be released.
_CLAIM_UNKNOWN_STAGE = {
    "RCC_COMPOSE_CREATE_UNKNOWN": "CREATE_TRANSPORT",
    "RCC_COMPOSE_CREATE_RECEIPT_UNVERIFIED": "CREATE_RECEIPT",
    "RCC_COMPOSE_CREATED_IDENTITY_UNVERIFIED": "CREATE_IDENTITY",
    "RCC_COMPOSE_SEND_UNKNOWN": "SEND_TRANSPORT",
    "RCC_COMPOSE_SEND_ACK_UNVERIFIED": "SEND_ACK",
    "RCC_COMPOSE_TERMINAL_EVIDENCE_MISMATCH": "RESULT_MISMATCH",
    "RCC_COMPOSE_TERMINAL_NOT_CONFIRMED": "RESULT_UNVERIFIED",
}


def _claim_unknown_detail(error: str | None, outcome: str | None,
                          capability: str | None) -> dict[str, str | None]:
    if outcome != "UNKNOWN":
        return {"stage": None, "error_code": None, "evidence": None}
    if capability != "relay_browser":
        return {"stage": "UNCLASSIFIED", "error_code": None, "evidence": "INSUFFICIENT"}
    # Prefix-only decoding, with an explicit allowlist: no raw exception, user
    # prompt, tab content, path, token, or internal transport details are exposed.
    code = str(error or "").split(":", 1)[0]
    if code not in _CLAIM_UNKNOWN_STAGE:
        return {"stage": "UNCLASSIFIED", "error_code": None, "evidence": "INSUFFICIENT"}
    return {"stage": _CLAIM_UNKNOWN_STAGE[code], "error_code": code,
            "evidence": "RECORDED_ERROR_CODE_ONLY"}


def _claim_executor_identity(pid: int | None, fingerprint: str | None) -> tuple[str, bool]:
    if pid is None:
        return "NOT_RECORDED", False
    if not fingerprint:
        return "FINGERPRINT_MISSING", False
    try:
        # Uses the existing PID + executable + creation-time fingerprint helper.
        # Failure to observe a process is not proof that the worker is dead.
        from bct.service_runtime import process_identity
        observed = process_identity(int(pid))
    except Exception:
        # A PID probe must never fail the entire read-only Monitor snapshot.
        observed = None
    if observed is None:
        return "NOT_OBSERVABLE", False
    if observed.fingerprint != fingerprint:
        return "PID_IDENTITY_MISMATCH", False
    return "MATCHES_RUNNING_PROCESS", True


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()
        self._node_label_notifier = None
        self._node_label_last_topology = None
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def _initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT, group_name TEXT,
                    revision INTEGER NOT NULL, active INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS connections (
                    connection_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, kind TEXT NOT NULL,
                    instance TEXT NOT NULL, endpoint TEXT NOT NULL, generation INTEGER NOT NULL,
                    active INTEGER NOT NULL, FOREIGN KEY(node_id) REFERENCES nodes(node_id)
                );
                -- Conversation-network records deliberately do not reuse the
                -- orchestration role/lease tables below. They are a project
                -- directory and an append-only Monitor observation ledger.
                CREATE TABLE IF NOT EXISTS conversation_network_projects (
                    project_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
                    active INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversation_network_conversations (
                    conversation_key TEXT PRIMARY KEY, display_name TEXT NOT NULL,
                    display_order INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                -- A durable, display-only number for a known conversation.  It
                -- is deliberately separate from a Node/Connection: it has no
                -- policy, routing, or authority meaning.
                CREATE TABLE IF NOT EXISTS conversation_network_node_labels (
                    conversation_key TEXT PRIMARY KEY, node_number INTEGER NOT NULL UNIQUE,
                    assigned_at REAL NOT NULL,
                    FOREIGN KEY(conversation_key) REFERENCES conversation_network_conversations(conversation_key)
                );
                CREATE TABLE IF NOT EXISTS conversation_network_memberships (
                    project_id TEXT NOT NULL, conversation_key TEXT NOT NULL,
                    activity TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY(project_id, conversation_key),
                    FOREIGN KEY(project_id) REFERENCES conversation_network_projects(project_id),
                    FOREIGN KEY(conversation_key) REFERENCES conversation_network_conversations(conversation_key)
                );
                CREATE TABLE IF NOT EXISTS conversation_network_membership_tags (
                    project_id TEXT NOT NULL, conversation_key TEXT NOT NULL, tag TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(project_id, conversation_key, tag),
                    FOREIGN KEY(project_id, conversation_key)
                        REFERENCES conversation_network_memberships(project_id, conversation_key)
                );
                CREATE TABLE IF NOT EXISTS conversation_network_monitor_snapshots (
                    snapshot_id TEXT PRIMARY KEY, observed_at TEXT NOT NULL,
                    completeness TEXT NOT NULL, payload_digest TEXT NOT NULL,
                    received_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversation_network_monitor_rows (
                    snapshot_id TEXT NOT NULL, node_label TEXT NOT NULL,
                    conversation_key TEXT NOT NULL, title TEXT NOT NULL, presence TEXT NOT NULL,
                    PRIMARY KEY(snapshot_id, conversation_key),
                    FOREIGN KEY(snapshot_id) REFERENCES conversation_network_monitor_snapshots(snapshot_id)
                );
                CREATE INDEX IF NOT EXISTS conversation_network_monitor_rows_snapshot_label
                    ON conversation_network_monitor_rows(snapshot_id, node_label);
                -- A project run is the small execution bridge for one existing
                -- conversation scope.  It deliberately does not create a second
                -- project/network object or grant authority to a role tag.
                CREATE TABLE IF NOT EXISTS persistent_project_runs (
                    run_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL,
                    objective TEXT NOT NULL, manager_conversation_key TEXT NOT NULL,
                    work_id TEXT, orchestration_session_id TEXT,
                    manager_node_id TEXT, manager_attachment_id TEXT,
                    manager_attachment_generation INTEGER,
                    state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    FOREIGN KEY(scope_id) REFERENCES conversation_network_projects(project_id),
                    FOREIGN KEY(manager_conversation_key)
                        REFERENCES conversation_network_conversations(conversation_key),
                    FOREIGN KEY(work_id) REFERENCES works(work_id),
                    FOREIGN KEY(orchestration_session_id)
                        REFERENCES orchestration_sessions(session_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS persistent_project_runs_active_scope
                    ON persistent_project_runs(scope_id)
                    WHERE state IN ('PLANNED','READY','DEGRADED');
                CREATE UNIQUE INDEX IF NOT EXISTS persistent_project_runs_session
                    ON persistent_project_runs(orchestration_session_id)
                    WHERE orchestration_session_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS works (
                    work_id TEXT PRIMARY KEY, request_summary TEXT NOT NULL, roots_json TEXT NOT NULL,
                    actions_json TEXT NOT NULL, owner_principal_id TEXT NOT NULL,
                    assignment_epoch INTEGER NOT NULL, state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY, work_id TEXT NOT NULL, principal_id TEXT NOT NULL,
                    request_digest TEXT NOT NULL, capability TEXT NOT NULL, target TEXT NOT NULL,
                    state TEXT NOT NULL, outcome TEXT, evidence_json TEXT NOT NULL,
                    error TEXT, assignment_epoch INTEGER NOT NULL, policy_revision TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    FOREIGN KEY(work_id) REFERENCES works(work_id)
                );
                CREATE TABLE IF NOT EXISTS resource_claims (
                    resource_key TEXT PRIMARY KEY, operation_id TEXT NOT NULL, work_id TEXT NOT NULL,
                    assignment_epoch INTEGER NOT NULL, unresolved INTEGER NOT NULL,
                    FOREIGN KEY(operation_id) REFERENCES operations(operation_id)
                );
                -- One row is one complete Manager -> Worker -> Manager relay.
                -- Runtime/tab generations are observations, not identity or
                -- authorization fences.  The immutable identity is the
                -- delivery id plus both exact conversation UUIDs and request
                -- hash.
                CREATE TABLE IF NOT EXISTS relay_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    manager_conversation_key TEXT NOT NULL,
                    worker_conversation_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    response_sha256 TEXT,
                    response_length INTEGER,
                    observation_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(work_id) REFERENCES works(work_id)
                );
                CREATE INDEX IF NOT EXISTS relay_deliveries_work_state
                    ON relay_deliveries(work_id,state,updated_at);
                -- A bounded B -> B continuation is separate from a Delivery:
                -- it never implies a Manager return and it must retain its
                -- own budget/identity fence across Core restarts.
                CREATE TABLE IF NOT EXISTS node_continuations (
                    continuation_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL REFERENCES works(work_id),
                    orchestration_session_id TEXT NOT NULL REFERENCES orchestration_sessions(session_id),
                    node_id TEXT NOT NULL REFERENCES nodes(node_id),
                    attachment_id TEXT NOT NULL,
                    attachment_generation INTEGER NOT NULL,
                    instance_id TEXT NOT NULL,
                    external_session_id TEXT NOT NULL,
                    tab_id INTEGER NOT NULL,
                    window_id INTEGER NOT NULL,
                    conversation_key TEXT NOT NULL,
                    max_self_turns INTEGER NOT NULL,
                    used_self_turns INTEGER NOT NULL,
                    deadline_at REAL NOT NULL,
                    state TEXT NOT NULL,
                    reserved_operation_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(attachment_id,attachment_generation)
                        REFERENCES orchestration_attachments(attachment_id,generation)
                );
                CREATE INDEX IF NOT EXISTS node_continuations_work_state
                    ON node_continuations(work_id,state,updated_at);
                -- UI stream reports are untrusted observations, separated from
                -- authoritative operation effects. Immutable append-only steps.
                CREATE TABLE IF NOT EXISTS chat_stream_checkpoints (
                    work_id TEXT NOT NULL, stream_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL, step_id TEXT NOT NULL,
                    source_operation_id TEXT NOT NULL, source_state TEXT NOT NULL,
                    source_outcome TEXT, source_receipt_sha256 TEXT NOT NULL,
                    source_release_sha TEXT NOT NULL, next_step TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(work_id,stream_id,sequence),
                    FOREIGN KEY(work_id) REFERENCES works(work_id),
                    FOREIGN KEY(source_operation_id) REFERENCES operations(operation_id)
                );
                CREATE TABLE IF NOT EXISTS chat_stream_transport_reports (
                    work_id TEXT NOT NULL, stream_id TEXT NOT NULL,
                    incident_id TEXT NOT NULL, signal TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(work_id,stream_id,incident_id),
                    FOREIGN KEY(work_id) REFERENCES works(work_id)
                );
                -- Opt-in exact RCC conversation binding; ordinary endpoints
                -- without a Work-scoped checkpoint are never watched.
                CREATE TABLE IF NOT EXISTS chat_stream_rcc_watches (
                    work_id TEXT NOT NULL, stream_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL, conversation_key TEXT NOT NULL,
                    last_state TEXT NOT NULL, last_session_id TEXT NOT NULL,
                    transition_counter INTEGER NOT NULL, last_signal TEXT NOT NULL,
                    assignment_epoch INTEGER NOT NULL,
                    PRIMARY KEY(work_id,stream_id),
                    FOREIGN KEY(work_id) REFERENCES works(work_id)
                );
                -- External CI observation is deliberately not a Work state or
                -- resource claim: waiting for GitHub must never lock Git/deploy.
                CREATE TABLE IF NOT EXISTS github_run_inbox (
                    subscription_id TEXT PRIMARY KEY, repository TEXT NOT NULL,
                    run_id INTEGER NOT NULL, head_sha TEXT NOT NULL,
                    workflow TEXT NOT NULL, context_json TEXT NOT NULL,
                    url TEXT, state TEXT NOT NULL, conclusion TEXT,
                    error_summary TEXT, next_step TEXT NOT NULL, trigger TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, terminal_at REAL,
                    UNIQUE(repository,run_id,head_sha)
                );
                CREATE TABLE IF NOT EXISTS github_run_inbox_recipients (
                    subscription_id TEXT NOT NULL, work_id TEXT NOT NULL,
                    node_id TEXT NOT NULL, conversation_uuid TEXT, notify_user INTEGER NOT NULL,
                    notify_manager INTEGER NOT NULL, unread INTEGER NOT NULL DEFAULT 1,
                    delivery_state TEXT NOT NULL DEFAULT 'READY_IN_INBOX',
                    next_step TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(subscription_id,work_id,node_id),
                    FOREIGN KEY(subscription_id) REFERENCES github_run_inbox(subscription_id),
                    FOREIGN KEY(work_id) REFERENCES works(work_id)
                );
                CREATE INDEX IF NOT EXISTS github_run_inbox_state ON github_run_inbox(state,updated_at);
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                    subject_id TEXT NOT NULL, data_json TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS node_label_notification_outbox (
                    event_id INTEGER PRIMARY KEY REFERENCES events(event_id),
                    conversation_key TEXT NOT NULL, node_number INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                        ('PENDING','STARTED','ACKED','NOT_APPLIED','UNKNOWN')),
                    operation_id TEXT, created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS node_label_notification_pending
                    ON node_label_notification_outbox(status,conversation_key);
                CREATE TABLE IF NOT EXISTS operation_effect_stages (
                    operation_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    stage TEXT NOT NULL, detail_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(operation_id, sequence),
                    FOREIGN KEY(operation_id) REFERENCES operations(operation_id)
                );
                CREATE TABLE IF NOT EXISTS operation_steps (
                    operation_id TEXT NOT NULL, step_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                    capability TEXT NOT NULL, request_digest TEXT NOT NULL,
                    state TEXT NOT NULL, outcome TEXT, evidence_json TEXT NOT NULL,
                    error TEXT, started_at REAL, finished_at REAL,
                    PRIMARY KEY(operation_id, step_id),
                    UNIQUE(operation_id, ordinal),
                    FOREIGN KEY(operation_id) REFERENCES operations(operation_id)
                );
                CREATE TABLE IF NOT EXISTS background_jobs (
                    operation_id TEXT PRIMARY KEY, job_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(operation_id) REFERENCES operations(operation_id)
                );
                CREATE TABLE IF NOT EXISTS background_job_executors (
                    operation_id TEXT PRIMARY KEY, pid INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL, claimed_at REAL NOT NULL,
                    FOREIGN KEY(operation_id) REFERENCES background_jobs(operation_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_sessions (
                    session_id TEXT PRIMARY KEY, work_id TEXT NOT NULL,
                    work_assignment_epoch INTEGER NOT NULL, objective TEXT NOT NULL,
                    roots_json TEXT NOT NULL, actions_json TEXT NOT NULL,
                    acceptance_json TEXT NOT NULL, plan_revision INTEGER NOT NULL,
                    manager_node_id TEXT, manager_epoch INTEGER NOT NULL,
                    state TEXT NOT NULL, terminal_summary_json TEXT NOT NULL,
                    wake_receipt_mode TEXT NOT NULL DEFAULT 'LEGACY_RETURN_V1',
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    FOREIGN KEY(work_id) REFERENCES works(work_id),
                    FOREIGN KEY(manager_node_id) REFERENCES nodes(node_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_manager_epochs (
                    session_id TEXT NOT NULL, epoch INTEGER NOT NULL,
                    manager_node_id TEXT NOT NULL, reason TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, started_at REAL NOT NULL,
                    ended_at REAL,
                    PRIMARY KEY(session_id, epoch),
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id),
                    FOREIGN KEY(manager_node_id) REFERENCES nodes(node_id)
                );
                -- A succession is a durable authority transition, not a hint
                -- derived from a Chrome tab.  It prevents an old manager from
                -- regaining authority when its delayed response finally ends.
                CREATE TABLE IF NOT EXISTS orchestration_manager_successions (
                    session_id TEXT NOT NULL, successor_epoch INTEGER NOT NULL,
                    predecessor_node_id TEXT NOT NULL, predecessor_epoch INTEGER NOT NULL,
                    successor_node_id TEXT NOT NULL, state TEXT NOT NULL,
                    close_state TEXT NOT NULL, evidence_json TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY(session_id,successor_epoch),
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id)
                );
                -- The initial context notice is its own one-shot effect.  It
                -- is never inferred from the takeover receipt and UNKNOWN is
                -- terminal: a new Manager must not receive a guessed resend.
                CREATE TABLE IF NOT EXISTS orchestration_manager_handoffs (
                    handoff_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    successor_epoch INTEGER NOT NULL, predecessor_node_id TEXT NOT NULL,
                    successor_node_id TEXT NOT NULL, attachment_id TEXT NOT NULL,
                    attachment_generation INTEGER NOT NULL, instance_id TEXT NOT NULL,
                    external_session_id TEXT NOT NULL, tab_id INTEGER NOT NULL,
                    conversation_key TEXT NOT NULL, relay_role TEXT NOT NULL,
                    binding_receipt_id TEXT NOT NULL, state TEXT NOT NULL,
                    delivery_id TEXT, payload_json TEXT NOT NULL, created_at REAL NOT NULL,
                    updated_at REAL NOT NULL, delivered_at REAL,
                    UNIQUE(session_id,successor_epoch),
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id)
                );
                -- The timer begins only after a current-manager observation.
                -- The raw state observation and the authority decision remain
                -- separate so an unavailable browser can never fabricate a
                -- successful result or a safe tab close.
                CREATE TABLE IF NOT EXISTS orchestration_manager_liveness (
                    session_id TEXT PRIMARY KEY, manager_epoch INTEGER NOT NULL,
                    manager_node_id TEXT NOT NULL, state TEXT NOT NULL,
                    blocked_since REAL, last_observed_at REAL NOT NULL,
                    evidence_json TEXT NOT NULL, updated_at REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_session_nodes (
                    session_id TEXT NOT NULL, node_id TEXT NOT NULL,
                    session_role TEXT NOT NULL, active INTEGER NOT NULL,
                    PRIMARY KEY(session_id,node_id),
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id),
                    FOREIGN KEY(node_id) REFERENCES nodes(node_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_attachments (
                    attachment_id TEXT NOT NULL, generation INTEGER NOT NULL,
                    node_id TEXT NOT NULL, kind TEXT NOT NULL,
                    instance_id TEXT NOT NULL, external_session_id TEXT NOT NULL,
                    tab_id INTEGER NOT NULL, window_id INTEGER NOT NULL,
                    conversation_key TEXT NOT NULL, endpoint TEXT NOT NULL,
                    relay_role TEXT, binding_receipt_id TEXT,
                    active INTEGER NOT NULL, observed_at REAL NOT NULL,
                    PRIMARY KEY(attachment_id, generation),
                    FOREIGN KEY(node_id) REFERENCES nodes(node_id)
                );
                -- One stable extension instance survives same-ID reloads, but
                -- only the most recently observed RCC session may receive new
                -- work.  Attachment rows from older sessions remain as audit
                -- history and are merely made inactive.
                CREATE TABLE IF NOT EXISTS orchestration_rcc_instance_sessions (
                    instance_id TEXT PRIMARY KEY,
                    external_session_id TEXT NOT NULL,
                    observed_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orchestration_assignments (
                    assignment_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    created_manager_epoch INTEGER NOT NULL,
                    request_digest TEXT NOT NULL, request_json TEXT NOT NULL,
                    roots_json TEXT NOT NULL, actions_json TEXT NOT NULL,
                    acceptance_json TEXT NOT NULL, state TEXT NOT NULL,
                    current_generation INTEGER NOT NULL,
                    terminal_result_json TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_dependencies (
                    assignment_id TEXT NOT NULL, depends_on_assignment_id TEXT NOT NULL,
                    PRIMARY KEY(assignment_id, depends_on_assignment_id),
                    FOREIGN KEY(assignment_id) REFERENCES orchestration_assignments(assignment_id),
                    FOREIGN KEY(depends_on_assignment_id) REFERENCES orchestration_assignments(assignment_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_assignment_attempts (
                    assignment_id TEXT NOT NULL, generation INTEGER NOT NULL,
                    manager_epoch INTEGER NOT NULL, worker_node_id TEXT NOT NULL,
                    attachment_id TEXT NOT NULL, attachment_generation INTEGER NOT NULL,
                    state TEXT NOT NULL, dispatch_message_id TEXT,
                    dispatch_operation_id TEXT, created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(assignment_id, generation),
                    FOREIGN KEY(assignment_id) REFERENCES orchestration_assignments(assignment_id),
                    FOREIGN KEY(worker_node_id) REFERENCES nodes(node_id),
                    FOREIGN KEY(attachment_id,attachment_generation)
                        REFERENCES orchestration_attachments(attachment_id,generation)
                );
                CREATE TABLE IF NOT EXISTS orchestration_mailbox (
                    message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    assignment_id TEXT, assignment_generation INTEGER,
                    kind TEXT NOT NULL, sender_node_id TEXT, recipient_node_id TEXT,
                    message_digest TEXT NOT NULL, payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL, delivered_at REAL, consumed_at REAL,
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id),
                    FOREIGN KEY(assignment_id) REFERENCES orchestration_assignments(assignment_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_manager_wakes (
                    event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    manager_epoch INTEGER NOT NULL, assignment_id TEXT NOT NULL,
                    assignment_generation INTEGER NOT NULL,
                    result_message_id TEXT NOT NULL, result_digest TEXT NOT NULL,
                    manager_node_id TEXT, attachment_id TEXT,
                    attachment_generation INTEGER, instance_id TEXT,
                    external_session_id TEXT, tab_id INTEGER,
                    conversation_key TEXT, relay_role TEXT,
                    binding_receipt_id TEXT, state TEXT NOT NULL,
                    delivery_id TEXT, created_at REAL NOT NULL,
                    updated_at REAL NOT NULL, delivered_at REAL,
                    acknowledged_at REAL,
                    envelope_schema INTEGER NOT NULL DEFAULT 1,
                    receipt_mode TEXT NOT NULL DEFAULT 'LEGACY_RETURN_V1',
                    decision_id TEXT,
                    result_hash TEXT,
                    result_ack_state TEXT NOT NULL DEFAULT 'NOT_REQUESTED',
                    result_acknowledged_at REAL,
                    UNIQUE(session_id, assignment_id, assignment_generation,
                           result_message_id, manager_epoch),
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id),
                    FOREIGN KEY(assignment_id) REFERENCES orchestration_assignments(assignment_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_consumption_receipts (
                    session_id TEXT NOT NULL, consumer_assignment_id TEXT NOT NULL,
                    result_message_id TEXT NOT NULL, result_digest TEXT NOT NULL,
                    manager_epoch INTEGER NOT NULL, decision_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(session_id, consumer_assignment_id, result_message_id),
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id),
                    FOREIGN KEY(consumer_assignment_id) REFERENCES orchestration_assignments(assignment_id),
                    FOREIGN KEY(result_message_id) REFERENCES orchestration_mailbox(message_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_consumption_decisions (
                    decision_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    consumer_assignment_id TEXT NOT NULL, manager_epoch INTEGER NOT NULL,
                    request_digest TEXT NOT NULL, decision_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id),
                    FOREIGN KEY(consumer_assignment_id) REFERENCES orchestration_assignments(assignment_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_durable_leases (
                    session_id TEXT PRIMARY KEY REFERENCES orchestration_sessions(session_id),
                    manager_node_id TEXT NOT NULL REFERENCES nodes(node_id),
                    epoch INTEGER NOT NULL, token TEXT NOT NULL,
                    expires_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orchestration_durable_lease_revocations (
                    session_id TEXT NOT NULL REFERENCES orchestration_sessions(session_id),
                    revoked_epoch INTEGER NOT NULL, owner_node_id TEXT NOT NULL,
                    token_digest TEXT NOT NULL, successor_epoch INTEGER NOT NULL,
                    reason TEXT NOT NULL, created_at REAL NOT NULL,
                    PRIMARY KEY(session_id,revoked_epoch)
                );
                CREATE TABLE IF NOT EXISTS orchestration_manager_recovery_leases (
                    lease_name TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    token TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    scan_cursor TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS orchestration_durable_wakes (
                    wake_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES orchestration_sessions(session_id),
                    assignment_id TEXT NOT NULL REFERENCES orchestration_assignments(assignment_id),
                    generation INTEGER NOT NULL, result_message_id TEXT NOT NULL REFERENCES orchestration_mailbox(message_id),
                    result_digest TEXT NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL,
                    UNIQUE(session_id,assignment_id,generation,result_message_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_dispatch_outbox (
                    delivery_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL REFERENCES orchestration_consumption_decisions(decision_id),
                    action_index INTEGER NOT NULL, session_id TEXT NOT NULL REFERENCES orchestration_sessions(session_id),
                    manager_epoch INTEGER NOT NULL, target_node_id TEXT NOT NULL REFERENCES nodes(node_id),
                    attachment_id TEXT NOT NULL, attachment_generation INTEGER NOT NULL,
                    assignment_id TEXT NOT NULL REFERENCES orchestration_assignments(assignment_id),
                    assignment_generation INTEGER NOT NULL, payload_json TEXT NOT NULL,
                    state TEXT NOT NULL, reservation_token TEXT, ack_digest TEXT,
                    created_at REAL NOT NULL, completed_at REAL,
                    UNIQUE(decision_id,action_index),
                    FOREIGN KEY(attachment_id,attachment_generation) REFERENCES orchestration_attachments(attachment_id,generation)
                );
                CREATE TABLE IF NOT EXISTS orchestration_durable_wake_attempts (
                    wake_id TEXT PRIMARY KEY REFERENCES orchestration_durable_wakes(wake_id),
                    epoch INTEGER NOT NULL, token TEXT NOT NULL,
                    state TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orchestration_dispatch_attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    delivery_id TEXT NOT NULL REFERENCES orchestration_dispatch_outbox(delivery_id),
                    phase TEXT NOT NULL, epoch INTEGER NOT NULL, created_at REAL NOT NULL
                );
                -- Routing is deliberately separate from the delivery receipt.
                -- It describes a pre-write scheduling decision only; it cannot
                -- make an applied or unknown delivery eligible for re-send.
                CREATE TABLE IF NOT EXISTS orchestration_dispatch_routes (
                    delivery_id TEXT PRIMARY KEY REFERENCES orchestration_dispatch_outbox(delivery_id),
                    routing_json TEXT NOT NULL, state TEXT NOT NULL,
                    detail_json TEXT NOT NULL, created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orchestration_reconciliations (
                    decision_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    assignment_id TEXT NOT NULL, generation INTEGER NOT NULL,
                    manager_epoch INTEGER NOT NULL, decision TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, created_at REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES orchestration_sessions(session_id),
                    FOREIGN KEY(assignment_id) REFERENCES orchestration_assignments(assignment_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS orchestration_attachment_active_role
                    ON orchestration_attachments(instance_id,relay_role)
                    WHERE active=1 AND relay_role IS NOT NULL AND relay_role!='';
                CREATE INDEX IF NOT EXISTS orchestration_attachment_conversation
                    ON orchestration_attachments(instance_id,conversation_key,active);
                CREATE UNIQUE INDEX IF NOT EXISTS orchestration_attachment_current_slot
                    ON orchestration_attachments(instance_id,tab_id)
                    WHERE active=1;
                CREATE UNIQUE INDEX IF NOT EXISTS orchestration_attempt_dispatch
                    ON orchestration_assignment_attempts(dispatch_operation_id)
                    WHERE dispatch_operation_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS orchestration_manager_wakes_pending
                    ON orchestration_manager_wakes(session_id,manager_epoch,state,created_at);
                """
            )
            conversation_columns = {
                row["name"] for row in db.execute(
                    "PRAGMA table_info(conversation_network_conversations)"
                ).fetchall()
            }
            if "display_order" not in conversation_columns:
                db.execute(
                    "ALTER TABLE conversation_network_conversations ADD COLUMN "
                    "display_order INTEGER NOT NULL DEFAULT 0"
                )
            inbox_recipient_columns = {
                row["name"] for row in db.execute(
                    "PRAGMA table_info(github_run_inbox_recipients)"
                ).fetchall()
            }
            if "next_step" not in inbox_recipient_columns:
                db.execute(
                    "ALTER TABLE github_run_inbox_recipients ADD COLUMN "
                    "next_step TEXT NOT NULL DEFAULT ''"
                )
            wake_columns = {
                row["name"] for row in db.execute(
                    "PRAGMA table_info(orchestration_manager_wakes)"
                ).fetchall()
            }
            if "envelope_schema" not in wake_columns:
                db.execute(
                    "ALTER TABLE orchestration_manager_wakes ADD COLUMN "
                    "envelope_schema INTEGER NOT NULL DEFAULT 1"
                )
            if "receipt_mode" not in wake_columns:
                db.execute(
                    "ALTER TABLE orchestration_manager_wakes ADD COLUMN "
                    "receipt_mode TEXT NOT NULL DEFAULT 'LEGACY_RETURN_V1'"
                )
            if "decision_id" not in wake_columns:
                db.execute(
                    "ALTER TABLE orchestration_manager_wakes ADD COLUMN decision_id TEXT"
                )
            if "result_hash" not in wake_columns:
                db.execute(
                    "ALTER TABLE orchestration_manager_wakes ADD COLUMN result_hash TEXT"
                )
            if "result_ack_state" not in wake_columns:
                db.execute(
                    "ALTER TABLE orchestration_manager_wakes ADD COLUMN "
                    "result_ack_state TEXT NOT NULL DEFAULT 'NOT_REQUESTED'"
                )
            if "result_acknowledged_at" not in wake_columns:
                db.execute(
                    "ALTER TABLE orchestration_manager_wakes ADD COLUMN "
                    "result_acknowledged_at REAL"
                )
            session_columns = {
                row["name"] for row in db.execute(
                    "PRAGMA table_info(orchestration_sessions)"
                ).fetchall()
            }
            if "wake_receipt_mode" not in session_columns:
                # Existing sessions are deliberately pinned to the legacy path.
                # Enabling trusted collaboration must never reinterpret an old
                # session or wake after a restart.
                db.execute(
                    "ALTER TABLE orchestration_sessions ADD COLUMN "
                    "wake_receipt_mode TEXT NOT NULL DEFAULT 'LEGACY_RETURN_V1'"
                )
            recovery_columns = {
                row["name"] for row in db.execute(
                    "PRAGMA table_info(orchestration_manager_recovery_leases)"
                ).fetchall()
            }
            if "scan_cursor" not in recovery_columns:
                db.execute(
                    "ALTER TABLE orchestration_manager_recovery_leases ADD COLUMN "
                    "scan_cursor TEXT NOT NULL DEFAULT ''"
                )


    def set_node_label_notifier(self, callback) -> None:
        # The callback schedules an in-memory wake. It must not dispatch IO.
        self._node_label_notifier = callback

    def record_node_label_assignment(self, db, conversation_key: str, node_number: int) -> int:
        if not conversation_key or node_number <= 0:
            raise ValueError("NODE_LABEL_EVENT_IDENTITY_INVALID")
        cursor = db.execute(
            "INSERT INTO events(kind,subject_id,data_json,created_at) VALUES(?,?,?,?)",
            ("NODE_LABEL_ASSIGNED", conversation_key,
             json.dumps({"node_label": f"N{node_number}"}, sort_keys=True), time.time()),
        )
        event_id = int(cursor.lastrowid)
        db.execute(
            "INSERT INTO node_label_notification_outbox(event_id,conversation_key,node_number,status,created_at) "
            "VALUES(?,?,?,'PENDING',?)",
            (event_id, conversation_key, node_number, time.time()),
        )
        return event_id

    def emit_node_label_notification(self, event_id: int) -> None:
        # Always invoked after a successful COMMIT. Wake failures leave PENDING durable.
        notifier = self._node_label_notifier
        if notifier is not None:
            try:
                notifier(event_id)
            except Exception:
                pass

    def pending_node_label_notifications(self, *, limit: int = 256,
                                         conversation_keys=None) -> list[dict]:
        limit = max(1, min(int(limit), 2048))
        keys = list(dict.fromkeys(str(key).lower() for key in (conversation_keys or [])))
        with self.transaction() as db:
            if conversation_keys is not None:
                if not keys:
                    return []
                placeholders = ",".join("?" for _ in keys)
                rows = db.execute(
                    f"SELECT * FROM node_label_notification_outbox WHERE status='PENDING' "
                    f"AND conversation_key IN ({placeholders}) ORDER BY event_id LIMIT ?",
                    (*keys,limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM node_label_notification_outbox WHERE status='PENDING' "
                    "ORDER BY event_id LIMIT ?", (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def wake_node_label_notifications(self, conversation_keys, *, topology) -> None:
        # Existing Monitor observations trigger only on a changed exact RCC
        # tab/session roster, never on each /monitor/state GET. No new polling.
        fingerprint = tuple(sorted(topology))
        with self._lock:
            if fingerprint == self._node_label_last_topology:
                return
            self._node_label_last_topology = fingerprint
        for record in self.pending_node_label_notifications(conversation_keys=conversation_keys):
            self.emit_node_label_notification(int(record["event_id"]))

    def node_label_notification(self, event_id: int) -> dict | None:
        with self.transaction() as db:
            row = db.execute(
                "SELECT o.*,e.kind FROM node_label_notification_outbox o "
                "JOIN events e ON e.event_id=o.event_id WHERE o.event_id=?", (int(event_id),)
            ).fetchone()
            if row is None or row["kind"] != "NODE_LABEL_ASSIGNED":
                return None
            current = db.execute(
                "SELECT node_number FROM conversation_network_node_labels "
                "WHERE conversation_key=?", (row["conversation_key"],)
            ).fetchone()
            if current is None or int(current["node_number"]) != int(row["node_number"]):
                return None
        return dict(row)

    def claim_node_label_notification(self, event_id: int, operation_id: str) -> bool:
        with self.transaction() as db:
            result = db.execute(
                "UPDATE node_label_notification_outbox SET status='STARTED',operation_id=? "
                "WHERE event_id=? AND status='PENDING'",
                (operation_id,int(event_id)),
            )
            return result.rowcount == 1

    def finish_node_label_notification(self, event_id: int, status: str) -> None:
        if status not in {"ACKED","NOT_APPLIED","UNKNOWN"}:
            raise ValueError("NODE_LABEL_NOTIFY_STATUS_INVALID")
        with self.transaction() as db:
            db.execute(
                "UPDATE node_label_notification_outbox SET status=? "
                "WHERE event_id=? AND status='STARTED'",
                (status,int(event_id)),
            )

    @staticmethod
    def _event(db: sqlite3.Connection, kind: str, subject_id: str, data: dict[str, Any]) -> None:
        db.execute(
            "INSERT INTO events(kind,subject_id,data_json,created_at) VALUES(?,?,?,?)",
            (kind, subject_id, json.dumps(data, sort_keys=True), time.time()),
        )

    def create_node(self, *, node_id: str, name: str, role: str | None = None,
                    group: str | None = None) -> dict[str, Any]:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO nodes(node_id,name,role,group_name,revision,active) VALUES(?,?,?,?,1,1)",
                (node_id, name, role, group),
            )
            self._event(db, "NODE_CREATED", node_id, {"name": name, "role": role, "group": group})
        return self.get_node(node_id)

    def get_node(self, node_id: str) -> dict[str, Any]:
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("NODE_NOT_FOUND")
        return {"node_id": row["node_id"], "name": row["name"], "role": row["role"],
                "group": row["group_name"], "revision": row["revision"], "active": bool(row["active"])}

    def update_node(self, *, node_id: str, expected_revision: int,
                    name: str | None = None, role: str | None = None,
                    group: str | None = None, active: bool | None = None) -> dict[str, Any]:
        current = self.get_node(node_id)
        values = {
            "name": current["name"] if name is None else name,
            "role": current["role"] if role is None else role,
            "group": current["group"] if group is None else group,
            "active": current["active"] if active is None else active,
        }
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE nodes SET name=?,role=?,group_name=?,active=?,revision=revision+1 "
                "WHERE node_id=? AND revision=?",
                (values["name"], values["role"], values["group"], int(values["active"]), node_id, expected_revision),
            ).rowcount
            if changed != 1:
                raise ConflictError("NODE_REVISION_MISMATCH")
            self._event(db, "NODE_UPDATED", node_id, values)
        return self.get_node(node_id)

    def replace_connection(self, *, connection_id: str, node_id: str, kind: str,
                           instance: str, endpoint: str, expected_generation: int | None) -> dict[str, Any]:
        with self.transaction() as db:
            node = db.execute("SELECT active FROM nodes WHERE node_id=?", (node_id,)).fetchone()
            if node is None or not node["active"]:
                raise ConflictError("NODE_NOT_ACTIVE")
            current = db.execute("SELECT * FROM connections WHERE connection_id=?", (connection_id,)).fetchone()
            if current is None:
                if expected_generation not in {None, 0}:
                    raise ConflictError("CONNECTION_GENERATION_MISMATCH")
                generation = 1
                db.execute(
                    "INSERT INTO connections(connection_id,node_id,kind,instance,endpoint,generation,active) "
                    "VALUES(?,?,?,?,?,?,1)",
                    (connection_id, node_id, kind, instance, endpoint, generation),
                )
            else:
                if current["node_id"] != node_id or expected_generation != current["generation"]:
                    raise ConflictError("CONNECTION_GENERATION_MISMATCH")
                generation = current["generation"] + 1
                db.execute(
                    "UPDATE connections SET kind=?,instance=?,endpoint=?,generation=?,active=1 WHERE connection_id=?",
                    (kind, instance, endpoint, generation, connection_id),
                )
            self._event(db, "CONNECTION_REPLACED", connection_id, {"node_id": node_id, "generation": generation})
        return self.get_connection(connection_id)

    def get_connection(self, connection_id: str) -> dict[str, Any]:
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM connections WHERE connection_id=?", (connection_id,)).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("CONNECTION_NOT_FOUND")
        return dict(row)

    def create_work(self, work: Work) -> Work:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO works VALUES(?,?,?,?,?,?,?)",
                (work.work_id, work.request_summary, json.dumps(work.roots), json.dumps(sorted(work.actions)),
                 work.owner_principal_id, work.assignment_epoch, work.state),
            )
            self._event(db, "WORK_CREATED", work.work_id, {"owner": work.owner_principal_id})
        return work

    def get_work(self, work_id: str) -> Work:
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("WORK_NOT_FOUND")
        return Work(row["work_id"], row["request_summary"], tuple(json.loads(row["roots_json"])),
                    frozenset(json.loads(row["actions_json"])), row["owner_principal_id"],
                    row["assignment_epoch"], row["state"])

    def active_rcc_attachment_for_node(
        self, *, work_id: str, orchestration_session_id: str, node_id: str,
        instance_id: str,
    ) -> dict[str, Any]:
        """Return exactly one current RCC binding for a self-directed send.

        A node name alone is intentionally insufficient: the durable session
        and active attachment fence prevent a same-named old tab becoming a
        "self" target after a handoff or reconnect.
        """
        db = self._connect()
        try:
            session = db.execute(
                "SELECT work_id FROM orchestration_sessions WHERE session_id=?",
                (orchestration_session_id,),
            ).fetchone()
            if session is None or session["work_id"] != work_id:
                raise ConflictError("RCC_SELF_SESSION_ACCESS_DENIED")
            rows = db.execute(
                "SELECT a.* FROM orchestration_attachments a "
                "JOIN orchestration_session_nodes sn ON sn.node_id=a.node_id "
                "WHERE sn.session_id=? AND sn.active=1 AND a.active=1 "
                "AND a.node_id=? AND a.kind='rcc' AND a.instance_id=? "
                "ORDER BY a.generation DESC",
                (orchestration_session_id, node_id, instance_id),
            ).fetchall()
            if not rows:
                raise KeyError("RCC_SELF_ATTACHMENT_NOT_FOUND")
            if len(rows) != 1:
                raise ConflictError("RCC_SELF_ATTACHMENT_AMBIGUOUS")
            return dict(rows[0])
        finally:
            db.close()

    @staticmethod
    def _continuation_public(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        value = dict(row)
        return {
            key: value[key] for key in (
                "continuation_id", "work_id", "orchestration_session_id", "node_id",
                "attachment_id", "attachment_generation", "instance_id",
                "external_session_id", "tab_id", "window_id", "conversation_key",
                "max_self_turns", "used_self_turns", "deadline_at", "state",
                "reserved_operation_id", "created_at", "updated_at",
            )
        }

    def reserve_node_continuation(
        self, *, continuation_id: str, work_id: str, orchestration_session_id: str,
        node_id: str, attachment: dict[str, Any], max_self_turns: int,
        deadline_at: float, phase: str, operation_id: str,
    ) -> dict[str, Any]:
        """Reserve exactly one initial or B->B continuation transmission.

        Reservation occurs before the browser effect.  A crash or unknown
        effect therefore leaves the continuation fenced rather than allowing a
        second self prompt to be silently sent.
        """
        now = time.time()
        if phase not in {"open", "continue"}:
            raise ValueError("NODE_CONTINUATION_PHASE_INVALID")
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM node_continuations WHERE continuation_id=?",
                (continuation_id,),
            ).fetchone()
            identity = {
                "work_id": work_id,
                "orchestration_session_id": orchestration_session_id,
                "node_id": node_id,
                "attachment_id": str(attachment["attachment_id"]),
                "attachment_generation": int(attachment["generation"]),
                "instance_id": str(attachment["instance_id"]),
                "external_session_id": str(attachment["external_session_id"]),
                "tab_id": int(attachment["tab_id"]),
                "window_id": int(attachment["window_id"]),
                "conversation_key": str(attachment["conversation_key"]),
            }
            if phase == "open":
                if row is not None:
                    raise ConflictError("NODE_CONTINUATION_ID_REUSE")
                db.execute(
                    "INSERT INTO node_continuations(continuation_id,work_id,orchestration_session_id,"
                    "node_id,attachment_id,attachment_generation,instance_id,external_session_id,"
                    "tab_id,window_id,conversation_key,max_self_turns,used_self_turns,deadline_at,"
                    "state,reserved_operation_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (continuation_id, work_id, orchestration_session_id, node_id,
                     identity["attachment_id"], identity["attachment_generation"],
                     identity["instance_id"], identity["external_session_id"],
                     identity["tab_id"], identity["window_id"], identity["conversation_key"],
                     max_self_turns, 0, deadline_at, "RESERVED", operation_id, now, now),
                )
            else:
                if row is None:
                    raise KeyError("NODE_CONTINUATION_NOT_FOUND")
                for key, expected in identity.items():
                    if row[key] != expected:
                        raise ConflictError("NODE_CONTINUATION_TARGET_CHANGED")
                if row["state"] != "ACTIVE":
                    raise ConflictError("NODE_CONTINUATION_NOT_ACTIVE:" + str(row["state"]))
                if now >= float(row["deadline_at"]):
                    db.execute("UPDATE node_continuations SET state='EXPIRED',updated_at=? WHERE continuation_id=?",
                               (now, continuation_id))
                    raise ConflictError("NODE_CONTINUATION_DEADLINE_EXPIRED")
                if int(row["used_self_turns"]) >= int(row["max_self_turns"]):
                    db.execute("UPDATE node_continuations SET state='BUDGET_EXHAUSTED',updated_at=? WHERE continuation_id=?",
                               (now, continuation_id))
                    raise ConflictError("NODE_CONTINUATION_BUDGET_EXHAUSTED")
                db.execute(
                    "UPDATE node_continuations SET state='RESERVED',reserved_operation_id=?,updated_at=? "
                    "WHERE continuation_id=?",
                    (operation_id, now, continuation_id),
                )
            saved = db.execute("SELECT * FROM node_continuations WHERE continuation_id=?", (continuation_id,)).fetchone()
            return self._continuation_public(saved)

    def finish_node_continuation(
        self, *, continuation_id: str, operation_id: str, phase: str,
        outcome: Outcome,
    ) -> dict[str, Any]:
        now = time.time()
        with self.transaction() as db:
            row = db.execute("SELECT * FROM node_continuations WHERE continuation_id=?", (continuation_id,)).fetchone()
            if row is None or row["state"] != "RESERVED" or row["reserved_operation_id"] != operation_id:
                raise ConflictError("NODE_CONTINUATION_RESERVATION_LOST")
            if outcome == Outcome.UNKNOWN:
                state = "UNKNOWN"
                used = int(row["used_self_turns"])
            elif outcome == Outcome.APPLIED:
                used = int(row["used_self_turns"]) + (1 if phase == "continue" else 0)
                state = "BUDGET_EXHAUSTED" if used >= int(row["max_self_turns"]) else "ACTIVE"
            else:
                state = "ACTIVE"
                used = int(row["used_self_turns"])
            db.execute(
                "UPDATE node_continuations SET state=?,used_self_turns=?,reserved_operation_id=NULL,updated_at=? "
                "WHERE continuation_id=?",
                (state, used, now, continuation_id),
            )
            saved = db.execute("SELECT * FROM node_continuations WHERE continuation_id=?", (continuation_id,)).fetchone()
            return self._continuation_public(saved)

    def close_node_continuation(self, *, continuation_id: str, work_id: str) -> dict[str, Any]:
        now = time.time()
        with self.transaction() as db:
            row = db.execute("SELECT * FROM node_continuations WHERE continuation_id=? AND work_id=?",
                             (continuation_id, work_id)).fetchone()
            if row is None:
                raise KeyError("NODE_CONTINUATION_NOT_FOUND")
            if row["state"] == "RESERVED":
                raise ConflictError("NODE_CONTINUATION_EFFECT_PENDING")
            if row["state"] not in {"UNKNOWN", "CLOSED"}:
                db.execute("UPDATE node_continuations SET state='CLOSED',updated_at=? WHERE continuation_id=?",
                           (now, continuation_id))
                row = db.execute("SELECT * FROM node_continuations WHERE continuation_id=?", (continuation_id,)).fetchone()
            return self._continuation_public(row)

    def register_github_run_inbox(self, *, subscription_id: str, repository: str, run_id: int,
                                  head_sha: str, workflow: str, context: dict[str, Any],
                                  work_id: str, node_id: str, conversation_uuid: str | None,
                                  notify_user: bool, notify_manager: bool, next_step: str,
                                  trigger: str | None = None) -> tuple[dict[str, Any], bool]:
        """Durably merge an exact run subscription without acquiring a Work claim."""
        now = time.time()
        with self.transaction() as db:
            row = db.execute("SELECT * FROM github_run_inbox WHERE repository=? AND run_id=? AND head_sha=?",
                             (repository, run_id, head_sha)).fetchone()
            created = row is None
            if created:
                db.execute("INSERT INTO github_run_inbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    subscription_id, repository, run_id, head_sha, workflow, json.dumps(context, sort_keys=True),
                    None, "WAITING_EXTERNAL", None, None, next_step, trigger or f"github-run:{run_id}:terminal", now, now, None))
            else:
                subscription_id = str(row["subscription_id"])
            terminal = row is not None and str(row["state"]) != "WAITING_EXTERNAL"
            db.execute("INSERT INTO github_run_inbox_recipients(subscription_id,work_id,node_id,conversation_uuid,notify_user,notify_manager,unread,next_step) "
                       "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(subscription_id,work_id,node_id) DO UPDATE SET "
                       "notify_user=MAX(notify_user,excluded.notify_user),notify_manager=MAX(notify_manager,excluded.notify_manager),"
                       "next_step=excluded.next_step,unread=CASE WHEN (SELECT state FROM github_run_inbox WHERE subscription_id=excluded.subscription_id)='WAITING_EXTERNAL' THEN github_run_inbox_recipients.unread ELSE 1 END",
                       (subscription_id, work_id, node_id, conversation_uuid, int(notify_user), int(notify_manager), int(terminal), next_step))
            result = db.execute("SELECT * FROM github_run_inbox WHERE subscription_id=?", (subscription_id,)).fetchone()
        return self._github_inbox_row(result), created

    def finish_github_run_inbox(self, *, subscription_id: str, state: str, conclusion: str | None,
                                url: str | None, error_summary: str | None) -> dict[str, Any]:
        if state not in {"SUCCESS", "FAILED", "CANCELLED", "TIMED_OUT"}:
            raise ValueError("GITHUB_INBOX_STATE_INVALID")
        now = time.time()
        with self.transaction() as db:
            changed = db.execute("UPDATE github_run_inbox SET state=?,conclusion=?,url=?,error_summary=?,updated_at=?,terminal_at=? "
                                 "WHERE subscription_id=? AND state='WAITING_EXTERNAL'", (state, conclusion, url, error_summary, now, now, subscription_id)).rowcount
            if changed:
                db.execute("UPDATE github_run_inbox_recipients SET unread=1 WHERE subscription_id=?", (subscription_id,))
            row = db.execute("SELECT * FROM github_run_inbox WHERE subscription_id=?", (subscription_id,)).fetchone()
        if row is None: raise KeyError("GITHUB_INBOX_NOT_FOUND")
        return self._github_inbox_row(row)

    def get_github_run_inbox(self, *, node_id: str | None = None, work_id: str | None = None,
                             acknowledge: bool = False, limit: int = 80) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 80))
        clauses, values = [], []
        if node_id: clauses.append("r.node_id=?"); values.append(node_id)
        if work_id: clauses.append("r.work_id=?"); values.append(work_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.transaction() if acknowledge else self._readonly() as db:
            rows = db.execute("SELECT i.*,r.work_id,r.node_id,r.conversation_uuid,r.notify_user,r.notify_manager,r.unread,r.delivery_state,r.next_step AS recipient_next_step "
                              "FROM github_run_inbox i JOIN github_run_inbox_recipients r ON r.subscription_id=i.subscription_id" + where +
                              " ORDER BY i.updated_at DESC LIMIT ?", (*values, limit)).fetchall()
            if acknowledge and rows:
                db.executemany("UPDATE github_run_inbox_recipients SET unread=0 WHERE subscription_id=? AND work_id=? AND node_id=? AND subscription_id IN (SELECT subscription_id FROM github_run_inbox WHERE state!='WAITING_EXTERNAL')",
                               [(r["subscription_id"], r["work_id"], r["node_id"]) for r in rows])
        return [self._github_inbox_row(row) for row in rows]

    @contextmanager
    def _readonly(self):
        db = self._connect()
        try: yield db
        finally: db.close()

    @staticmethod
    def _github_inbox_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row); value["context"] = json.loads(value.pop("context_json"));
        if "recipient_next_step" in value:
            value["next_step"] = value.pop("recipient_next_step")
        for key in ("notify_user", "notify_manager", "unread"):
            if key in value: value[key] = bool(value[key])
        value["next_step_advisory_only"] = True
        return value

    def monitor_snapshot(self, *, event_limit: int = 50) -> dict[str, Any]:
        """Return a bounded, read-only projection for the local BCT monitor."""
        limit = max(1, min(int(event_limit), 200))
        db = self._connect()
        try:
            nodes = [dict(row) for row in db.execute(
                "SELECT node_id,name,role,group_name,revision,active FROM nodes ORDER BY node_id"
            ).fetchall()]
            connections = [dict(row) for row in db.execute(
                "SELECT connection_id,node_id,kind,instance,endpoint,generation,active "
                "FROM connections ORDER BY connection_id"
            ).fetchall()]
            works = [dict(row) for row in db.execute(
                "SELECT work_id,request_summary,owner_principal_id,assignment_epoch,state "
                "FROM works ORDER BY rowid DESC LIMIT 100"
            ).fetchall()]
            operations = [dict(row) for row in db.execute(
                "SELECT operation_id,work_id,capability,target,state,outcome,created_at,updated_at "
                "FROM operations ORDER BY updated_at DESC LIMIT 100"
            ).fetchall()]
            claims = [dict(row) for row in db.execute(
                "SELECT resource_key,operation_id,work_id,assignment_epoch "
                "FROM resource_claims WHERE unresolved=1 ORDER BY resource_key"
            ).fetchall()]
            events = [dict(row) for row in db.execute(
                "SELECT event_id,kind,subject_id,created_at FROM events "
                "ORDER BY event_id DESC LIMIT ?", (limit,)
            ).fetchall()]
            orchestration_sessions = [dict(row) for row in db.execute(
                "SELECT session_id,work_id,manager_node_id,manager_epoch,state,plan_revision,updated_at "
                "FROM orchestration_sessions ORDER BY updated_at DESC LIMIT 50"
            ).fetchall()]
            orchestration_assignments = [dict(row) for row in db.execute(
                "SELECT assignment_id,session_id,created_manager_epoch,state,current_generation,updated_at "
                "FROM orchestration_assignments ORDER BY updated_at DESC LIMIT 100"
            ).fetchall()]
            inbox = [self._github_inbox_row(row) for row in db.execute(
                "SELECT i.*,r.work_id,r.node_id,r.conversation_uuid,r.notify_user,r.notify_manager,r.unread,r.delivery_state,r.next_step AS recipient_next_step "
                "FROM github_run_inbox i JOIN github_run_inbox_recipients r ON r.subscription_id=i.subscription_id "
                "ORDER BY i.updated_at DESC LIMIT 80").fetchall()]
        finally:
            db.close()
        for node in nodes:
            node["active"] = bool(node["active"])
            node["group"] = node.pop("group_name")
        for connection in connections:
            connection["active"] = bool(connection["active"])
        return {
            "nodes": nodes,
            "connections": connections,
            "works": works,
            "operations": operations,
            "unresolved_claims": claims,
            "events": events,
            "orchestration_sessions": orchestration_sessions,
            "orchestration_assignments": orchestration_assignments,
            "github_run_inbox": inbox,
        }

    def claim_diagnostics(self) -> list[dict[str, Any]]:
        """Read-only, unbounded-by-recent-operations claim provenance projection.

        Never infer process liveness or safe claim release from a stale record.
        Excludes payloads, prompts, credentials, command lines and file contents.
        """
        db = self._connect()
        try:
            rows = db.execute(
                "SELECT c.resource_key,c.operation_id,c.work_id,c.assignment_epoch,"
                "o.capability,o.target,o.state AS operation_state,o.outcome,"
                "o.created_at,o.updated_at,o.error,"
                "x.pid AS executor_pid,x.claimed_at AS executor_claimed_at,"
                "x.fingerprint AS executor_fingerprint,"
                "e.kind AS latest_event_kind,e.created_at AS latest_event_at,"
                "j.stage AS effect_stage,j.created_at AS effect_stage_at "
                "FROM resource_claims c "
                "LEFT JOIN operations o ON o.operation_id=c.operation_id "
                "AND o.work_id=c.work_id "
                "AND o.assignment_epoch=c.assignment_epoch "
                "LEFT JOIN background_job_executors x ON x.operation_id=o.operation_id "
                "LEFT JOIN events e ON e.event_id=("
                "SELECT MAX(ev.event_id) FROM events ev "
                "WHERE ev.subject_id=o.operation_id "
                "AND ev.kind IN ("
                "'OPERATION_STARTED','OPERATION_FINISHED','OPERATION_RECONCILED',"
                "'OPERATION_STEPS_INITIALIZED','OPERATION_STEP_STARTED',"
                "'OPERATION_STEP_FINISHED','OPERATION_STEP_SKIPPED')) "
                "LEFT JOIN operation_effect_stages j ON j.sequence=("
                "SELECT MAX(js.sequence) FROM operation_effect_stages js "
                "WHERE js.operation_id=o.operation_id) AND j.operation_id=o.operation_id "
                "WHERE c.unresolved=1 ORDER BY c.resource_key"
            ).fetchall()
        finally:
            db.close()
        output = []
        for row in rows:
            state, outcome = row["operation_state"], row["outcome"]
            detail = _claim_unknown_detail(row["error"], outcome, row["capability"])
            identity_status, identity_verified = _claim_executor_identity(
                row["executor_pid"], row["executor_fingerprint"])
            # Claims are observational metadata. Preserve UNKNOWN as the
            # historical outcome, but never project it as execution ownership.
            if outcome == "UNKNOWN":
                diagnosis = "UNKNOWN_EFFECT"
            elif state == "FINISHED":
                diagnosis = "FINISHED_CLAIMED"
            else:
                diagnosis = "INSUFFICIENT_EVIDENCE"
            resource_key = str(row["resource_key"] or "")
            exact_scope = (
                resource_key.startswith("orchestration-attachment:")
                or resource_key.startswith("orchestration-run:")
                or resource_key.startswith("execution:")
                or ":rename:" in resource_key
                or ":direct-tab:" in resource_key
                or ":read:" in resource_key
            )
            scope = "EXACT_RESOURCE" if exact_scope else "SHARED_RESOURCE"
            terminal_operation = state == "FINISHED"
            output.append({
                "resource_key": resource_key,
                "operation_id": row["operation_id"],
                "work_id": row["work_id"],
                "assignment_epoch": row["assignment_epoch"],
                "capability": row["capability"],
                "operation_state": state,
                "outcome": outcome,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "executor": None if row["executor_pid"] is None else {
                    "pid": row["executor_pid"],
                    "claimed_at": row["executor_claimed_at"],
                    "fingerprint_present": bool(row["executor_fingerprint"]),
                    "identity_verified": identity_verified,
                    "identity_status": identity_status,
                },
                "effect_detail": detail,
                "last_event": None if row["latest_event_kind"] is None else {
                    "kind": row["latest_event_kind"],
                    "at": row["latest_event_at"],
                },
                "effect_stage": None if row["effect_stage"] is None else {
                    "stage": row["effect_stage"], "at": row["effect_stage_at"],
                },
                "diagnosis": diagnosis,
                "scope": scope,
                "blocks_unrelated_work": False,
                "blocks_same_resource": False,
                "requires_live_state_check": False,
                # Kept as a read-compatible status field. Every claim is
                # replaced by a later measurement without a retirement gate.
                "retires_on_next_reservation": terminal_operation,
                "replay_allowed": False if outcome == "UNKNOWN" else None,
                # Kept for compatibility: the diagnostics/read path itself
                # never mutates claims.
                "can_auto_release": False,
            })
        return output

    def handoff_work(self, *, work_id: str, old_principal_id: str, new_principal_id: str,
                     expected_epoch: int) -> Work:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
            if row is None:
                raise KeyError("WORK_NOT_FOUND")
            if row["owner_principal_id"] != old_principal_id or row["assignment_epoch"] != expected_epoch:
                raise ConflictError("WORK_HANDOFF_FENCE_MISMATCH")
            # Claims are measurements, not work ownership. Handoff fencing is
            # based only on the Work epoch and actual nonterminal operations.
            running = db.execute(
                "SELECT COUNT(*) FROM operations WHERE work_id=? AND state!=?",
                (work_id, OperationState.FINISHED.value),
            ).fetchone()[0]
            if running:
                raise ConflictError("WORK_HAS_ACTIVE_OPERATION")
            db.execute(
                "UPDATE works SET owner_principal_id=?,assignment_epoch=assignment_epoch+1 WHERE work_id=?",
                (new_principal_id, work_id),
            )
            self._event(db, "WORK_HANDED_OFF", work_id, {"old": old_principal_id, "new": new_principal_id})
        return self.get_work(work_id)

    def begin_operation(self, *, operation_id: str, work: Work, principal_id: str,
                        request_digest: str, capability: str, target: str,
                        resources: tuple[str, ...], policy_revision: str,
                        background_job: dict[str, Any] | None = None,
                        ) -> tuple[bool, OperationResult]:
        now = time.time()
        with self.transaction() as db:
            current = db.execute("SELECT * FROM works WHERE work_id=?", (work.work_id,)).fetchone()
            if current is None or current["owner_principal_id"] != principal_id or current["assignment_epoch"] != work.assignment_epoch:
                raise ConflictError("WORK_ASSIGNMENT_CHANGED")
            existing = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            if existing is not None:
                if existing["work_id"] != work.work_id:
                    raise ConflictError("OPERATION_RESULT_ACCESS_DENIED")
                if existing["request_digest"] != request_digest:
                    raise ConflictError("OPERATION_ID_REQUEST_MISMATCH")
                if background_job is not None:
                    self._record_background_job(
                        db, operation_id=operation_id, job=background_job,
                        operation_created_at=float(existing["created_at"]),
                    )
                return False, self._row_result(existing, duplicate=True)
            db.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (operation_id, work.work_id, principal_id, request_digest, capability, target,
                 OperationState.RECORDED.value, None, "{}", None, work.assignment_epoch,
                 policy_revision, now, now),
            )
            for resource in sorted(set(resources)):
                # A Claim is an observational sample for this resource, never
                # an execution lock. A newer independent operation replaces the
                # current sample regardless of its Work, outcome, or resource
                # family. Operation identity and feature-specific leases remain
                # the only idempotency and live-control boundaries.
                db.execute(
                    "INSERT OR REPLACE INTO resource_claims VALUES(?,?,?,?,1)",
                    (resource, operation_id, work.work_id, work.assignment_epoch),
                )
            db.execute("UPDATE operations SET state=?,updated_at=? WHERE operation_id=?",
                       (OperationState.RUNNING.value, now, operation_id))
            if background_job is not None:
                self._record_background_job(
                    db, operation_id=operation_id, job=background_job,
                    operation_created_at=now,
                )
            self._event(db, "OPERATION_STARTED", operation_id, {"capability": capability, "resources": resources})
            self._append_effect_stage(db, operation_id=operation_id,
                                      stage="CLAIM_RESERVED", detail={})
            row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            return True, self._row_result(row)

    def _record_background_job(
        self, db, *, operation_id: str, job: dict[str, Any],
        operation_created_at: float,
    ) -> None:
        value = dict(job)
        delay = float(value.pop("_not_before_delay", 0.0))
        value["created_at"] = operation_created_at
        value["not_before"] = operation_created_at + max(0.0, delay)
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
        existing = db.execute(
            "SELECT job_json FROM background_jobs WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            db.execute(
                "INSERT INTO background_jobs VALUES(?,?,?)",
                (operation_id, payload, operation_created_at),
            )
        else:
            prior = json.loads(existing["job_json"])
            for key in ("operation_id", "work_id", "capability"):
                if str(prior.get(key) or "") != str(value.get(key) or ""):
                    raise ConflictError("BACKGROUND_JOB_REQUEST_MISMATCH")
            if str((prior.get("principal") or {}).get("principal_id") or "") != str(
                (value.get("principal") or {}).get("principal_id") or ""
            ):
                raise ConflictError("BACKGROUND_JOB_REQUEST_MISMATCH")

    def acquire_background_executor(
        self, *, operation_id: str, pid: int, fingerprint: str,
    ) -> bool:
        with self.transaction() as db:
            operation = db.execute(
                "SELECT state FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            job = db.execute(
                "SELECT 1 FROM background_jobs WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if operation is None or job is None \
                    or operation["state"] != OperationState.RUNNING.value:
                return False
            current = db.execute(
                "SELECT * FROM background_job_executors WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if current is not None:
                return current["fingerprint"] == fingerprint and current["pid"] == pid
            db.execute(
                "INSERT INTO background_job_executors VALUES(?,?,?,?)",
                (operation_id, pid, fingerprint, time.time()),
            )
            return True

    def background_executor(self, operation_id: str) -> dict[str, Any] | None:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT * FROM background_job_executors WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            return None if row is None else dict(row)
        finally:
            db.close()

    def clear_background_executor(
        self, *, operation_id: str, fingerprint: str,
    ) -> bool:
        with self.transaction() as db:
            cursor = db.execute(
                "DELETE FROM background_job_executors WHERE operation_id=? "
                "AND fingerprint=?",
                (operation_id, fingerprint),
            )
            return cursor.rowcount == 1

    def running_background_jobs(self, *, capability: str | None = None) -> list[dict[str, Any]]:
        db = self._connect()
        try:
            query = (
                "SELECT b.job_json FROM background_jobs b JOIN operations o "
                "ON o.operation_id=b.operation_id WHERE o.state=?"
            )
            params: list[Any] = [OperationState.RUNNING.value]
            if capability is not None:
                query += " AND o.capability=?"
                params.append(capability)
            query += " ORDER BY b.created_at,b.operation_id"
            return [json.loads(row["job_json"]) for row in db.execute(
                query, tuple(params)
            ).fetchall()]
        finally:
            db.close()

    def background_job(self, operation_id: str) -> dict[str, Any] | None:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT job_json FROM background_jobs WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            return None if row is None else json.loads(row["job_json"])
        finally:
            db.close()

    def finish_rename_claim_reclassification(
        self, *, resolver_operation_id: str, original_operation_id: str,
        expected_original_digest: str, expected_work_id: str,
        instance_id: str, new_resource_key: str,
        evidence: dict[str, Any],
    ) -> OperationResult:
        """Atomically narrow a legacy broad rename claim; preserve its UNKNOWN."""
        broad_key = "rcc-instance:" + instance_id
        if (not new_resource_key.startswith(broad_key + ":rename:")
                or not expected_original_digest):
            raise ConflictError("RCC_RENAME_RECLASSIFICATION_INVALID_TARGET")
        with self.transaction() as db:
            resolver = db.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (resolver_operation_id,)).fetchone()
            original = db.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (original_operation_id,)).fetchone()
            if (resolver is None or resolver["state"] != OperationState.RUNNING.value
                    or resolver["work_id"] != expected_work_id
                    or original is None or original["work_id"] != expected_work_id
                    or original["principal_id"] != resolver["principal_id"]
                    or original["capability"] != "relay_browser"
                    or original["target"] != instance_id
                    or original["state"] != OperationState.FINISHED.value
                    or original["outcome"] != Outcome.UNKNOWN.value
                    or not str(original["error"] or "").startswith(
                        "RCC_HOST_OUTCOME_UNVERIFIED:")
                    or original["request_digest"] != expected_original_digest):
                raise ConflictError("RCC_RENAME_RECLASSIFICATION_ORIGINAL_FENCE")
            old = db.execute(
                "SELECT * FROM resource_claims WHERE operation_id=? AND resource_key=?"
                " AND unresolved=1",
                (original_operation_id, broad_key)).fetchone()
            if old is None:
                raise ConflictError("RCC_RENAME_LEGACY_BROAD_CLAIM_NOT_FOUND")
            conflict = db.execute(
                "SELECT operation_id FROM resource_claims "
                "WHERE resource_key=? AND unresolved=1",
                (new_resource_key,)).fetchone()
            if conflict is not None:
                raise ConflictError("RCC_RENAME_TARGET_ALREADY_CLAIMED")
            db.execute(
                "UPDATE resource_claims SET resource_key=? WHERE "
                "operation_id=? AND resource_key=? AND unresolved=1",
                (new_resource_key, original_operation_id, broad_key))
            db.execute(
                "UPDATE operations SET state=?, outcome=?, evidence_json=?,error=?,updated_at=? "
                "WHERE operation_id=? AND state=?",
                (OperationState.FINISHED.value, Outcome.APPLIED.value,
                 json.dumps(evidence, sort_keys=True), None, time.time(),
                 resolver_operation_id, OperationState.RUNNING.value))
            db.execute(
                "UPDATE resource_claims SET unresolved=0 WHERE operation_id=?",
                (resolver_operation_id,))
            self._event(db, "RCC_RENAME_CLAIM_RECLASSIFIED", original_operation_id, {
                "resolver_operation_id": resolver_operation_id,
                "original_outcome_preserved": "UNKNOWN",
                "new_resource_key": new_resource_key,
            })
            self._event(db, "OPERATION_FINISHED", resolver_operation_id, {
                "outcome": "APPLIED", "claims_released": True,
                "reconciled_operation_ids": [],
            })
            row = db.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (resolver_operation_id,)).fetchone()
        return self._row_result(row)

    def finish_rename_claim_operator_quarantine(
        self, *, resolver_operation_id: str, original_operation_id: str,
        expected_original_digest: str, expected_work_id: str, instance_id: str,
        new_resource_key: str,
        evidence: dict[str, Any],
    ) -> OperationResult:
        """Narrow one legacy rename fence without deciding its UNKNOWN effect.

        This is deliberately not reconciliation: it is permitted only after a
        fresh RCC observation proves the target is still OPEN and the old
        terminal receipt is explicitly MISSING.  The original operation and
        its UNKNOWN outcome are never changed or released.
        """
        broad_key = "rcc-instance:" + instance_id
        required = {
            "command": "quarantine-legacy-rename-claim",
            "audit_kind": "OPERATOR_QUARANTINE_NOT_RECONCILIATION",
            "original_operation_id": original_operation_id,
            "expected_original_digest": expected_original_digest,
            "instance_id": instance_id,
            "new_resource_key": new_resource_key,
            "observed_presence": "OPEN",
            "receipt_state": "MISSING",
        }
        if (not new_resource_key.startswith(broad_key + ":rename:")
                or not expected_original_digest
                or not str(evidence.get("operator_justification") or "").strip()
                or not str(evidence.get("operator_acknowledgement") or "").strip()
                or any(evidence.get(key) != value for key, value in required.items())):
            raise ConflictError("RCC_RENAME_OPERATOR_QUARANTINE_INVALID_EVIDENCE")
        with self.transaction() as db:
            resolver = db.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (resolver_operation_id,)).fetchone()
            original = db.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (original_operation_id,)).fetchone()
            if (resolver is None or resolver["state"] != OperationState.RUNNING.value
                    or resolver["work_id"] != expected_work_id
                    or original is None or original["work_id"] != expected_work_id
                    or original["principal_id"] != resolver["principal_id"]
                    or original["capability"] != "relay_browser"
                    or original["target"] != instance_id
                    or original["state"] != OperationState.FINISHED.value
                    or original["outcome"] != Outcome.UNKNOWN.value
                    or not str(original["error"] or "").startswith(
                        "RCC_HOST_OUTCOME_UNVERIFIED:")
                    or original["request_digest"] != expected_original_digest):
                raise ConflictError("RCC_RENAME_OPERATOR_QUARANTINE_ORIGINAL_FENCE")
            old = db.execute(
                "SELECT * FROM resource_claims WHERE operation_id=? AND resource_key=?"
                " AND unresolved=1",
                (original_operation_id, broad_key)).fetchone()
            if old is None:
                raise ConflictError("RCC_RENAME_LEGACY_BROAD_CLAIM_NOT_FOUND")
            conflict = db.execute(
                "SELECT operation_id FROM resource_claims "
                "WHERE resource_key=? AND unresolved=1",
                (new_resource_key,)).fetchone()
            if conflict is not None:
                raise ConflictError("RCC_RENAME_TARGET_ALREADY_CLAIMED")
            db.execute(
                "UPDATE resource_claims SET resource_key=? WHERE "
                "operation_id=? AND resource_key=? AND unresolved=1",
                (new_resource_key, original_operation_id, broad_key))
            db.execute(
                "UPDATE operations SET state=?, outcome=?, evidence_json=?,error=?,updated_at=? "
                "WHERE operation_id=? AND state=?",
                (OperationState.FINISHED.value, Outcome.APPLIED.value,
                 json.dumps(evidence, sort_keys=True), None, time.time(),
                 resolver_operation_id, OperationState.RUNNING.value))
            db.execute(
                "UPDATE resource_claims SET unresolved=0 WHERE operation_id=?",
                (resolver_operation_id,))
            self._event(db, "RCC_RENAME_CLAIM_OPERATOR_QUARANTINED", original_operation_id, {
                "resolver_operation_id": resolver_operation_id,
                "original_outcome_preserved": "UNKNOWN",
                "new_resource_key": new_resource_key,
                "operator_justification": evidence["operator_justification"],
                "operator_acknowledgement": evidence["operator_acknowledgement"],
            })
            self._event(db, "OPERATION_FINISHED", resolver_operation_id, {
                "outcome": "APPLIED", "claims_released": True,
                "reconciled_operation_ids": [],
            })
            row = db.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (resolver_operation_id,)).fetchone()
        return self._row_result(row)

    def finish_operation(self, *, operation_id: str, outcome: Outcome,
                         evidence: dict[str, Any], error: str | None,
                         release_claims: bool,
                         reconciled_operation_ids: tuple[str, ...] = ()) -> OperationResult:
        with self.transaction() as db:
            resolver = db.execute(
                "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if resolver is None or resolver["state"] != OperationState.RUNNING.value:
                raise ConflictError("OPERATION_NOT_RUNNING")
            reconciled = tuple(sorted(set(reconciled_operation_ids)))
            running_reconciled: list[str] = []
            for original_id in reconciled:
                original = db.execute(
                    "SELECT * FROM operations WHERE operation_id=?", (original_id,)
                ).fetchone()
                if original is None or original["work_id"] != resolver["work_id"]:
                    raise ConflictError("RECONCILIATION_OPERATION_ACCESS_DENIED")
                finished_unknown = (
                    original["state"] == OperationState.FINISHED.value
                    and original["outcome"] == Outcome.UNKNOWN.value
                )
                recoverable_running = (
                    original["state"] == OperationState.RUNNING.value
                    and original["capability"] == "orchestrate"
                    and resolver["capability"] == "orchestrate"
                    and evidence.get("operation") in {
                        "reconcile", "chain-resume", "recover-not-dispatched"
                    }
                )
                if not finished_unknown and not recoverable_running:
                    raise ConflictError("RECONCILIATION_ORIGINAL_NOT_UNKNOWN")
                if (
                    resolver["capability"] == "desktop_window_activate_reconcile"
                    and original["capability"] != "desktop_window_activate"
                ):
                    raise ConflictError("RECONCILIATION_ORIGINAL_CAPABILITY_MISMATCH")
                if resolver["capability"] == "claim_reconcile" and original["capability"] == "desktop_uia_element_action":
                    # Exact original identity and uncertainty remain immutable.
                    # Reclaim ONLY the retired global UIA reservation; unrelated
                    # claims from this operation and any other work stay protected.
                    code = "DESKTOP_SESSION_AGENT_EFFECT_UNKNOWN:DESKTOP_UIA_ACTION_CHANGED_FOREGROUND"
                    original_evidence = json.loads(original["evidence_json"])
                    active_claims = db.execute(
                        "SELECT resource_key FROM resource_claims "
                        "WHERE operation_id=? AND unresolved=1",
                        (original_id,),
                    ).fetchall()
                    if (original["error"] != code
                            or original_evidence != {"phase": "EXECUTION", "code": code}
                            or [row["resource_key"] for row in active_claims]
                               != ["desktop-control:interactive-session"]
                            or evidence.get("proof") != "RETIRED_DESKTOP_CLAIM_ONLY_EFFECT_REMAINS_UNKNOWN"):
                        raise ConflictError("DESKTOP_UIA_RECLAIM_EXACT_CLAIM_REQUIRED")
                if recoverable_running:
                    running_reconciled.append(original_id)
                unresolved = db.execute(
                    "SELECT COUNT(*) FROM resource_claims WHERE operation_id=? AND unresolved=1",
                    (original_id,),
                ).fetchone()[0]
                if not unresolved:
                    raise ConflictError("RECONCILIATION_CLAIM_NOT_UNRESOLVED")
            changed = db.execute(
                "UPDATE operations SET state=?,outcome=?,evidence_json=?,error=?,updated_at=? "
                "WHERE operation_id=? AND state=?",
                (OperationState.FINISHED.value, outcome.value, json.dumps(evidence, sort_keys=True), error,
                 time.time(), operation_id, OperationState.RUNNING.value),
            ).rowcount
            if changed != 1:
                raise ConflictError("OPERATION_NOT_RUNNING")
            if release_claims:
                db.execute("UPDATE resource_claims SET unresolved=0 WHERE operation_id=?", (operation_id,))
            for original_id in reconciled:
                if original_id in running_reconciled:
                    recovered_outcome = (
                        Outcome.NOT_APPLIED
                        if evidence.get("operation") == "recover-not-dispatched"
                        else outcome
                    )
                    db.execute(
                        "UPDATE operations SET state=?,outcome=?,evidence_json=?,error=?,"
                        "updated_at=? WHERE operation_id=? AND state=?",
                        (
                            OperationState.FINISHED.value, recovered_outcome.value,
                            json.dumps({
                                "phase": "RECONCILED_RUNNING",
                                "resolver_operation_id": operation_id,
                                "recovered_outcome": recovered_outcome.value,
                            }, sort_keys=True),
                            None,
                            time.time(), original_id, OperationState.RUNNING.value,
                        ),
                    )
                db.execute(
                    "UPDATE resource_claims SET unresolved=0 WHERE operation_id=?",
                    (original_id,),
                )
                self._event(db, "OPERATION_RECONCILED", original_id, {
                    "resolver_operation_id": operation_id,
                    "original_outcome": (
                        (Outcome.NOT_APPLIED if evidence.get("operation")
                         == "recover-not-dispatched" else outcome).value
                        if original_id in running_reconciled
                        else Outcome.UNKNOWN.value
                    ),
                })
            self._event(db, "OPERATION_FINISHED", operation_id,
                        {"outcome": outcome.value, "claims_released": release_claims,
                         "reconciled_operation_ids": list(reconciled)})
            self._append_effect_stage(
                db, operation_id=operation_id, stage="RECEIPT_PERSISTED",
                detail={"outcome": outcome.value},
            )
            row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        return self._row_result(row)

    def finish_orchestration_recovery_in_transaction(
        self, db, *, resolver_operation_id: str, original_operation_id: str,
        resolver_outcome: Outcome, original_outcome: Outcome | None,
        evidence: dict[str, Any], release_original: bool,
        expected_original_error: str | None = None,
    ) -> None:
        """Atomically close a result-only orchestration resolver and its original.

        The caller already owns ``db``'s IMMEDIATE transaction together with the
        assignment/session evidence that proves the outcome.  Keeping these writes
        together removes the crash window between durable reconciliation and the
        outer operation receipts.
        """
        resolver = db.execute(
            "SELECT * FROM operations WHERE operation_id=? AND capability='orchestrate'",
            (resolver_operation_id,),
        ).fetchone()
        original = db.execute(
            "SELECT * FROM operations WHERE operation_id=? AND capability='orchestrate'",
            (original_operation_id,),
        ).fetchone()
        if (
            resolver is None or resolver["state"] != OperationState.RUNNING.value
            or original is None or original["work_id"] != resolver["work_id"]
        ):
            raise ConflictError("ORCHESTRATION_RECOVERY_OPERATION_STATE_INVALID")
        now = time.time()
        db.execute(
            "UPDATE operations SET state=?,outcome=?,evidence_json=?,error=NULL,updated_at=? "
            "WHERE operation_id=? AND state=?",
            (
                OperationState.FINISHED.value, resolver_outcome.value,
                json.dumps(evidence, sort_keys=True), now, resolver_operation_id,
                OperationState.RUNNING.value,
            ),
        )
        db.execute(
            "UPDATE resource_claims SET unresolved=0 WHERE operation_id=?",
            (resolver_operation_id,),
        )
        original_persisted_outcome = str(original["outcome"] or "UNRESOLVED")
        takeover_unknown = (
            original["state"] == OperationState.FINISHED.value
            and original["outcome"] == Outcome.UNKNOWN.value
            and original["error"] == "ORCHESTRATION_RECOVERY_TAKEOVER"
        )
        exact_unknown = (
            expected_original_error is not None
            and original["state"] == OperationState.FINISHED.value
            and original["outcome"] == Outcome.UNKNOWN.value
            and original["error"] == expected_original_error
        )
        if original_outcome is not None and (
            original["state"] == OperationState.RUNNING.value
            or takeover_unknown or exact_unknown
        ):
            db.execute(
                "UPDATE operations SET state=?,outcome=?,evidence_json=?,error=NULL,updated_at=? "
                "WHERE operation_id=?",
                (
                    OperationState.FINISHED.value, original_outcome.value,
                    json.dumps({
                        "phase": "ORCHESTRATION_RECOVERED",
                        "resolver_operation_id": resolver_operation_id,
                        "recovered_outcome": original_outcome.value,
                    }, sort_keys=True),
                    now, original_operation_id,
                ),
            )
            original_persisted_outcome = original_outcome.value
        elif original["state"] != OperationState.FINISHED.value:
            raise ConflictError("ORCHESTRATION_RECOVERY_ORIGINAL_INVALID")
        if release_original:
            db.execute(
                "UPDATE resource_claims SET unresolved=0 WHERE operation_id=?",
                (original_operation_id,),
            )
        self._event(db, "OPERATION_FINISHED", resolver_operation_id, {
            "outcome": resolver_outcome.value,
            "claims_released": True,
            "atomic_orchestration_recovery": True,
        })
        self._event(db, "OPERATION_RECONCILED", original_operation_id, {
            "resolver_operation_id": resolver_operation_id,
            "original_outcome": original_persisted_outcome,
            "resolved_outcome": (
                original_outcome.value if original_outcome is not None else None
            ),
            "claims_released": release_original,
        })

    def initialize_operation_steps(self, *, operation_id: str,
                                   steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Persist one immutable ordered plan before the first child is dispatched."""
        with self.transaction() as db:
            operation = db.execute(
                "SELECT state FROM operations WHERE operation_id=?", (operation_id,),
            ).fetchone()
            if operation is None or operation["state"] != OperationState.RUNNING.value:
                raise ConflictError("OPERATION_NOT_RUNNING")
            existing = db.execute(
                "SELECT step_id,ordinal,capability,request_digest FROM operation_steps "
                "WHERE operation_id=? ORDER BY ordinal", (operation_id,),
            ).fetchall()
            expected = [
                (str(step["step_id"]), int(step["ordinal"]), str(step["capability"]),
                 str(step["request_digest"]))
                for step in steps
            ]
            if existing:
                actual = [
                    (row["step_id"], row["ordinal"], row["capability"], row["request_digest"])
                    for row in existing
                ]
                if actual != expected:
                    raise ConflictError("OPERATION_STEP_PLAN_MISMATCH")
            else:
                for step_id, ordinal, capability, request_digest in expected:
                    db.execute(
                        "INSERT INTO operation_steps VALUES(?,?,?,?,?,'PENDING',NULL,'{}',NULL,NULL,NULL)",
                        (operation_id, step_id, ordinal, capability, request_digest),
                    )
                self._event(db, "OPERATION_STEPS_INITIALIZED", operation_id, {
                    "count": len(expected),
                    "steps": [value[0] for value in expected],
                })
        return self.get_operation_steps(operation_id=operation_id)

    def start_operation_step(self, *, operation_id: str, step_id: str) -> dict[str, Any]:
        now = time.time()
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE operation_steps SET state='RUNNING',started_at=? "
                "WHERE operation_id=? AND step_id=? AND state='PENDING'",
                (now, operation_id, step_id),
            ).rowcount
            if changed != 1:
                raise ConflictError("OPERATION_STEP_NOT_PENDING")
            self._event(db, "OPERATION_STEP_STARTED", operation_id, {"step_id": step_id})
        return self.get_operation_step(operation_id=operation_id, step_id=step_id)

    def finish_operation_step(self, *, operation_id: str, step_id: str,
                              outcome: Outcome, evidence: dict[str, Any],
                              error: str | None = None) -> dict[str, Any]:
        now = time.time()
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE operation_steps SET state='FINISHED',outcome=?,evidence_json=?,"
                "error=?,finished_at=? WHERE operation_id=? AND step_id=? AND state='RUNNING'",
                (outcome.value, json.dumps(evidence, sort_keys=True), error, now,
                 operation_id, step_id),
            ).rowcount
            if changed != 1:
                raise ConflictError("OPERATION_STEP_NOT_RUNNING")
            self._event(db, "OPERATION_STEP_FINISHED", operation_id, {
                "step_id": step_id, "outcome": outcome.value,
            })
        return self.get_operation_step(operation_id=operation_id, step_id=step_id)

    def skip_pending_operation_steps(self, *, operation_id: str,
                                     after_ordinal: int, reason: str) -> None:
        now = time.time()
        with self.transaction() as db:
            rows = db.execute(
                "SELECT step_id FROM operation_steps WHERE operation_id=? AND ordinal>? "
                "AND state='PENDING' ORDER BY ordinal", (operation_id, after_ordinal),
            ).fetchall()
            for row in rows:
                db.execute(
                    "UPDATE operation_steps SET state='SKIPPED',outcome=?,evidence_json=?,"
                    "finished_at=? WHERE operation_id=? AND step_id=? AND state='PENDING'",
                    (Outcome.NOT_APPLIED.value, json.dumps({"code": reason}, sort_keys=True),
                     now, operation_id, row["step_id"]),
                )
                self._event(db, "OPERATION_STEP_SKIPPED", operation_id, {
                    "step_id": row["step_id"], "reason": reason,
                })

    def get_operation_step(self, *, operation_id: str, step_id: str) -> dict[str, Any]:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT * FROM operation_steps WHERE operation_id=? AND step_id=?",
                (operation_id, step_id),
            ).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("OPERATION_STEP_NOT_FOUND")
        return self._step_row(row)

    def get_operation_steps(self, *, operation_id: str) -> list[dict[str, Any]]:
        db = self._connect()
        try:
            rows = db.execute(
                "SELECT * FROM operation_steps WHERE operation_id=? ORDER BY ordinal",
                (operation_id,),
            ).fetchall()
        finally:
            db.close()
        return [self._step_row(row) for row in rows]

    def get_operation_steps_for(self, *, operation_id: str, work_id: str,
                                principal_id: str) -> list[dict[str, Any]]:
        self.get_operation_for(
            operation_id=operation_id, work_id=work_id, principal_id=principal_id,
        )
        return self.get_operation_steps(operation_id=operation_id)

    def get_operation_for(self, *, operation_id: str, work_id: str, principal_id: str) -> OperationResult:
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("OPERATION_NOT_FOUND")
        if row["work_id"] != work_id:
            raise ConflictError("OPERATION_RESULT_ACCESS_DENIED")
        work = self.get_work(work_id)
        if row["principal_id"] != principal_id and work.owner_principal_id != principal_id:
            raise ConflictError("OPERATION_RESULT_ACCESS_DENIED")
        return self._row_result(row)

    def get_operation_request_digest_for(self, *, operation_id: str,
                                         work_id: str, principal_id: str) -> str:
        self.get_operation_for(operation_id=operation_id, work_id=work_id,
                               principal_id=principal_id)
        db = self._connect()
        try:
            row = db.execute(
                "SELECT request_digest FROM operations WHERE operation_id=? AND work_id=?",
                (operation_id, work_id)).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("OPERATION_NOT_FOUND")
        return str(row["request_digest"])

    def get_operation_metadata_for(self, *, operation_id: str, work_id: str,
                                   principal_id: str) -> dict[str, Any]:
        self.get_operation_for(operation_id=operation_id, work_id=work_id,
                               principal_id=principal_id)
        db = self._connect()
        try:
            row = db.execute(
                "SELECT capability,target,state,outcome,error,evidence_json FROM operations "
                "WHERE operation_id=? AND work_id=?", (operation_id, work_id),
            ).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("OPERATION_NOT_FOUND")
        value = dict(row)
        value["evidence"] = json.loads(value.pop("evidence_json"))
        return value

    @staticmethod
    def _append_effect_stage(db: sqlite3.Connection, *, operation_id: str,
                             stage: str, detail: dict[str, Any]) -> None:
        allowed = {
            "CLAIM_RESERVED", "DISPATCH_INTENT", "EFFECT_RESULT_OBSERVED",
            "EFFECT_REJECTED", "EFFECT_UNCERTAIN", "RECEIPT_PERSIST_INTENT",
            "RECEIPT_PERSISTED",
        }
        if stage not in allowed:
            raise ValueError("EFFECT_STAGE_INVALID")
        safe = {key: value for key, value in detail.items()
                if key in {"outcome", "error_type", "error_code"}
                and (value is None or isinstance(value, (str, int, float, bool)))}
        sequence = db.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM operation_effect_stages "
            "WHERE operation_id=?", (operation_id,),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO operation_effect_stages VALUES(?,?,?,?,?)",
            (operation_id, sequence, stage,
             json.dumps(safe, sort_keys=True, separators=(",", ":")), time.time()),
        )

    def record_effect_stage(self, *, operation_id: str, stage: str,
                            detail: dict[str, Any] | None = None) -> None:
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM operations WHERE operation_id=?",
                          (operation_id,)).fetchone() is None:
                raise KeyError("OPERATION_NOT_FOUND")
            self._append_effect_stage(db, operation_id=operation_id,
                                      stage=stage, detail=detail or {})

    def get_effect_journal_for(self, *, operation_id: str, work_id: str,
                               principal_id: str) -> list[dict[str, Any]]:
        self.get_operation_for(operation_id=operation_id, work_id=work_id,
                               principal_id=principal_id)
        db = self._connect()
        try:
            rows = db.execute(
                "SELECT sequence,stage,detail_json,created_at "
                "FROM operation_effect_stages WHERE operation_id=? ORDER BY sequence",
                (operation_id,),
            ).fetchall()
        finally:
            db.close()
        return [{"sequence": row["sequence"], "stage": row["stage"],
                 "detail": json.loads(row["detail_json"]),
                 "created_at": row["created_at"]} for row in rows]

    def get_operation_target_for(self, *, operation_id: str, work_id: str, principal_id: str) -> str:
        # Reuse the exact work/principal authorization check before revealing target.
        self.get_operation_for(operation_id=operation_id, work_id=work_id, principal_id=principal_id)
        db = self._connect()
        try:
            row = db.execute(
                "SELECT target FROM operations WHERE operation_id=? AND work_id=?",
                (operation_id, work_id),
            ).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError("OPERATION_NOT_FOUND")
        return str(row["target"])

    @staticmethod
    def _row_result(row: sqlite3.Row, *, duplicate: bool = False) -> OperationResult:
        return OperationResult(
            row["operation_id"], OperationState(row["state"]),
            Outcome(row["outcome"]) if row["outcome"] else None,
            json.loads(row["evidence_json"]), duplicate, row["error"],
        )

    @staticmethod
    def _step_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "step_id": row["step_id"],
            "ordinal": row["ordinal"],
            "capability": row["capability"],
            "request_digest": row["request_digest"],
            "state": row["state"],
            "outcome": row["outcome"],
            "evidence": json.loads(row["evidence_json"]),
            "error": row["error"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }
