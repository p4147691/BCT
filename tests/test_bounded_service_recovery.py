import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from bct.bounded_service_recovery import BoundedServiceRecovery
from bct.core.models import PreconditionError, UnknownEffectError
from bct.features.deploy import ServiceControlFeature


class RecoveryTests(unittest.TestCase):
    def test_core_probe_requires_exact_ready_service(self):
        f = BoundedServiceRecovery()
        for payload in ({"service": "other", "ready": True},
                        {"service": "bct-core", "ready": False}):
            f._probe = Mock(return_value=(True, json.dumps(payload)))
            self.assertFalse(f.ready("core"))
        f._probe = Mock(return_value=(True, '{"service":"bct-core","ready":true}'))
        self.assertTrue(f.ready("core"))

    def test_external_tunnel_url_never_probed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / ".local/state/tunnel-client/health/act-control.url"
            file.parent.mkdir(parents=True)
            f = BoundedServiceRecovery()
            f._probe = Mock()
            with patch("bct.bounded_service_recovery.Path.home", return_value=root):
                for url in ("http://example.com:80", "http://u:p@127.0.0.1:123",
                            "https://127.0.0.1:123"):
                    file.write_text(url)
                    self.assertFalse(f.ready("mcp_tunnel"))
                f._probe.assert_not_called()
                file.write_text("http://127.0.0.1:12345/some-path")
                f._probe.side_effect = [(True, "live"), (True, "ready")]
                self.assertTrue(f.ready("mcp_tunnel"))
                self.assertEqual("http://127.0.0.1:12345/readyz",
                                 f._probe.call_args.args[0])

    def test_tunnel_probe_rejects_negative_and_partial_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / ".local/state/tunnel-client/health/act-control.url"
            file.parent.mkdir(parents=True)
            file.write_text("http://127.0.0.1:12345")
            f = BoundedServiceRecovery()
            with patch("bct.bounded_service_recovery.Path.home", return_value=root):
                for health, ready in (("not live", "ready"), ("live", "not ready"),
                                      ("alive", "ready"), ("live", "already")):
                    f._probe = Mock(side_effect=[(True, health), (True, ready)])
                    self.assertFalse(f.ready("mcp_tunnel"))
                f._probe = Mock(side_effect=[(True, "live\n"), (True, "ready\n")])
                self.assertTrue(f.ready("mcp_tunnel"))

    @patch("bct.bounded_service_recovery.os.name", "nt")
    def test_already_ready_never_dispatches(self):
        f = BoundedServiceRecovery()
        f.ready = Mock(return_value=True)
        f._dispatch = Mock()
        self.assertFalse(f.recover("core")["task_dispatched"])
        f._dispatch.assert_not_called()

    @patch("bct.bounded_service_recovery.os.name", "nt")
    def test_exact_task_dispatched_once_and_ready_verified(self):
        f = BoundedServiceRecovery()
        f.ready = Mock(side_effect=[False, True])
        f._dispatch = Mock()
        self.assertTrue(f.recover("mcp_tunnel")["ready"])
        f._dispatch.assert_called_once_with("BCT Tunnel Supervisor")

    @patch("bct.bounded_service_recovery.os.name", "nt")
    def test_postdispatch_unready_is_unknown_not_retried(self):
        f = BoundedServiceRecovery()
        f.ready = Mock(return_value=False)
        f._dispatch = Mock()
        with patch("bct.bounded_service_recovery.time.monotonic", side_effect=[0, 19]):
            with self.assertRaises(UnknownEffectError):
                f.recover("core")
        f._dispatch.assert_called_once_with("BCT Core Supervisor")

    def test_arbitrary_target_rejected(self):
        with self.assertRaises(PreconditionError):
            BoundedServiceRecovery().recover("other-task")


class PublicRecoveryContractTests(unittest.TestCase):
    def setUp(self):
        self.profile = SimpleNamespace(name="bct_runtime_v1", service_name="bct-core", port=18790)
        self.f = ServiceControlFeature(SimpleNamespace(get=lambda _: self.profile))
        self.args = {"profile": "bct_runtime_v1", "action": "recover",
                     "target": "mcp_tunnel", "expected_release_sha": "a" * 40}

    def test_public_contract_requires_fixed_target_and_release(self):
        request = self.f.prepare(work=None, arguments=self.args)
        self.assertEqual("BCT Tunnel Supervisor", request.target)
        for change in ({"target": "random"}, {"command": "whoami"}, {"url": "http://other"},
                       {"expected_release_sha": "not-sha"}, {"target": []}):
            with self.assertRaises(PreconditionError):
                self.f.prepare(work=None, arguments={**self.args, **change})

    def test_other_service_profile_rejected(self):
        self.profile.name = "another_profile"
        with self.assertRaises(PreconditionError):
            self.f.prepare(work=None, arguments=self.args)
