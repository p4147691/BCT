import unittest
from bct.core.models import Work, PreconditionError
from bct.features.rcc import RelayBrowserFeature

class RCCSendSchemaContract(unittest.TestCase):
    def setUp(self):
        self.feature = RelayBrowserFeature()
        self.work = Work("n38-contract", "read-only fixture", ("D:\\BCT",), frozenset({"relay_browser"}), "owner")
        self.instance = "6174664e1c1b4e6db1d4729c841db3c9"

    def test_send_missing_fields_keep_exact_legacy_code(self):
        for extra in ({"tab_id": 594835763, "text": "test"},
                      {"target": "594835763", "text": "test"},
                      {"to": "target"}, {"text": "test"}):
            with self.subTest(extra=extra), self.assertRaises(PreconditionError) as captured:
                self.feature.prepare(work=self.work, arguments={"command": "send", "instance_id": self.instance, **extra})
            self.assertEqual(str(captured.exception), "RCC_SEND_TARGET_AND_TEXT_REQUIRED")

    def test_send_generic_resource_is_unchanged(self):
        prepared = self.feature.prepare(work=self.work, arguments={"command": "send", "instance_id": self.instance, "to": "target", "text": "hello"})
        self.assertEqual(prepared.resources, ("rcc-instance:" + self.instance,))

    def test_exact_tab_resource_and_invalid_identity(self):
        args = {"command": "send-to-tab", "instance_id": self.instance, "session_id": "786b7b6b9671446f85497e097111e5ec", "tab_id": 594835763, "window_id": 594835507, "conversation_key": "6adcfacf-c7e8-83ee-8ecc-2ff0dbfe3b54", "text": "test"}
        prepared = self.feature.prepare(work=self.work, arguments=args)
        self.assertEqual(prepared.resources, ("rcc-instance:" + self.instance + ":direct-tab:594835763",))
        for field, value in (("session_id", "invalid"), ("conversation_key", "bad"), ("tab_id", 0)):
            with self.subTest(field=field), self.assertRaises(PreconditionError):
                self.feature.prepare(work=self.work, arguments={**args, field: value})

    def test_delivery_start_rejects_invalid_identities(self):
        base = {"command": "delivery-start", "instance_id": self.instance, "delivery_id": "d1", "manager_conversation_key": "6adbfb63-ddb0-83ee-8a42-dcdb8e56874c", "worker_conversation_key": "6adbfb66-57dc-83e8-b321-0bfe59aa013f", "text": "test"}
        for field, value in (("delivery_id", ""), ("worker_conversation_key", "invalid"), ("manager_conversation_key", base["worker_conversation_key"])):
            with self.subTest(field=field), self.assertRaises(PreconditionError):
                self.feature.prepare(work=self.work, arguments={**base, field: value})
if __name__ == "__main__": unittest.main()
