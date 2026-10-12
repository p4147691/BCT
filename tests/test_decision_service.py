from __future__ import annotations

import hashlib
import socket
import tempfile
import unittest
from pathlib import Path

from bct.decision_service import DecisionServiceController


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


_FAKE_SERVER = r'''
import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

model = os.environ["LAYA_DEFAULT_MODEL"]
port = int(os.environ["LAYA_PORT"])

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        if self.path != "/health":
            self.send_response(404); self.end_headers(); return
        body = json.dumps({"status":"ok","loaded":[model]}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)

ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''


class DecisionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.module = self.root / "fake_decision.py"
        self.module.write_text(_FAKE_SERVER, encoding="utf-8")
        self.model = self.root / "model"
        self.model.mkdir()
        weights = self.model / "model.safetensors"
        weights.write_bytes(b"bct-test-model")
        self.sha = hashlib.sha256(weights.read_bytes()).hexdigest()
        self.controller = DecisionServiceController(
            state_root=self.root / "state", endpoint_file=self.root / "state" / "endpoint.json",
            model_path=self.model, model_name="bct-test-model", model_sha256=self.sha,
            port=free_port(), python_paths=[str(self.root)], module="fake_decision", readiness_timeout=10,
        )

    def tearDown(self):
        try:
            if self.controller.inspect().get("state") == "RUNNING":
                self.controller.stop()
        finally:
            self.temporary.cleanup()

    def test_start_duplicate_restart_and_stop_have_exact_process_receipts(self):
        started = self.controller.start()
        duplicate = self.controller.start()
        self.assertEqual(started["state"], "RUNNING")
        self.assertFalse(started["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(started["process"]["fingerprint"], duplicate["process"]["fingerprint"])

        restarted = self.controller.restart()
        self.assertEqual(restarted["state"], "RUNNING")
        self.assertNotEqual(
            restarted["pre"]["process"]["fingerprint"],
            restarted["post"]["process"]["fingerprint"],
        )
        self.assertEqual(restarted["post"]["generation"], started["generation"] + 1)

        stopped = self.controller.stop()
        repeated = self.controller.stop()
        self.assertEqual(stopped["state"], "STOPPED")
        self.assertFalse(stopped["duplicate"])
        self.assertTrue(repeated["duplicate"])


if __name__ == "__main__":
    unittest.main()
