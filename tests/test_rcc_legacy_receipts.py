import unittest
from bct.features.rcc_legacy_receipts import legacy_send_effect_state, legacy_send_ack_verified

class LegacyReceiptTests(unittest.TestCase):
    def test_historical_send_effect(self):
        self.assertEqual("SUBMITTED", legacy_send_effect_state("send", {"effectState":"submitted"}, ""))
        self.assertEqual("QUEUED", legacy_send_effect_state("send-message", {"effectState":"submitted"}, "QUEUED"))
    def test_historical_ack(self):
        self.assertTrue(legacy_send_ack_verified("send", {"type":"host:ack", "submitted":True}, "SUBMITTED"))
        self.assertFalse(legacy_send_ack_verified("send", {"type":"host:ack", "submitted":False}, "SUBMITTED"))
        self.assertTrue(legacy_send_ack_verified("send-message", {"type":"host:ack"}, ""))

if __name__ == "__main__": unittest.main()