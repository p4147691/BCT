"""Read-only history classification and a rollback-only legacy writer fence."""
from contextlib import contextmanager, closing
import hashlib
import json
import sqlite3
import time

import psutil

from .errors import PreconditionError


def history_digest(db):
    db.row_factory = sqlite3.Row
    operations = [dict(row) for row in db.execute(
        "SELECT * FROM operations WHERE state IN ('RECORDED','RUNNING') OR "
        "operation_id IN (SELECT operation_id FROM resource_claims WHERE unresolved=1) "
        "ORDER BY operation_id")]
    claims = [dict(row) for row in db.execute(
        "SELECT * FROM resource_claims WHERE unresolved=1 ORDER BY resource_key")]
    payload = {"operations": operations, "claims": claims}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def assert_quiescent(db, retained_history_sha256=None):
    """History is retained, never completed or replayed to permit a restart.

    An exact, independently reviewed history pin is required for exceptions.
    Only synchronous execute records predating this OS boot can be orphaned;
    background jobs and all other nonterminal operations remain blockers.
    """
    db.row_factory = sqlite3.Row
    active = list(db.execute("SELECT * FROM operations WHERE state IN ('RECORDED','RUNNING')"))
    claims = list(db.execute("SELECT * FROM resource_claims WHERE unresolved=1"))
    evidence = {"retained_operations": len(active), "retained_claims": len(claims)}
    if active or claims:
        try:
            actual = history_digest(db)
            if not retained_history_sha256 or actual != retained_history_sha256:
                raise ValueError("history not pinned")
            boot = psutil.boot_time()
            for row in active:
                if (row['capability'] != 'execute' or row['created_at'] >= boot
                        or row['updated_at'] >= boot or db.execute(
                            'SELECT 1 FROM background_jobs WHERE operation_id=?',
                            (row['operation_id'],)).fetchone()):
                    raise ValueError("live or resumable operation")
            for claim in claims:
                row = db.execute('SELECT * FROM operations WHERE operation_id=?',
                                 (claim['operation_id'],)).fetchone()
                if row is None or row['capability'] in ('deploy', 'deployment', 'service_control'):
                    raise ValueError("unverified runtime effect")
                if row['state'] not in ('FINISHED', 'RUNNING', 'RECORDED'):
                    raise ValueError("unclassified operation")
            evidence.update(history_sha256=actual, boot_time=boot)
        except (KeyError, IndexError, sqlite3.Error, ValueError) as exc:
            raise PreconditionError('MAINTENANCE_ACTIVE_OR_UNRESOLVED_WORK') from exc
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # Poller leadership is not an execution. Session leases and pre-send
    # reservations are: do not stop a possibly in-flight external dispatch.
    checks = {
        'orchestration_durable_leases': ('expires_at>?', (time.time(),)),
        'orchestration_dispatch_outbox': ("state IN ('RESERVED','DISPATCHING')", ()),
        'orchestration_dispatch_routes': ("state NOT IN ('DELIVERED','ACKNOWLEDGED','FAILED','UNKNOWN')", ()),
        'orchestration_durable_wake_attempts': ("state IN ('RESERVED','DISPATCHING','RUNNING')", ()),
        'loop_recipe_self_outbox': ("state IN ('RESERVED','DISPATCHING','SENDING')", ()),
        'node_label_notification_outbox': ("status IN ('PENDING','SENDING','DISPATCHING')", ()),
    }
    for table, (where, args) in checks.items():
        if table in tables and db.execute(f'SELECT 1 FROM {table} WHERE {where} LIMIT 1', args).fetchone():
            raise PreconditionError('MAINTENANCE_IN_FLIGHT_DISPATCH:' + table)
    return evidence


@contextmanager
def admission_fence(root):
    """Block Store BEGIN IMMEDIATE before its admission/dispatch writes.

    This makes no persistent DB changes. Hold until the exact Core exits. A
    timeout or unexpected schema/state fails closed; no force termination.
    """
    with closing(sqlite3.connect(root / 'state/state.sqlite', timeout=5, isolation_level=None)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            yield db
        finally:
            db.rollback()
