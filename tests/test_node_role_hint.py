from __future__ import annotations

import unittest

from bct.node_role_hint import format_node_role_hint


class NodeRoleHintTests(unittest.TestCase):
    def test_desktop_and_role_tags(self) -> None:
        self.assertEqual("D2 · 검색 · CI", format_node_role_hint(" D2 ", ["검색", "CI"]))

    def test_reasoning_is_explicitly_preference(self) -> None:
        self.assertEqual("D2 · 검색 · 선호: Instant", format_node_role_hint("D2", ["검색"], "Instant"))

    def test_no_role(self) -> None:
        self.assertEqual("D2", format_node_role_hint("D2", []))

    def test_empty_desktop_is_unknown(self) -> None:
        self.assertEqual("D? · 구현", format_node_role_hint("", ["구현"]))

    def test_dedupe_casefold_and_first_spelling(self) -> None:
        self.assertEqual("D1 · CI · 검색", format_node_role_hint("D1", [" CI ", "ci", "", "검색", "검색"]))

    def test_multiple_roles_but_bounded_to_six(self) -> None:
        values = ["a", "b", "c", "d", "e", "f", "g"]
        self.assertEqual("D2 · a · b · c · d · e · f", format_node_role_hint("D2", values))

    def test_invalid_elements_ignored(self) -> None:
        self.assertEqual("D3 · 검색", format_node_role_hint("D3", [None, 1, "검색"]))

    def test_reasoning_empty_ignored(self) -> None:
        self.assertEqual("D2 · 검색", format_node_role_hint("D2", ["검색"], "  "))

    def test_truncation_retains_max_chars(self) -> None:
        value = format_node_role_hint("D2", ["Long task name for assessment", "CI"], "High", 14)
        self.assertEqual(len(value), 14)
        self.assertTrue(value.endswith("…"))

    def test_exact_limit_does_not_truncate(self) -> None:
        self.assertEqual("D2 · 검색", format_node_role_hint("D2", ["검색"], max_chars=7 + 1))

    def test_minimum_max_chars(self) -> None:
        for limit in (0, -1, 7, 3.5, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                format_node_role_hint("D2", [], max_chars=limit)

    def test_no_special_role_is_privileged(self) -> None:
        text = format_node_role_hint("D2", ["Manager", "Worker", "검색", "CI"])
        self.assertEqual(text, "D2 · Manager · Worker · 검색 · CI")


if __name__ == "__main__":
    unittest.main()
