from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from bct.integrations.desktop_session import DesktopSessionClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default=r"D:\BCT\runtime\desktop-session\endpoint.json")
    parser.add_argument("--evidence-root", default=r"D:\BCT\data\desktop-session\evidence")
    args = parser.parse_args()
    prefix = "github-vtl-readonly-" + uuid.uuid4().hex[:12]
    client = DesktopSessionClient(
        endpoint_path=Path(args.endpoint), evidence_root=Path(args.evidence_root)
    )
    status = client.status(request_id=prefix + "-status")
    endpoint = client._endpoint()
    capture = client.capture(
        request_id=prefix + "-capture", target_type="virtual_screen",
        monitor_index=None, hwnd="", max_width=640, max_height=400,
    )
    windows = client.windows(
        request_id=prefix + "-windows", include_minimized=False,
        title_query="", limit=100,
    )
    capture_value = capture["capture"]
    window_value = windows["windows"]
    print(json.dumps({
        "result": "PASS",
        "agent_version": endpoint.agent_version,
        "session_id": status["session"]["sessionId"],
        "monitor_count": len(status["monitors"]),
        "capture_width": capture_value["width"],
        "capture_height": capture_value["height"],
        "capture_sha256": capture_value["sha256"],
        "visible_window_count": window_value["count"],
        "windows_truncated": window_value["truncated"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
