import unittest
from bct.features.window_layout_identity import resolve_chrome_window

class IdentityProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tab={"tab_id":17,"window_id":23,"conversation_key":"uuid-1"}
        self.fingerprint={"hwnd":"1234","pid":987,"process_start_time_utc":"timestamp"}
        self.rcc=[{"window_id":23,"tabs":[self.tab],"desktop_fingerprint":self.fingerprint}]
        self.desktop=[self.fingerprint]
    def test_exact_mapping(self):
        got=resolve_chrome_window(self.tab,self.rcc,self.desktop)
        self.assertEqual((got["hwnd"],got["pid"],got["tab_id"]),("1234",987,17))
    def test_missing_bridge_rejected(self):
        del self.rcc[0]["desktop_fingerprint"]
        with self.assertRaises(ValueError):
            resolve_chrome_window(self.tab,self.rcc,self.desktop)
    def test_stale_pid_rejected(self):
        self.desktop[0]={**self.fingerprint,"pid":988}
        with self.assertRaises(ValueError):
            resolve_chrome_window(self.tab,self.rcc,self.desktop)
    def test_ambiguous_window_rejected(self):
        self.rcc.append(self.rcc[0].copy())
        with self.assertRaises(ValueError):
            resolve_chrome_window(self.tab,self.rcc,self.desktop)
    def test_reassigned_tab_rejected(self):
        self.rcc[0]["tabs"]=[]
        with self.assertRaises(ValueError):
            resolve_chrome_window(self.tab,self.rcc,self.desktop)
