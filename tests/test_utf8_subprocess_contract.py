from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Utf8SubprocessContractTests(unittest.TestCase):
    def test_production_text_subprocesses_declare_encoding(self):
        missing: list[str] = []
        for path in sorted((ROOT / "src" / "bct").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in {"run", "Popen", "check_output"}:
                    continue
                keywords = {item.arg: item.value for item in node.keywords if item.arg}
                text_mode = keywords.get("text") or keywords.get("universal_newlines")
                if not isinstance(text_mode, ast.Constant) or text_mode.value is not True:
                    continue
                if "encoding" not in keywords:
                    relative = path.relative_to(ROOT).as_posix()
                    missing.append(f"{relative}:{node.lineno}")
        self.assertEqual([], missing, "text subprocess must not depend on Windows ACP")


if __name__ == "__main__":
    unittest.main()
