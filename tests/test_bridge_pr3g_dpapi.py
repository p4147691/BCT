import os
import secrets
import unittest

from bct.core import bridge_pr3g_dpapi as dpapi


@unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
class DpapiTests(unittest.TestCase):
    context = b"bct-bridge-peer|fixture-host|generation=1"

    def test_round_trip_is_bound_to_context(self):
        secret = secrets.token_bytes(32)
        protected = dpapi.protect(secret, context=self.context)
        self.assertNotEqual(secret, protected)
        self.assertEqual(secret, dpapi.unprotect(protected, context=self.context))
        with self.assertRaisesRegex(RuntimeError, "DPAPI_DENIED"):
            dpapi.unprotect(protected, context=b"bct-bridge-peer|fixture-host|generation=2")

    def test_invalid_values_are_rejected_before_windows_api(self):
        with self.assertRaisesRegex(ValueError, "DPAPI_ARGUMENT_INVALID"):
            dpapi.protect(b"x", context=self.context)
        with self.assertRaisesRegex(ValueError, "DPAPI_ARGUMENT_INVALID"):
            dpapi.unprotect(b"", context=self.context)
        with self.assertRaisesRegex(ValueError, "DPAPI_ARGUMENT_INVALID"):
            dpapi.protect(secrets.token_bytes(32), context=b"")


if __name__ == "__main__":
    unittest.main()
