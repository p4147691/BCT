"""Historical RCC release immutability and new Loop focus candidate pin.

The old composer-rebind manifest is a fixed provenance record. The new
manifest is a separately pinned source candidate, not an edited baseline.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from modules.rcc.release.verify_release_candidate import inventory_digest, verify


ROOT = Path(__file__).resolve().parents[1]
HISTORIC = ROOT / "modules/rcc/release/rcc_v2_rc.json"
NEW = ROOT / "modules/rcc/release/rcc_loop_focus_20261111.json"
EXT = ROOT / "modules/rcc/extension"
HISTORIC_MANIFEST_SHA = "e792a81e8b628481e1765bcf9d77cd1e1988bced24f3d70fa89882a22439b34d"
HISTORIC_CANDIDATE_AGGREGATE = "e054f0fae6598c64c2eb0e4ff397740ffa76acba50abe06dd2e78dfb288e1f02"


class LoopFocusPinnedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.old_raw = HISTORIC.read_bytes()
        self.old = json.loads(self.old_raw.decode("utf-8-sig"))
        self.new = json.loads(NEW.read_text(encoding="utf-8"))

    def test_original_candidate_manifest_is_byte_immutable(self):
        self.assertEqual(hashlib.sha256(self.old_raw).hexdigest(), HISTORIC_MANIFEST_SHA)
        self.assertEqual(self.old["candidate"], "RCC_COMPOSER_REBIND_20261110")
        self.assertEqual(self.old["candidateInventory"]["aggregateSha256"],
                         HISTORIC_CANDIDATE_AGGREGATE)
        self.assertEqual(self.old["rollbackBaseline"], self.new["rollbackBaseline"])
        self.assertEqual(self.old["rollbackPlanSha256"], self.new["rollbackPlanSha256"])

    def test_separate_manifest_pin_rejects_changed_candidate(self):
        pin=json.loads((ROOT/"modules/rcc/release/rcc_loop_focus_20261111.pin.json")
                       .read_text(encoding="utf-8"))
        self.assertEqual(pin["schema"],1)
        self.assertEqual(pin["candidate"],self.new["candidate"])
        self.assertEqual(pin["candidateManifestSha256"],
                         hashlib.sha256(NEW.read_bytes()).hexdigest())
        self.assertEqual(pin["candidateInventoryAggregateSha256"],
                         self.new["candidateInventory"]["aggregateSha256"])
        self.assertEqual(pin["historicalManifestSha256"],
                         hashlib.sha256(self.old_raw).hexdigest())
        changed=EXT/pin["changedPayload"]
        self.assertEqual(changed.stat().st_size,pin["changedPayloadBytes"])
        self.assertEqual(hashlib.sha256(changed.read_bytes()).hexdigest(),
                         pin["changedPayloadSha256"])
        self.assertEqual(pin["installedExtensionVerification"],"NOT_PERFORMED")

    def test_new_candidate_declares_exact_historical_lineage(self):
        lineage = self.new["supersedes"]
        self.assertEqual(lineage["manifest"], "modules/rcc/release/rcc_v2_rc.json")
        self.assertEqual(lineage["manifestSha256"], HISTORIC_MANIFEST_SHA)
        self.assertEqual(lineage["candidate"], self.old["candidate"])
        self.assertEqual(lineage["candidateInventorySha256"], HISTORIC_CANDIDATE_AGGREGATE)
        self.assertEqual(self.new["candidate"], "RCC_LOOP_FOCUS_SETTLE_20261111")
        self.assertEqual(self.new["sourceRoot"], self.old["sourceRoot"])
        self.assertEqual(self.new["contracts"], self.old["contracts"])

    def test_all_58_source_payloads_are_pinned_not_just_changed_file(self):
        self.assertEqual(58, self.new["candidateInventory"]["fileCount"])
        old_rows = {row["path"]: row for row in self.old["candidateInventory"]["files"]}
        new_rows = {row["path"]: row for row in self.new["candidateInventory"]["files"]}
        self.assertEqual(set(old_rows), set(new_rows))
        self.assertEqual(inventory_digest(self.new["candidateInventory"]["files"]),
                         self.new["candidateInventory"]["aggregateSha256"])
        changed = []
        for name, row in new_rows.items():
            raw = (EXT / name).read_bytes()
            self.assertEqual(len(raw), row["size"], name)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row["sha256"], name)
            if row != old_rows[name]:
                changed.append(name)
        self.assertEqual(changed, ["content/simple_relay_executor.js"])
        self.assertEqual(verify(NEW)["ok"], True)


if __name__ == "__main__":
    unittest.main()
