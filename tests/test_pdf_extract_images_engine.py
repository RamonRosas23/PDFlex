from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz
from PIL import Image

from core.pdf_extract_images_engine import (
    ExtractImagesConfig,
    ExtractImagesJob,
    PdfExtractImagesEngine,
)


class PdfExtractImagesEngineTests(unittest.TestCase):
    def test_extracts_embedded_image_once_when_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf_with_reused_image(root / "con_imagen.pdf")
            out_dir = root / "out"

            result = PdfExtractImagesEngine().run_job(
                ExtractImagesJob(str(source), str(out_dir), base_name="doc", add_tool_suffix=False),
                ExtractImagesConfig(deduplicate=True),
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(len(result.image_results), 1)
            image_result = result.image_results[0]
            self.assertTrue(Path(image_result.output_path).exists())
            self.assertEqual(image_result.width, 80)
            self.assertEqual(image_result.height, 50)
            self.assertIn(image_result.ext, {"png", "jpg"})
            self.assertGreater(result.skipped_duplicates, 0)

    def test_extracts_each_occurrence_when_deduplication_is_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf_with_reused_image(root / "con_imagen.pdf")
            out_dir = root / "out"

            result = PdfExtractImagesEngine().run_job(
                ExtractImagesJob(str(source), str(out_dir), base_name="doc", add_tool_suffix=False),
                ExtractImagesConfig(deduplicate=False),
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(len(result.image_results), 2)
            self.assertEqual(len({r.output_path for r in result.image_results}), 2)

    def test_pdf_without_images_returns_clear_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "sin_imagen.pdf")
            out_dir = root / "out"

            result = PdfExtractImagesEngine().run_job(
                ExtractImagesJob(str(source), str(out_dir), base_name="doc", add_tool_suffix=False),
                ExtractImagesConfig(),
            )

            self.assertFalse(result.success)
            self.assertIn("imagenes", result.error.lower())

    @staticmethod
    def _make_pdf_with_reused_image(path: Path) -> Path:
        img_path = path.with_suffix(".png")
        image = Image.new("RGB", (80, 50), (220, 40, 40))
        image.save(img_path)

        doc = fitz.open()
        page1 = doc.new_page(width=300, height=200)
        xref = page1.insert_image(fitz.Rect(36, 36, 156, 111), filename=str(img_path))
        page2 = doc.new_page(width=300, height=200)
        page2.insert_image(fitz.Rect(48, 48, 168, 123), xref=xref)
        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _make_text_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((36, 72), "Solo texto")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
