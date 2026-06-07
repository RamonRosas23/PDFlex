from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz
from PIL import Image

from core.pdf_to_images_engine import (
    PdfToImagesConfig,
    PdfToImagesEngine,
    PdfToImagesJob,
    parse_page_selection,
)


class PdfToImagesEngineTests(unittest.TestCase):
    def test_parse_page_selection_supports_ranges_and_last_page(self) -> None:
        self.assertEqual(parse_page_selection("1-3, final", 5), [0, 1, 2, 4])
        self.assertEqual(parse_page_selection("2-final", 4), [1, 2, 3])
        self.assertEqual(parse_page_selection("pares", 5), [1, 3])
        self.assertEqual(parse_page_selection("impares", 5), [0, 2, 4])

    def test_exports_only_selected_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = self._make_pdf(root / "doc.pdf", pages=4)
            out_dir = root / "out"

            result = PdfToImagesEngine()._process_job(
                PdfToImagesJob(str(pdf), str(out_dir), base_name="doc", add_tool_suffix=False),
                PdfToImagesConfig(format="png", dpi=72, page_range="2,4"),
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual([r.page_index for r in result.image_results], [1, 3])
            self.assertEqual([Path(r.output_path).name for r in result.image_results], ["doc_p002.png", "doc_p004.png"])
            for image_result in result.image_results:
                self.assertTrue(Path(image_result.output_path).exists())

    def test_panoramic_uses_selected_pages_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = self._make_pdf(root / "doc.pdf", pages=3)
            out_dir = root / "out"

            result = PdfToImagesEngine()._process_job(
                PdfToImagesJob(str(pdf), str(out_dir), base_name="doc", add_tool_suffix=False),
                PdfToImagesConfig(format="jpg", dpi=72, panoramic=True, page_range="2-3"),
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(len(result.image_results), 1)
            self.assertEqual(result.image_results[0].page_index, -1)
            with Image.open(result.image_results[0].output_path) as image:
                self.assertGreater(image.height, image.width)

    def test_invalid_page_range_returns_job_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = self._make_pdf(root / "doc.pdf", pages=2)

            result = PdfToImagesEngine()._process_job(
                PdfToImagesJob(str(pdf), str(root / "out"), base_name="doc", add_tool_suffix=False),
                PdfToImagesConfig(page_range="10"),
            )

            self.assertFalse(result.success)
            self.assertIn("rango", result.error.lower())

    @staticmethod
    def _make_pdf(path: Path, pages: int) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=200, height=260)
            page.insert_text((36, 72), f"Pagina {index + 1}")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
