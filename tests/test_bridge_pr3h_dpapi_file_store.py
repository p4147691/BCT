import secrets
import tempfile
import unittest
from pathlib import Path

from bct.core.bridge_pr3h_dpapi_file_store import DpapiFileSecretStore


class DpapiFileSecretStoreTests(unittest.TestCase):
    peer = "fixture-peer"; generation = 1

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "owned"; self.directory.mkdir()
        self.store = DpapiFileSecretStore(self.directory)

    def test_round_trip_is_create_only_and_does_not_expose_secret(self):
        secret = secrets.token_bytes(32)
        self.store.put_secret(self.peer, self.generation, secret)
        self.assertEqual(secret, self.store.get_secret(self.peer, self.generation))
        only_file = next(self.directory.iterdir())
        self.assertNotIn(secret, only_file.read_bytes())
        self.assertNotIn(self.peer, only_file.name)
        with self.assertRaises(FileExistsError):
            self.store.put_secret(self.peer, self.generation, secrets.token_bytes(32))
        self.assertEqual(secret, self.store.get_secret(self.peer, self.generation))

    def test_context_and_cleanup_are_exact(self):
        first = secrets.token_bytes(32); second = secrets.token_bytes(32)
        self.store.put_secret(self.peer, 1, first)
        self.store.put_secret(self.peer, 2, second)
        self.assertIsNone(self.store.get_secret("other-peer", 1))
        self.store.delete_secret(self.peer, 1)
        self.assertIsNone(self.store.get_secret(self.peer, 1))
        self.assertEqual(second, self.store.get_secret(self.peer, 2))

    def test_missing_directory_and_bad_arguments_are_denied(self):
        missing = DpapiFileSecretStore(self.directory / "missing")
        with self.assertRaisesRegex(RuntimeError, "PEER_SECRET_STORE_UNAVAILABLE"):
            missing.put_secret(self.peer, 1, secrets.token_bytes(32))
        with self.assertRaisesRegex(ValueError, "PEER_SECRET_STORE_ARGUMENT_INVALID"):
            self.store.put_secret("", 1, secrets.token_bytes(32))
        with self.assertRaisesRegex(ValueError, "PEER_SECRET_STORE_ARGUMENT_INVALID"):
            self.store.delete_secret(self.peer, 0)


if __name__ == "__main__":
    unittest.main()
