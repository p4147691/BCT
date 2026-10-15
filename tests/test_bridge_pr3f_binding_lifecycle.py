import base64
import hashlib
import json
import secrets
import tempfile
import unittest
from pathlib import Path

from bct.core.bridge_pr3b_auth import ORIGIN
from bct.core.bridge_pr3e_peer_adapter import PeerAdapter, make_peer_proof
from bct.core.bridge_pr3f_binding_lifecycle import BindingLifecycle
from bct.core.bridge_pr3h_dpapi_file_store import DpapiFileSecretStore
from bct.core.models import ConflictError
from bct.core.store import Store


class _MemorySecrets:
    def __init__(self):
        self.values = {}
        self.fail_put = self.fail_delete = False

    def put_secret(self, peer_id, binding_generation, secret):
        if self.fail_put:
            raise RuntimeError("backend unavailable")
        if (peer_id, binding_generation) in self.values:
            raise RuntimeError("already provisioned")
        self.values[(peer_id, binding_generation)] = secret

    def get_secret(self, peer_id, binding_generation):
        return self.values.get((peer_id, binding_generation))

    def delete_secret(self, peer_id, binding_generation):
        if self.fail_delete:
            raise RuntimeError("backend unavailable")
        self.values.pop((peer_id, binding_generation), None)


class BindingLifecycleTests(unittest.TestCase):
    peer_id = "fixture-bridge-host"
    launcher = hashlib.sha256(b"bridge-host").hexdigest()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite"
        self.secrets = _MemorySecrets()
        self.lifecycle = BindingLifecycle(Store(self.path), self.secrets)

    def provision(self, generation=1, secret=None):
        return self.lifecycle.provision(self.peer_id, binding_generation=generation,
                                        launcher_sha256=self.launcher,
                                        secret=secret or secrets.token_bytes(32))

    def test_provision_has_no_default_secret_or_sqlite_secret(self):
        with self.assertRaisesRegex(ValueError, "PEER_SECRET_STORE_REQUIRED"):
            BindingLifecycle(Store(Path(self.temp.name) / "other.sqlite"), None)
        value = self.provision(); self.assertEqual("ACTIVE", value.state)
        self.assertIsNotNone(self.lifecycle.resolve_peer_binding(self.peer_id))
        dump = self.path.read_bytes()
        self.assertNotIn(self.secrets.values[(self.peer_id, 1)], dump)

    def test_rotation_retires_old_binding_and_old_frame_is_denied(self):
        old_secret = secrets.token_bytes(32); self.provision(secret=old_secret)
        new_secret = secrets.token_bytes(32)
        self.lifecycle.rotate(self.peer_id, binding_generation=2, launcher_sha256=self.launcher,
                              secret=new_secret)
        current = self.lifecycle.resolve_peer_binding(self.peer_id)
        self.assertEqual(2, current.binding_generation)
        self.assertEqual(new_secret, current.secret)
        self.assertNotIn((self.peer_id, 1), self.secrets.values)
        self.assertEqual(new_secret, self.secrets.values[(self.peer_id, 2)])
        with self.assertRaisesRegex(ConflictError, "PEER_BINDING_DENIED"):
            self.lifecycle.rotate(self.peer_id, binding_generation=4, launcher_sha256=self.launcher,
                                  secret=secrets.token_bytes(32))

    def test_revoke_fails_closed_even_when_external_delete_fails(self):
        self.provision(); self.secrets.fail_delete = True
        self.assertEqual("REVOKED", self.lifecycle.revoke(self.peer_id).state)
        self.assertIsNone(self.lifecycle.resolve_peer_binding(self.peer_id))
        self.secrets.fail_delete = False
        with self.assertRaisesRegex(ConflictError, "PEER_BINDING_DENIED"):
            self.lifecycle.provision(self.peer_id, binding_generation=1,
                                     launcher_sha256=self.launcher,
                                     secret=secrets.token_bytes(32))

    def test_secret_backend_failures_leave_no_active_binding(self):
        self.secrets.fail_put = True
        with self.assertRaisesRegex(ConflictError, "PEER_BINDING_DENIED"):
            self.provision()
        self.assertIsNone(self.lifecycle.resolve_peer_binding(self.peer_id))

    def test_create_only_secret_store_prevents_duplicate_overwrite(self):
        original = secrets.token_bytes(32); self.provision(secret=original)
        with self.assertRaisesRegex(ConflictError, "PEER_BINDING_DENIED"):
            self.lifecycle.provision(self.peer_id, binding_generation=1,
                                     launcher_sha256=self.launcher,
                                     secret=secrets.token_bytes(32))
        self.assertEqual(original, self.lifecycle.resolve_peer_binding(self.peer_id).secret)

    def test_metadata_survives_reopen_but_requires_injected_secret_store(self):
        secret = secrets.token_bytes(32); self.provision(secret=secret)
        reopened = BindingLifecycle(Store(self.path), self.secrets)
        self.assertEqual(secret, reopened.resolve_peer_binding(self.peer_id).secret)
        missing = BindingLifecycle(Store(self.path), _MemorySecrets())
        self.assertIsNone(missing.resolve_peer_binding(self.peer_id))

    def test_lifecycle_is_compatible_with_peer_adapter_provider_contract(self):
        secret = secrets.token_bytes(32); self.provision(secret=secret)
        envelope = b"{}"
        proof = make_peer_proof(secret, peer_id=self.peer_id, binding_generation=1,
                                launcher_sha256=self.launcher, origin=ORIGIN,
                                sequence=1, envelope=envelope)
        frame = json.dumps({"version": 1, "peer_id": self.peer_id,
                            "binding_generation": 1, "launcher_sha256": self.launcher,
                            "origin": ORIGIN, "sequence": 1,
                            "envelope_b64": base64.b64encode(envelope).decode("ascii"),
                            "proof": proof}, separators=(",", ":")).encode()
        # It crosses the peer boundary; inner `{}` is then correctly rejected
        # by PR3-c rather than by secret resolution.
        from bct.core.bridge_pr3e_peer_adapter import install_schema
        install_schema(self.lifecycle._store)
        with self.assertRaises(ConflictError):
            PeerAdapter(self.lifecycle).ingress(self.lifecycle._store, frame)
        self.lifecycle.revoke(self.peer_id)
        with self.assertRaisesRegex(ConflictError, "PEER_ADAPTER_DENIED"):
            PeerAdapter(self.lifecycle).ingress(self.lifecycle._store, frame)

    def test_dpapi_store_survives_reopen_and_rotation_removes_retired_secret(self):
        directory = Path(self.temp.name) / "bridge-owned"; directory.mkdir()
        secret_store = DpapiFileSecretStore(directory)
        lifecycle = BindingLifecycle(Store(self.path), secret_store)
        first = secrets.token_bytes(32)
        lifecycle.provision(self.peer_id, binding_generation=1,
                            launcher_sha256=self.launcher, secret=first)
        self.assertEqual(first, lifecycle.resolve_peer_binding(self.peer_id).secret)

        # Reopening reconstructs metadata from SQLite and bytes from the
        # explicitly injected DPAPI store; neither is a runtime default.
        reopened = BindingLifecycle(Store(self.path), DpapiFileSecretStore(directory))
        self.assertEqual(first, reopened.resolve_peer_binding(self.peer_id).secret)
        second = secrets.token_bytes(32)
        reopened.rotate(self.peer_id, binding_generation=2,
                        launcher_sha256=self.launcher, secret=second)
        self.assertIsNone(secret_store.get_secret(self.peer_id, 1))
        self.assertEqual(second, secret_store.get_secret(self.peer_id, 2))
        self.assertEqual(1, len(list(directory.iterdir())))

        reopened.revoke(self.peer_id)
        self.assertIsNone(reopened.resolve_peer_binding(self.peer_id))
        self.assertEqual([], list(directory.iterdir()))


if __name__ == "__main__":
    unittest.main()
