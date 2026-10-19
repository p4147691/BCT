from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        bodies = {"/healthz": b"live", "/readyz": b"ready"}
        body = bodies.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@unittest.skipUnless(os.name == "nt", "the production supervisor is Windows-only")
class TunnelSupervisorTests(unittest.TestCase):
    @staticmethod
    def _script() -> Path:
        return (
            Path(__file__).resolve().parents[1]
            / "modules"
            / "mcp"
            / "ops"
            / "run_bct_tunnel_supervisor.ps1"
        )

    @staticmethod
    def _cutover_script() -> Path:
        return (
            Path(__file__).resolve().parents[1]
            / "modules"
            / "mcp"
            / "ops"
            / "invoke_bct_tunnel_cutover.ps1"
        )

    def test_recovers_missing_health_url_from_exact_process_listener(self) -> None:
        shell = shutil.which("pwsh") or shutil.which("powershell")
        self.assertIsNotNone(shell)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                health_file = Path(temp) / "health" / "act-control.url"
                result = subprocess.run(
                    [
                        str(shell),
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(self._script()),
                        "-TunnelClientPath",
                        str(Path(sys.executable).resolve()),
                        "-HealthUrlFile",
                        str(health_file),
                        "-RepairHealthOnly",
                        "-RepairProcessId",
                        str(os.getpid()),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr or result.stdout)
                self.assertEqual(
                    f"http://127.0.0.1:{server.server_port}",
                    health_file.read_text(encoding="utf-8").strip(),
                )
                self.assertIn('"repaired":true', result.stdout)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_refuses_ambiguous_exact_process_health_listeners(self) -> None:
        shell = shutil.which("pwsh") or shutil.which("powershell")
        self.assertIsNotNone(shell)
        servers = [http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler) for _ in range(2)]
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
        for thread in threads:
            thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                health_file = Path(temp) / "health" / "act-control.url"
                result = subprocess.run(
                    [
                        str(shell),
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(self._script()),
                        "-TunnelClientPath",
                        str(Path(sys.executable).resolve()),
                        "-HealthUrlFile",
                        str(health_file),
                        "-RepairHealthOnly",
                        "-RepairProcessId",
                        str(os.getpid()),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    check=False,
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn("BCT_TUNNEL_HEALTH_ENDPOINT_AMBIGUOUS count=2", result.stderr)
                self.assertFalse(health_file.exists())
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=5)

    def test_reads_utf8_and_legacy_windows_profiles_without_corrupting_paths(self) -> None:
        script = self._script().read_text(encoding="utf-8")
        self.assertIn(
            "function Read-TunnelProfileText([string]$Path)",
            script,
        )
        self.assertIn("[Text.UTF8Encoding]::new($false, $true)", script)
        self.assertIn("[Text.Encoding]::Unicode", script)
        self.assertIn("[Text.Encoding]::BigEndianUnicode", script)
        self.assertIn("[Text.Encoding]::Default", script)

    def test_cutover_fixture_fails_closed_for_each_missing_gate(self) -> None:
        shell = shutil.which("pwsh") or shutil.which("powershell")
        self.assertIsNotNone(shell)
        result = subprocess.run(
            [
                str(shell),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self._cutover_script()),
                "-Mode",
                "FixtureTest",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual("PASS", payload["status"])
        self.assertFalse(payload["operational_effects"])
        self.assertEqual(8, len(payload["checks"]))
        self.assertTrue(all(check["pass"] for check in payload["checks"]))


if __name__ == "__main__":
    unittest.main()
