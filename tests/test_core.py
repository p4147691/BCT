from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from bct import BCT
from bct.core.models import (
    AuthorizationError, ConflictError, FeatureRequest, FeatureResult, Outcome,
    Principal, UnknownEffectError,
)


class CountingFeature:
    capability = "write"

    def __init__(self):
        self.calls = 0

    def prepare(self, *, work, arguments):
        resource = str(arguments.get("resource", "counter"))
        return FeatureRequest(self.capability, resource, dict(arguments), ("counter:" + resource,))

    def execute(self, request):
        self.calls += 1
        return FeatureResult(Outcome.APPLIED, {"calls": self.calls})


class UnknownFeature(CountingFeature):
    def execute(self, request):
        self.calls += 1
        raise UnknownEffectError("lost result after dispatch")


class BlockingFeature(CountingFeature):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def execute(self, request):
        self.calls += 1
        self.started.set()
        if not self.release.wait(5):
            raise RuntimeError("test release timeout")
        return FeatureResult(Outcome.APPLIED, {"calls": self.calls})


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.policy = self.root / "bct.toml"
        self.policy.write_text(
            '[policy]\nnormal_actions=["read","write","test","git_commit"]\n'
            'approval_actions=["deploy"]\n', encoding="utf-8"
        )
        self.bct = BCT(state_path=self.root / "state.sqlite", policy_path=self.policy)
        self.owner = Principal("owner", "test", frozenset({"read", "write", "test", "git_commit"}))
        self.other = Principal("other", "test", frozenset({"read", "write", "test", "git_commit"}))
        self.bct.create_work(work_id="work-1", request_summary="test", roots=[str(self.root)],
                             actions=["read", "write", "test", "git_commit"], principal=self.owner)

    def tearDown(self):
        self.temp.cleanup()

    def replace_feature(self, feature):
        self.bct.operations._features[feature.capability] = feature

    def test_duplicate_operation_executes_once(self):
        feature = CountingFeature()
        self.replace_feature(feature)
        first = self.bct.operations.run(
            principal=self.owner, work_id="work-1", operation_id="op-1",
            capability="write", arguments={"resource": "x"},
        )
        second = self.bct.operations.run(
            principal=self.owner, work_id="work-1", operation_id="op-1",
            capability="write", arguments={"resource": "x"},
        )
        self.assertEqual(Outcome.APPLIED, first.outcome)
        self.assertTrue(second.duplicate)
        self.assertEqual(1, feature.calls)

    def test_background_begin_and_resume_execute_exactly_once(self):
        feature = CountingFeature()
        self.replace_feature(feature)
        call = {
            "principal": self.owner, "work_id": "work-1", "operation_id": "background-1",
            "capability": "write", "arguments": {"resource": "background"},
        }
        created, pending = self.bct.operations.begin(**call)
        repeated, duplicate = self.bct.operations.begin(**call)
        self.assertTrue(created)
        self.assertFalse(repeated)
        self.assertEqual("RUNNING", pending.state.value)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(0, feature.calls)

        completed = self.bct.operations.resume(**call)
        completed_again = self.bct.operations.resume(**call)
        self.assertEqual(Outcome.APPLIED, completed.outcome)
        self.assertTrue(completed_again.duplicate)
        self.assertEqual(1, feature.calls)

    def test_background_resume_without_begin_is_not_applied(self):
        feature = CountingFeature()
        self.replace_feature(feature)
        result = self.bct.operations.resume(
            principal=self.owner, work_id="work-1", operation_id="background-unprepared",
            capability="write", arguments={"resource": "unprepared"},
        )
        self.assertEqual(Outcome.NOT_APPLIED, result.outcome)
        self.assertEqual("BACKGROUND_OPERATION_NOT_PREPARED", result.error)
        self.assertEqual(0, feature.calls)

    def test_same_operation_id_with_different_request_is_denied(self):
        self.replace_feature(CountingFeature())
        self.bct.operations.run(principal=self.owner, work_id="work-1", operation_id="op-1",
                                capability="write", arguments={"resource": "x"})
        with self.assertRaises(ConflictError):
            self.bct.operations.run(principal=self.owner, work_id="work-1", operation_id="op-1",
                                    capability="write", arguments={"resource": "y"})

    def test_wrong_principal_cannot_run_or_read_result(self):
        self.replace_feature(CountingFeature())
        self.bct.operations.run(principal=self.owner, work_id="work-1", operation_id="op-1",
                                capability="write", arguments={"resource": "x"})
        with self.assertRaises(AuthorizationError):
            self.bct.operations.run(principal=self.other, work_id="work-1", operation_id="op-2",
                                    capability="write", arguments={"resource": "x"})
        with self.assertRaises(ConflictError):
            self.bct.store.get_operation_for(operation_id="op-1", work_id="work-1",
                                             principal_id=self.other.principal_id)

    def test_unknown_effect_blocks_new_operation_for_same_resource(self):
        feature = UnknownFeature()
        self.replace_feature(feature)
        first = self.bct.operations.run(principal=self.owner, work_id="work-1", operation_id="op-1",
                                        capability="write", arguments={"resource": "x"})
        self.assertEqual(Outcome.UNKNOWN, first.outcome)
        with self.assertRaises(ConflictError):
            self.bct.operations.run(principal=self.owner, work_id="work-1", operation_id="op-2",
                                    capability="write", arguments={"resource": "x"})
        self.assertEqual(1, feature.calls)

    def test_concurrent_writer_for_same_resource_is_denied(self):
        feature = BlockingFeature()
        self.replace_feature(feature)
        result = []

        def first_writer():
            result.append(self.bct.operations.run(
                principal=self.owner, work_id="work-1", operation_id="op-1",
                capability="write", arguments={"resource": "x"},
            ))

        thread = threading.Thread(target=first_writer)
        thread.start()
        self.assertTrue(feature.started.wait(5))
        try:
            with self.assertRaises(ConflictError):
                self.bct.operations.run(
                    principal=self.owner, work_id="work-1", operation_id="op-2",
                    capability="write", arguments={"resource": "x"},
                )
        finally:
            feature.release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(Outcome.APPLIED, result[0].outcome)
        self.assertEqual(1, feature.calls)

    def test_node_properties_and_connection_are_independent_of_work(self):
        node = self.bct.identity.create_node(node_id="node-1", name="EXEC1", role="EXEC", group="A")
        connection = self.bct.identity.replace_connection(
            connection_id="browser-1", node_id="node-1", kind="browser",
            instance="tab-1", endpoint="conversation-1", expected_generation=None,
        )
        updated = self.bct.identity.update_node(
            node_id="node-1", expected_revision=node["revision"],
            name="Builder", role="REVIEW", group="B",
        )
        replaced = self.bct.identity.replace_connection(
            connection_id="browser-1", node_id="node-1", kind="browser",
            instance="tab-2", endpoint="conversation-2",
            expected_generation=connection["generation"],
        )
        work = self.bct.store.get_work("work-1")
        self.assertEqual("owner", work.owner_principal_id)
        self.assertEqual("Builder", updated["name"])
        self.assertEqual(2, replaced["generation"])
        with self.assertRaises(ConflictError):
            self.bct.identity.replace_connection(
                connection_id="browser-1", node_id="node-1", kind="browser",
                instance="tab-3", endpoint="conversation-3", expected_generation=1,
            )

    def test_handoff_requires_no_unresolved_operation(self):
        self.replace_feature(UnknownFeature())
        self.bct.operations.run(principal=self.owner, work_id="work-1", operation_id="op-1",
                                capability="write", arguments={"resource": "x"})
        with self.assertRaises(ConflictError):
            self.bct.identity.handoff_work(work_id="work-1", old_principal_id="owner",
                                           new_principal_id="other", expected_epoch=1)

    def test_handoff_after_terminal_released_operation(self):
        self.replace_feature(CountingFeature())
        self.bct.operations.run(principal=self.owner, work_id="work-1", operation_id="op-1",
                                capability="write", arguments={"resource": "x"})
        handed = self.bct.identity.handoff_work(work_id="work-1", old_principal_id="owner",
                                                new_principal_id="other", expected_epoch=1)
        self.assertEqual("other", handed.owner_principal_id)
        self.assertEqual(2, handed.assignment_epoch)
        prior = self.bct.store.get_operation_for(operation_id="op-1", work_id="work-1",
                                                  principal_id="other")
        self.assertEqual(Outcome.APPLIED, prior.outcome)


if __name__ == "__main__":
    unittest.main()
