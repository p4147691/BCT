"""Durable Loop-only run and continuation ledger.

This ledger owns no browser or network effect.  Its job is to make a pending
Loop link durable before a future adapter registers a Watch or sends anything.
It keeps the original operation, Watch, and receipt references immutable so an
UNKNOWN result can only be reconciled, never silently re-issued.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from bct.core.store import Store
from bct.loop_recipe_contracts import Continuation, LoopContractError
from bct.loop_recipe_flow import LinkKind


class LoopRecipeLedger:
    def __init__(self, store: Store):
        self.store = store
        with self.store.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS loop_recipe_v2_runs (
                    loop_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    current_block_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS loop_recipe_v2_continuations (
                    continuation_id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL,
                    source_block_id TEXT NOT NULL,
                    next_block_id TEXT NOT NULL,
                    link_kind TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    operation_id TEXT NOT NULL,
                    watch_id TEXT NOT NULL,
                    receipt_ref TEXT NOT NULL,
                    required_capabilities_json TEXT NOT NULL,
                    artifact_refs_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    observation TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(loop_id) REFERENCES loop_recipe_v2_runs(loop_id)
                );
                CREATE INDEX IF NOT EXISTS loop_recipe_v2_continuations_pending
                    ON loop_recipe_v2_continuations(loop_id, state, revision);
                CREATE TABLE IF NOT EXISTS loop_recipe_v2_contexts (
                    loop_id TEXT PRIMARY KEY,
                    instruction_text TEXT NOT NULL,
                    direction_text TEXT NOT NULL,
                    manager_conversation_key TEXT NOT NULL,
                    supervisor_conversation_key TEXT NOT NULL,
                    network_project_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(loop_id) REFERENCES loop_recipe_v2_runs(loop_id)
                );
            """)

    @staticmethod
    def _public(row) -> dict[str, Any]:
        value = dict(row)
        value["required_capabilities"] = json.loads(value.pop("required_capabilities_json"))
        value["artifact_refs"] = json.loads(value.pop("artifact_refs_json"))
        return value

    def start(self, *, loop_id: str, work_id: str, entry_block_id: str = "resume") -> dict[str, Any]:
        if not loop_id or not work_id or not entry_block_id:
            raise LoopContractError("LOOP_RUN_IDENTITY_REQUIRED")
        now = time.time()
        with self.store.transaction() as db:
            existing = db.execute("SELECT * FROM loop_recipe_v2_runs WHERE loop_id=?", (loop_id,)).fetchone()
            if existing is not None:
                return dict(existing)
            db.execute("""INSERT INTO loop_recipe_v2_runs
                (loop_id, work_id, current_block_id, revision, state, created_at, updated_at)
                VALUES (?, ?, ?, 0, 'ACTIVE', ?, ?)""", (loop_id, work_id, entry_block_id, now, now))
            return dict(db.execute("SELECT * FROM loop_recipe_v2_runs WHERE loop_id=?", (loop_id,)).fetchone())

    def get_run(self, loop_id: str) -> dict[str, Any] | None:
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM loop_recipe_v2_runs WHERE loop_id=?", (loop_id,)).fetchone()
            return dict(row) if row is not None else None

    def bind_context(self, *, loop_id: str, instruction_text: str, direction_text: str,
                     manager_conversation_key: str, supervisor_conversation_key: str,
                     network_project_id: str) -> dict[str, Any]:
        values = (
            instruction_text.strip(), direction_text.strip(),
            manager_conversation_key.strip().lower(),
            supervisor_conversation_key.strip().lower(), network_project_id.strip(),
        )
        if any(not value for value in values):
            raise LoopContractError("LOOP_CONTEXT_REQUIRED")
        if max(len(values[0]), len(values[1])) > 12000:
            raise LoopContractError("LOOP_CONTEXT_TOO_LONG")
        uuid_pattern = r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
        if (not re.fullmatch(uuid_pattern, values[2])
                or not re.fullmatch(uuid_pattern, values[3]) or values[2] == values[3]):
            raise LoopContractError("LOOP_TOPOLOGY_IDENTITY_INVALID")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", values[4]):
            raise LoopContractError("LOOP_NETWORK_PROJECT_ID_INVALID")
        now = time.time()
        with self.store.transaction() as db:
            run = db.execute("SELECT 1 FROM loop_recipe_v2_runs WHERE loop_id=?", (loop_id,)).fetchone()
            if run is None:
                raise LoopContractError("LOOP_RUN_NOT_FOUND")
            existing = db.execute(
                "SELECT * FROM loop_recipe_v2_contexts WHERE loop_id=?", (loop_id,),
            ).fetchone()
            if existing is not None:
                actual = tuple(existing[key] for key in (
                    "instruction_text", "direction_text", "manager_conversation_key",
                    "supervisor_conversation_key", "network_project_id",
                ))
                if actual != values:
                    raise LoopContractError("LOOP_CONTEXT_CONFLICT")
                return dict(existing)
            db.execute(
                "INSERT INTO loop_recipe_v2_contexts VALUES(?,?,?,?,?,?,?)",
                (loop_id, *values, now),
            )
            return dict(db.execute(
                "SELECT * FROM loop_recipe_v2_contexts WHERE loop_id=?", (loop_id,),
            ).fetchone())

    def get_context(self, loop_id: str) -> dict[str, Any] | None:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM loop_recipe_v2_contexts WHERE loop_id=?", (loop_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_continuation(self, continuation_id: str) -> dict[str, Any] | None:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM loop_recipe_v2_continuations WHERE continuation_id=?",
                (continuation_id,),
            ).fetchone()
            return self._public(row) if row is not None else None

    def advance_immediate(self, *, loop_id: str, expected_revision: int,
                          source_block_id: str, next_block_id: str,
                          complete: bool = False) -> dict[str, Any]:
        now = time.time()
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM loop_recipe_v2_runs WHERE loop_id=?", (loop_id,)).fetchone()
            if row is None:
                raise LoopContractError("LOOP_RUN_NOT_FOUND")
            if (row["state"] != "ACTIVE" or row["revision"] != expected_revision
                    or row["current_block_id"] != source_block_id):
                raise LoopContractError("LOOP_RUN_REVISION_STALE")
            state = "COMPLETED" if complete else "ACTIVE"
            db.execute("UPDATE loop_recipe_v2_runs SET current_block_id=?, revision=?, state=?, "
                       "updated_at=? WHERE loop_id=?", (
                           next_block_id, expected_revision + 1, state, now, loop_id,
                       ))
            return dict(db.execute("SELECT * FROM loop_recipe_v2_runs WHERE loop_id=?", (loop_id,)).fetchone())

    def stage(self, *, continuation: Continuation, link: LinkKind) -> dict[str, Any]:
        if link not in {LinkKind.WAIT, LinkKind.HANDOFF, LinkKind.BLOCKED}:
            raise LoopContractError("LOOP_CONTINUATION_LINK_INVALID")
        now = time.time()
        with self.store.transaction() as db:
            existing = db.execute("SELECT * FROM loop_recipe_v2_continuations WHERE continuation_id=?",
                                  (continuation.continuation_id,)).fetchone()
            if existing is not None:
                if (existing["loop_id"], existing["operation_id"], existing["watch_id"],
                        existing["receipt_ref"], existing["source_block_id"],
                        existing["next_block_id"], existing["link_kind"]) != (
                            continuation.loop_id, continuation.operation_id, continuation.watch_id,
                            continuation.receipt_ref, continuation.source_block_id,
                            continuation.next_block_id, link.value):
                    raise LoopContractError("LOOP_CONTINUATION_ID_CONFLICT")
                return {**self._public(existing), "created": False}
            run = db.execute("SELECT * FROM loop_recipe_v2_runs WHERE loop_id=?", (continuation.loop_id,)).fetchone()
            if run is None:
                raise LoopContractError("LOOP_RUN_NOT_FOUND")
            if run["state"] != "ACTIVE" or run["revision"] != continuation.revision:
                raise LoopContractError("LOOP_RUN_REVISION_STALE")
            if run["current_block_id"] != continuation.source_block_id:
                raise LoopContractError("LOOP_RUN_SOURCE_BLOCK_STALE")
            db.execute("""INSERT INTO loop_recipe_v2_continuations
                (continuation_id, loop_id, source_block_id, next_block_id, link_kind, revision,
                 operation_id, watch_id, receipt_ref, required_capabilities_json,
                 artifact_refs_json, state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)""", (
                    continuation.continuation_id, continuation.loop_id, continuation.source_block_id,
                    continuation.next_block_id, link.value, continuation.revision,
                    continuation.operation_id, continuation.watch_id, continuation.receipt_ref,
                    json.dumps(sorted(continuation.required_capabilities)),
                    json.dumps(list(continuation.artifact_refs)), now, now,
                ))
            db.execute("""UPDATE loop_recipe_v2_runs
                SET revision=?, current_block_id=?, state='WAITING', updated_at=?
                WHERE loop_id=?""", (continuation.revision + 1, continuation.next_block_id, now,
                                       continuation.loop_id))
            return {**self._public(db.execute(
                "SELECT * FROM loop_recipe_v2_continuations WHERE continuation_id=?",
                (continuation.continuation_id,),
            ).fetchone()), "created": True}

    def observe_original_receipt(self, *, continuation_id: str, observation: str) -> dict[str, Any]:
        if observation not in {"DELIVERED", "NOT_APPLIED", "UNKNOWN"}:
            raise LoopContractError("LOOP_RECEIPT_OBSERVATION_INVALID")
        now = time.time()
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM loop_recipe_v2_continuations WHERE continuation_id=?",
                             (continuation_id,)).fetchone()
            if row is None:
                raise LoopContractError("LOOP_CONTINUATION_NOT_FOUND")
            state = "READY" if observation in {"DELIVERED", "NOT_APPLIED"} else "UNKNOWN"
            db.execute("UPDATE loop_recipe_v2_continuations SET state=?, observation=?, updated_at=? "
                       "WHERE continuation_id=?", (state, observation, now, continuation_id))
            if observation == "UNKNOWN":
                db.execute("UPDATE loop_recipe_v2_runs SET state='RECONCILING', updated_at=? WHERE loop_id=?",
                           (now, row["loop_id"]))
            return self._public(db.execute("SELECT * FROM loop_recipe_v2_continuations WHERE continuation_id=?",
                                           (continuation_id,)).fetchone())

    def claim_resume(self, continuation_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM loop_recipe_v2_continuations WHERE continuation_id=?",
                             (continuation_id,)).fetchone()
            if row is None or row["state"] != "READY":
                return None
            db.execute("UPDATE loop_recipe_v2_continuations SET state='CLAIMED', updated_at=? "
                       "WHERE continuation_id=?", (now, continuation_id))
            db.execute("UPDATE loop_recipe_v2_runs SET state='ACTIVE', updated_at=? WHERE loop_id=?",
                       (now, row["loop_id"]))
            return self._public(db.execute("SELECT * FROM loop_recipe_v2_continuations WHERE continuation_id=?",
                                           (continuation_id,)).fetchone())
