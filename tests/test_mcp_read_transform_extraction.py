"""Contracts for transport-free read/composition extraction from MCP handlers."""
from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import replace
import importlib
import inspect
from pathlib import Path
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bct.conversation_network import upsert_project
from bct.core.models import Principal, Work
from bct.core.store import Store
from bct.discovery_views import capability_view, rcc_command_view, rcc_recipe_view
from bct.mcp_server import build_mcp
from bct.project_plan import prepare_project_plan
from bct.recipes.code_blocks import scan_work_code_blocks
from bct.recipes.runtime import ChainRecipeRuntime
from bct.status_queries import read_conversation_network, read_status
from bct.trace_timing import TRACE_ID

ROOT = Path(__file__).resolve().parents[1]
MODULES = {
    "discovery_views": ("capability_view", "rcc_command_view", "rcc_recipe_view"),
    "status_queries": ("read_status", "read_conversation_network"),
    "project_plan": ("prepare_project_plan",),
    "recipes.code_blocks": ("scan_work_code_blocks",),
}


def valid_plan(**overrides):
    return {
        "work_id": "owned-work", "plan_id": "Plan-1", "project": "Project Alpha",
        "objective": "Separate read composition.", "acceptance": "Existing contracts pass.",
        "steps": [{"instruction": "Extract", "acceptance": "Same results"}],
        "author": "owner", **overrides,
    }


def database_dump(store):
    with store._readonly() as db:
        return tuple(db.iterdump())


class NoEffects:
    capabilities = ("read", "browser", "project_context")

    def run(self, **kwargs):
        raise AssertionError("Read-only path must not execute a capability")


class ExtractionStructureTests(unittest.TestCase):
    def test_services_have_real_module_ownership_and_no_mcp_dependency(self):
        for name, symbols in MODULES.items():
            module = importlib.import_module("bct." + name)
            tree = ast.parse(inspect.getsource(module))
            for symbol in symbols:
                self.assertEqual(getattr(module, symbol).__module__, module.__name__)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or "").startswith("mcp"))
                    self.assertNotIn("mcp_server", node.module or "")
                elif isinstance(node, ast.Import):
                    self.assertFalse(any(item.name.startswith("mcp") for item in node.names))
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, {"tool", "call_tool"})

    def test_read_entries_only_forward_to_owned_queries(self):
        tree = ast.parse((ROOT / "src/bct/mcp_server.py").read_text(encoding="utf-8"))
        entries = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)}
        for name, target in {
            "bct_status": "read_status",
            "bct_get_conversation_network": "read_conversation_network",
            "scan_code_blocks": "scan_work_code_blocks",
            "bct_rcc_command_catalog": "rcc_command_view",
            "bct_rcc_recipe_catalog": "rcc_recipe_view",
        }.items():
            statements = [node for node in entries[name].body if not (
                isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str))]
            self.assertEqual(len(statements), 1, name)
            self.assertIsInstance(statements[0], ast.Return)
            value = statements[0].value
            if isinstance(value, ast.Await):
                value = value.value
            self.assertEqual(ast.unparse(value.func), target)

    def test_all_extracted_modules_are_shipped_once(self):
        config = tomllib.loads((ROOT / "bct.toml").read_text(encoding="utf-8"))
        shipped = config["deployment"]["profiles"]["bct_runtime_v1"]["files"]
        for name in MODULES:
            self.assertEqual(shipped.count("src/bct/" + name.replace(".", "/") + ".py"), 1)


class DiscoveryViewTests(unittest.TestCase):
    def test_actual_metadata_and_warning_are_preserved_without_mutating_inputs(self):
        tools = [{"name": "bct_browser", "description": "Actual metadata", "inputSchema": {"type": "object"}}]
        usage = {"browser": "Current browser contract"}
        original = deepcopy((tools, usage))
        result = capability_view(tool_metadata=tools, capabilities=("browser",), usage=usage,
                                 tool_name="bct_browser", catalogue_warning="invalid saved catalogue")
        self.assertEqual(result["tool"], tools[0])
        self.assertEqual(result["tools"], ["bct_browser"])
        self.assertEqual(result["browser_usage"], usage["browser"])
        self.assertEqual(result["catalogue_warning"], "invalid saved catalogue")
        self.assertTrue(result["read_only"])
        self.assertFalse(result["authorizes_execution"])
        self.assertEqual((tools, usage), original)

    def test_query_validation_and_empty_warning_keep_the_public_shape(self):
        result = capability_view(tool_metadata=[], capabilities=(), usage={"browser": "contract"},
                                 limit=21, catalogue_warning="")
        self.assertEqual(result["status"], "INVALID_REQUEST")
        self.assertEqual(result["reason"], "LIBRARY_QUERY_INVALID")
        self.assertNotIn("catalogue_warning", result)
        self.assertEqual(result["tools"], [])

    def test_rcc_views_reuse_the_existing_catalogues(self):
        from bct.features.rcc import command_catalog, recipe_catalog
        commands, recipes = rcc_command_view(), rcc_recipe_view()
        self.assertEqual(commands["commands"], command_catalog())
        self.assertEqual(recipes["recipes"], recipe_catalog())
        self.assertEqual(commands["tool"], "bct_browser")
        self.assertEqual(recipes["invocation"]["required"],
                         ["work_id", "operation_id", "arguments.command"])


class ProjectPlanPreparationTests(unittest.TestCase):
    def test_pure_preparation_matches_the_exact_existing_project_context_payload(self):
        args = valid_plan(expected_revision=3, discretion="limited", assumptions=["Keep existing behavior."])
        original = deepcopy(args)
        prepared = prepare_project_plan(**args)
        self.assertEqual(prepared, {
            "status": "READY",
            "arguments": {
                "operation": "central-save", "project": "run-plan-plan-1",
                "author": "owner", "expected_revision": 3,
                "record": {
                    "title": "Run plan Plan-1", "goal": "Separate read composition.",
                    "scope_note": "Project: Project Alpha; discretion: limited",
                    "summary": "Existing contracts pass.",
                    "links": [{"type": "bct_work", "id": "owned-work"}],
                    "items": [{"text": "1/1: Extract | 완료: Same results", "evidence": []}],
                    "decisions": [{"text": "재량: limited", "evidence": []}],
                    "next_actions": [{"text": "가정: Keep existing behavior.", "evidence": []}],
                    "checkpoints": {"external": {"plan_id": "Plan-1", "project": "Project Alpha", "stage": "PLANNED"}},
                },
            },
        })
        self.assertEqual(args, original)

    def test_invalid_inputs_keep_exact_reason_and_validation_order(self):
        cases = [
            ({"plan_id": "bad space", "project": ""}, "ID_INVALID"),
            ({"plan_id": "x" * 81}, "ID_INVALID"),
            ({"project": " "}, "REQUIRED_FIELDS"),
            ({"objective": ""}, "REQUIRED_FIELDS"),
            ({"acceptance": ""}, "REQUIRED_FIELDS"),
            ({"steps": []}, "STEPS_INVALID"),
            ({"steps": {}}, "STEPS_INVALID"),
            ({"discretion": "unlimited"}, "DISCRETION_INVALID"),
            ({"steps": [{}]}, "STEP_INVALID"),
            ({"steps": ["not a mapping"]}, "STEP_INVALID"),
            ({"steps": [{"instruction": "", "acceptance": "valid"}]}, "STEP_INVALID"),
            ({"steps": [{"instruction": "valid", "acceptance": 2}]}, "STEP_INVALID"),
            ({"expected_revision": True}, "REVISION_INVALID"),
            ({"expected_revision": -1}, "REVISION_INVALID"),
            ({"expected_revision": 1.0}, "REVISION_INVALID"),
            ({"assumptions": "not a list"}, "ASSUMPTIONS_INVALID"),
            ({"assumptions": [3]}, "ASSUMPTIONS_INVALID"),
        ]
        for overrides, reason in cases:
            with self.subTest(overrides=overrides):
                self.assertEqual(prepare_project_plan(**valid_plan(**overrides)),
                                 {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_" + reason})

    def test_list_and_text_limits_keep_their_existing_inclusive_boundaries(self):
        step = {"instruction": "i" * 4000, "acceptance": "a" * 4000}
        self.assertEqual(prepare_project_plan(**valid_plan(steps=[step] * 50, assumptions=["x" * 2000] * 30))["status"], "READY")
        for overrides, reason in [
            ({"steps": [step] * 51}, "STEPS_INVALID"),
            ({"steps": [{**step, "instruction": "i" * 4001}]}, "STEP_INVALID"),
            ({"steps": [{**step, "acceptance": "a" * 4001}]}, "STEP_INVALID"),
            ({"assumptions": ["x"] * 31}, "ASSUMPTIONS_INVALID"),
            ({"assumptions": ["x" * 2001]}, "ASSUMPTIONS_INVALID"),
        ]:
            self.assertEqual(prepare_project_plan(**valid_plan(**overrides))["reason"], "RUN_PLAN_" + reason)


class QueryContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "state.sqlite")
        self.bct = SimpleNamespace(store=self.store, operations=NoEffects())

    async def test_status_reads_provider_once_keeps_source_and_database_unchanged(self):
        snapshot = {"core": {"release": "fixture"}, "monitor": {"works": [{"work_id": str(i)} for i in range(9)]}}
        original = deepcopy(snapshot)
        before = database_dump(self.store)
        provider = Mock(return_value=snapshot)
        token = TRACE_ID.set("read-query-fixture")
        try:
            result = await read_status(self.bct, principal_id="owner", status_provider=provider,
                                       browser_usage="current contract")
        finally:
            TRACE_ID.reset(token)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(result["monitor"]["works"], original["monitor"]["works"][:5])
        self.assertTrue(result["compact"])
        self.assertEqual(result["browser_usage"], "current contract")
        self.assertEqual(result["mcp_trace_id"], "read-query-fixture")
        self.assertEqual(result["chain_branch_attention"], [])
        self.assertEqual(snapshot, original)
        self.assertEqual(database_dump(self.store), before)

    async def test_status_rejects_invalid_requests_before_observation_or_store_access(self):
        provider = Mock(side_effect=AssertionError("Unexpected observation"))
        self.assertEqual(await read_status(object(), principal_id="owner", status_provider=None,
                                          browser_usage="contract", scope="invalid"),
                         {"status": "UNAVAILABLE", "reason": "STATUS_PROVIDER_NOT_CONFIGURED"})
        self.assertEqual(await read_status(object(), principal_id="owner", status_provider=provider,
                                          browser_usage="contract", scope="invalid"),
                         {"status": "INVALID_REQUEST", "reason": "BCT_STATUS_SCOPE_INVALID"})
        provider.assert_not_called()

    async def test_non_default_scope_does_not_require_a_store(self):
        provider = Mock(return_value={})
        result = await read_status(object(), principal_id="owner", status_provider=provider,
                                   browser_usage="contract", scope="node")
        self.assertEqual(result, {"status": "UNAVAILABLE", "scope": "node", "reason": "MONITOR_SNAPSHOT_UNAVAILABLE"})
        self.assertEqual(provider.call_count, 1)

    async def test_status_attention_filters_owner_and_retains_compact_and_full_limits(self):
        self.store.create_work(Work("mine", "mine", (), frozenset(), "owner"))
        self.store.create_work(Work("theirs", "theirs", (), frozenset(), "other"))
        attention = [{"request_id": str(i)} for i in range(22)]
        with patch("bct.chain_direction.ChainBranchRequestLedger.tree", return_value={"manager_attention": attention}) as tree, \
             patch("bct.chain_execution_plan.ChainExecutionPlanLedger.list_latest_execute_plan_checks", return_value=[]) as checks, \
             patch("bct.chain_direction.ChainDirectionLedger.list_pending_chain_starts", return_value=[]) as pending:
            for compact, limit in ((True, 5), (False, 20)):
                result = await read_status(self.bct, principal_id="owner", status_provider=lambda: {},
                                           browser_usage="contract", compact=compact)
                self.assertEqual(result["chain_branch_attention"],
                                 [{"root_work_id": "mine", **item} for item in attention[:limit]])
                checks.assert_called_with(store=self.store, limit=limit)
                pending.assert_called_with(store=self.store, principal_id="owner", limit=limit)
            self.assertEqual([call.kwargs["root_work_id"] for call in tree.call_args_list], ["mine", "mine"])

    async def test_network_error_mapping_and_real_query_are_read_only(self):
        upsert_project(self.store, project_id="project-one", display_name="Project One")
        before = database_dump(self.store)
        result = await read_conversation_network(self.bct, project="Project One")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["project"], {"display_name": "Project One", "active": True})
        self.assertNotIn("project_id", result["project"])
        self.assertEqual(await read_conversation_network(self.bct, project="missing"),
                         {"status": "NOT_FOUND", "reason": "CONVERSATION_NETWORK_PROJECT_NOT_FOUND"})
        self.assertEqual(await read_conversation_network(self.bct, project=" "),
                         {"status": "INVALID_REQUEST", "reason": "CONVERSATION_NETWORK_PROJECT_REFERENCE_INVALID"})
        self.assertEqual(database_dump(self.store), before)

    async def test_two_servers_keep_snapshot_and_network_dependencies_separate(self):
        servers, counters = [], [0, 0]
        for index in range(2):
            store = Store(Path(self.temp.name) / f"server-{index}.sqlite")
            upsert_project(store, project_id="same-project", display_name=f"Network {index}")
            def provider(index=index):
                counters[index] += 1
                return {"marker": index}
            servers.append(build_mcp(SimpleNamespace(store=store, operations=NoEffects()), status_provider=provider))
        for index in (0, 1, 0):
            _, status = await servers[index].call_tool("bct_status", {})
            _, network = await servers[index].call_tool("bct_get_conversation_network", {"project": "same-project"})
            self.assertEqual(status["marker"], index)
            self.assertEqual(network["project"]["display_name"], f"Network {index}")
        self.assertEqual(counters, [2, 1])

    async def test_scan_keeps_work_owner_root_and_read_fences_without_effects(self):
        root = Path(self.temp.name) / "scan"
        root.mkdir()
        source = root / "one.py"
        source.write_text("def original():\n    return 1\n", encoding="utf-8")
        self.store.create_work(Work("scan-work", "read only", (str(root),), frozenset({"read"}), "owner"))
        runtime = ChainRecipeRuntime(self.bct, Principal("owner", "test", frozenset({"read"})), None,
                                     lambda capability: (_ for _ in ()).throw(AssertionError("No executor")))
        before = database_dump(self.store)
        result = await scan_work_code_blocks(runtime, work_id="scan-work")
        self.assertTrue(result["read_only"])
        self.assertTrue(result["scan"]["complete"])
        self.assertEqual(result["scan"]["files"], 1)
        self.assertEqual(source.read_text(encoding="utf-8"), "def original():\n    return 1\n")
        self.assertEqual(database_dump(self.store), before)
        with self.assertRaisesRegex(PermissionError, "WORK_ACCESS_DENIED"):
            await scan_work_code_blocks(replace(runtime, principal=Principal("other", "test", frozenset())), work_id="scan-work")
        with self.assertRaisesRegex(PermissionError, "ROOT_OUTSIDE_WORK"):
            await scan_work_code_blocks(runtime, work_id="scan-work", root=self.temp.name)
        self.store.create_work(Work("no-read", "not readable", (str(root),), frozenset(), "owner"))
        with self.assertRaisesRegex(PermissionError, "READ_REQUIRED"):
            await scan_work_code_blocks(runtime, work_id="no-read")
        with self.assertRaisesRegex(RuntimeError, "STORE_REQUIRED"):
            await scan_work_code_blocks(replace(runtime, bct=object()), work_id="scan-work")

    async def test_plan_aliases_execute_one_unchanged_authorized_request_and_invalid_plan_none(self):
        calls = []
        class Operations:
            capabilities = ("project_context",)
            def run(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(as_dict=lambda: {"state": "FINISHED", "outcome": "APPLIED"})
        server = build_mcp(SimpleNamespace(operations=Operations()))
        request = {**valid_plan(), "operation_id": "exact-plan-operation", "approval_ref": "existing-approval"}
        expected = prepare_project_plan(**valid_plan())["arguments"]
        for name in ("bct_run_plan", "bct_set_project_plan", "bct_plan_run"):
            _, value = await server.call_tool(name, request)
            self.assertEqual(value, {"state": "FINISHED", "outcome": "APPLIED"})
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertEqual(call["capability"], "project_context")
            self.assertEqual(call["arguments"], expected)
            self.assertEqual(call["operation_id"], "exact-plan-operation")
            self.assertEqual(call["approval_ref"], "existing-approval")
            self.assertEqual(call["principal"].principal_id, "bct-mcp-local")
        _, value = await server.call_tool("bct_run_plan", {**request, "plan_id": "bad plan"})
        self.assertEqual(value, {"status": "INVALID_REQUEST", "reason": "RUN_PLAN_ID_INVALID"})
        self.assertEqual(len(calls), 3)

    async def test_loop_new_start_stays_blocked_before_any_store_provider_or_effect(self):
        provider = Mock(side_effect=AssertionError("No observation for disabled start"))
        server = build_mcp(SimpleNamespace(operations=NoEffects()), status_provider=provider)
        _, result = await server.call_tool("bct_loop_recipe", {"action": "start"})
        self.assertEqual(result, {"status": "INVALID_REQUEST", "reason": "LOOP_NEW_START_DISABLED_CHAIN_RESTORED",
                                  "effects": "NONE", "existing_records": "PRESERVED"})
        provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
