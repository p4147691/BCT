from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bct.component_library import BUNDLE_PATH, discover, load_library, get_manual_guidance
from bct.mcp_server import build_mcp

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("library_builder", ROOT / "scripts/build_component_library.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class Operations:
    capabilities = ("read", "desktop_capture")

    def run(self, **kwargs):
        raise AssertionError("Library discovery must never execute an operation")


class LibraryBundleTests(unittest.TestCase):
    def test_guidance_is_bounded_section_of_same_manual_not_a_second_copy(self):
        bundle = load_library()
        guide = get_manual_guidance(bundle)
        self.assertEqual("AVAILABLE", guide["status"])
        self.assertIn(guide["text"], bundle["manual"]["text"])
        self.assertLessEqual(len(guide["text"]), 3000)
        self.assertEqual(bundle["manual"]["sha256"], guide["manual_sha256"])
        self.assertFalse(guide["authorizes_execution"])
        self.assertIn("새 Manager를 자칭하지 않는다", guide["text"])

    def test_missing_or_unbounded_guidance_is_explicit(self):
        for bundle in ({}, {"manual": {"text": "## 바로 시작하는 노드 안내\n" + "x" * 3001}}):
            guide = get_manual_guidance(bundle)
            self.assertEqual("UNAVAILABLE", guide["status"])
            self.assertNotIn("text", guide)
            self.assertEqual("bct_capabilities", guide["read_more"]["tool"])

    def test_bundle_matches_manual_catalogue_and_every_tracked_source(self):
        self.assertEqual(builder.render(builder.build_bundle()), builder.source_text(BUNDLE_PATH),
                         "Review manual and run build_component_library.py --write --reviewed")

    def test_source_drift_is_detected(self):
        original = builder.source_text
        def altered(path):
            text = original(path)
            return text + "\n# changed\n" if path.name == "chain_direction.py" else text
        with patch.object(builder, "source_text", side_effect=altered):
            self.assertNotEqual(builder.build_bundle()["source_fingerprint"], load_library()["source_fingerprint"])

    def test_core_release_and_python_package_include_same_bundle(self):
        config = tomllib.loads((ROOT / "bct.toml").read_text(encoding="utf-8"))
        files = config["deployment"]["profiles"]["bct_runtime_v1"]["files"]
        self.assertIn("src/bct/component_library.py", files)
        self.assertIn("src/bct/data/component-library.json", files)
        package = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("data/*.json", package["tool"]["setuptools"]["package-data"]["bct"])

    def test_freshness_gate_runs_before_ci_scope_can_skip_core(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertLess(workflow.index("python scripts/build_component_library.py"),
                        workflow.index("Resolve exact validation scope"))

    def test_missing_or_corrupt_bundle_does_not_claim_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual("UNAVAILABLE", load_library(Path(tmp) / "missing")["status"])
        with patch("pathlib.Path.read_text", return_value='{"schema": "wrong"}'):
            self.assertEqual("UNAVAILABLE", load_library()["status"])
        damaged = load_library()
        damaged["manual"]["text"] += "wrong"
        with patch("pathlib.Path.read_text", return_value=json.dumps(damaged)):
            self.assertEqual("UNAVAILABLE", load_library()["status"])

    def test_internal_component_is_not_invented_as_tool(self):
        value = discover(tools=[], capabilities=(), usage={}, component_id="monitor.node_token_visual")
        self.assertEqual("SOURCE_COMPONENT_ONLY", value["components"][0]["availability"])
        self.assertEqual([], value["components"][0]["available_tools"])


class LibraryMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_catalogue_exposes_guidance_and_chain_lookup_includes_manual(self):
        for mode in ("full", "compact", "hybrid"):
            server = self.server(mode)
            default = await self.call(server)
            self.assertEqual(get_manual_guidance(), default["manual_guidance"])
            chain = await self.call(server, tool_name="bct_chain_recipe")
            self.assertEqual(load_library()["manual"], chain["manual"])
            self.assertIn("manual_guidance", chain["tool"]["description"])
            self.assertIn("include_manual=true", server.instructions)
            other = await self.call(server, tool_name="bct_set_direction")
            self.assertEqual(default["manual_guidance"], other["manual_guidance"])
            self.assertNotIn("manual", other)

    def server(self, mode="full"):
        return build_mcp(SimpleNamespace(operations=Operations()),
                         compact_catalogue=mode == "compact", hybrid_catalogue=mode == "hybrid")

    async def call(self, server, **args):
        _, data = await server.call_tool("bct_capabilities", args)
        return data

    async def test_existing_default_contract_and_small_discovery_hint(self):
        data = await self.call(self.server())
        self.assertIn("bct_chain_recipe", data["tools"])
        self.assertNotIn("bct_chain_message", data["tools"])
        self.assertEqual(["read", "desktop_capture"], data["capabilities"])
        self.assertIn("browser_usage", data)
        self.assertTrue(data["read_only"])
        self.assertFalse(data["authorizes_execution"])
        self.assertNotIn("manual", data)
        self.assertEqual("bct_capabilities", data["discovery"]["tool"])

    async def test_exact_input_schema_comes_from_each_actual_mode(self):
        for mode in ("full", "compact", "hybrid"):
            server = self.server(mode)
            actual = {t.name: t for t in await server.list_tools()}
            result = await self.call(server, tool_name="bct_set_direction")
            self.assertEqual(actual["bct_set_direction"].inputSchema, result["tool"]["inputSchema"])
            read = await self.call(server, tool_name="bct_read")
            self.assertEqual("NOT_FOUND" if mode == "compact" else "OK", read["status"])

    async def test_shared_manual_exact_utf8_text_and_scope(self):
        data = await self.call(self.server(), include_manual=True)
        text = builder.source_text(ROOT / builder.MANUAL)
        self.assertEqual(text, data["manual"]["text"])
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), data["manual"]["sha256"])
        self.assertIn("bct_status", data["manual_scope"])

    async def test_manual_tool_names_and_examples_exist_in_runtime(self):
        server = self.server()
        actual = {t.name for t in await server.list_tools()}
        actual.update(t.name for t in await self.server("compact").list_tools())
        text = builder.source_text(ROOT / builder.MANUAL)
        mentioned = set(re.findall(r"\bbct_[a-z_]+\b", text))
        # Explicitly unavailable names must not be advertised as callable tools.
        self.assertIn("`bct_run_execute_plan`을 새로 만들지 않는다", text)
        self.assertIn("이전 `bct_delayed_send_message`는 공개 별칭으로 남기지 않는다", text)
        self.assertNotIn("bct_delayed_send_message", actual)
        self.assertIn("bct_send_delayed_message", actual)
        self.assertEqual(set(), mentioned - actual - {
            "bct_run_execute_plan", "bct_delayed_send_message"})
        self.assertIn("bct_create_work", actual)  # Public alias is real, not a documentation typo.
        for example in (await self.call(server))["discovery"]["examples"]:
            self.assertEqual("OK", (await self.call(server, **example))["status"])

    async def test_korean_search_finds_scan_and_desktop(self):
        scan = await self.call(self.server(), query="코드 블럭", limit=20)
        self.assertIn("scan_code_blocks", [t["name"] for t in scan["matching_tools"]])
        self.assertIn("code.scan_blocks", [c["id"] for c in scan["components"]])
        desktop = await self.call(self.server(), query="데스크탑")
        self.assertIn("bct_desktop_capture", [t["name"] for t in desktop["matching_tools"]])

    async def test_capability_routes_respect_full_compact_and_hybrid(self):
        for mode in ("full", "compact", "hybrid"):
            result = await self.call(self.server(mode), query="read")
            route = next(r for r in result["capability_routes"] if r["capability"] == "read")
            self.assertEqual("bct_dispatch" if mode == "compact" else "bct_read", route["tool"])
            self.assertTrue(route["requires_work_authorization"])

    async def test_bounded_query_pagination_and_unknown_names(self):
        server = self.server()
        first = await self.call(server, query="bct", limit=2)
        second = await self.call(server, query="bct", limit=2, offset=first["next_offset"])
        self.assertEqual(2, len(first["matching_tools"]))
        self.assertNotEqual(first["matching_tools"], second["matching_tools"])
        for args in ({"query": "x" * 301}, {"limit": 0}, {"limit": 21}, {"offset": -1}):
            self.assertEqual("INVALID_REQUEST", (await self.call(server, **args))["status"])
        self.assertEqual("NOT_FOUND", (await self.call(server, tool_name="bct_run_execute_plan"))["status"])
        self.assertEqual("NOT_FOUND", (await self.call(server, component_id="fake.part"))["status"])

    async def test_runtime_schema_still_available_when_library_missing(self):
        with patch("bct.component_library.load_library", return_value={"status": "UNAVAILABLE"}):
            data = await self.call(self.server(), tool_name="bct_chain_recipe", include_manual=True)
        self.assertEqual("UNAVAILABLE", data["library_status"])
        self.assertEqual("UNAVAILABLE", data["manual"]["status"])
        self.assertEqual("bct_chain_recipe", data["tool"]["name"])


if __name__ == "__main__":
    unittest.main()
