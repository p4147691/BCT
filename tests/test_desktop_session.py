from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from bct.core.models import Outcome, PreconditionError, UnknownEffectError, Work
from bct.features.desktop_session import (
    DesktopCaptureFeature, DesktopControlLeaseFeature, DesktopEmergencyStopFeature,
    DesktopSessionStatusFeature,
)
from bct.integrations.desktop_session import (
    DesktopSessionClient, DesktopSessionEffectUnknown, DesktopSessionRequestFailed,
    DesktopSessionUnavailable,
)


class FakeDesktopSessionClient:
    def __init__(self, root: Path):
        self.root = root
        self.status_calls = 0
        self.capture_calls = 0
        self.control_calls = []

    @staticmethod
    def _base(command: str):
        return {
            "type": "desktop-session:result", "ok": True,
            "requestId": "unused", "command": command, "instanceId": "a" * 32,
            "session": {
                "pid": 123, "sessionId": 1, "userSid": "S-1-5-21-test",
                "logonSid": "S-1-5-5-1-2", "userInteractive": True,
                "inputDesktopAvailable": True, "foregroundWindow": None,
            },
            "monitors": [{"index": 0, "primary": True}],
        }

    def status(self, *, request_id: str):
        self.status_calls += 1
        value = self._base("status")
        value["requestId"] = request_id
        return value

    def capture(self, *, request_id: str, **arguments):
        self.capture_calls += 1
        path = self.root / f"{request_id}.png"
        path.write_bytes(b"fake png")
        value = self._base("capture")
        value["requestId"] = request_id
        value["capture"] = {
            "targetType": arguments["target_type"], "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "width": 10, "height": 10, "bytes": path.stat().st_size,
            "mimeType": "image/png",
        }
        return value

    def control(self, *, request_id: str, command: str, arguments=None):
        self.control_calls.append((request_id, command, arguments or {}))
        value = self._base(command)
        value["requestId"] = request_id
        value["control"] = {
            "lease": ({
                "leaseId": "b" * 32, "ownerId": (arguments or {}).get("ownerId"),
                "ttlSeconds": (arguments or {}).get("ttlSeconds", 30),
                "target": {"type": (arguments or {}).get("targetType", "session")},
            } if command in {"lease_acquire", "lease_renew"} else None),
            "emergencyStop": {
                "active": command == "emergency_stop", "generation": 1,
                "reason": (arguments or {}).get("reason", ""),
            },
        }
        return value


class DesktopSessionFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = FakeDesktopSessionClient(self.root)
        self.work = Work("desktop", "observe desktop", (str(self.root),),
                         frozenset({
                             "desktop_session_status", "desktop_capture",
                             "desktop_control_lease", "desktop_emergency_stop",
                         }), "owner")

    def tearDown(self):
        self.temp.cleanup()

    def test_status_returns_exact_session_and_monitor_evidence(self):
        feature = DesktopSessionStatusFeature(self.client)
        request = feature.prepare(work=self.work, arguments={})
        request = request.__class__(**{**request.__dict__, "operation_id": "status-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual(1, result.evidence["session"]["sessionId"])
        self.assertEqual(1, len(result.evidence["monitors"]))

    def test_capture_normalizes_target_and_returns_hash_evidence(self):
        feature = DesktopCaptureFeature(self.client)
        request = feature.prepare(work=self.work, arguments={"target_type": "monitor", "monitor_index": 0})
        request = request.__class__(**{**request.__dict__, "operation_id": "capture-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("monitor", result.evidence["capture"]["targetType"])
        self.assertTrue(Path(result.evidence["capture"]["path"]).is_file())

    def test_window_requires_exact_numeric_hwnd(self):
        feature = DesktopCaptureFeature(self.client)
        with self.assertRaisesRegex(PreconditionError, "HWND_INVALID"):
            feature.prepare(work=self.work, arguments={"target_type": "window", "hwnd": "foreground"})

    def test_agent_terminal_capture_failure_releases_as_failed_not_unknown(self):
        class RejectingClient(FakeDesktopSessionClient):
            def capture(self, **_arguments):
                raise DesktopSessionRequestFailed("DESKTOP_SESSION_AGENT_ERROR:INPUT_DESKTOP_UNAVAILABLE")

        feature = DesktopCaptureFeature(RejectingClient(self.root))
        request = feature.prepare(work=self.work, arguments={})
        request = request.__class__(**{**request.__dict__, "operation_id": "capture-rejected"})
        from bct.core.models import ConfirmedFailure
        with self.assertRaisesRegex(ConfirmedFailure, "INPUT_DESKTOP_UNAVAILABLE") as caught:
            feature.execute(request)
        self.assertTrue(caught.exception.release_claims)

    def test_client_fails_closed_without_endpoint(self):
        client = DesktopSessionClient(
            endpoint_path=self.root / "missing.json", evidence_root=self.root / "evidence",
        )
        with self.assertRaisesRegex(DesktopSessionUnavailable, "ENDPOINT_UNAVAILABLE"):
            client.status(request_id="status-missing")

    def test_control_lease_derives_owner_and_normalizes_session_acquire(self):
        feature = DesktopControlLeaseFeature(self.client)
        request = feature.prepare(work=self.work, arguments={
            "operation": "acquire", "ttl_seconds": 45, "target_type": "session",
        })
        self.assertEqual("desktop", request.arguments["owner_id"])
        self.assertEqual(("desktop-control:interactive-session",), request.resources)
        request = request.__class__(**{**request.__dict__, "operation_id": "lease-acquire-1"})
        result = feature.execute(request)
        self.assertEqual(Outcome.APPLIED, result.outcome)
        self.assertEqual("b" * 32, result.evidence["control"]["lease"]["leaseId"])
        self.assertEqual("lease_acquire", self.client.control_calls[-1][1])

    def test_control_lease_validates_id_ttl_and_reset_generation(self):
        feature = DesktopControlLeaseFeature(self.client)
        with self.assertRaisesRegex(PreconditionError, "TTL_INVALID"):
            feature.prepare(work=self.work, arguments={"operation": "acquire", "ttl_seconds": 1})
        with self.assertRaisesRegex(PreconditionError, "LEASE_ID_INVALID"):
            feature.prepare(work=self.work, arguments={"operation": "renew", "lease_id": "bad"})
        with self.assertRaisesRegex(PreconditionError, "GENERATION_INVALID"):
            feature.prepare(work=self.work, arguments={
                "operation": "reset_emergency", "expected_stop_generation": 0,
            })

    def test_control_mutation_transport_loss_is_unknown(self):
        class UnknownClient(FakeDesktopSessionClient):
            def control(self, **_arguments):
                raise DesktopSessionEffectUnknown("DESKTOP_SESSION_TRANSPORT_UNKNOWN")

        feature = DesktopControlLeaseFeature(UnknownClient(self.root))
        request = feature.prepare(work=self.work, arguments={"operation": "acquire"})
        request = request.__class__(**{**request.__dict__, "operation_id": "lease-unknown"})
        with self.assertRaisesRegex(UnknownEffectError, "TRANSPORT_UNKNOWN"):
            feature.execute(request)

    def test_emergency_stop_uses_independent_claim_and_returns_latched_state(self):
        feature = DesktopEmergencyStopFeature(self.client)
        request = feature.prepare(work=self.work, arguments={"reason": "operator"})
        self.assertEqual(("desktop-emergency-stop:interactive-session",), request.resources)
        request = request.__class__(**{**request.__dict__, "operation_id": "emergency-stop-1"})
        result = feature.execute(request)
        self.assertTrue(result.evidence["control"]["emergencyStop"]["active"])
        self.assertIsNone(result.evidence["control"]["lease"])


if __name__ == "__main__":
    unittest.main()
