from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz

from core.margin_detector import MembreteMargins
from core.membrete_engine import (
    MembreteEngine,
    MembreteJob,
    compact_page_indexes,
    parse_membrete_page_scope,
)


class MembreteEngineScopeTests(unittest.TestCase):
    def test_preserves_unselected_pages_without_letterhead(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            letterhead = self._make_pdf(root / "lh.pdf", pages=1, width=500, height=700)
            source = self._make_pdf(root / "source.pdf", pages=3, width=240, height=320)
            out = root / "out.pdf"

            result = MembreteEngine().run_batch(
                [
                    MembreteJob(
                        pdf_path=str(source),
                        output_path=str(out),
                        pages_to_letterhead=[0, 2],
                        preserve_unselected=True,
                    )
                ],
                str(letterhead),
                MembreteMargins(top_pt=40, bottom_pt=40, left_pt=20, right_pt=20),
            )[0]

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.pages_letterheaded, 2)
            self.assertEqual(result.pages_preserved, 1)
            self.assertEqual(result.pages_omitted, 0)

            doc = fitz.open(str(out))
            try:
                self.assertEqual(doc.page_count, 3)
                self.assertAlmostEqual(doc[0].rect.width, 500, delta=1)
                self.assertAlmostEqual(doc[1].rect.width, 240, delta=1)
                self.assertAlmostEqual(doc[2].rect.width, 500, delta=1)
            finally:
                doc.close()

    def test_can_omit_unselected_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            letterhead = self._make_pdf(root / "lh.pdf", pages=1)
            source = self._make_pdf(root / "source.pdf", pages=4)
            out = root / "out.pdf"

            result = MembreteEngine().run_batch(
                [
                    MembreteJob(
                        pdf_path=str(source),
                        output_path=str(out),
                        pages_to_letterhead=[1, 3],
                        preserve_unselected=False,
                    )
                ],
                str(letterhead),
                MembreteMargins(top_pt=40, bottom_pt=40, left_pt=20, right_pt=20),
            )[0]

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.page_count, 2)
            self.assertEqual(result.pages_letterheaded, 2)
            self.assertEqual(result.pages_omitted, 2)

    def test_page_scope_parser_include_exclude_and_compact(self) -> None:
        self.assertEqual(parse_membrete_page_scope("include", "1-2, final", 5), [0, 1, 4])
        self.assertEqual(parse_membrete_page_scope("exclude", "1, 5", 5), [1, 2, 3])
        self.assertEqual(parse_membrete_page_scope("even", "", 5), [1, 3])
        self.assertEqual(compact_page_indexes([0, 1, 3, 4, 6]), "1-2, 4-5, 7")

    def test_letterheaded_annotations_are_flattened_without_touching_preserved_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            letterhead = self._make_pdf(root / "lh.pdf", pages=1, width=500, height=700)
            source = self._make_annotated_pdf(
                root / "source.pdf",
                pages=2,
                annotated_pages={0, 1},
            )
            out = root / "out.pdf"

            result = MembreteEngine().run_batch(
                [
                    MembreteJob(
                        pdf_path=str(source),
                        output_path=str(out),
                        pages_to_letterhead=[0],
                        preserve_unselected=True,
                    )
                ],
                str(letterhead),
                MembreteMargins(top_pt=40, bottom_pt=40, left_pt=20, right_pt=20),
            )[0]

            self.assertTrue(result.success, result.error)

            doc = fitz.open(str(out))
            try:
                self.assertEqual(doc.page_count, 2)
                self.assertTrue(
                    self._page_has_red_stroke(doc[0]),
                    "El subrayado de la pagina membretada debe quedar visible.",
                )
                self.assertTrue(
                    doc[1].annot_xrefs(),
                    "La pagina preservada debe conservar sus anotaciones originales.",
                )
            finally:
                doc.close()

    @staticmethod
    def _make_pdf(
        path: Path,
        *,
        pages: int,
        width: float = 300,
        height: float = 420,
    ) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=width, height=height)
            page.insert_text((36, 36), f"{path.stem} {index + 1}")
        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _make_annotated_pdf(
        path: Path,
        *,
        pages: int,
        annotated_pages: set[int],
    ) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=300, height=420)
            text = f"Texto subrayado {index + 1}"
            page.insert_text((50, 100), text, fontsize=18)
            if index in annotated_pages:
                rects = page.search_for(text)
                annot = page.add_underline_annot(rects)
                annot.set_colors(stroke=(1, 0, 0))
                annot.update()
        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _page_has_red_stroke(page: fitz.Page) -> bool:
        for drawing in page.get_drawings():
            color = drawing.get("color")
            if not color or len(color) < 3:
                continue
            if color[0] > 0.8 and color[1] < 0.2 and color[2] < 0.2:
                return True
        return False


if __name__ == "__main__":
    unittest.main()
