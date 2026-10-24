import hashlib
import json
import unittest
from unittest.mock import Mock
from bct.features.rcc import RelayBrowserFeature
from bct.core.models import FeatureRequest, ConfirmedFailure
from bct.integrations.rcc import RelayUnavailable, RelayEffectUnknown

TEXT = "한글😀\\nworker result"
SHA = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
LENGTH = len(TEXT.encode("utf-16-le")) // 2
DID = "fixture-1"

class ReadContractTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.feature = RelayBrowserFeature(client=self.client)
        self.feature.delivery_ledger = Mock()
        self.row = dict(instance_id="fixture-instance",
            manager_conversation_key="11111111-1111-1111-1111-111111111111",
            worker_conversation_key="22222222-2222-2222-2222-222222222222",
            request_sha256="a"*64, state="RETURNED",
            response_sha256=SHA, response_length=LENGTH)
        self.feature.delivery_ledger.get_for_work.return_value = self.row
        self.request = FeatureRequest("relay_browser", "fixture-instance",
            dict(command="delivery-response-read",instance_id="fixture-instance",
                 extra=dict(deliveryId=DID,workId="fixture-work"),text="",timeout_s=1.0),
            ("fixture-resource",), {})

    def execute(self, response):
        self.client.request.return_value = response
        got = self.feature._execute_delivery(self.request)
        self.assertEqual(self.feature.delivery_ledger.observe.call_count, 0)
        self.assertEqual(self.client.request.call_args.kwargs["command"], "delivery-response-read")
        self.assertEqual(self.client.request.call_args.kwargs["extra"]["workId"], "fixture-work")
        json.dumps(got.output, ensure_ascii=False)
        return got

    def test_success_utf16_sha_ledger(self):
        got=self.execute(dict(ok=True,deliveryId=DID,responseText=TEXT,
            responseSha256=SHA,responseLength=LENGTH))
        self.assertEqual(got.output["responseText"],TEXT)
        self.assertTrue(got.output["ledgerMatch"])
        self.assertEqual(got.output["responseLength"],LENGTH)
        self.assertEqual(got.output["responseSha256"],SHA)

    def test_codes(self):
        for code in ("ACCESS_DENIED","NOT_FOUND","NOT_RETAINED","UNAVAILABLE",
                     "INTEGRITY_MISMATCH"):
            with self.subTest(code=code):
                got=self.execute(dict(ok=False,deliveryId=DID,code=code))
                self.assertEqual(got.output["code"],code)

    def test_transport_errors_are_read_unavailable(self):
        for error in (RelayUnavailable("offline"),RelayEffectUnknown("unknown")):
            with self.subTest(error=type(error).__name__):
                self.client.request.side_effect=error
                got=self.feature._execute_delivery(self.request)
                self.assertEqual(got.output["code"],"UNAVAILABLE")
                self.assertEqual(self.feature.delivery_ledger.observe.call_count,0)
        self.client.request.side_effect=None

    def test_response_id_mismatch(self):
        got=self.execute(dict(ok=True,deliveryId="wrong",responseText=TEXT,
            responseSha256=SHA,responseLength=LENGTH))
        self.assertEqual(got.output["code"],"UNAVAILABLE")

    def test_ledger_integrity_fence(self):
        with self.assertRaises(ConfirmedFailure):
            self.execute(dict(ok=True,deliveryId=DID,responseText=TEXT,
                responseSha256=SHA,responseLength=LENGTH+1))
        self.row["response_sha256"]="f"*64
        with self.assertRaises(ConfirmedFailure):
            self.execute(dict(ok=True,deliveryId=DID,responseText=TEXT,
                responseSha256=SHA,responseLength=LENGTH))

    def test_unauthorized_work_denied_before_rcc(self):
        from bct.core.models import ConflictError
        self.feature.delivery_ledger.get_for_work.side_effect=ConflictError("denied")
        with self.assertRaisesRegex(ConfirmedFailure,"ACCESS_DENIED"):
            self.feature._execute_delivery(self.request)
        self.client.request.assert_not_called()

if __name__=="__main__":unittest.main()
