from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import socket
import tempfile
import textwrap
import unittest
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from bct.service_runtime import RuntimeServiceController


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


class MCPIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "hello.txt").write_text("hello from MCP\n", encoding="utf-8")
        (self.project / "slow.py").write_text(
            textwrap.dedent(
                """\
                import time
                time.sleep(1.25)
                print("slow execution complete")
                """
            ),
            encoding="utf-8",
        )
        self.release_sha = "1" * 40
        self.manifest_sha = hashlib.sha256(b"mcp-test").hexdigest()
        self.release = self.runtime / "releases" / self.release_sha
        source = Path(__file__).resolve().parents[1]
        shutil.copytree(
            source / "src" / "bct",
            self.release / "src" / "bct",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        capabilities = [
            "read", "write", "test", "git_commit", "github_push", "github_pr_create",
            "github_pr_status", "github_pr_merge", "github_sync_main", "deploy", "service_control",
            "relay_browser", "system_inspect", "execute", "decision_model", "decision_service", "monitor",
            "process_session",
        ]
        (self.release / "bct.toml").write_text(
            "[policy]\n"
            f"normal_actions={json.dumps(capabilities)}\n"
            "approval_actions=[]\n",
            encoding="utf-8",
        )
        self.port = free_port()
        self.controller = RuntimeServiceController(
            runtime_root=self.runtime,
            service_name="bct-mcp-test",
            port=self.port,
            readiness_timeout=10,
        )
        self.service = self.controller.start({
            "source_head": self.release_sha,
            "manifest_sha256": self.manifest_sha,
            "release_path": str(self.release),
        })

    def tearDown(self):
        try:
            if self.controller.inspect().get("state") == "RUNNING":
                self.controller.stop()
        finally:
            self.temp.cleanup()

    async def exercise_mcp(self) -> None:
        url = f"http://127.0.0.1:{self.port}/mcp"
        unauthorized = httpx.post(url, json={}, timeout=3)
        self.assertEqual(401, unauthorized.status_code)
        tunnel_probe = httpx.post(
            url,
            headers={"X-BCT-Token": self.controller.mcp_secret()},
            json={},
            timeout=3,
        )
        self.assertNotEqual(401, tunnel_probe.status_code)
        headers = {"Authorization": "Bearer " + self.controller.mcp_secret()}
        async with httpx.AsyncClient(headers=headers, timeout=10) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    self.assertEqual("BCT", initialized.serverInfo.name)
                    catalogue = await session.list_tools()
                    names = {tool.name for tool in catalogue.tools}
                    expected_capability_tools = {
                        "bct_deploy", "bct_git_commit", "bct_github_pr_create",
                        "bct_github_pr_merge", "bct_github_pr_status", "bct_github_push",
                        "bct_github_sync_main", "bct_read", "bct_service_control",
                        "bct_relay_browser",
                        "bct_system_inspect", "bct_execute", "bct_decision_model", "bct_decision_service", "bct_monitor",
                        "bct_process_session",
                        "bct_test", "bct_write",
                    }
                    self.assertEqual(
                        expected_capability_tools | {
                            "bct_capabilities", "bct_status", "bct_work_create", "bct_operation_get",
                        },
                        names,
                    )
                    capabilities = await session.call_tool("bct_capabilities", {})
                    self.assertFalse(capabilities.isError)
                    self.assertEqual(expected_capability_tools, set(capabilities.structuredContent["tools"]))
                    status = await session.call_tool("bct_status", {})
                    self.assertFalse(status.isError)
                    self.assertTrue(status.structuredContent["core"]["ready"])
                    self.assertEqual(self.release_sha, status.structuredContent["runtime"]["release_sha"])
                    self.assertIn("rcc", status.structuredContent["monitor"])
                    work_arguments = {
                        "work_id": "mcp-read-work",
                        "request_summary": "read one exact test file",
                        "roots": [str(self.project)],
                        "actions": ["read"],
                    }
                    created = await session.call_tool("bct_work_create", work_arguments)
                    repeated = await session.call_tool("bct_work_create", work_arguments)
                    self.assertFalse(created.isError)
                    self.assertFalse(created.structuredContent["duplicate"])
                    self.assertTrue(repeated.structuredContent["duplicate"])
                    call_arguments = {
                        "work_id": "mcp-read-work",
                        "operation_id": "mcp-read-1",
                        "arguments": {"path": str(self.project / "hello.txt")},
                    }
                    read_result = await session.call_tool("bct_read", call_arguments)
                    duplicate = await session.call_tool("bct_read", call_arguments)
                    receipt = await session.call_tool("bct_operation_get", {
                        "work_id": "mcp-read-work", "operation_id": "mcp-read-1",
                    })
                    self.assertFalse(read_result.isError)
                    self.assertEqual("APPLIED", read_result.structuredContent["outcome"])
                    self.assertEqual("hello from MCP\n", read_result.structuredContent["output"]["text"])
                    self.assertTrue(duplicate.structuredContent["duplicate"])
                    self.assertEqual("APPLIED", receipt.structuredContent["outcome"])
                    conflict = await session.call_tool("bct_work_create", {
                        **work_arguments, "roots": [str(self.root)],
                    })
                    self.assertTrue(conflict.isError)

                    execute_work = {
                        "work_id": "mcp-execute-work",
                        "request_summary": "prove MCP execution does not block service health",
                        "roots": [str(self.project)],
                        "actions": ["execute"],
                    }
                    await session.call_tool("bct_work_create", execute_work)
                    pending = asyncio.create_task(session.call_tool("bct_execute", {
                        "work_id": execute_work["work_id"],
                        "operation_id": "mcp-slow-execute",
                        "arguments": {
                            "kind": "python", "cwd": str(self.project),
                            "script": str(self.project / "slow.py"), "timeout_s": 5,
                        },
                    }))
                    await asyncio.sleep(0.1)
                    async with httpx.AsyncClient(timeout=0.5) as health_client:
                        health = await health_client.get(
                            f"http://127.0.0.1:{self.port}/health"
                        )
                    self.assertEqual(200, health.status_code)
                    self.assertTrue(health.json()["ready"])
                    completed = await pending
                    self.assertFalse(completed.isError, completed)
                    self.assertEqual("APPLIED", completed.structuredContent["outcome"])

        monitor = httpx.get(f"http://127.0.0.1:{self.port}/monitor/state", timeout=3)
        self.assertEqual(200, monitor.status_code)
        monitor_state = monitor.json()
        self.assertEqual(1, monitor_state["schema"])
        self.assertEqual(self.release_sha, monitor_state["service"]["release_sha"])
        self.assertGreaterEqual(monitor_state["counts"]["works"], 2)
        self.assertGreaterEqual(monitor_state["counts"]["operations"], 2)

    def test_authenticated_catalogue_work_call_and_duplicate_receipt(self):
        asyncio.run(self.exercise_mcp())


if __name__ == "__main__":
    unittest.main()
