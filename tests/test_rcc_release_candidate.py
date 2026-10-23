from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


class RccReleaseCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.release = cls.root / "modules" / "rcc" / "release"
        spec = importlib.util.spec_from_file_location(
            "verify_rcc_release_candidate", cls.release / "verify_release_candidate.py"
        )
        assert spec and spec.loader
        cls.verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.verifier)

    def test_committed_release_candidate_is_coherent(self):
        receipt = self.verifier.verify(self.release / "rcc_v2_rc.json")
        self.assertTrue(receipt["ok"])
        self.assertFalse(receipt["liveBaselineVerified"])
        self.assertFalse(receipt["stagedCandidateVerified"])
        self.assertGreater(receipt["candidateFileCount"], 30)
        self.assertGreater(receipt["rollbackFileCount"], 20)
        self.assertEqual(
            "4d5c89995beec26e294ecc776737205216c79fb9a93d44214b24189954fb9a88",
            receipt["rollbackAggregateSha256"],
        )

    def test_inventory_digest_is_order_independent_and_tamper_evident(self):
        files = [
            {"path": "b.js", "size": 2, "sha256": "b" * 64},
            {"path": "a.js", "size": 1, "sha256": "a" * 64},
        ]
        digest = self.verifier.inventory_digest(files)
        self.assertEqual(digest, self.verifier.inventory_digest(list(reversed(files))))
        changed = json.loads(json.dumps(files))
        changed[0]["size"] = 3
        self.assertNotEqual(digest, self.verifier.inventory_digest(changed))

    def test_exact_rollback_verification_rejects_extra_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "payload.js").write_text("ok", encoding="utf-8")
            item = {
                "path": "payload.js",
                "size": 2,
                "sha256": self.verifier._sha256(root / "payload.js"),
            }
            inventory = {
                "fileCount": 1,
                "files": [item],
                "aggregateSha256": self.verifier.inventory_digest([item]),
            }
            (root / "extra.js").write_text("extra", encoding="utf-8")
            with self.assertRaises(self.verifier.VerificationError):
                self.verifier._verify_inventory(root, inventory, exact=True)


if __name__ == "__main__":
    unittest.main()
