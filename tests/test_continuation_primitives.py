import unittest

from bct.continuation_primitives import (
    AlarmKind, ActionKind, ActionRequest, ContinuationContext, ContinuationDecision,
    ContinuationRoute, response_ready_alarm, wakeup_message,
)


class ContinuationPrimitiveTests(unittest.TestCase):
    def test_exact_terminal_input_ready_response_emits_alarm(self):
        alarm = response_ready_alarm(
            watch_ref="task-1:1", subject_ref="worker-uuid",
            expected_response_turn_id="turn-1", response_turn_id="turn-1",
            response_text="Completed.", response_complete=True, input_ready=True,
        )
        self.assertIsNotNone(alarm)
        self.assertEqual(AlarmKind.RESPONSE_READY, alarm.kind)
        request = ActionRequest(ActionKind.WAKEUP_MESSAGE, alarm, "manager")
        self.assertEqual("manager", request.recipient_role)

    def test_wrong_or_incomplete_observation_never_emits_alarm(self):
        base = dict(
            watch_ref="task-1:1", subject_ref="worker-uuid",
            expected_response_turn_id="turn-1", response_turn_id="turn-1",
            response_text="Completed.", response_complete=True, input_ready=True,
        )
        for change in (
            {"response_turn_id": "other"},
            {"response_complete": False},
            {"input_ready": False},
            {"response_text": None},
        ):
            self.assertIsNone(response_ready_alarm(**{**base, **change}))

    def test_delayed_recipe_context_keeps_named_roles_without_lookup(self):
        context = ContinuationContext.delayed_send(
            work_id="work-1", principal_id="owner-1", assignment_epoch=2,
            instance_id="worker-instance", conversation_key="worker-uuid",
            manager_conversation_key="manager-uuid",
            manager_instance_id="manager-instance",
        )
        self.assertEqual("worker-uuid", context.subject_ref)
        self.assertEqual("manager-uuid", context.recipients["manager"])
        record = context.as_legacy_record()
        self.assertEqual("worker-uuid", record["conversation_key"])
        self.assertEqual("manager-instance", record["manager_instance_id"])

    def test_wakeup_message_is_a_reference_without_a_send_or_decision(self):
        alarm = response_ready_alarm(
            watch_ref="task-1:1", subject_ref="worker-uuid",
            expected_response_turn_id="turn-1", response_turn_id="turn-1",
            response_text="Completed.", response_complete=True, input_ready=True,
        )
        request = wakeup_message(
            alarm=alarm,
            execution_ref="task-1:1",
        )
        self.assertEqual(ActionKind.WAKEUP_MESSAGE, request.kind)
        self.assertEqual("worker", request.recipient_role)
        self.assertEqual("task-1:1", request.payload)
        with self.assertRaisesRegex(ValueError, "REFERENCE_INVALID"):
            wakeup_message(alarm=alarm, execution_ref="")
