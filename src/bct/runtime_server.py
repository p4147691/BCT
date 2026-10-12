from __future__ import annotations

import argparse
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from bct import BCT
from bct.service_runtime import current_process_identity


class RuntimeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    state: dict[str, Any]
    control_token: str


class Handler(BaseHTTPRequestHandler):
    server: RuntimeHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, status: int, value: dict[str, Any]) -> None:
        payload = json.dumps(value, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path != "/health":
            self._json(404, {"error": "NOT_FOUND"})
            return
        self._json(200, self.server.state)

    def do_POST(self) -> None:
        if self.path != "/shutdown":
            self._json(404, {"error": "NOT_FOUND"})
            return
        supplied = self.headers.get("X-BCT-Control-Token", "")
        if not hmac.compare_digest(supplied, self.server.control_token):
            self._json(403, {"error": "CONTROL_TOKEN_INVALID"})
            return
        self._json(200, {"accepted": True})
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--service-name", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--port", required=True, type=int)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    runtime_root = Path(arguments.runtime_root).resolve()
    release_root = runtime_root / "releases" / arguments.release_sha
    policy_path = release_root / "bct.toml"
    if not policy_path.is_file():
        raise RuntimeError("RUNTIME_POLICY_MISSING")
    bct = BCT(state_path=runtime_root / "state" / "state.sqlite", policy_path=policy_path)
    identity = current_process_identity()
    control_token = os.environ.get("BCT_CONTROL_TOKEN", "")
    if len(control_token) != 64:
        raise RuntimeError("BCT_CONTROL_TOKEN_MISSING")
    state = {
        "status": "OK",
        "ready": True,
        "service": arguments.service_name,
        **identity.as_dict(),
        "release_sha": arguments.release_sha,
        "manifest_sha256": arguments.manifest_sha256,
        "generation": arguments.generation,
        "instance_id": arguments.instance_id,
        "capabilities": list(bct.operations.capabilities),
        "started_at": time.time(),
    }
    server = RuntimeHTTPServer(("127.0.0.1", arguments.port), Handler)
    server.state = state
    server.control_token = control_token
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
