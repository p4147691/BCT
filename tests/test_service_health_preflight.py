from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psutil

from bct.core.models import PreconditionError
from bct.service_runtime import (
    RuntimeServiceController,
    _fingerprint,
    _loopback_listener_state,
    atomic_json,
    current_process_identity,
)


class _Response:
    def __init__(self, value: dict):
        self.payload = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit: int):
        return self.payload[:limit]


class ServiceHealthPreflightTests(unittest.TestCase):
    def controller(self, root: Path, port: int = 43210) -> RuntimeServiceController:
        return RuntimeServiceController(
            runtime_root=root / "runtime",
            service_name="health-preflight-test",
            port=port,
            readiness_timeout=1,
        )

    @staticmethod
    def listener(port: int, ip: str = "127.0.0.1"):
        return SimpleNamespace(
            status=psutil.CONN_LISTEN,
            laddr=SimpleNamespace(ip=ip, port=port),
        )

    def test_listener_state_detects_exact_loopback_and_wildcard(self):
        with patch("bct.service_runtime.psutil.net_connections") as connections:
            connections.return_value = [
                self.listener(41000),
                self.listener(42000, "0.0.0.0"),
            ]
            self.assertTrue(_loopback_listener_state(41000))
            self.assertTrue(_loopback_listener_state(42000))
            self.assertFalse(_loopback_listener_state(43000))
            connections.assert_called_with(kind="tcp4")

    def test_listener_query_failure_falls_back_to_existing_http_health(self):
        with tempfile.TemporaryDirectory() as temp:
            controller = self.controller(Path(temp))
            with (
                patch(
                    "bct.service_runtime.psutil.net_connections",
                    side_effect=psutil.AccessDenied(pid=os.getpid()),
                ),
                patch("bct.service_runtime.urllib.request.urlopen") as urlopen,
            ):
                urlopen.return_value = _Response({"ready": True, "status": "OK"})
                self.assertEqual({"ready": True, "status": "OK"}, controller._health())
                urlopen.assert_called_once()

    def test_absent_listener_skips_http_request(self):
        with tempfile.TemporaryDirectory() as temp:
            controller = self.controller(Path(temp))
            with (
                patch("bct.service_runtime.psutil.net_connections", return_value=[]),
                patch("bct.service_runtime.urllib.request.urlopen") as urlopen,
            ):
                self.assertIsNone(controller._health())
                urlopen.assert_not_called()

    def test_present_listener_keeps_http_health_and_ownership_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            controller = self.controller(root)
            identity = current_process_identity()
            receipt = {
                "service": controller.service_name,
                **identity.as_dict(),
                "release_sha": "a" * 40,
                "manifest_sha256": "b" * 64,
                "generation": 1,
                "instance_id": "expected-instance",
            }
            atomic_json(controller.service_path, receipt)
            foreign_health = {
                **receipt,
                "service": "foreign-service",
                "ready": True,
            }
            with (
                patch(
                    "bct.service_runtime.psutil.net_connections",
                    return_value=[self.listener(controller.port)],
                ),
                patch(
                    "bct.service_runtime.urllib.request.urlopen",
                    return_value=_Response(foreign_health),
                ),
            ):
                with self.assertRaisesRegex(
                    PreconditionError, "SERVICE_HEALTH_OWNERSHIP_MISMATCH"
                ):
                    controller.inspect()


if __name__ == "__main__":
    unittest.main()
