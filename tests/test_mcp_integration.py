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

import httpx2 as httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from bct.conversation_network import (
    record_monitor_snapshot, set_membership, upsert_conversation, upsert_project,
)
from bct.core.store import Store
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
        (self.project / "blocks.py").write_text(
            "def keep():\n    return 'keep'\n\n"
            "def change(value):\n    return value + 1\n",
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
        shutil.copytree(source / "src" / "bct_maintenance",
                        self.release / "src" / "bct_maintenance",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        capabilities = [
            "read", "write", "test", "git_commit", "github_push", "github_pr_create",
            "github_pr_status", "github_pr_merge", "github_sync_main", "github_run_watch", "deploy", "service_control",
            "browser", "system_inspect", "execute", "monitor",
            "process_session", "verify", "orchestrate",
            "claim_reconcile",
            "browser_extension_manage",
            "owned_extension_action",
            "desktop_session_status", "desktop_capture",
            "desktop_explore",
            "desktop_application_target",
            "desktop_chrome_content_list",
            "desktop_chrome_content_action",
            "desktop_uia_elements_list",
            "desktop_uia_element_action",
            "desktop_chrome_tab_reconcile",
            "desktop_chrome_tab_select",
            "desktop_control_lease", "desktop_emergency_stop", "desktop_input",
            "desktop_clipboard",
            "desktop_window_list", "desktop_window_activate",
            "desktop_window_activate_reconcile", "desktop_window_manage",
            "desktop_program_launch", "file_action_plan", "process_stop_plan", "file_local_action", "process_local_stop", "file_action_apply", "process_stop_apply", "approval_challenge", "desktop_explorer_folder_open",
            "vtl_validate",
        ]
        self.port = free_port()
        (self.release / "bct.toml").write_text(
            "[policy]\n"
            f"normal_actions={json.dumps(capabilities)}\n"
            'approval_actions=["desktop_read"]\n\n'
            "[deployment.profiles.mcp_test]\n"
            f"source_root={json.dumps(str(source))}\n"
            f"runtime_root={json.dumps(str(self.runtime))}\n"
            'service_name="bct-mcp-test"\n'
            f"port={self.port}\n"
            'files=["bct.toml"]\n',
            encoding="utf-8",
        )
        state_root = self.runtime / "state"
        state_root.mkdir(parents=True, exist_ok=True)
        conversation_store = Store(state_root / "state.sqlite")
        self.manager = "6ad5afa4-b1e0-83ee-8692-aec4bb51523e"
        upsert_project(conversation_store, project_id="bct.rcc", display_name="BCT RCC", now=100.0)
        upsert_conversation(conversation_store, conversation_key=self.manager, display_name="Manager", now=100.0)
        set_membership(conversation_store, project_id="bct.rcc", conversation_key=self.manager,
                       tags=["조정"], now=100.0)
        record_monitor_snapshot(conversation_store, {
            "schema": "BCT_MONITOR_NODE_SNAPSHOT_V1", "source": "MONITOR",
            "snapshot_id": "mcp.monitor.1", "observed_at": "2026-10-20T03:18:00Z",
            "completeness": "COMPLETE", "nodes": [{
                "node_label": "D1-3", "conversation_key": self.manager,
                "title": "Manager", "presence": "OPEN",
            }],
        }, now=200.0)
        self.controller = RuntimeServiceController(
            runtime_root=self.runtime,
            service_name="bct-mcp-test",
            port=self.port,
            readiness_timeout=30,  # Windows GitHub-hosted runners may take longer to start the test service.
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
        protocol = "2026-07-28"
        async with httpx.AsyncClient(headers=headers, timeout=10) as modern:
            async def call_modern(method, *, name=None, arguments=None):
                request_headers = {
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": protocol,
                    "Mcp-Method": method,
                }
                params = {"_meta": {"io.modelcontextprotocol/protocolVersion": protocol,
                                    "io.modelcontextprotocol/clientCapabilities": {}}}
                if name is not None:
                    request_headers["Mcp-Name"] = name
                    params.update(name=name, arguments=arguments or {})
                response = await modern.post(url, headers=request_headers, json={
                    "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
                })
                self.assertEqual(200, response.status_code, response.text)
                self.assertNotIn("Mcp-Session-Id", response.headers)
                return response.json()["result"]

            await call_modern("server/discover")
            health = (await call_modern("tools/call", name="bct_status",
                                        arguments={"scope": "health"}))["structuredContent"]
            self.assertEqual({"schema", "status", "scope", "core", "runtime", "mcp_trace_id"}, set(health))
            self.assertEqual(health["runtime"]["release_sha"], self.release_sha)
            self.assertEqual(health["core"], {"ready": True, "mcp_ready": True, "maintenance_paused": False})
            self.assertLess(len(json.dumps(health)), 1024)
            modern_status = await call_modern("tools/call", name="bct_status",
                                              arguments={"compact": True, "scope": "bct"})
            self.assertFalse(modern_status.get("isError", False))
            self.assertEqual(self.release_sha, modern_status["structuredContent"]["runtime"]["release_sha"])
        async with httpx.AsyncClient(headers=headers, timeout=10) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    self.assertEqual("BCT", initialized.server_info.name)
                    catalogue = await session.list_tools()
                    names = {tool.name for tool in catalogue.tools}
                    relay_description = next(tool.description for tool in catalogue.tools
                                             if tool.name == "bct_browser")
                    self.assertIn("bct_rcc_command_catalog", relay_description)
                    self.assertIn("arguments.command", relay_description)
                    self.assertIn("rcc-browser-command-v2", relay_description)
                    self.assertIn("UNKNOWN", relay_description)
                    expected_capability_tools = {
                        "bct_deploy", "bct_git_commit", "bct_github_pr_create",
                        "bct_github_pr_merge", "bct_github_pr_status", "bct_github_push", "bct_github_run_watch",
                        "bct_github_sync_main", "bct_read", "bct_scoped_read", "bct_service_control",
                        "bct_browser", "bct_relay_control", "bct_owned_extension_action",
                        "bct_system_inspect", "bct_execute", "bct_monitor",
                        "bct_conversation_network_update", "bct_project_context",
                        "bct_cdp_inspect", "bct_browser_extension_manage",
                        "bct_process_session",
                        "bct_test", "bct_write", "bct_verify", "bct_orchestrate",
                        "bct_claim_reconcile",
                        "bct_desktop_session_status", "bct_desktop_capture",
                        "bct_desktop_explore",
                        "bct_desktop_application_target",
                        "bct_desktop_chrome_content_list",
                        "bct_desktop_chrome_content_action",
                        "bct_desktop_uia_elements_list",
                        "bct_desktop_uia_element_action",
                        "bct_desktop_chrome_tab_reconcile",
                        "bct_desktop_chrome_tab_select",
                        "bct_desktop_control_lease", "bct_desktop_emergency_stop",
                        "bct_desktop_input", "bct_desktop_clipboard",
                        "bct_desktop_window_list", "bct_desktop_window_activate",
                        "bct_desktop_window_activate_reconcile",
                        "bct_desktop_window_manage",
                        "bct_desktop_program_launch", "bct_file_action_plan", "bct_process_stop_plan", "bct_file_local_action", "bct_process_local_stop", "bct_file_action_apply", "bct_process_stop_apply", "bct_approval_challenge", "bct_desktop_explorer_folder_open",
                        "bct_vtl_validate",
                    }
                    self.assertEqual(
                        expected_capability_tools | {
                            "bct_capabilities", "bct_status", "queue_message", "bct_get_conversation_network", "bct_check_conversation_network", "scan_code_blocks", "organize_code_blocks", "bct_run_plan", "bct_set_conversation_network",
                            "bct_execution_context", "bct_set_direction", "bct_get_direction", "bct_chain_branch", "bct_chain_recipe", "bct_loop_recipe", "bct_set_execute_plan", "bct_update_execute_plan", "bct_get_execute_plan", "bct_work_create", "bct_operation_get", "bct_inbox_get", "bct_task_run", "bct_task_message", "bct_send_delayed_message", "bct_delayed_send_cancel",
                            "bct_check_node", "bct_recheck_node", "bct_pause_node", "bct_replace_node", "bct_reset_node",
                            "bct_github_inbox_get", "bct_send_message", "bct_set_project_plan", "bct_plan_run", "bct_run_task", "bct_context", "bct_cancel_delayed_send",
                            "bct_create_work", "bct_operation", "bct_github_inbox", "bct_inbox", "bct_move_tab", "bct_close_tab", "bct_rcc_command_catalog", "bct_rcc_recipe_catalog",
                        },
                        names,
                    )
                    capabilities = await session.call_tool("bct_capabilities", {})
                    library = await session.call_tool("bct_capabilities", {
                        "query": "코드 블럭", "tool_name": "scan_code_blocks", "include_manual": True,
                    })
                    self.assertFalse(library.is_error)
                    self.assertEqual("AVAILABLE", library.structured_content["library_status"])
                    self.assertTrue(library.structured_content["read_only"])
                    scan_tool = next(t for t in catalogue.tools if t.name == "scan_code_blocks")
                    self.assertEqual(scan_tool.input_schema, library.structured_content["tool"]["inputSchema"])
                    manual = library.structured_content["manual"]
                    self.assertIn("Chain Recipe 공통 설명서", manual["text"])
                    self.assertEqual(hashlib.sha256(manual["text"].encode("utf-8")).hexdigest(), manual["sha256"])
                    self.assertFalse(capabilities.is_error)
                    live_relay_usage = capabilities.structured_content["browser_usage"]
                    self.assertIn("bct_rcc_command_catalog", live_relay_usage)
                    self.assertIn("arguments.command", live_relay_usage)
                    self.assertIn("rcc_send_message_to_tab", capabilities.structured_content["browser_public_commands"])
                    self.assertIn("rcc_create_chat_and_send_message", capabilities.structured_content["browser_public_commands"])
                    self.assertIn("rcc_bind_conversation_to_node", capabilities.structured_content["browser_public_commands"])
                    self.assertEqual(
                        expected_capability_tools | {
                            "bct_capabilities", "bct_status", "queue_message", "bct_get_conversation_network", "bct_check_conversation_network", "scan_code_blocks", "organize_code_blocks", "bct_run_plan", "bct_set_conversation_network",
                            "bct_execution_context", "bct_set_direction", "bct_get_direction", "bct_chain_branch", "bct_chain_recipe", "bct_loop_recipe", "bct_set_execute_plan", "bct_update_execute_plan", "bct_get_execute_plan", "bct_work_create", "bct_operation_get", "bct_inbox_get", "bct_task_run", "bct_task_message", "bct_send_delayed_message", "bct_delayed_send_cancel",
                            "bct_check_node", "bct_recheck_node", "bct_pause_node", "bct_replace_node", "bct_reset_node",
                            "bct_github_inbox_get", "bct_send_message", "bct_set_project_plan", "bct_plan_run", "bct_run_task", "bct_context", "bct_cancel_delayed_send",
                            "bct_create_work", "bct_operation", "bct_github_inbox", "bct_inbox", "bct_move_tab", "bct_close_tab", "bct_rcc_command_catalog", "bct_rcc_recipe_catalog",
                        },
                        set(capabilities.structured_content["tools"]),
                    )
                    status = await session.call_tool("bct_status", {})
                    self.assertFalse(status.is_error)
                    self.assertTrue(status.structured_content["core"]["ready"])
                    self.assertEqual(live_relay_usage,
                                     status.structured_content["browser_usage"])
                    self.assertRegex(status.structured_content["mcp_trace_id"], r"^[0-9a-f]{32}$")
                    self.assertEqual(self.release_sha, status.structured_content["runtime"]["release_sha"])
                    self.assertIn("rcc", status.structured_content["monitor"])
                    conversation_network = await session.call_tool(
                        "bct_get_conversation_network", {"project": "BCT RCC"}
                    )
                    self.assertFalse(conversation_network.is_error, conversation_network)
                    self.assertEqual("OK", conversation_network.structured_content["status"])
                    member = conversation_network.structured_content["members"][0]
                    self.assertEqual("D1-3", member["monitor"]["node_label"])
                    self.assertNotIn(self.manager, json.dumps(conversation_network.structured_content))
                    network_alias = await session.call_tool(
                        "bct_get_conversation_network", {"project": "BCT RCC"}
                    )
                    self.assertFalse(network_alias.is_error)
                    self.assertEqual(conversation_network.structured_content,
                                     network_alias.structured_content)
                    network_check = await session.call_tool(
                        "bct_check_conversation_network", {"project": "BCT RCC"}
                    )
                    self.assertFalse(network_check.is_error)
                    self.assertEqual("OK", network_check.structured_content["status"])
                    self.assertTrue(network_check.structured_content["read_only"])
                    self.assertTrue(network_check.structured_content["context_requires_work"])
                    self.assertEqual("AUTH_CONTEXT_REQUIRED",
                                     network_check.structured_content["context_status"])
                    self.assertEqual("CURRENT_CONFIRMED_NODES_ONLY",
                                     network_check.structured_content["candidates_scope"])
                    self.assertEqual("NOT_REQUESTED",
                                     network_check.structured_content["historical_contexts_status"])
                    self.assertIn(network_check.structured_content["supervisor"]["status"],
                                  {"MISSING", "PRESENT", "MULTIPLE"})
                    self.assertEqual("supervisor",
                                     network_check.structured_content["supervisor"]["role_tag"])
                    self.assertEqual("CURRENT_CONFIRMED_NODES_ONLY",
                                     network_check.structured_content["supervisor"]["scope"])
                    scopes = network_check.structured_content["scope_directory"]
                    self.assertTrue(any(item["scope_name"] == "BCT RCC" and item["state"] == "ACTIVE"
                                        for item in scopes))
                    blank_network_check = await session.call_tool("bct_check_conversation_network", {})
                    self.assertFalse(blank_network_check.is_error)
                    self.assertEqual("OK", blank_network_check.structured_content["status"])
                    self.assertEqual("NOT_REQUESTED", blank_network_check.structured_content["context_status"])
                    self.assertIsNone(blank_network_check.structured_content["project_context"])

                    self.assertEqual("OK", network_check.structured_content["network"]["status"])
                    checked_member = network_check.structured_content["network"]["members"][0]
                    self.assertEqual("NOT_OPEN", checked_member["current_node_presence"])
                    self.assertIsNone(checked_member["current_node"])
                    self.assertNotIn("_conversation_key", checked_member)
                    self.assertIn("nodes", network_check.structured_content)
                    self.assertIn("rcc", network_check.structured_content)

                    work_arguments = {
                        "work_id": "mcp-read-work",
                        "request_summary": "read one exact test file",
                        "roots": [str(self.project)],
                        "actions": ["read"],
                    }
                    created = await session.call_tool("bct_work_create", work_arguments)
                    repeated = await session.call_tool("bct_work_create", work_arguments)
                    self.assertFalse(created.is_error)
                    scanned = await session.call_tool("scan_code_blocks", {
                        "work_id": "mcp-read-work", "max_files": 20, "max_blocks": 100,
                    })
                    self.assertFalse(scanned.is_error, scanned)
                    self.assertEqual("bct.code-block-scan.v1", scanned.structured_content["schema"])
                    self.assertTrue(scanned.structured_content["read_only"])
                    self.assertIn("block_map", scanned.structured_content)
                    self.assertIn("block_cards", scanned.structured_content)
                    block = next(
                        item for item in scanned.structured_content["block_cards"]
                        if item["path"] == "blocks.py" and item["name"] == "change"
                    )
                    planned_block = await session.call_tool("organize_code_blocks", {
                        "work_id": "mcp-read-work", "action": "plan",
                        "path": "blocks.py", "block_id": block["block_id"],
                        "replacement": "def change(value):\n    return value * 2",
                        "expected_file_sha256": block["file_sha256"],
                        "expected_block_sha256": block["source_sha256"],
                    })
                    self.assertFalse(planned_block.is_error, planned_block)
                    plan = planned_block.structured_content
                    self.assertTrue(plan["read_only"])
                    self.assertIn("return value * 2", plan["diff"])
                    write_work = await session.call_tool("bct_work_create", {
                        "work_id": "mcp-block-write-work",
                        "request_summary": "apply one exact scanned block",
                        "roots": [str(self.project)], "actions": ["read", "write"],
                    })
                    self.assertFalse(write_work.is_error, write_work)
                    apply_args = {
                        "work_id": "mcp-block-write-work", "action": "apply",
                        "operation_id": "mcp-block-apply-1",
                        "path": "blocks.py", "block_id": block["block_id"],
                        "replacement": plan["replacement"],
                        "expected_file_sha256": plan["expected_file_sha256"],
                        "expected_block_sha256": plan["expected_block_sha256"],
                        "expected_after_sha256": plan["after_file_sha256"],
                        "plan_sha256": plan["plan_sha256"],
                    }
                    applied_block = await session.call_tool("organize_code_blocks", apply_args)
                    replayed_block = await session.call_tool("organize_code_blocks", apply_args)
                    self.assertFalse(applied_block.is_error, applied_block)
                    self.assertEqual("APPLIED", applied_block.structured_content["outcome"])
                    self.assertTrue(replayed_block.structured_content["duplicate"])
                    updated = (self.project / "blocks.py").read_text(encoding="utf-8")
                    self.assertIn("return 'keep'", updated)
                    self.assertIn("return value * 2", updated)
                    self.assertNotIn("return value + 1", updated)
                    self.assertFalse(created.structured_content["duplicate"])
                    self.assertTrue(repeated.structured_content["duplicate"])
                    denied_context = await session.call_tool("bct_check_conversation_network", {
                        "project": "missingproject",
                        "work_id": "mcp-read-work",
                        "operation_id": "mcp-context-denied-1",
                    })
                    self.assertFalse(denied_context.is_error)
                    self.assertEqual("ACCESS_DENIED",
                                     denied_context.structured_content["context_status"])
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
                    self.assertFalse(read_result.is_error)
                    self.assertEqual("APPLIED", read_result.structured_content["outcome"])
                    self.assertEqual("hello from MCP\n", read_result.structured_content["output"]["text"])
                    self.assertTrue(duplicate.structured_content["duplicate"])
                    self.assertEqual("APPLIED", receipt.structured_content["outcome"])
                    batch_result = await session.call_tool("bct_read", {
                        "work_id": "mcp-read-work",
                        "operation_id": "mcp-read-batch-1",
                        "arguments": {
                            "operation": "batch",
                            "items": [
                                {"id": "hello", "path": str(self.project / "hello.txt")},
                                {"id": "tree", "operation": "directory_tree",
                                 "path": str(self.project), "depth": 0, "limit": 20},
                            ],
                        },
                    })
                    self.assertFalse(batch_result.is_error, batch_result)
                    self.assertEqual("APPLIED", batch_result.structured_content["outcome"])
                    self.assertEqual("COMPLETE", batch_result.structured_content["output"]["status"])
                    self.assertEqual(
                        ["hello", "tree"],
                        [item["id"] for item in batch_result.structured_content["output"]["items"]],
                    )
                    self.assertEqual(
                        "hello from MCP\n",
                        batch_result.structured_content["output"]["items"][0]["output"]["text"],
                    )
                    scoped_denial = await session.call_tool("bct_scoped_read", {
                        "work_id": "mcp-read-work", "operation_id": "scoped-denied",
                        "arguments": {"path": str(self.root / "outside.txt")},
                    })
                    self.assertTrue(scoped_denial.is_error)
                    self.assertIn("TARGET_OUTSIDE_WORK_SCOPE", scoped_denial.content[0].text)
                    absent = await session.call_tool("bct_operation_get", {
                        "work_id": "mcp-read-work", "operation_id": "scoped-denied",
                    })
                    self.assertTrue(absent.is_error)
                    self.assertIn("OPERATION_NOT_FOUND", absent.content[0].text)
                    direct_work = await session.call_tool("bct_work_create", {
                        "work_id": "pc-read-receipts", "request_summary": "direct read",
                        "roots": [], "actions": ["desktop_read"],
                    })
                    self.assertFalse(direct_work.is_error)
                    foreign_receipt = await session.call_tool("bct_operation_get", {
                        "work_id": "pc-read-receipts", "operation_id": "mcp-read-1",
                    })
                    self.assertTrue(foreign_receipt.is_error)
                    self.assertIn("OPERATION_NOT_FOUND", foreign_receipt.content[0].text)
                    direct_denial = await session.call_tool("bct_read", {
                        "work_id": "pc-read-receipts", "operation_id": "direct-unconfigured",
                        "arguments": {"path": str(self.project / "hello.txt")},
                        "approval_ref": "e30.eA",
                    })
                    self.assertTrue(direct_denial.is_error)
                    self.assertIn("APPROVAL_VERIFIER_DISABLED", direct_denial.content[0].text)
                    continued = await session.call_tool("bct_work_create", {
                        **work_arguments,
                        "request_summary": "continue the same task with a broader authorized root",
                        "roots": [str(self.root)],
                        "actions": ["read", "write"],
                    })
                    self.assertFalse(continued.is_error, continued)
                    self.assertTrue(continued.structured_content["updated"])
                    self.assertFalse(continued.structured_content["duplicate"])
                    self.assertEqual(
                        {"read", "write"},
                        set(continued.structured_content["work"]["actions"]),
                    )
                    self.assertEqual(
                        [str(self.project.resolve()), str(self.root.resolve())],
                        continued.structured_content["work"]["roots"],
                    )

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
                    self.assertFalse(completed.is_error, completed)
                    self.assertEqual("APPLIED", completed.structured_content["outcome"])

                    await session.call_tool("bct_work_create", {
                        "work_id": "verification", "request_summary": "bounded verification",
                        "roots": [str(self.project)], "actions": ["verify", "read", "test"],
                    })
                    verification = {
                        "work_id": "verification", "operation_id": "verification-1",
                        "arguments": {"steps": [
                            {"id": "source", "capability": "read", "arguments": {"path": str(self.project / "slow.py")}},
                            {"id": "compile", "capability": "test", "arguments": {
                                "cwd": str(self.project), "kind": "py_compile", "targets": ["slow.py"]}},
                        ]},
                    }
                    accepted = await session.call_tool("bct_verify", verification)
                    self.assertFalse(accepted.is_error, accepted)
                    duplicate = await session.call_tool("bct_verify", verification)
                    self.assertTrue(duplicate.structured_content["duplicate"])
                    cached = await session.call_tool("bct_test", {
                        **verification, "arguments": {**verification["arguments"], "operation": "verify"},
                    })
                    self.assertFalse(cached.is_error, cached)
                    self.assertTrue(cached.structured_content["duplicate"])
                    continued_verification = await session.call_tool("bct_test", {
                        **verification, "work_id": "mcp-read-work",
                        "operation_id": "continued-work-recipe",
                        "arguments": {**verification["arguments"], "operation": "verify"},
                    })
                    self.assertFalse(continued_verification.is_error, continued_verification)
                    continued_done = await session.call_tool("bct_operation_get", {
                        "work_id": "mcp-read-work",
                        "operation_id": "continued-work-recipe",
                        "wait_seconds": 25,
                    })
                    self.assertFalse(continued_done.is_error, continued_done)
                    self.assertEqual("APPLIED", continued_done.structured_content["outcome"])

        # Disconnect before waiting: the one-shot worker must complete independently.
        async with httpx.AsyncClient(headers=headers, timeout=30) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    completed = await session.call_tool("bct_operation_get", {
                        "work_id": "verification", "operation_id": "verification-1", "wait_seconds": 25,
                    })
                    self.assertFalse(completed.is_error, completed)
                    self.assertEqual("APPLIED", completed.structured_content["outcome"])
                    self.assertEqual("PASS", completed.structured_content["evidence"]["status"])
                    self.assertEqual(2, len(completed.structured_content["evidence"]["steps"]))
                    self.assertEqual(2, len(completed.structured_content["step_journal"]))
                    self.assertTrue(all(
                        step["state"] == "FINISHED"
                        for step in completed.structured_content["step_journal"]
                    ))
                    self.assertNotIn("output", completed.structured_content)

        monitor = httpx.get(f"http://127.0.0.1:{self.port}/monitor/state", timeout=3)
        self.assertEqual(200, monitor.status_code)
        monitor_state = monitor.json()
        self.assertEqual(1, monitor_state["schema"])
        self.assertEqual(self.release_sha, monitor_state["service"]["release_sha"])
        self.assertTrue(monitor_state["observability"]["read_only"])
        self.assertNotIn("counts", monitor_state)
        self.assertIn("instances", monitor_state["rcc"])

        roster_revision = httpx.get(f"http://127.0.0.1:{self.port}/monitor/roster-revision", timeout=3)
        self.assertEqual(200, roster_revision.status_code)
        roster_revision_view = roster_revision.json()
        self.assertEqual(1, roster_revision_view["schema"])
        self.assertEqual("READ_ONLY_MONITOR_ROSTER_REVISION", roster_revision_view["source"])
        self.assertRegex(roster_revision_view["revision"], r"^[a-f0-9]{64}$")
        roster_events_url = f"http://127.0.0.1:{self.port}/monitor/roster-events"
        self.assertEqual(httpx.get(roster_events_url, timeout=3).status_code, 403)
        event_headers = {"X-BCT-Monitor-Events": "1"}
        self.assertEqual(httpx.get(roster_events_url, headers={**event_headers, "Origin": "https://example.com"},
                                   timeout=3).status_code, 403)
        with httpx.stream("GET", roster_events_url, headers=event_headers, timeout=3) as event_stream:
            self.assertEqual(event_stream.status_code, 200)
            self.assertEqual(next(event_stream.iter_lines()), "data: changed")

        current_nodes = httpx.get(f"http://127.0.0.1:{self.port}/monitor/current-nodes", timeout=3)
        self.assertEqual(200, current_nodes.status_code)
        current_node_view = current_nodes.json()
        self.assertEqual("READ_ONLY_MONITOR_UI_SNAPSHOT", current_node_view["source"])
        self.assertIn("items", current_node_view["current_nodes"])
        self.assertIn("conversation_network_managers", current_node_view)

        command_catalog = httpx.get(f"http://127.0.0.1:{self.port}/monitor/rcc-command-catalog", timeout=3)
        self.assertEqual(200, command_catalog.status_code)
        command_catalog_view = command_catalog.json()
        self.assertEqual(1, command_catalog_view["schema"])
        self.assertEqual("bct.features.rcc.command_catalog", command_catalog_view["source"])
        self.assertIn("rcc_get_extension_state", {row["command"] for row in command_catalog_view["commands"]})

    def test_authenticated_catalogue_work_call_and_duplicate_receipt(self):
        asyncio.run(self.exercise_mcp())


if __name__ == "__main__":
    unittest.main()
