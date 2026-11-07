from __future__ import annotations

import asyncio
import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bct import BCT
from bct.chat_input_queue import ChatInputQueue, validate_queue_identity
from bct.core.models import Principal
from bct.core.store import Store
from bct.mcp_server import build_mcp


A = "6ae5bbd7-bd00-83ee-b34e-c976e990efdb"
B = "6ae5bd13-43a0-83ec-8222-36ef5197c3c6"
DIGEST = hashlib.sha256(b"verified result").hexdigest()


class ChatInputQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "state.sqlite"
        self.store = Store(self.path)
        self.queue = ChatInputQueue(self.store)
        self.work = "test-queue-work"

    def add(self, name, target=A, instruction="do one safe task"):
        return self.queue.enqueue(
            work_id=self.work, target_conversation_key=target,
            message_id=name, instruction=instruction,
        )

    def claim(self, target=A, ident="claim-01"):
        return self.queue.claim(
            work_id=self.work, target_conversation_key=target, claim_id=ident,
        )

    def done(self, message, claim):
        return self.queue.complete(
            work_id=self.work, target_conversation_key=A,
            message_id=message, claim_id=claim, result_sha256=DIGEST,
        )

    def test_fifo_and_no_implicit_dispatch(self):
        self.add("msg-01")
        self.add("msg-02")
        self.add("msg-03")
        first = self.claim()
        self.assertEqual("msg-01", first["message"]["message_id"])
        self.assertEqual("do one safe task", first["message"]["instruction"])
        self.assertEqual("BLOCKED", self.claim(ident="claim-02")["status"])
        self.assertEqual("DONE", self.done("msg-01", "claim-01")["status"])
        self.assertEqual("msg-02", self.claim(ident="claim-02")["message"]["message_id"])
        st = self.queue.status(work_id=self.work, target_conversation_key=A)
        self.assertEqual({"QUEUED": 1, "CLAIMED": 1, "HELD_PRE_DISPATCH": 0,
                          "HELD_UNKNOWN": 0, "DONE": 1}, st["counts"])
        self.assertNotIn("instruction", st["messages"][0])
        self.assertFalse(st["delivery_enabled"])
        with self.store._readonly() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM operations").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT count(*) FROM resource_claims").fetchone()[0])

    def test_duplicate_exact_and_conflicting_ids(self):
        first = self.add("msg-01")
        same = self.add("msg-01")
        self.assertTrue(same["message"]["duplicate"])
        self.assertEqual(first["message"]["sequence"], same["message"]["sequence"])
        with self.assertRaisesRegex(ValueError, "MESSAGE_ID_CONFLICT"):
            self.add("msg-01", instruction="different")
        with self.assertRaisesRegex(ValueError, "MESSAGE_ID_CONFLICT"):
            self.add("msg-01", target=B)
        self.assertEqual(1, self.queue.status(
            work_id=self.work, target_conversation_key=A)["counts"]["QUEUED"])

    def test_target_isolation_and_unknown_hold_no_replay(self):
        self.add("first-a")
        self.add("second-a")
        self.add("first-b", target=B)
        self.claim()
        self.queue.hold(work_id=self.work, target_conversation_key=A,
                        message_id="first-a", claim_id="claim-01",
                        kind="UNKNOWN", reason="external effect not proved absent")
        self.assertEqual("BLOCKED", self.claim(ident="claim-02")["status"])
        self.assertEqual("HELD_UNKNOWN", self.queue.status(
            work_id=self.work, target_conversation_key=A)["head"]["state"])
        with self.assertRaisesRegex(ValueError, "UNKNOWN_REQUIRES_TRUSTED"):
            self.queue.resume(work_id=self.work, target_conversation_key=A,
                              message_id="first-a", claim_id="claim-01")
        self.assertEqual("first-b", self.claim(target=B, ident="claim-b")["message"]["message_id"])
        self.assertEqual("BLOCKED", self.claim(ident="claim-03")["status"])

    def test_explicit_predispatch_resume_preserves_claim_history(self):
        self.add("msg-01")
        first = self.claim(ident="attempt-old")
        self.assertEqual("CLAIMED", first["status"])
        self.queue.hold(work_id=self.work, target_conversation_key=A,
                        message_id="msg-01", claim_id="attempt-old",
                        kind="PRE_DISPATCH", reason="not dispatched")
        self.queue.resume(work_id=self.work, target_conversation_key=A,
                          message_id="msg-01", claim_id="attempt-old")
        again = self.queue.resume(work_id=self.work, target_conversation_key=A,
                                  message_id="msg-01", claim_id="attempt-old")
        self.assertEqual("ALREADY_RESUMED", again["status"])
        self.assertTrue(again["message"]["duplicate"])
        with self.assertRaisesRegex(ValueError, "CLAIM_ID_REUSED"):
            self.claim(ident="attempt-old")
        second = self.claim(ident="attempt-new")
        self.assertEqual(2, second["message"]["attempt"])
        self.assertEqual("DONE", self.done("msg-01", "attempt-new")["status"])
        self.assertTrue(self.done("msg-01", "attempt-new")["message"]["duplicate"])
        with self.assertRaisesRegex(ValueError, "NOT_CLAIMED"):
            self.queue.hold(work_id=self.work, target_conversation_key=A,
                            message_id="msg-01", claim_id="attempt-new",
                            reason="too late")

    def test_crash_reopen_does_not_reclaim_inflight(self):
        self.add("msg-01")
        self.claim()
        reopened = ChatInputQueue(Store(self.path))
        result = reopened.claim(work_id=self.work, target_conversation_key=A, claim_id="new-claim")
        self.assertEqual("BLOCKED", result["status"])
        duplicate = reopened.claim(work_id=self.work, target_conversation_key=A, claim_id="claim-01")
        self.assertTrue(duplicate["message"]["duplicate"])
        self.assertEqual("CLAIMED", duplicate["status"])

    def test_concurrent_claims_only_one_acquires_head(self):
        self.add("msg-01")
        def claim_one(i):
            return self.claim(ident=f"claim-{i}")["status"]
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(claim_one, range(6)))
        self.assertEqual(1, results.count("CLAIMED"))
        self.assertEqual(5, results.count("BLOCKED"))

    def test_status_before_first_write_does_not_create_queue_tables(self):
        fresh = Store(self.root / "fresh.sqlite")
        read_only = ChatInputQueue(fresh)
        st = read_only.status(work_id=self.work, target_conversation_key=A)
        self.assertIsNone(st["head"])
        self.assertEqual(0, sum(st["counts"].values()))
        with fresh._readonly() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='chat_input_queue'").fetchone())

    def test_wrong_target_or_claim_fail_closed(self):
        self.add("msg-01")
        self.claim()
        with self.assertRaisesRegex(ValueError, "IDENTITY_CONFLICT"):
            self.queue.complete(work_id=self.work, target_conversation_key=B,
                                message_id="msg-01", claim_id="claim-01", result_sha256=DIGEST)
        with self.assertRaisesRegex(ValueError, "CLAIM_MISMATCH"):
            self.done("msg-01", "wrong-claim")
        self.assertEqual("CLAIMED", self.queue.status(work_id=self.work,
                          target_conversation_key=A)["head"]["state"])

    def test_invalid_ids_are_rejected_before_writing(self):
        with self.assertRaisesRegex(ValueError, "TARGET_INVALID"):
            self.add("msg-01", target="N96")
        with self.assertRaisesRegex(ValueError, "MESSAGE_ID_INVALID"):
            self.add("../escape")
        with self.assertRaisesRegex(ValueError, "INSTRUCTION_INVALID"):
            self.add("msg-01", instruction="  ")
        with self.assertRaisesRegex(ValueError, "RESULT_SHA_INVALID"):
            self.queue.complete(work_id=self.work, target_conversation_key=A,
                                message_id="msg-01", claim_id="claim-01",
                                result_sha256="wrong")
        self.assertIsNone(self.queue.status(work_id=self.work, target_conversation_key=A)["head"])

    def test_common_identity_validator_canonicalizes_every_queue_partition(self):
        identity = validate_queue_identity(work_id=self.work, target_conversation_key=A)
        self.assertEqual(self.work, identity.work_id)
        self.assertEqual(A, identity.target_conversation_key)
        with self.assertRaisesRegex(ValueError, "TARGET_NOT_CANONICAL"):
            validate_queue_identity(work_id=self.work, target_conversation_key=A.upper())


class ChatInputQueueMCPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        cfg = root / "policy.toml"
        cfg.write_text('[policy]\nnormal_actions=["read","orchestrate"]\napproval_actions=[]\n',
                       encoding="utf-8")
        self.bct = BCT(state_path=root / "state.sqlite", policy_path=cfg)
        principal = Principal("bct-mcp-local", "test",
                              frozenset({"read", "orchestrate"}))
        self.work = self.bct.create_work(
            work_id="queue-mcp", request_summary="queue", roots=[str(root)],
            actions=["read"], principal=principal,
        )
        other = Principal("different-principal", "test", frozenset({"read", "orchestrate"}))
        self.other = self.bct.create_work(
            work_id="queue-other", request_summary="unauthorized", roots=[str(root)],
            actions=["read", "orchestrate"], principal=other,
        )

    def test_public_tool_uses_active_work_and_exact_queue_identity_not_authority(self):
        async def check():
            full = build_mcp(self.bct)
            compact = build_mcp(self.bct, compact_catalogue=True)
            for server in (full, compact):
                self.assertIn("queue_message", {x.name for x in await server.list_tools()})
            await full.call_tool("queue_message", {
                "work_id": self.work.work_id, "target_conversation_key": A,
                "action": "enqueue", "message_id": "public-01",
                "instruction": "one queued instruction",
            })
            self.assertEqual(1, ChatInputQueue(self.bct.store).status(
                work_id=self.work.work_id,
                target_conversation_key=A)["counts"]["QUEUED"])
            await full.call_tool("queue_message", {
                "work_id": self.work.work_id, "target_conversation_key": A,
                "action": "claim", "claim_id": "mcp-claim-01",
            })
            self.assertEqual("CLAIMED", ChatInputQueue(self.bct.store).status(
                work_id=self.work.work_id, target_conversation_key=A)["head"]["state"])
            await full.call_tool("queue_message", {
                "work_id": self.work.work_id, "target_conversation_key": A,
                "action": "complete", "message_id": "public-01",
                "claim_id": "mcp-claim-01", "result_sha256": DIGEST,
            })
            self.assertEqual("DONE", ChatInputQueue(self.bct.store).status(
                work_id=self.work.work_id, target_conversation_key=A)["messages"][0]["state"])
            await full.call_tool("queue_message", {
                "work_id": self.other.work_id, "target_conversation_key": A,
                "action": "enqueue", "message_id": "foreign-work-01",
                "instruction": "same durable identity rules, no owner gate",
            })
            self.assertEqual(1, ChatInputQueue(self.bct.store).status(
                work_id=self.other.work_id, target_conversation_key=A)["counts"]["QUEUED"])
            with self.assertRaisesRegex(Exception, "TARGET_INVALID"):
                await full.call_tool("queue_message", {
                    "work_id": self.work.work_id, "target_conversation_key": "N4",
                    "action": "enqueue", "message_id": "invalid-target",
                    "instruction": "must retain exact conversation identity",
                })
        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
