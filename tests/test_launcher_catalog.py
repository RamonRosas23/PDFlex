from __future__ import annotations

import unittest

from shell.launcher import EDITORIAL_ORDER, catalog_sections
from shell.tool_registry import TOOLS
from shell.tool_usage import ToolUsageStat, rank_tool_ids


class LauncherCatalogTests(unittest.TestCase):
    def test_catalog_sections_include_every_registered_tool_once(self) -> None:
        tool_ids = [tool.id for tool in TOOLS]
        section_ids = [
            tool_id
            for section in catalog_sections(TOOLS)
            for tool_id in section.tool_ids
        ]

        self.assertEqual(set(section_ids), set(tool_ids))
        self.assertEqual(len(section_ids), len(set(section_ids)))

    def test_editorial_order_starts_with_core_workflows(self) -> None:
        self.assertEqual(
            EDITORIAL_ORDER[:5],
            ("firmador", "foleador", "separador", "unir", "membretado"),
        )

    def test_usage_ranking_prioritizes_frequent_tools_then_editorial_order(self) -> None:
        ranked = rank_tool_ids(
            ["firmador", "foleador", "unir", "ocr"],
            {
                "ocr": ToolUsageStat(count=5, last_used=10),
                "unir": ToolUsageStat(count=2, last_used=20),
            },
            EDITORIAL_ORDER,
            limit=4,
        )

        self.assertEqual(ranked[:2], ["ocr", "unir"])
        self.assertEqual(ranked[2:], ["firmador", "foleador"])


if __name__ == "__main__":
    unittest.main()
