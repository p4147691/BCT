import tempfile
import unittest
from pathlib import Path
from bct.core.store import Store
from bct.dot_identity import dot_directory, save_dot_info

class DotIdentityTests(unittest.TestCase):
    def test_registration_revision_and_uuid_isolation(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            self.assertEqual({}, dot_directory(store))
            payload = dict(dot_key="opaque-dot~opaque-context", display_name="Dot", expected_revision=0)
            saved = save_dot_info(store, payload)
            self.assertEqual("", saved["conversation_key"])
            self.assertEqual("O", saved["node_label"])
            self.assertEqual(["Orchestrator"], saved["role_tags"])
            self.assertEqual(saved, dot_directory(store)[payload["dot_key"]])
            with self.assertRaisesRegex(ValueError, "CONFLICT"):
                save_dot_info(store, payload)
            with self.assertRaisesRegex(ValueError, "ALREADY_REGISTERED"):
                save_dot_info(store, {**payload, "dot_key":"another~context"})
            with self.assertRaisesRegex(ValueError, "GLOBAL_ONLY"):
                save_dot_info(store, {**payload, "expected_revision":1, "scope_name":"network"})
            with store.transaction() as db:
                self.assertEqual(0, db.execute("SELECT count(*) FROM conversation_network_node_labels").fetchone()[0])
            save_dot_info(store, {**payload, "expected_revision":1, "node_memo":"updated"})
            self.assertEqual("updated", dot_directory(store)[payload["dot_key"]]["node_memo"])

    def test_invalid_identity_roles_and_fields(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            for values in [
                {"dot_key":"6af0f057-6c7c-83ee-a593-88ca92d40c20"},
                {"dot_key":"valid~context","role_tags":["Supervisor"]},
                {"dot_key":"valid~context","conversation_key":"fake"},
            ]:
                with self.assertRaises(ValueError):
                    save_dot_info(store, {**values, "expected_revision":0})

    def test_ui_projection_includes_saved_dot_info_without_registering(self):
        from unittest.mock import patch
        from bct.monitor_runtime import build_monitor_ui_state
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / "state.sqlite")
            with patch("bct.monitor_runtime.discover_instance_ids", return_value=[]), \
                 patch("bct.monitor_runtime._rcc_states", return_value=[]):
                before = build_monitor_ui_state(
                    store=store, service_state={}, data_root=Path(root),
                )
                self.assertEqual({}, before["dot_node_info"])
                payload = {
                    "dot_key": "opaque-dot~opaque-context",
                    "display_name": "Dot",
                    "expected_revision": 0,
                }
                save_dot_info(store, payload)
                after = build_monitor_ui_state(
                    store=store, service_state={}, data_root=Path(root),
                )
                self.assertEqual("O", after["dot_node_info"][payload["dot_key"]]["node_label"])


class DotHttpIntegrationTests(unittest.TestCase):
    def test_http_roundtrip_origin_revision_and_reload(self):
        import asyncio
        from types import SimpleNamespace
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient
        from bct.runtime_server import dot_node_info_response, MONITOR_EXTENSION_ORIGIN
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.sqlite"
            bct = SimpleNamespace(store=Store(path))
            async def endpoint(request):
                return await dot_node_info_response(bct, request)
            app = Starlette(routes=[Route("/monitor/dot-node-info",endpoint,methods=["GET","POST"])])
            with TestClient(app) as client:
                self.assertEqual(403,client.get("/monitor/dot-node-info").status_code)
                headers = {"origin":MONITOR_EXTENSION_ORIGIN}
                payload = {"dot_key":"opaque~context","display_name":"Dot","expected_revision":0,"node_memo":"hello"}
                saved = client.post("/monitor/dot-node-info",json=payload,headers=headers)
                self.assertEqual(200,saved.status_code)
                self.assertEqual(400,client.post("/monitor/dot-node-info",json=payload,headers=headers).status_code)
                bct.store = Store(path)
                response = client.get("/monitor/dot-node-info",headers=headers).json()
                self.assertEqual("hello",response["dots"]["opaque~context"]["node_memo"])
                self.assertEqual("",response["dots"]["opaque~context"]["scope_id"])
