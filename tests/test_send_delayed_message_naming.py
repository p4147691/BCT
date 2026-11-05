"""Public/function names align while existing request and lock identity survives."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bct.core.models import Outcome, PreconditionError
from bct.features.rcc import BrowserFeature
from bct.mcp_server import build_mcp
from test_lightweight_mcp import DummyOperations


class SendDelayedMessagePublicNameTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_public_name_has_matching_function_and_no_old_alias(self):
        operations = DummyOperations()
        server = build_mcp(SimpleNamespace(operations=operations))
        names = {tool.name for tool in await server.list_tools()}
        self.assertIn("bct_send_delayed_message", names)
        self.assertNotIn("bct_delayed_send_message", names)
        tool = server._tool_manager.get_tool("bct_send_delayed_message")
        self.assertEqual("bct_send_delayed_message", tool.fn.__name__)
        await server.call_tool("bct_send_delayed_message", {"work_id": "W", "task_id": "T"})
        self.assertEqual(1, len(operations.called))
        call = operations.called[0]
        self.assertEqual("send-delayed-message", call["arguments"]["command"])
        self.assertTrue(call["operation_id"].startswith("send-delayed-"))

    async def test_old_public_call_does_not_dispatch(self):
        operations = DummyOperations()
        server = build_mcp(SimpleNamespace(operations=operations))
        with self.assertRaises(Exception):
            await server.call_tool("bct_delayed_send_message", {"work_id": "W", "task_id": "T"})
        self.assertEqual([], operations.called)


class SendDelayedMessageHistoricalRequestTests(unittest.TestCase):
    def setUp(self):
        self.work = SimpleNamespace(work_id="W")
        self.feature = BrowserFeature(Mock())
        self.arguments = {"command": "send-delayed-message", "task_id": "T"}

    def test_new_request_uses_existing_watch_lock_and_cancel_identity(self):
        request = self.feature.prepare(work=self.work, arguments=self.arguments)
        self.assertEqual("send-delayed-message", request.arguments["command"])
        self.assertEqual("delayed-send:W:T", request.target)
        self.assertEqual(("delayed-send:W:T",), request.resources)
        cancel = self.feature.prepare(work=self.work, arguments={
            "command": "delayed-send-cancel", "task_id": "T", "generation": 1})
        self.assertEqual(request.resources, cancel.resources)

    def test_old_command_cannot_prepare_a_new_request(self):
        with self.assertRaisesRegex(PreconditionError, "RCC_COMMAND_NOT_ALLOWED"):
            self.feature.prepare(work=self.work, arguments={
                **self.arguments, "command": "delayed-send-message"})

    def test_existing_prepared_request_preserves_original_command_and_id(self):
        prepared = self.feature.prepare(work=self.work, arguments=self.arguments)
        historical = replace(prepared, operation_id="original-old-arm", arguments={
            **prepared.arguments, "command": "delayed-send-message"})
        self.feature.store = Mock()
        self.feature.store.get_work.return_value = self.work
        with patch("bct.send_delayed_message.SendDelayedMessageService") as service:
            service.return_value.prearm.return_value = {
                "task_id": "T", "state": "WATCHING", "generation": 1, "created": False}
            result = self.feature.execute(historical)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("delayed-send-message", result.evidence["command"])
        service.return_value.prearm.assert_called_once()
        self.assertEqual("original-old-arm", service.return_value.prearm.call_args.kwargs["operation_id"])
        self.assertEqual("T", service.return_value.prearm.call_args.kwargs["task_id"])


if __name__ == "__main__":
    unittest.main()
