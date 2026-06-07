from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz
from PIL import Image, ImageDraw

from core.watermark_engine import (
    WatermarkEngine,
    WatermarkJob,
    WatermarkOptions,
    parse_page_selection,
    preset_for,
)


class WatermarkEngineTests(unittest.TestCase):
    def test_text_watermark_applies_to_custom_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "input.pdf", pages=3)
            output = root / "out" / "input_sellado.pdf"
            options = WatermarkOptions(
                mode="text",
                text="APROBADO",
                rotation_deg=0,
                opacity=0.85,
                font_size=28,
                page_scope="custom",
                custom_pages="1,3",
            )

            result = WatermarkEngine().run_job(
                WatermarkJob(str(source), str(output), options)
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.stamped_pages, 2)
            self.assertTrue(output.exists())

            doc = fitz.open(output)
            try:
                self.assertIn("APROBADO", doc[0].get_text())
                self.assertNotIn("APROBADO", doc[1].get_text())
                self.assertIn("APROBADO", doc[2].get_text())
            finally:
                doc.close()

    def test_image_watermark_creates_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "input.pdf", pages=2)
            image = self._make_stamp_image(root / "stamp.png")
            output = root / "out" / "input_sellado.pdf"
            options = WatermarkOptions(
                mode="image",
                image_path=str(image),
                opacity=0.55,
                rotation_deg=18,
                image_width_pct=28,
                page_scope="first",
            )

            result = WatermarkEngine().run_job(
                WatermarkJob(str(source), str(output), options)
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.stamped_pages, 1)
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 0)
            self.assertIn("Imagen", result.meta_text)

    def test_page_selection_parser(self) -> None:
        self.assertEqual(parse_page_selection("all", "", 3), [0, 1, 2])
        self.assertEqual(parse_page_selection("first", "", 3), [0])
        self.assertEqual(parse_page_selection("last", "", 3), [2])
        self.assertEqual(parse_page_selection("custom", "1, 3-4, 9", 5), [0, 2, 3])
        self.assertEqual(parse_page_selection("custom", "2-", 4), [1, 2, 3])

    def test_preset_lookup_falls_back_to_confidential(self) -> None:
        self.assertEqual(preset_for("pagado").text, "PAGADO")
        self.assertEqual(preset_for("nope").id, "confidencial")

    @staticmethod
    def _make_pdf(path: Path, pages: int) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=360, height=260)
            page.insert_text((36, 72), f"Pagina {index + 1}")
        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _make_stamp_image(path: Path) -> Path:
        image = Image.new("RGBA", (240, 90), (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 232, 82), outline=(220, 30, 30, 255), width=6)
        draw.text((54, 32), "SELLO", fill=(220, 30, 30, 255))
        image.save(path)
        return path


if __name__ == "__main__":
    unittest.main()
