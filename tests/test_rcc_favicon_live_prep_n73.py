"""Portable pre-LIVE manifest and combined PR #351/#354 safety contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "modules" / "rcc" / "extension"
RELEASE = ROOT / "modules" / "rcc" / "release"
ROLLBACK_EXTRA = {
    "browser/tab_group_adapter.js", "browser/tab_group_contract.js",
    "domain/tab_group_service.js",
}


class RccFaviconLivePreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads((RELEASE / "rcc_v2_rc.json").read_text(encoding="utf-8"))
        cls.rollback = {entry["path"]: entry for entry in cls.payload["rollbackBaseline"]["files"]}
        cls.candidate = {entry["path"]: entry for entry in cls.payload["candidateInventory"]["files"]}

    def test_old_installed_three_files_stay_in_exact_rollback(self):
        self.assertEqual(57, len(self.rollback))
        self.assertTrue(ROLLBACK_EXTRA.issubset(self.rollback))
        self.assertEqual(58, len(self.candidate))
        self.assertEqual(set(self.candidate) - set(self.rollback),
                         {"domain/node_favicon_notify_service.js"})

    def test_candidate_contains_both_rename_diagnostic_and_node_favicon(self):
        router = (EXT / "content" / "content_router.js").read_text(encoding="utf-8")
        rename = (EXT / "domain" / "conversation_rename_service.js").read_text(encoding="utf-8")
        policy = (EXT / "legacy" / "command_policy.js").read_text(encoding="utf-8")
        loader = (EXT / "background_loader.js").read_text(encoding="utf-8")
        self.assertIn("renameDiagnostic: error?.renameDiagnostic || null", router)
        self.assertIn("result.renameDiagnostic", rename)
        self.assertIn("relay:nodeLabelNotify", router)
        self.assertIn("NODE_LABEL_COMMANDS", policy)
        self.assertIn("domain/node_favicon_notify_service.js", loader)

    def test_payload_hashes_cover_all_release_items(self):
        for name, entry in self.candidate.items():
            with self.subTest(name=name):
                raw = (EXT / name).read_bytes()
                self.assertEqual(len(raw), entry["size"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])

    def test_rollback_plan_is_pinned_to_exact_installed_57(self):
        doc = (RELEASE / "ROLLBACK.md").read_text(encoding="utf-8")
        self.assertIn("installed 1.0.59 baseline", doc)
        self.assertIn("57-file", doc)
        self.assertEqual(self.payload["rollbackPlanSha256"],
                         hashlib.sha256((RELEASE / "ROLLBACK.md").read_bytes()).hexdigest())
        manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "1.0.61")


if __name__ == "__main__":
    unittest.main()
