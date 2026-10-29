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
