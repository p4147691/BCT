from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from bct.service import BCT


class CapabilityRetirementTests(unittest.TestCase):
    def test_optional_decision_capabilities_are_not_registered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "bct.toml"
            policy.write_text("[policy]\nnormal_actions=[\"read\",\"monitor\"]\napproval_actions=[]\n", encoding="utf-8")
            core = BCT(state_path=root / "state.sqlite", policy_path=policy)
            self.assertNotIn("decision_model", core.operations._features)
            self.assertNotIn("decision_service", core.operations._features)

    def test_deployment_profile_omits_retired_optional_module(self):
        project = Path(__file__).resolve().parents[1]
        config = tomllib.loads((project / "bct.toml").read_text(encoding="utf-8"))
        self.assertNotIn("decision_model", config["policy"]["normal_actions"])
        self.assertNotIn("decision_service", config["policy"]["normal_actions"])
        self.assertNotIn("decision", config)
        deploy_files = config["deployment"]["profiles"]["bct_runtime_v1"]["files"]
        self.assertNotIn("src/bct/features/decision.py", deploy_files)
        self.assertNotIn("src/bct/features/decision_service.py", deploy_files)


if __name__ == "__main__":
    unittest.main()
