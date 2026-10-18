from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from bct.core.models import Outcome, PreconditionError, Work
from bct.features.desktop_session import DesktopCaptureFeature, DesktopSessionStatusFeature
from bct.integrations.desktop_session import (
    DesktopSessionClient, DesktopSessionRequestFailed, DesktopSessionUnavailable,
)


class FakeDesktopSessionClient:
    def __init__(self, root: Path):
        self.root = root
        self.status_calls = 0
        self.capture_calls = 0

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


class DesktopSessionFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = FakeDesktopSessionClient(self.root)
        self.work = Work("desktop", "observe desktop", (str(self.root),),
                         frozenset({"desktop_session_status", "desktop_capture"}), "owner")

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


if __name__ == "__main__":
    unittest.main()
