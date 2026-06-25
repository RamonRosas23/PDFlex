from __future__ import annotations

import unittest

from core.pdf_page_rules import (
    PageCompressionRule,
    build_page_compression_plan,
    compact_page_indexes,
    parse_page_spec,
)


class PdfPageRulesTests(unittest.TestCase):
    def test_parse_common_page_specs(self) -> None:
        self.assertEqual(parse_page_spec("1", 5), [0])
        self.assertEqual(parse_page_spec("1-3", 5), [0, 1, 2])
        self.assertEqual(parse_page_spec("1, 3, 5", 5), [0, 2, 4])
        self.assertEqual(parse_page_spec("3-fin", 5), [2, 3, 4])
        self.assertEqual(parse_page_spec("pares", 5), [1, 3])
        self.assertEqual(parse_page_spec("impares", 5), [0, 2, 4])
        self.assertEqual(parse_page_spec("todo", 3), [0, 1, 2])

    def test_parse_rejects_invalid_specs(self) -> None:
        for spec in ("", "0", "8", "4-2", "abc"):
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    parse_page_spec(spec, 5)

    def test_compact_page_indexes(self) -> None:
        self.assertEqual(compact_page_indexes([0, 1, 2, 4, 7, 8]), "1-3, 5, 8-9")
        self.assertEqual(compact_page_indexes([]), "Ninguna")

    def test_build_plan_assigns_explicit_rules(self) -> None:
        plan = build_page_compression_plan(
            6,
            "balanced",
            [
                PageCompressionRule("1-2", "exclude", id="a"),
                PageCompressionRule("3-4", "quality", id="b"),
                PageCompressionRule("6", "email", id="c"),
            ],
        )

        self.assertTrue(plan.has_explicit_rules)
        self.assertEqual(plan.pages_excluded, 2)
        self.assertEqual(plan.pages_with_rules, 5)
        self.assertEqual(plan.rule_for_page(0).preset, "exclude")
        self.assertTrue(plan.rule_for_page(1).excluded)
        self.assertEqual(plan.rule_for_page(2).profile_id, "quality")
        self.assertEqual(plan.rule_for_page(4).profile_id, "balanced")
        self.assertEqual(plan.rule_for_page(5).profile_id, "email")

    def test_build_plan_rejects_overlapping_rules(self) -> None:
        with self.assertRaisesRegex(ValueError, "ya tienen una regla"):
            build_page_compression_plan(
                5,
                "balanced",
                [
                    PageCompressionRule("1-3", "quality"),
                    PageCompressionRule("3-4", "email"),
                ],
            )

    def test_custom_rule_keeps_options(self) -> None:
        plan = build_page_compression_plan(
            2,
            "balanced",
            [
                PageCompressionRule(
                    "2",
                    "custom",
                    id="custom",
                    options={
                        "dpi_target": 200,
                        "quality": 81,
                        "validation_level": "strict",
                    },
                )
            ],
        )

        rule = plan.rule_for_page(1)
        self.assertEqual(rule.preset, "custom")
        self.assertEqual(rule.options["dpi_target"], 200)
        self.assertEqual(rule.options["quality"], 81)


if __name__ == "__main__":
    unittest.main()
