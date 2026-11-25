from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bct.approval_issuer import issue_after_human_confirmation
from bct.core.models import AuthorizationError, PreconditionError, Principal, Work
from bct.core.operations import OperationCoordinator
from bct.core.policy import Policy
from bct.core.store import Store
from bct.features.approval_challenge import ApprovalChallengeFeature
from bct.features.desktop_read import DesktopReadFeature
from bct.features.files import FileReadFeature


class DesktopReadTests(unittest.TestCase):
    def test_independent_exact_grant_and_shared_read_operations(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as name:
            root = Path(name)
            scoped_root = root / "work"
            scoped_root.mkdir()
            outside = root / "reports"
            outside.mkdir()
            first = outside / "report.txt"
            second = outside / "copy.txt"
            protected = outside / ".env"
            for path in (first, second, protected):
                path.write_text("fixture\n", encoding="utf-8")
            policy = root / "policy.toml"
            policy.write_text('[policy]\nnormal_actions=["read","approval_challenge"]\n'
                              'approval_actions=["desktop_read"]\n', encoding="utf-8")
            store = Store(root / "state.sqlite")
            work = Work("work", "test", (str(scoped_root),), frozenset({"read"}), "principal")
            store.create_work(work)
            principal = Principal("principal", "fixture", frozenset({"read","desktop_read"}))
            coordinator = OperationCoordinator(store=store, policy=Policy(policy))
            direct = DesktopReadFeature(store)
            coordinator.register(direct)
            coordinator.register(FileReadFeature(store))
            challenge = ApprovalChallengeFeature({"desktop_read": direct})
            key = Ed25519PrivateKey.generate()

            def run(operation_id, arguments, approval_ref=None):
                return coordinator.run(principal=principal, work_id=work.work_id, operation_id=operation_id,
                                       capability="desktop_read", arguments=arguments, approval_ref=approval_ref)

            def grant(operation_id, arguments):
                with patch.object(direct, "path_guard", side_effect=AssertionError("pre-approval filesystem probe")):
                    prepared = challenge.prepare(work=work, arguments={
                        "capability": "desktop_read", "operation_id": operation_id, "arguments": arguments,
                    })
                return issue_after_human_confirmation(
                    prepared.arguments["challenge"], SimpleNamespace(load=lambda _: key), "fixture", confirmed=True,
                )

            request = {"path":str(first)}
            with patch.object(direct, "path_guard", side_effect=AssertionError("unsigned filesystem probe")):
                with self.assertRaisesRegex(AuthorizationError, "APPROVAL_SIGNED_GRANT_REQUIRED"):
                    run("no-grant", request)
            with self.assertRaisesRegex(PreconditionError, "TARGET_OUTSIDE_WORK_SCOPE"):
                coordinator.run(principal=principal, work_id=work.work_id, operation_id="scoped",
                                capability="read", arguments=request)
            with patch.object(coordinator.approval_verifier, "_public_key", return_value=key.public_key()):
                self.assertEqual("fixture\n", run("file", request, grant("file", request)).output["text"])
                with self.assertRaisesRegex(AuthorizationError, "APPROVAL_SCOPE_MISMATCH"):
                    run("changed", {"path": str(second)}, grant("changed", request))
                functions = {
                    "directory_tree": {"path": str(outside)},
                    "search": {"path": str(outside), "query": "*.txt"},
                    "duplicates": {"path": str(outside)},
                    "compare": {"path_a":str(first), "path_b":str(second)},
                    "batch": {"items":[{"id":"item","path":str(first)}]},
                    "snapshot": {"files":[{"id":"item","path":str(first)}],"receipt_ids":["file"]},
                }
                for operation, arguments in functions.items():
                    with self.subTest(operation=operation):
                        arguments = {"operation": operation, **arguments}
                        result = run(operation, arguments, grant(operation, arguments))
                        self.assertEqual("APPLIED", result.outcome.value, result.error)
                        self.assertNotIn(".env", repr(result.output))
                        self.assertEqual("APPLIED", store.get_operation_for(
                            work_id="work", operation_id=operation, principal_id="principal").outcome.value)
                denied = {"path": str(protected)}
                self.assertEqual("READ_PROTECTED_FILE", run("protected", denied, grant("protected", denied)).error)

