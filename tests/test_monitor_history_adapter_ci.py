"""Ensure the isolated Monitor history JavaScript adapter is tested by BCT CI."""
from pathlib import Path
import shutil
import subprocess
import unittest

class MonitorHistoryAdapterCITest(unittest.TestCase):
    def test_node_adapter_and_readonly_contract(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required to verify Monitor history adapter")
        root = Path(__file__).resolve().parents[1]
        script = root / "modules" / "monitor" / "tools" / "check_monitor_history_readonly.cjs"
        result = subprocess.run([node, str(script)], cwd=root, capture_output=True,
                                text=True, timeout=30, shell=False)
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("6 monitor history tests PASS", result.stdout)

if __name__ == "__main__":
    unittest.main()
