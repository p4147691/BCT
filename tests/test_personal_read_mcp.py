from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
from io import BytesIO
import json
import time
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs

from starlette.testclient import TestClient

from bct.core.models import Work
from bct.core.operations import OperationCoordinator
from bct.core.policy import Policy
from bct.core.store import Store
from bct.features.files import FileReadFeature
from bct.mcp_server import BCTMCPServer, LocalBearerMiddleware, MCP_PRINCIPAL_ID, build_mcp
from bct.personal_read_mcp import attach_personal_read
from types import SimpleNamespace


class PersonalReadMCPTests(unittest.TestCase):
    def test_oauth_metadata_and_owner_bound_access_token(self):
        with TemporaryDirectory(dir=Path.cwd()) as name:
            root = Path(name)
            runtime = root / "runtime"
            (runtime / "state").mkdir(parents=True)
            ordinary = root / "ordinary"
            ordinary.mkdir()
            fixture = ordinary / "example.txt"
            fixture.write_text("oauth read fixture", encoding="utf-8")
            shared_server = BCTMCPServer("Worker fixture")
            shared = LocalBearerMiddleware(shared_server.streamable_http_app(stateless_http=True, json_response=True),
                                           "worker-token")
            issuer = "https://issuer.example"
            resource = "https://relay.example/personal-mcp"
            app = attach_personal_read(shared, runtime, shared_token="worker-token", auth_digest="",
                                       roots_json=json.dumps([str(ordinary)]), introspection_secret="test-secret",
                                       oauth_json=json.dumps({"issuer": issuer, "resource": resource,
                                           "introspection_url": issuer + "/introspect", "chatgpt_client": "chat-client",
                                           "owner_subject": "owner", "introspection_client": "introspection-client"}))
            verified = {"active": True, "iss": issuer, "sub": "owner", "aud": [resource],
                        "client_id": "chat-client", "scope": "files:read", "exp": int(time.time()) + 60}
            token_claims = {"owner-token": verified,
                            "foreign-user": {**verified, "sub": "other"},
                            "foreign-client": {**verified, "client_id": "other"},
                            "wrong-audience": {**verified, "aud": [resource, "other"]},
                            "wrong-issuer": {**verified, "iss": "https://other.example"},
                            "wrong-scope": {**verified, "scope": "files:write"},
                            "expired-token": {**verified, "exp": 1}}

            def introspect(request, *, timeout):
                self.assertEqual(issuer + "/introspect", request.full_url)
                self.assertTrue(request.headers["Authorization"].startswith("Basic "))
                token = parse_qs(request.data.decode())["token"][0]
                self.assertNotEqual("worker-token", token)
                if token == "issuer-unavailable":
                    raise URLError("synthetic outage")
                return BytesIO(json.dumps(token_claims.get(token, {"active": False})).encode())

            with TestClient(app, base_url="http://127.0.0.1:8765") as client, patch(
                "bct.personal_read_mcp.build_opener", return_value=SimpleNamespace(open=introspect),
            ):
                discovery = client.get("/.well-known/oauth-protected-resource/personal-mcp").json()
                self.assertEqual(resource, discovery["resource"])
                self.assertEqual([issuer], discovery["authorization_servers"])
                for token in ("worker-token", "foreign-user", "foreign-client", "wrong-audience", "wrong-issuer",
                              "wrong-scope", "expired-token", "issuer-unavailable", "inactive-token"):
                    response = self._call(client, "/personal-mcp", token, "bct_operation_get", {"operation_id": "oauth"})
                    self.assertEqual(401, response.status_code, token)
                    self.assertIn('resource_metadata="https://relay.example/.well-known/oauth-protected-resource/personal-mcp"',
                                  response.headers["WWW-Authenticate"])
                read = self._call(client, "/personal-mcp", "owner-token", "bct_read", {
                    "operation_id": "oauth", "arguments": {"path": str(fixture)},
                }).json()["result"]["structuredContent"]
                self.assertEqual("oauth read fixture", read["output"]["text"])
                receipt = self._call(client, "/personal-mcp", "owner-token", "bct_operation_get", {
                    "operation_id": "oauth",
                }).json()["result"]["structuredContent"]
                self.assertEqual(read["evidence"], receipt["evidence"])

    @staticmethod
    def _call(client, path, token, name, arguments):
        protocol = "2026-07-28"
        return client.post(path, headers={
            "Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream",
            "Mcp-Protocol-Version": protocol, "Mcp-Method": "tools/call", "Mcp-Name": name,
        }, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": name, "arguments": arguments,
            "_meta": {"io.modelcontextprotocol/protocolVersion": protocol,
                      "io.modelcontextprotocol/clientCapabilities": {}},
        }})

    def test_separate_credentials_and_public_read_receipt(self):
        with TemporaryDirectory(dir=Path.cwd()) as name:
            root = Path(name)
            runtime = root / "runtime"
            (runtime / "state").mkdir(parents=True)
            public = root / "ordinary"
            work_root = root / "worker"
            for folder in (public, work_root):
                folder.mkdir()
            sample = public / "example.txt"
            sample.write_text("ordinary fixture", encoding="utf-8")
            (public / ".env").write_text("protected fixture", encoding="utf-8")
            policy = root / "policy.toml"
            policy.write_text('[policy]\nnormal_actions=["read"]\napproval_actions=[]\n', encoding="utf-8")
            worker = Store(runtime / "state/shared.sqlite")
            worker.create_work(Work("worker", "fixture", (str(work_root),), frozenset({"read"}), MCP_PRINCIPAL_ID))
            operations = OperationCoordinator(store=worker, policy=Policy(policy))
            operations.register(FileReadFeature(worker))
            shared_server = build_mcp(SimpleNamespace(operations=operations, store=worker))
            shared_token, personal_token = "a" * 64, "b" * 64
            shared = LocalBearerMiddleware(
                shared_server.streamable_http_app(stateless_http=True, json_response=True), shared_token,
            )
            roots = json.dumps([str(public)])
            self.assertIs(shared, attach_personal_read(
                shared, runtime, shared_token=shared_token, auth_digest="", roots_json="",
            ))
            with self.assertRaisesRegex(ValueError, "PERSONAL_MCP_CREDENTIAL_MUST_BE_SEPARATE"):
                attach_personal_read(shared, runtime, shared_token=shared_token,
                                     auth_digest=hashlib.sha256(shared_token.encode()).hexdigest(), roots_json=roots)
            app = attach_personal_read(shared, runtime, shared_token=shared_token,
                                       auth_digest=hashlib.sha256(personal_token.encode()).hexdigest(), roots_json=roots)

            with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                def call(path, token, name, arguments):
                    return self._call(client, path, token, name, arguments)

                args = {"operation_id": "example", "arguments": {"path": str(sample)}}
                self.assertEqual(401, call("/personal-mcp", shared_token, "bct_read", args).status_code)
                self.assertEqual(401, call("/mcp", personal_token, "bct_read", args).status_code)
                denied = call("/mcp", shared_token, "bct_scoped_read", {**args, "work_id": "worker"})
                self.assertIn("TARGET_OUTSIDE_WORK_SCOPE", denied.text)
                reply = call("/personal-mcp", personal_token, "bct_read", args).json()["result"]["structuredContent"]
                self.assertEqual("ordinary fixture", reply["output"]["text"])
                receipt = call("/personal-mcp", personal_token, "bct_operation_get",
                               {"operation_id": "example"}).json()["result"]["structuredContent"]
                self.assertEqual("FINISHED", receipt["state"])
                self.assertEqual(reply["evidence"], receipt["evidence"])
                self.assertNotIn("output", receipt)
                duplicate = call("/personal-mcp", personal_token, "bct_read", args).json()["result"]["structuredContent"]
                self.assertTrue(duplicate["duplicate"])
                self.assertNotIn("output", duplicate)
                for identifier, path, reason in (
                    ("secret", public / ".env", "READ_PROTECTED_FILE"),
                    ("outside", work_root, "TARGET_OUTSIDE_PERSONAL_READ_SCOPE"),
                ):
                    response = call("/personal-mcp", personal_token, "bct_read",
                                    {"operation_id": identifier, "arguments": {"path": str(path)}})
                    self.assertIn(reason, response.text)
                    self.assertNotIn("protected fixture", response.text)
                tree = call("/personal-mcp", personal_token, "bct_read", {"operation_id": "tree", "arguments": {
                    "operation": "directory_tree", "path": str(public), "depth": 0,
                }})
                self.assertIn("example.txt", tree.text)
                self.assertNotIn(".env", tree.text)
                self.assertNotIn('\"outcome\":\"APPLIED\"', call("/personal-mcp", personal_token, "bct_execute",
                                                                  {"operation_id": "wrong"}).text)
