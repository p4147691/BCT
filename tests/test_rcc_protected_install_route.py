"""No-live protected RCC extension installer and BCT deploy route acceptance."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from bct import rcc_protected_install as ri
from bct.core.models import PreconditionError, Principal, Work
from bct.features.deploy import DeployFeature, DeploymentProfiles
from bct.service import BCT


def _aggregate(files: list[dict]) -> str:
    return ri._aggregate(files)


class ProtectedRccRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.live = self.base / "chrome" / "extension"
        self.source = self.base / "candidate"
        self.reference = self.base / "rollback-source"
        self.journal = self.base / "journal"
        self.policy_manifest = self.base / "release.json"
        self.pub = b"safe-rcc-test-public-key-n73"
        alphabet = "abcdefghijklmnop"
        self.id = "".join(alphabet[n] for b in hashlib.sha256(self.pub).digest()[:16]
                          for n in (b >> 4, b & 15))
        manifest = lambda ver: {
            "manifest_version": 3, "name": "BCT RCC",
            "version": ver, "key": base64.b64encode(self.pub).decode("ascii")
        }
        self.live.mkdir(parents=True)
        self.source.mkdir(parents=True)
        for folder,version in ((self.live,"1.0.59"),(self.source,"1.0.60")):
            (folder/"manifest.json").write_text(json.dumps(manifest(version)), encoding="utf-8")
            for n in range(56):
                (folder/f"f{n:02d}.txt").write_text(f"{n}:{version}",encoding="utf-8")
        (self.source/"domain").mkdir()
        (self.source/"domain"/"node_favicon_notify_service.js").write_text("pass",encoding="utf-8")
        shutil.copytree(self.live,self.reference)
        self.release = {
            "rollbackBaseline": self._inv(self.live),
            "candidateInventory": self._inv(self.source)
        }
        self.policy_manifest.write_text(json.dumps(self.release),encoding="utf-8")
        self.prev_id=ri.EXTENSION_ID
        ri.EXTENSION_ID=self.id
        self.addCleanup(lambda: setattr(ri,"EXTENSION_ID",self.prev_id))

    @staticmethod
    def _inv(folder):
        files=ri._inventory(folder)
        return {"fileCount":len(files),"files":files,"aggregateSha256":_aggregate(files)}

    def inspect(self, op="N73-TEST-01"):
        return ri.inspect(op,live=self.live,candidate=self.source,
                          backup_source=self.reference,
                          manifest_file=self.policy_manifest,journal_root=self.journal)

    def install(self, plan, approve=lambda _:True):
        return ri.install(plan,authorization=approve,live=self.live,
                          candidate=self.source,backup_source=self.reference,
                          manifest_file=self.policy_manifest,journal_root=self.journal)

    def rollback(self, op,approve=lambda _:True):
        return ri.rollback(op,authorization=approve,live=self.live,
                           manifest_file=self.policy_manifest,journal_root=self.journal)

    def test_01_exact_read_only_preflight_57_58_identity(self):
        plan=self.inspect()
        self.assertEqual((plan["installed_files"],plan["candidate_files"]),(57,58))
        self.assertEqual(plan["extension_id"],self.id)
        self.assertFalse(self.journal.exists())

    def test_02_without_trusted_bct_authorization_installs_nothing(self):
        plan=self.inspect()
        with self.assertRaisesRegex(PreconditionError,"AUTHORIZATION_REQUIRED"):
            self.install(plan,approve=None)
        self.assertEqual(ri._inventory(self.live),self.release["rollbackBaseline"]["files"])

    def test_03_no_implicit_browser_reload_and_exact_stage_preservation(self):
        plan=self.inspect()
        result=self.install(plan)
        self.assertEqual(result["state"],"INSTALLED_AWAITING_RELOAD")
        self.assertFalse(result["reload_performed"])
        self.assertEqual(ri._inventory(self.live),self.release["candidateInventory"]["files"])
        self.assertEqual(ri._inventory(self.base/"chrome"/".rcc-previous-N73-TEST-01"),
                         self.release["rollbackBaseline"]["files"])
        self.assertEqual(ri._inventory(self.journal/"backup-N73-TEST-01"),
                         self.release["rollbackBaseline"]["files"])
        self.assertTrue((self.journal/"N73-TEST-01.json").is_file())

    def test_04_exact_rollback_original_57_and_no_automatic_reload(self):
        self.install(self.inspect())
        result=self.rollback("N73-TEST-01")
        self.assertEqual(result["state"],"ROLLBACK_AWAITING_RELOAD")
        self.assertFalse(result["reload_performed"])
        self.assertEqual(ri._inventory(self.live),self.release["rollbackBaseline"]["files"])
        self.assertEqual(ri._inventory(self.base/"chrome"/".rcc-rejected-N73-TEST-01"),
                         self.release["candidateInventory"]["files"])

    def test_05_duplicate_install_and_rollback_fail_closed(self):
        plan=self.inspect()
        self.install(plan)
        with self.assertRaises(PreconditionError):
            self.install(plan)
        self.rollback("N73-TEST-01")
        with self.assertRaises(PreconditionError):
            self.rollback("N73-TEST-01")

    def test_06_modified_manifest_and_payload_deny_preflight(self):
        (self.source/"f01.txt").write_text("tampered",encoding="utf-8")
        with self.assertRaisesRegex(PreconditionError,"DIGEST_MISMATCH"):
            self.inspect()

    def test_07_wrong_extension_identity_denied(self):
        (self.source/"manifest.json").write_text(json.dumps({
            "manifest_version": 3,"version":"1.0.60",
            "key":base64.b64encode(b"other-key").decode()
        }),encoding="utf-8")
        with self.assertRaisesRegex(PreconditionError,"IDENTITY_MISMATCH"):
            self.inspect()

    def test_08_missing_target_or_ambiguous_install_journal_deny(self):
        plan=self.inspect()
        self.journal.mkdir()
        (self.journal/"another-operation.json").write_text("{}",encoding="utf-8")
        with self.assertRaisesRegex(PreconditionError,"PREVIOUS_STATE"):
            self.install(plan)

    def test_09_interrupted_two_rename_transition_is_unknown_and_not_replayed(self):
        plan=self.inspect()
        original_rename=ri.os.rename
        count=0
        def interrupted(src,dst):
            nonlocal count
            count+=1
            if count==2: raise OSError("interrupted")
            return original_rename(src,dst)
        with patch.object(ri.os,"rename",side_effect=interrupted):
            with self.assertRaisesRegex(Exception,"RECONCILIATION"):
                self.install(plan)
        state=json.loads((self.journal/"N73-TEST-01.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"],"ORIGINAL_QUARANTINED")
        self.assertFalse(self.live.exists())
        self.assertTrue(Path(state["previous"]).exists())
        with self.assertRaises(PreconditionError):
            self.install(plan)

    def test_11_real_bct_deploy_operation_inspect_install_and_rollback(self):
        from bct.service import BCT
        from bct.core.models import Principal, Outcome
        from bct.features.deploy import DeployFeature
        policy=self.base / "bct.toml"
        policy.write_text(
            '[policy]\nnormal_actions=["deploy"]\napproval_actions=[]\n',
            encoding="utf-8",
        )
        bct=BCT(state_path=self.base/"bct-state.sqlite", policy_path=policy)
        principal=Principal("supervisor-test","isolated",frozenset({"deploy"}))
        bct.create_work(
            work_id="rcc-temp-protected", request_summary="No live effects",
            roots=[str(self.base)], actions=["deploy"], principal=principal,
        )
        head=subprocess.check_output(
            ["git","rev-parse","HEAD"],cwd=Path(__file__).resolve().parents[1],
            text=True,encoding="utf-8",
        ).strip()
        params={
            "expected_source_head":head,
            "expected_installed_aggregate":self.release["rollbackBaseline"]["aggregateSha256"],
            "expected_candidate_aggregate":self.release["candidateInventory"]["aggregateSha256"],
            "expected_manifest_sha256":ri._sha(self.policy_manifest.read_bytes()),
            "instance_id":"b"*32,
        }
        def effect(op_id,operation,original=None):
            args={"operation":operation,**params}
            if original:
                args["install_operation_id"]=original
            return bct.operations.run(
                principal=principal,work_id="rcc-temp-protected",
                operation_id=op_id,capability="deploy",arguments=args,
            )
        with patch.object(ri,"EXACT_INSTALLED",self.live),\
             patch.object(ri,"EXACT_STAGE",self.source),\
             patch.object(ri,"EXACT_ROLLBACK",self.reference),\
             patch.object(ri,"EXACT_MANIFEST",self.policy_manifest),\
             patch.object(ri,"EXACT_JOURNAL",self.journal),\
             patch.object(DeployFeature,"RCC_SOURCE_ROOT",Path(__file__).resolve().parents[1]):
            inspected=effect("rcc-inspect-1","rcc-inspect")
            self.assertEqual(inspected.outcome,Outcome.APPLIED,inspected.as_dict())
            self.assertFalse(self.journal.exists())
            installed=effect("rcc-install-1","rcc-install")
            self.assertEqual(installed.outcome,Outcome.APPLIED)
            self.assertEqual(ri._inventory(self.live),self.release["candidateInventory"]["files"])
            self.assertTrue(installed.evidence["effect"]=="FILES_INSTALLED_PENDING_RELOAD")
            self.assertEqual(installed.evidence["reload"],"NOT_PERFORMED")
            self.assertTrue(effect("rcc-install-1","rcc-install").duplicate)
            restored=effect("rcc-rollback-1","rcc-rollback","rcc-install-1")
            self.assertEqual(restored.outcome,Outcome.APPLIED)
            self.assertEqual(ri._inventory(self.live),self.release["rollbackBaseline"]["files"])
            self.assertEqual(restored.evidence["reload"],"NOT_PERFORMED")

    def test_10_work_root_and_strict_argument_protection(self):
        work=Work("w","prepare",(str(self.base),),frozenset({"deploy"}),"trusted")
        with patch.object(ri,"EXACT_INSTALLED",self.live),\
             patch.object(ri,"EXACT_MANIFEST",self.policy_manifest):
            args={
                "operation":"rcc-inspect","expected_source_head":"a"*40,
                "expected_installed_aggregate":self.release["rollbackBaseline"]["aggregateSha256"],
                "expected_candidate_aggregate":self.release["candidateInventory"]["aggregateSha256"],
                "expected_manifest_sha256":ri._sha(self.policy_manifest.read_bytes()),
                "instance_id":"b"*32
            }
            prepared=DeployFeature._prepare_rcc(work,"rcc-inspect",args)
            self.assertEqual(prepared.capability,"deploy")
            self.assertEqual(prepared.arguments["operation"],"rcc-inspect")
            with self.assertRaises(PreconditionError):
                DeployFeature._prepare_rcc(
                    work,"rcc-inspect",{**args,"unapproved_path":"D:/somewhere"}
                )
            with self.assertRaises(PreconditionError):
                DeployFeature._prepare_rcc(
                    Work("wrong","wrong",(str(self.base/"else"),),
                         frozenset({"deploy"}),"trusted"),
                    "rcc-inspect",args,
                )


if __name__ == "__main__":
    unittest.main()
