import unittest
from bct.features.window_layout_commands import plan_tab_move,plan_window_state_action

class CommandPlans(unittest.TestCase):
    def test_minimize_restore(self):
        for action in ("minimize","restore","maximize"):
            self.assertEqual(plan_window_state_action("a"*32,action),("desktop_window_manage",{"lease_id":"a"*32,"operation":action}))
    def test_lease_invalid(self):
        with self.assertRaises(ValueError): plan_window_state_action("bad","restore")
    def test_same_and_other_window_moves(self):
        key="11111111-2222-3333-4444-555555555555"
        base=dict(instance_id="a"*32,session_id="b"*32,tab_id=10,window_id=11,index=0,conversation_key=key,observed={"tab_id":10,"window_id":11,"conversation_key":key,"generating":False})
        for target in (11,12):
            capability, args=plan_tab_move(**base,target_window_id=target)
            self.assertEqual(capability,"relay_browser")
            self.assertEqual(args["target_window_id"],target)
    def test_identity_and_generating_protected(self):
        key="11111111-2222-3333-4444-555555555555"
        base=dict(instance_id="a"*32,session_id="b"*32,tab_id=10,window_id=11,target_window_id=12,index=0,conversation_key=key,observed={"tab_id":10,"window_id":11,"conversation_key":key,"generating":True})
        with self.assertRaises(ValueError): plan_tab_move(**base)
        base["observed"]={**base["observed"],"generating":False,"window_id":99}
        with self.assertRaises(ValueError): plan_tab_move(**base)

class IntegratedGatewayTests(unittest.TestCase):
    def test_one_invoke_and_independent_readback(self):
        from bct.features.window_layout_commands import execute_verified_once
        calls = []
        def invoke(cap, op, args):
            calls.append((cap, op, args))
            return {"operation_id":op,"outcome":"APPLIED","state":"FINISHED"}
        result = execute_verified_once(operation_id="isolated-window-1", capability="desktop_window_manage",
            arguments={"operation":"restore","lease_id":"a"*32}, invoke=invoke,
            readback=lambda:{"restored":True}, verify=lambda x:x["restored"])
        self.assertEqual(result["outcome"],"APPLIED")
        self.assertEqual(len(calls),1)
    def test_unknown_no_retry(self):
        from bct.features.window_layout_commands import execute_verified_once
        calls = []
        def invoke(cap, op, args):
            calls.append(op)
            return {"operation_id":op,"outcome":"UNKNOWN","state":"FINISHED"}
        r=execute_verified_once(operation_id="isolated-tab-1",capability="relay_browser",arguments={},
            invoke=invoke,readback=lambda:None,verify=lambda x:False)
        self.assertEqual((r["outcome"],r["retry"],len(calls)),("UNKNOWN",False,1))
    def test_readback_mismatch_remains_unknown(self):
        from bct.features.window_layout_commands import execute_verified_once
        r=execute_verified_once(operation_id="isolated-window-2",capability="desktop_window_manage",arguments={},
            invoke=lambda cap,op,args:{"operation_id":op,"outcome":"APPLIED","state":"FINISHED"},
            readback=lambda:{"restored":False},verify=lambda x:x["restored"])
        self.assertEqual(r["outcome"],"UNKNOWN")
