from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz

from core.margin_detector import MembreteMargins
from core.membrete_engine import MembreteEngine, MembreteJob
from core.pdf_merge_engine import PdfMergeEngine, PdfMergeOptions


class PdfMergeEngineTests(unittest.TestCase):
    def test_merges_all_pages_with_blanks_bookmarks_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._make_pdf(root / "a.pdf", pages=2)
            second = self._make_pdf(root / "b.pdf", pages=3)
            output = root / "merged.pdf"

            result = PdfMergeEngine().run(
                [str(first), str(second)],
                str(output),
                PdfMergeOptions(blank_between=True, add_bookmarks=True),
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.expected_pages, 6)
            self.assertEqual(result.total_pages, 6)
            self.assertEqual(result.blank_pages, 1)
            self.assertEqual([s.inserted_pages for s in result.sources], [2, 3])

            with fitz.open(str(output)) as doc:
                self.assertEqual(doc.page_count, 6)
                self.assertEqual(
                    [[level, title, page] for level, title, page in doc.get_toc()],
                    [[1, "a", 1], [1, "b", 4]],
                )

    def test_merges_letterheaded_pdf_without_losing_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            letterhead = self._make_letterhead(root / "membrete.pdf")
            source = self._make_pdf(root / "cliente.pdf", pages=3)
            letterheaded = root / "cliente_membretado.pdf"
            other_a = self._make_pdf(root / "otro_a.pdf", pages=1)
            other_b = self._make_pdf(root / "otro_b.pdf", pages=1)
            output = root / "merged.pdf"

            letterheaded_result = MembreteEngine().run_batch(
                [MembreteJob(str(source), str(letterheaded))],
                str(letterhead),
                MembreteMargins(top_pt=56, bottom_pt=42, left_pt=18, right_pt=18),
            )[0]
            self.assertTrue(letterheaded_result.success, letterheaded_result.error)
            self.assertEqual(letterheaded_result.page_count, 3)

            result = PdfMergeEngine().run(
                [str(other_a), str(letterheaded), str(other_b)],
                str(output),
                PdfMergeOptions(),
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.expected_pages, 5)
            self.assertEqual(result.total_pages, 5)
            self.assertEqual([s.page_count for s in result.sources], [1, 3, 1])

            with fitz.open(str(output)) as doc:
                self.assertEqual(doc.page_count, 5)

    def test_falls_back_to_normalized_copy_when_direct_copy_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._make_pdf(root / "a.pdf", pages=2)
            second = self._make_pdf(root / "b.pdf", pages=1)
            output = root / "merged.pdf"

            with patch(
                "core.pdf_merge_engine._merge_direct",
                side_effect=RuntimeError("fallo directo simulado"),
            ):
                result = PdfMergeEngine().run(
                    [str(first), str(second)],
                    str(output),
                    PdfMergeOptions(),
                )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.expected_pages, 3)
            self.assertEqual(result.total_pages, 3)
            self.assertTrue(result.warnings)
            self.assertTrue(all(src.used_pagewise_fallback for src in result.sources))

            with fitz.open(str(output)) as doc:
                self.assertEqual(doc.page_count, 3)

    def test_uses_visual_rescue_when_vector_copy_modes_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._make_pdf(root / "a.pdf", pages=2)
            second = self._make_pdf(root / "b.pdf", pages=1)
            output = root / "merged.pdf"

            with (
                patch(
                    "core.pdf_merge_engine._merge_direct",
                    side_effect=RuntimeError("fallo directo simulado"),
                ),
                patch(
                    "core.pdf_merge_engine._merge_normalized",
                    side_effect=RuntimeError("fallo normalizado simulado"),
                ),
            ):
                result = PdfMergeEngine().run(
                    [str(first), str(second)],
                    str(output),
                    PdfMergeOptions(),
                )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.expected_pages, 3)
            self.assertEqual(result.total_pages, 3)
            self.assertTrue(result.warnings)
            self.assertTrue(all(src.used_raster_fallback for src in result.sources))

            with fitz.open(str(output)) as doc:
                self.assertEqual(doc.page_count, 3)
                for page in doc:
                    self.assertTrue(page.get_images())

    @staticmethod
    def _make_pdf(path: Path, *, pages: int) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=360, height=480)
            page.insert_text((48, 80), f"{path.stem} pagina {index + 1}", fontsize=18)
            page.draw_rect(fitz.Rect(36, 50, 324, 430), color=(0, 0, 0), width=1)
            page.insert_text((48, 410), f"pie {index + 1}", fontsize=10)
        doc.save(str(path))
        doc.close()
        return path

    @staticmethod
    def _make_letterhead(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=420, height=560)
        page.draw_rect(fitz.Rect(24, 24, 396, 536), color=(0.0, 0.2, 0.8), width=2)
        page.insert_text((42, 46), "MEMBRETE", fontsize=16)
        page.insert_text((42, 525), "PIE MEMBRETE", fontsize=10)
        doc.save(str(path))
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
