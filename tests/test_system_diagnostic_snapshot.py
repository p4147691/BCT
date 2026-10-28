import unittest
from unittest.mock import patch

from bct.core.models import PreconditionError, Work
from bct.features.execution import SystemInspectFeature


class DiagnosticSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.feature = SystemInspectFeature()
        self.work = Work("pc-diagnose", "test", ("C:\\",),
                         frozenset({"system_inspect"}), "local")

    def test_single_authorized_read_only_diagnosis(self):
        req = self.feature.prepare(work=self.work, arguments={
            "operation": "diagnose", "query": "python", "ports": [18790], "limit": 8,
        })
        with (patch("bct.features.execution.list_processes",
                    return_value=[{"pid": 400, "name": "python.exe"}]) as processes,
              patch("bct.features.execution.port_owners",
                    return_value=[{"pid": 400}]) as ports):
            result = self.feature.execute(req)
        processes.assert_called_once_with(query="python", limit=8)
        ports.assert_called_once_with(18790)
        self.assertTrue(result.output["read_only"])
        self.assertEqual(1, result.output["process_count"])
        self.assertEqual(18790, result.output["ports"][0]["port"])
        self.assertTrue(result.evidence["read_only"])

    def test_query_only(self):
        req = self.feature.prepare(work=self.work, arguments={
            "operation": "diagnose", "query": "explorer.exe",
        })
        with patch("bct.features.execution.list_processes", return_value=[]):
            result = self.feature.execute(req)
        self.assertEqual([], result.output["ports"])

    def test_port_only(self):
        req = self.feature.prepare(work=self.work, arguments={
            "operation": "diagnose", "ports": [12345],
        })
        with patch("bct.features.execution.port_owners", return_value=[]):
            result = self.feature.execute(req)
        self.assertEqual([], result.output["processes"])
        self.assertEqual(1, len(result.output["ports"]))

    def test_selector_required(self):
        with self.assertRaisesRegex(PreconditionError, "SELECTOR_REQUIRED"):
            self.feature.prepare(work=self.work, arguments={"operation": "diagnose"})

    def test_port_rejects_bool(self):
        with self.assertRaisesRegex(PreconditionError, "PORTS_INVALID"):
            self.feature.prepare(work=self.work, arguments={
                "operation": "diagnose", "ports": [True],
            })

    def test_port_duplicates_and_limit(self):
        for args in ({"ports": [8000, 8000]}, {"ports": [0]},
                     {"ports": [100000]}, {"ports": list(range(1, 11))},
                     {"query": "python", "limit": True}):
            with self.subTest(args=args), self.assertRaises(PreconditionError):
                self.feature.prepare(work=self.work, arguments={
                    "operation": "diagnose", **args,
                })

    def test_unknown_fields_fail_closed(self):
        with self.assertRaisesRegex(PreconditionError, "FIELDS_INVALID"):
            self.feature.prepare(work=self.work, arguments={
                "operation": "diagnose", "query": "python", "terminate": True,
            })

    def test_legacy_process_list_contract(self):
        req = self.feature.prepare(work=self.work, arguments={
            "operation": "process_list", "query": "bct", "limit": 10,
        })
        with patch("bct.features.execution.list_processes", return_value=[]):
            result = self.feature.execute(req)
        self.assertEqual({"processes": [], "count": 0}, result.output)
