from __future__ import annotations

import xml.etree.ElementTree as ET
import unittest
from pathlib import Path


class CoreRecoveryTaskTests(unittest.TestCase):
    def test_supervisor_resolves_python_without_a_profile_literal(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "modules" / "mcp" / "ops" / "run_bct_core_supervisor.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)", script)
        self.assertNotIn(r"C:\\Users\\", script)

    def test_task_is_bounded_to_the_bct_supervisor_and_restarts_on_failure(self):
        root = Path(__file__).resolve().parents[1]
        document = (root / "modules" / "mcp" / "ops" / "BCT-Core-Supervisor.task.xml").read_text(
            encoding="utf-8"
        )
        task = ET.fromstring(document)
        namespace = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        command = task.findtext(".//t:Actions/t:Exec/t:Command", namespaces=namespace)
        arguments = task.findtext(".//t:Actions/t:Exec/t:Arguments", namespaces=namespace)
        working = task.findtext(".//t:Actions/t:Exec/t:WorkingDirectory", namespaces=namespace)
        self.assertEqual(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe", command)
        self.assertEqual(
            r'-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "D:\BCT\runtime\ops\run_bct_core_supervisor.ps1"',
            arguments,
        )
        self.assertEqual(r"D:\BCT\runtime", working)
        self.assertEqual("PT1M", task.findtext(".//t:RestartOnFailure/t:Interval", namespaces=namespace))
        self.assertEqual("999", task.findtext(".//t:RestartOnFailure/t:Count", namespaces=namespace))
        self.assertEqual("PT0S", task.findtext(".//t:ExecutionTimeLimit", namespaces=namespace))
        self.assertEqual("IgnoreNew", task.findtext(".//t:MultipleInstancesPolicy", namespaces=namespace))
        self.assertNotIn("ACT", document)
        self.assertNotIn("codex-runtimes", document)
        self.assertNotIn("<?xml", document)

    def test_tunnel_task_starts_only_the_bounded_tunnel_supervisor(self):
        root = Path(__file__).resolve().parents[1]
        document = (root / "modules" / "mcp" / "ops" / "BCT-Tunnel-Supervisor.task.xml").read_text(
            encoding="utf-8"
        )
        task = ET.fromstring(document)
        namespace = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        command = task.findtext(".//t:Actions/t:Exec/t:Command", namespaces=namespace)
        arguments = task.findtext(".//t:Actions/t:Exec/t:Arguments", namespaces=namespace)
        working = task.findtext(".//t:Actions/t:Exec/t:WorkingDirectory", namespaces=namespace)
        self.assertEqual(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe", command)
        self.assertEqual(
            r'-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "D:\BCT\runtime\ops\run_bct_tunnel_supervisor.ps1" -RuntimeDir "D:\BCT\runtime"',
            arguments,
        )
        self.assertEqual(r"D:\BCT\runtime", working)
        self.assertEqual("PT1M", task.findtext(".//t:RestartOnFailure/t:Interval", namespaces=namespace))
        self.assertEqual("999", task.findtext(".//t:RestartOnFailure/t:Count", namespaces=namespace))
        self.assertEqual("PT0S", task.findtext(".//t:ExecutionTimeLimit", namespaces=namespace))
        self.assertEqual("IgnoreNew", task.findtext(".//t:MultipleInstancesPolicy", namespaces=namespace))
        self.assertIsNotNone(task.find(".//t:Triggers/t:LogonTrigger", namespaces=namespace))
        self.assertNotIn("ACT", document)
        self.assertNotIn("codex-runtimes", document)


if __name__ == "__main__":
    unittest.main()
