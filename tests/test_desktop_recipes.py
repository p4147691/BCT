from __future__ import annotations

import unittest

from bct.desktop_recipes import desktop_catalogue, plan_desktop_recipe


class DesktopRecipeTests(unittest.TestCase):
    def test_catalogue_classifies_existing_parts(self):
        value = desktop_catalogue()
        self.assertEqual("PLAN_ONLY", value["execution"])
        ids = {item["id"] for item in value["modules"]}
        self.assertIn("bdc.observe", ids)
        self.assertIn("bdc.chrome_ui", ids)
        capabilities = {item["capability"] for item in value["primitives"]}
        self.assertIn("desktop_emergency_stop", capabilities)
        self.assertIn("desktop_chrome_content_action", capabilities)

    def test_plan_keeps_effects_as_separate_public_capabilities(self):
        value = plan_desktop_recipe("use_chrome")
        self.assertEqual("OK", value["status"])
        self.assertEqual("PLAN_ONLY", value["execution"])
        names = [step["capability"] for step in value["steps"]]
        self.assertEqual("desktop_application_target", names[0])
        self.assertIn("desktop_chrome_content_action", names)
        self.assertEqual("desktop_control_lease", names[-1])

    def test_unknown_recipe_fails_closed(self):
        value = plan_desktop_recipe("do_everything")
        self.assertEqual("INVALID_REQUEST", value["status"])
        self.assertEqual("BDC_RECIPE_UNKNOWN", value["reason"])


    def test_supported_target_scope_is_explicit(self):
        for name in ("use_application", "arrange_window"):
            plan = plan_desktop_recipe(name)
            self.assertEqual("CHROME_OR_EXPLORER_ONLY", plan["target_scope"])
            self.assertIn("readback", plan["steps"][-1]["purpose"].lower())

    def test_effect_recipes_require_explicit_independent_readback(self):
        cases = {
            "use_application": ("desktop_uia_element_action", "desktop_uia_elements_list"),
            "use_chrome": ("desktop_chrome_content_action", "desktop_chrome_content_list"),
            "arrange_window": ("desktop_window_manage", "desktop_window_list"),
            "launch_program": ("desktop_program_launch", "desktop_window_list"),
        }
        for name, (effect, readback) in cases.items():
            with self.subTest(recipe=name):
                plan = plan_desktop_recipe(name)
                capabilities = [step["capability"] for step in plan["steps"]]
                self.assertEqual(readback, capabilities[capabilities.index(effect) + 1])
                self.assertEqual("desktop_control_lease", capabilities[-1])
                self.assertTrue(any("UNVERIFIED" in step["purpose"] for step in plan["steps"]))

    def test_incomplete_effect_recipes_are_partial(self):
        for name in ("arrange_window", "launch_program"):
            self.assertEqual("partial_recipe", plan_desktop_recipe(name)["kind"])

    def test_release_inventory_contains_desktop_recipes(self):
        import tomllib
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        manifest = tomllib.loads((root / "bct.toml").read_text(encoding="utf-8"))
        files = manifest["deployment"]["profiles"]["bct_runtime_v1"]["files"]
        self.assertIn("src/bct/desktop_recipes.py", files)

if __name__ == "__main__":
    unittest.main()
