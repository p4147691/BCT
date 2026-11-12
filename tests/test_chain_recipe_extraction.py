"""Extraction guards: public compatibility and independent recipe ownership."""
from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import tempfile
import tomllib
from types import SimpleNamespace
import unittest

from bct.conversation_network import upsert_project
from bct.core.models import Principal, Work
from bct.core.store import Store
from bct.mcp_server import build_mcp
from bct.recipes.input import input_recipe
from bct.recipes.runtime import ChainRecipeRuntime
from bct.recipes.state import read_stored_networks_recipe

ROOT = Path(__file__).resolve().parents[1]
CAPABILITIES = ("browser", "conversation_network_update", "read")
# Independently measured on the source baseline with the LOOP entry excluded.
# Chain Recipe itself must still match the original immutable baseline below.
# Hash every sorted Tool.model_dump(mode="json", exclude_none=True), including
# names, descriptions, inputSchema and outputSchema. No Git history is needed
# at test time (release archives and shallow CI checkouts remain supported).
BASELINE_CATALOGUES = {
    "full": (50, "33cb04a9cc0cc6b87cfc5ff0fc52b16cdd8d802a5aa675a1e38a5f8f6dc5091d"),
    "compact": (48, "ee1e8c5578276017e3c1467c6b3d4c98def213dd136c482d0e17d22809edf57b"),
    "hybrid": (49, "beb53bc80b1ca757fc216806d5db6ef5c0361d78426b6cfb181be21c5eea2169"),
}
BASELINE_CHAIN = "6bd459c6682f8464632fc75d8b27418b79307a47130e0678899b7843b32eea12"
OWNERS = {
    "input": ("input_recipe", "manager_return_chain_link_recipe", "manager_return_save_context"),
    "state": ("state_recipe", "build_current_node_info_recipe", "read_stored_networks_recipe", "check_conversation_network_recipe"),
    "direction": ("prepare_direction_recipe", "write_direction_recipe", "save_direction_recipe", "read_saved_direction"),
    "outline": ("chain_recipe_outline", "chain_recipe_progress"),
    "recovery": ("recover_node_recipe",),
    "network": ("apply_conversation_network_recipe",),
    "delivery": ("prepare_send_direction_recipe", "send_direction_recipe", "send_chain_delivery", "_run_direction_targets"),
    "chain": ("chain_recipe",),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


class NoEffects:
    capabilities = CAPABILITIES

    def run(self, **kwargs):
        raise AssertionError("Read-only extraction contract must not execute effects")


class ChainRecipeStructureTests(unittest.TestCase):
    def test_mcp_entry_only_forwards_every_argument_to_full_recipe(self):
        tree = ast.parse((ROOT / "src/bct/mcp_server.py").read_text(encoding="utf-8"))
        entry = next(node for node in ast.walk(tree)
                     if isinstance(node, ast.AsyncFunctionDef) and node.name == "bct_chain_recipe")
        body = [node for node in entry.body if not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str))]
        self.assertEqual(len(body), 1, "MCP entry must not retain recipe decisions")
        self.assertIsInstance(body[0], ast.Return)
        self.assertIsInstance(body[0].value, ast.Await)
        call = body[0].value.value
        self.assertIsInstance(call, ast.Call)
        self.assertEqual(ast.unparse(call.func), "chain_recipe")
        self.assertEqual([ast.unparse(arg) for arg in call.args], ["recipe_runtime"])
        self.assertEqual({item.arg: ast.unparse(item.value) for item in call.keywords},
                         {arg.arg: arg.arg for arg in entry.args.args})

    def test_partial_recipes_are_owned_by_standalone_transport_free_modules(self):
        server_tree = ast.parse((ROOT / "src/bct/mcp_server.py").read_text(encoding="utf-8"))
        server_definitions = {node.name for node in ast.walk(server_tree)
                              if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for module_name, symbols in OWNERS.items():
            module = importlib.import_module("bct.recipes." + module_name)
            tree = ast.parse(inspect.getsource(module))
            with self.subTest(module=module_name):
                for symbol in symbols:
                    function = getattr(module, symbol)
                    self.assertEqual(function.__module__, module.__name__)
                    self.assertNotIn(symbol, server_definitions)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        self.assertFalse((node.module or "").startswith("mcp"))
                        self.assertNotIn("mcp_server", node.module or "")
                    elif isinstance(node, ast.Import):
                        self.assertFalse(any(alias.name.startswith("mcp") for alias in node.names))
                    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        self.assertNotIn(node.func.attr, {"call_tool", "tool"})

    def test_release_manifest_contains_every_recipe_module(self):
        config = tomllib.loads((ROOT / "bct.toml").read_text(encoding="utf-8"))
        shipped = config["deployment"]["profiles"]["bct_runtime_v1"]["files"]
        modules = list((ROOT / "src/bct/recipes").glob("*.py"))
        self.assertGreaterEqual(len(modules), 10)
        for path in modules:
            relative = path.relative_to(ROOT).as_posix()
            with self.subTest(path=relative):
                self.assertEqual(shipped.count(relative), 1)


class ChainRecipeRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_public_metadata_matches_pre_extraction_baseline(self):
        for mode, (count, expected) in BASELINE_CATALOGUES.items():
            with self.subTest(mode=mode):
                server = build_mcp(SimpleNamespace(operations=NoEffects()),
                                   compact_catalogue=mode == "compact",
                                   hybrid_catalogue=mode == "hybrid")
                metadata = sorted((tool.model_dump(mode="json", exclude_none=True)
                                   for tool in await server.list_tools()), key=lambda item: item["name"])
                chain = next(tool for tool in metadata if tool["name"] == "bct_chain_recipe")
                self.assertEqual(digest(chain), BASELINE_CHAIN, "Chain public metadata changed")
                self.assertEqual(len(metadata), count)
                unrelated = [tool for tool in metadata if tool["name"] != "bct_loop_recipe"]
                self.assertEqual(digest(unrelated), expected, "Non-LOOP tool metadata changed")

    async def test_two_mcp_instances_keep_work_store_and_snapshot_ports_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            servers, counters = [], [0, 0]
            for index in range(2):
                store = Store(Path(directory) / f"server-{index}.sqlite")
                store.create_work(Work("same-work", f"work-{index}", (), frozenset(), "bct-mcp-local"))
                upsert_project(store, project_id=f"project-{index}", display_name=f"Distinct network {index}")
                def provider(index=index):
                    counters[index] += 1
                    return {}
                servers.append(build_mcp(SimpleNamespace(store=store, operations=NoEffects()),
                                         status_provider=provider, compact_catalogue=True))
            # Interleave after both servers exist: catches last-instance global capture.
            for index in (0, 1, 0):
                _, result = await servers[index].call_tool("bct_chain_recipe", {
                    "work_id": "same-work", "source_text": "Inspect without effects.",
                })
                self.assertEqual(result["status"], "RECIPE_READY", result)
                self.assertEqual(result["input"]["work"]["request_summary"], f"work-{index}")
                stored = json.dumps(result["state"]["stored_networks"])
                self.assertIn(f"Distinct network {index}", stored)
                self.assertNotIn(f"Distinct network {1-index}", stored)
                self.assertTrue(result["read_only"])
                self.assertFalse(result["authorizes_send"])
            self.assertEqual(counters, [2, 1], "State must read its own provider exactly once per prepare")

    async def test_runtime_keeps_principal_and_executor_ports_explicit_and_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "runtime.sqlite")
            store.create_work(Work("private-work", "owned", (), frozenset(), "owner"))
            calls = []
            def executor_for(label):
                def make_executor(capability):
                    async def execute(*args, **kwargs):
                        calls.append((label, capability, args))
                        return {"outcome": "APPLIED", "output": {"items": [{"project_id": label}]}}
                    return execute
                return make_executor
            runtime = ChainRecipeRuntime(SimpleNamespace(store=store),
                Principal("owner", "test", frozenset()), None, executor_for("first"))
            other = replace(runtime, principal=Principal("other", "test", frozenset()),
                            make_executor=executor_for("second"))
            with self.assertRaises(FrozenInstanceError):
                runtime.status_provider = lambda: {}
            arguments = dict(work_id="private-work", source_kind="USER", source_task_id="",
                             source_generation=0, source_text="Inspect.", allow_unbound_user=False,
                             require_source_text=True)
            self.assertEqual((await input_recipe(runtime, **arguments))["status"], "OK")
            self.assertEqual(await input_recipe(other, **arguments),
                             {"status": "NOT_FOUND", "reason": "WORK_NOT_FOUND"})
            for current in (runtime, other, runtime):
                result = await read_stored_networks_recipe(current, current_node_items=[], candidates={},
                    work_id="private-work", operation_id="read-context")
                self.assertEqual(result["historical_contexts_status"], "OK", result)
            self.assertEqual([call[:2] for call in calls],
                             [("first", "project_context"), ("second", "project_context"),
                              ("first", "project_context")])


if __name__ == "__main__":
    unittest.main()
