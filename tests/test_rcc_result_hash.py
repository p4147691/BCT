from __future__ import annotations

import json
import unittest
from pathlib import Path

from bct.core.rcc_result import rcc_result_hash, rcc_result_payload_json


class RccResultHashContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        fixture_path = (
            root / "modules" / "rcc" / "extension" / "fixtures"
            / "result_hash_v1.json"
        )
        cls.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    def test_python_matches_js_json_and_sha256_fixture(self):
        self.assertEqual(1, self.fixture["schema"])
        for vector in self.fixture["vectors"]:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(
                    vector["bounded_json"],
                    rcc_result_payload_json(vector["input"]),
                )
                self.assertEqual(vector["sha256"], rcc_result_hash(vector["input"]))

    def test_non_string_result_text_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "RCC_RESULT_REPLY_TYPE_INVALID"):
            rcc_result_hash({"ok": True, "reply": 7})


if __name__ == "__main__":
    unittest.main()
