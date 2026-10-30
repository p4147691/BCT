import unittest
from bct.features.window_layout_receipts import classify_window_readback, classify_tab_readback

class ReadbackTests(unittest.TestCase):
    def test_exact_geometry(self):
        a={"x":-1920,"y":40,"width":960,"height":520}
        self.assertEqual(classify_window_readback(a,a,same_process=True,operation_finished=True),"APPLIED")
    def test_geometry_uncertain_never_not_applied(self):
        a={"x":0,"y":0,"width":960,"height":520}
        for observed in (None,{"x":1,"y":0,"width":960,"height":520}):
            self.assertEqual(classify_window_readback(a,observed,same_process=True,operation_finished=True),"UNKNOWN")
        self.assertEqual(classify_window_readback(a,a,same_process=False,operation_finished=True),"UNKNOWN")
    def test_tab_identity(self):
        a={"tab_id":42,"window_id":12,"tab_index":1,"conversation_key":"abc"}
        args=dict(expected_tab_id=42,expected_window_id=12,expected_index=1,expected_conversation_key="abc",same_session=True,operation_finished=True)
        self.assertEqual(classify_tab_readback(observed=a,**args),"APPLIED")
        self.assertEqual(classify_tab_readback(observed={**a,"window_id":13},**args),"UNKNOWN")
        self.assertEqual(classify_tab_readback(observed=a,**{**args,"same_session":False}),"UNKNOWN")
if __name__=="__main__":
    unittest.main()
