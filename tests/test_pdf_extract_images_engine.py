from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

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
            with Image.open(image_result.output_path) as extracted:
                self.assertEqual(extracted.size, (80, 50))
                red, green, blue = extracted.convert("RGB").getpixel((40, 25))
                self.assertGreater(red, 180)
                self.assertLess(green, 80)
                self.assertLess(blue, 80)

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

        canvas = Canvas(str(path), pagesize=(300, 200))
        image_reader = ImageReader(str(img_path))
        canvas.drawImage(image_reader, 36, 89, width=120, height=75)
        canvas.showPage()
        canvas.drawImage(image_reader, 48, 77, width=120, height=75)
        canvas.showPage()
        canvas.save()
        return path

    @staticmethod
    def _make_text_pdf(path: Path) -> Path:
        canvas = Canvas(str(path), pagesize=(300, 200))
        canvas.drawString(36, 128, "Solo texto")
        canvas.showPage()
        canvas.save()
        return path


if __name__ == "__main__":
    unittest.main()
