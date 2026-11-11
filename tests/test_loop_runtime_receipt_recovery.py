"""Run the production recovery-loop body for one crash-recovery pass."""
import ast
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bct.core.models import Work
from bct.core.store import Store
from bct.loop_store import LoopStore
from bct.loop_self_outbox import LoopSelfOutbox
from bct.mcp_server import MCP_PRINCIPAL_ID
from bct.status_views import status_view
from test_loop_self_dispatch import OWNER, production_snapshot


class LoopRuntimeReceiptRecoveryTests(unittest.TestCase):
    def run_pass(self, receipt_result):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            store.create_work(Work(work_id="w", request_summary="receipt recovery",
                                  roots=(root,), actions=frozenset({"browser"}),
                                  owner_principal_id=MCP_PRINCIPAL_ID))
            LoopStore(store).start(work_id="w", direction_id="d", task_id="t",
                                  owner=OWNER, plan_text="plan")
            outbox = LoopSelfOutbox(store)
            queued = outbox.queue(work_id="w", epoch=1, step=0, owner=OWNER, message="step")
            outbox.reserve(work_id="w", epoch=1, step=0, owner=OWNER)
            receipt = Mock()
            if receipt_result is None:
                receipt.side_effect = KeyError("original receipt missing")
            else:
                receipt.return_value = SimpleNamespace(
                    state=SimpleNamespace(value="FINISHED"),
                    outcome=SimpleNamespace(value=receipt_result))
            store.get_operation_for = receipt
            operations = SimpleNamespace(_features={"browser": Mock()}, run=Mock())
            stop = SimpleNamespace(done=False)
            stop.is_set = lambda: stop.done
            stop.wait = lambda _: setattr(stop, "done", True)
            state = {"loop_recipe_recovery": {"runs": 0}}
            source = Path(__file__).resolve().parents[1] / "src/bct/runtime_server.py"
            tree = ast.parse(source.read_text(encoding="utf-8"))
            body = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                        and n.name == "loop_recipe_recovery_loop")
            namespace = dict(__package__="bct", __name__="bct.runtime_server",
                             bct=SimpleNamespace(store=store, operations=operations),
                             recovery_stop=stop, state=state, time=time,
                             runtime_root=Path(root), status_view=status_view,
                             build_monitor_state=lambda **_: production_snapshot())
            with patch("bct.loop_self_continuation.LoopSelfContinuation") as continuation:
                continuation.return_value.observe_once.return_value = {"status": "OBSERVED"}
                exec(compile(ast.Module(body=[body], type_ignores=[]), str(source), "exec"), namespace)
                namespace["loop_recipe_recovery_loop"]()
                self.assertIsNone(state["loop_recipe_recovery"].get("last_error"))
                operations.run.assert_not_called()
                receipt.assert_called_once_with(operation_id=queued["operation_id"],
                                                work_id="w", principal_id=MCP_PRINCIPAL_ID)
                self.assertEqual(continuation.return_value.observe_once.call_count,
                                 1 if receipt_result == "APPLIED" else 0)
            return outbox.get(work_id="w", epoch=1, step=0)["state"]

    def test_crash_after_applied_receipt_resumes_observation_without_send(self):
        self.assertEqual(self.run_pass("APPLIED"), "DELIVERED")

    def test_missing_or_unknown_receipt_never_replays(self):
        self.assertEqual(self.run_pass(None), "UNKNOWN")
        self.assertEqual(self.run_pass("UNKNOWN"), "UNKNOWN")

    def test_definitive_not_applied_never_implicitly_requeues(self):
        self.assertEqual(self.run_pass("NOT_APPLIED"), "NOT_APPLIED")
