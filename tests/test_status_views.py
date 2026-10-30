import unittest
from bct.status_views import status_view


class StatusViewTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "core": {"status": "OK"},
            "monitor": {
                "current_nodes": {"counts": {"confirmed": 1}, "items": [
                    {"node_number": "N7", "status": "CONFIRMED", "tab_id": 8}
                ]},
                "rcc": {"instances": [{"instance_id": "example"}]},
                "service": {"status": "OK"},
                "observability": {"ok": True},
                "schema": 1, "generated_at": 123,
                "nodes": [{"node_number": "N6", "status": "CLOSED"}],
            },
        }

    def test_bct_keeps_existing_full_snapshot(self):
        self.assertEqual(self.snapshot, status_view(self.snapshot, "bct"))

    def test_node_excludes_historical_closed_nodes(self):
        view = status_view(self.snapshot, "node")
        self.assertEqual(1, view["current_nodes"]["counts"]["confirmed"])
        self.assertEqual("N7", view["current_nodes"]["items"][0]["node_number"])
        self.assertNotIn("nodes", view)

    def test_rcc_and_monitor_views(self):
        self.assertEqual("example", status_view(self.snapshot, "rcc")["rcc"]["instances"][0]["instance_id"])
        monitor = status_view(self.snapshot, "monitor")["monitor"]
        self.assertEqual("OK", monitor["service"]["status"])
        self.assertNotIn("nodes", monitor)

    def test_missing_monitor_and_invalid_scope(self):
        self.assertEqual("UNAVAILABLE", status_view({}, "node")["status"])
        with self.assertRaises(ValueError):
            status_view(self.snapshot, "all")


if __name__ == "__main__":
    unittest.main()
