import unittest

from bct.chain_derived_tasks import dispatch_plan, validate_derived_tasks
from bct.chain_direction import validate_direction_assessment
from bct.chain_worker_preparation import (
    validate_worker_preparation, worker_preparation_operation_id,
)


def key(letter):
    return f"{letter * 8}-{letter * 4}-{letter * 4}-{letter * 4}-{letter * 12}"


MANAGER, WORKER, SUPERVISOR, SECOND = (key(letter) for letter in "abcd")


def task(task_id, classification, *, target="", depends_on=(), scopes=()):
    return {
        "task_id": task_id,
        "classification": classification,
        "summary": "bounded derived work " + task_id,
        "depends_on": list(depends_on),
        "target_conversation_key": target,
        "mutable_scopes": list(scopes),
    }


class DerivedTaskTests(unittest.TestCase):
    def test_direction_can_persist_an_initial_worker_preparation_without_guessing_uuid(self):
        assessment = {
            "answers": {}, "manager_conversation_key": MANAGER,
            "supervisor_conversation_key": SUPERVISOR,
            "network_name": "Project", "network_updates": [], "targets": [],
            "worker_preparations": [{
                "preparation_id": "initial-worker", "command": "create-chat-tab",
                "instance_id": "instance123", "window_id": 11,
                "instruction": "Implement the initial bounded task.",
                "display_name": "Initial Worker", "scope_name": "Project",
                "role_tags": ["Worker"], "arrange": None,
            }],
        }
        checked = validate_direction_assessment(assessment, decision="NEW_TASK")
        self.assertNotIn("worker_conversation_key", checked)
        self.assertEqual("initial-worker", checked["worker_preparations"][0]["preparation_id"])

    def test_worker_preparation_is_explicit_bounded_and_deterministic(self):
        value = validate_worker_preparation({
            "preparation_id": "independent-fix", "command": "create-chat-tab",
            "instance_id": "instance123", "window_id": 11,
            "instruction": "Fix the independent module.",
            "display_name": "Fix Worker", "scope_name": "Project",
            "role_tags": ["Worker"],
            "arrange": {"target_window_id": 12, "index": 0},
        })
        first = worker_preparation_operation_id(
            direction_id="direction-1", preparation_id=value["preparation_id"],
            stage="create",
        )
        self.assertEqual(first, worker_preparation_operation_id(
            direction_id="direction-1", preparation_id=value["preparation_id"],
            stage="create",
        ))
        with self.assertRaisesRegex(ValueError, "ROLE_CONFLICT"):
            validate_worker_preparation({**value, "role_tags": ["Worker", "Supervisor"]})

    def test_independent_tasks_are_ready_and_other_categories_are_deferred(self):
        tasks = validate_derived_tasks([
            task("fix", "INDEPENDENT", target=WORKER, scopes=["src/fix.py"]),
            task("self-check", "SELF"),
            task("risk", "RISK"),
            task("follow", "INDEPENDENT", target=SECOND, depends_on=["fix"]),
        ], target_keys={WORKER, SECOND})
        plan = dispatch_plan(tasks=tasks, targets=[
            {"conversation_key": WORKER}, {"conversation_key": SECOND},
        ])
        self.assertEqual({WORKER}, plan["ready_target_keys"])
        self.assertEqual("MANAGER_DECLARED", plan["classification"])
        self.assertCountEqual(["self-check", "risk", "follow"],
                              [item["task_id"] for item in plan["deferred"]])

    def test_rejects_shared_mutable_scope_for_parallel_work(self):
        with self.assertRaisesRegex(ValueError, "MUTABLE_SCOPE_CONFLICT"):
            validate_derived_tasks([
                task("first", "INDEPENDENT", target=WORKER, scopes=["src/shared.py"]),
                task("second", "INDEPENDENT", target=SECOND, scopes=["src/shared.py"]),
            ], target_keys={WORKER, SECOND})

    def test_rejects_dependency_cycle(self):
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_CYCLE"):
            validate_derived_tasks([
                task("first", "BLOCKED", depends_on=["second"]),
                task("second", "BLOCKED", depends_on=["first"]),
            ], target_keys=set())

    def test_direction_persists_validated_derived_tasks(self):
        assessment = {
            "answers": {}, "manager_conversation_key": MANAGER,
            "worker_conversation_key": WORKER,
            "supervisor_conversation_key": SUPERVISOR,
            "network_name": "Project", "network_updates": [],
            "targets": [
                {"conversation_key": WORKER, "role": "worker", "instruction": "Fix it."},
                {"conversation_key": SECOND, "role": "worker", "instruction": "Review it."},
            ],
            "derived_tasks": [
                task("fix", "INDEPENDENT", target=WORKER, scopes=["src/fix.py"]),
                task("review", "INDEPENDENT", target=SECOND, depends_on=["fix"]),
            ],
        }
        checked = validate_direction_assessment(assessment, decision="NEW_TASK")
        self.assertEqual("fix", checked["derived_tasks"][0]["task_id"])
        self.assertEqual(2, len(checked["derived_tasks"]))


if __name__ == "__main__":
    unittest.main()
