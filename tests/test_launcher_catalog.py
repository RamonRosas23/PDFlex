from __future__ import annotations

import unittest

from core.media_conversion import (
    DOCUMENT_IMPORT_EXTENSIONS,
    IMAGE_EXTENSIONS,
    WORD_EXTENSIONS,
)
from shell.launcher import EDITORIAL_ORDER, catalog_sections, _section_tool_ids
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

    def test_quick_tools_can_be_removed_from_base_sections(self) -> None:
        section = catalog_sections(TOOLS)[0]
        visible_ids = _section_tool_ids(section, {"firmador", "unir"})

        self.assertNotIn("firmador", visible_ids)
        self.assertNotIn("unir", visible_ids)
        self.assertIn("foleador", visible_ids)

    def test_tools_advertise_import_extensions_for_auto_conversion(self) -> None:
        document_imports = set(DOCUMENT_IMPORT_EXTENSIONS)
        word_to_pdf_imports = set(WORD_EXTENSIONS | IMAGE_EXTENSIONS)

        for tool in TOOLS:
            exts = set(tool.input_extensions)
            if tool.id == "word_a_pdf":
                self.assertEqual(exts, word_to_pdf_imports)
            else:
                self.assertTrue(
                    document_imports.issubset(exts),
                    f"{tool.id} does not expose every auto-convertible import type",
                )


if __name__ == "__main__":
    unittest.main()
