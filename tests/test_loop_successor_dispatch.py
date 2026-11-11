"""Isolated exact one-shot successor browser operations; no real RCC effects."""
import unittest
from types import SimpleNamespace
from bct.loop_store import LoopStateError
from bct.loop_successor_dispatch import LoopSuccessorDispatch
from test_loop_successor import SuccessorTests, snapshot, NEW


class FakeBrowser:
    def __init__(self):
        self.calls=[]
    def run(self,**kw):
        self.calls.append(kw)
        return SimpleNamespace(outcome=SimpleNamespace(value="APPLIED"))


class SuccessorDispatchTests(unittest.TestCase):
    """Reuse fixture helpers without rerunning every base test."""
    setUp=SuccessorTests.setUp
    prepare=SuccessorTests.prepare

    def test_create_and_initial_send_only_once(self):
        case=self.prepare()
        operations=FakeBrowser()
        dispatcher=LoopSuccessorDispatch(self.store,operations)
        created=dispatcher.create_once(work_id="w")
        self.assertEqual(created["operation_id"],case["create_op"])
        self.assertEqual(operations.calls[0]["arguments"]["command"],"create-chat-tab")
        self.assertEqual(self.ledger.get("w")["state"],"CREATE_DISPATCHING")
        with self.assertRaisesRegex(LoopStateError,"LOOP_SUCCESSOR_ALREADY_DISPATCHED"):
            dispatcher.create_once(work_id="w")
        self.created=case
        self.ledger.confirm_create(work_id="w",principal_id="principal",
                                   snapshot=snapshot(),now=162)
        outgoing=dispatcher.send_initial_once(
            work_id="w",snapshot=snapshot(),instruction="Continue same Work"
        )
        self.assertEqual(outgoing["operation_id"],case["send_op"])
        self.assertEqual(operations.calls[1]["arguments"]["create_operation_id"],
                         case["create_op"])
        self.assertEqual(operations.calls[1]["arguments"]["conversation_key"],"")
        with self.assertRaisesRegex(LoopStateError,"LOOP_SUCCESSOR_CREATE_NOT_CONFIRMED"):
            dispatcher.send_initial_once(
                work_id="w",snapshot=snapshot(),instruction="Continue again"
            )
        self.assertEqual(len(operations.calls),2)

    def test_bound_tab_never_receives_bootstrap_send(self):
        case=self.prepare()
        operations=FakeBrowser()
        dispatcher=LoopSuccessorDispatch(self.store,operations)
        dispatcher.create_once(work_id="w")
        self.created=case
        self.ledger.confirm_create(work_id="w",principal_id="principal",
                                   snapshot=snapshot(),now=162)
        with self.assertRaisesRegex(LoopStateError,"LOOP_SUCCESSOR_NOT_BLANK_TAB"):
            dispatcher.send_initial_once(
                work_id="w",snapshot=snapshot(key=NEW),
                instruction="unexpected",
            )
        self.assertEqual(len(operations.calls),1)


if __name__=="__main__":
    unittest.main()
