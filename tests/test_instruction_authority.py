from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstructionAuthorityTests(unittest.TestCase):
    def test_one_common_policy_and_one_cursor_pointer(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("single canonical common instruction", agents)
        self.assertIn(r"D:\BCT\source", agents)
        self.assertIn("Work**: one durable BCT scope/authorization record", agents)
        self.assertNotIn("46-file RC2", agents)
        self.assertNotIn(r"runtime\backups\rcc-", agents)

        rules = sorted((ROOT / ".cursor" / "rules").glob("*.mdc"))
        self.assertEqual(["bct-delivery-flow.mdc"], [x.name for x in rules])
        pointer = rules[0].read_text(encoding="utf-8")
        self.assertIn("alwaysApply: true", pointer)
        self.assertIn(r"D:\BCT\source\AGENTS.md", pointer)
        self.assertLess(len(pointer.encode("utf-8")), 2000)
        self.assertFalse((ROOT / ".cursor" / "rules" / "bct-persistent-supervision.mdc").exists())

    def test_module_policy_is_monitor_specific(self):
        text = (ROOT / "modules" / "monitor" / "extension" / "AGENTS.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(r"D:\BCT\source\AGENTS.md", text)
        self.assertIn("expected-live-SHA", text)
        self.assertIn("extension/monitor.js", text)
        self.assertNotIn("GitHub p4147691/BCT is publication", text)

    def test_classification_document_names_all_authority_classes(self):
        text = (ROOT / "docs" / "INSTRUCTION_AUTHORITY.md").read_text(encoding="utf-8")
        for heading in (
            "Canonical common instruction",
            "Module-specific rules",
            "Thin editor adapters",
            "Runtime/project settings",
            "Machine enforcement",
            "Compatibility instructions",
            "Reference/history only",
            "Drafts in feature Worktrees",
        ):
            self.assertIn(heading, text)

    def test_stale_checker_matches_self_and_detects_changed_worktree(self):
        path = ROOT / "scripts" / "check_instruction_authority.py"
        spec = importlib.util.spec_from_file_location("instruction_check", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        current = module.compare(ROOT, ROOT)
        self.assertFalse(current["stale"])
        self.assertTrue(all(x["status"] == "MATCH" for x in current["results"]))

        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw)
            for rel in (
                "AGENTS.md",
                ".cursor/rules/bct-delivery-flow.mdc",
                "modules/monitor/extension/AGENTS.md",
            ):
                out = target / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes((ROOT / rel).read_bytes())
            # Windows line-ending conversion must not produce a false stale result.
            same = (target / "AGENTS.md").read_text(encoding="utf-8")
            (target / "AGENTS.md").write_text(
                same.replace("\n", "\r\n"), encoding="utf-8", newline=""
            )
            equivalent = module.compare(ROOT, target)
            self.assertFalse(equivalent["stale"])

            (target / "AGENTS.md").write_text("old common policy\r\n", encoding="utf-8", newline="")
            stale = module.compare(ROOT, target)
            self.assertTrue(stale["stale"])
            states = {x["path"]: x["status"] for x in stale["results"]}
            self.assertEqual("STALE_INSTRUCTIONS", states["AGENTS.md"])


if __name__ == "__main__":
    unittest.main()
