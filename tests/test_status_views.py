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

    def test_node_enriches_exact_fresh_monitor_editor_data(self):
        uuid = "11111111-2222-3333-4444-555555555555"
        row = self.snapshot["monitor"]["current_nodes"]["items"][0]
        row["conversation_uuid"] = uuid
        row["window_id"] = 9
        self.snapshot["monitor"]["rcc"]["instances"] = [{
            "state": "OPEN", "cached": False,
            "tabs": [{
                "tab_id": 8, "window_id": 9, "conversation_key": uuid,
                "presence": "OPEN", "title": "Worker A", "active": True,
                "conversation_scope": {
                    "scope_id": "project-one", "scope_name": "Project One",
                    "role_tags": ["developer"], "display_order": 2,
                },
            }],
        }]
        view = status_view(self.snapshot, "node")
        item = view["current_nodes"]["items"][0]
        self.assertEqual("Worker A", item["name"])
        self.assertEqual("Project One", item["network"])
        self.assertEqual(["developer"], item["roles"])
        self.assertEqual(1, view["current_nodes"]["counts"]["confirmed"])
        self.snapshot["monitor"]["rcc"]["instances"][0]["cached"] = True
        cached = status_view(self.snapshot, "node")["current_nodes"]["items"][0]
        self.assertNotIn("roles", cached)

    def test_node_sort_modes(self):
        rows = self.snapshot["monitor"]["current_nodes"]["items"]
        rows[0]["node_number"] = "N12"
        rows[0]["generating"] = False
        rows.append({"status": "CONFIRMED", "node_number": "N3", "generating": True})
        self.assertEqual("N3", status_view(self.snapshot, "node")["current_nodes"]["items"][0]["node_number"])
        self.assertEqual("N3", status_view(self.snapshot, "node", sort_by="activity")["current_nodes"]["items"][0]["node_number"])
        for mode in ("network", "role"):
            self.assertEqual(2, len(status_view(self.snapshot, "node", sort_by=mode)["current_nodes"]["items"]))
        with self.assertRaises(ValueError):
            status_view(self.snapshot, "node", sort_by="invalid")

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
