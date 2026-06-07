from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz
from PIL import Image

from core.pdf_compress_engine import (
    CompressJob,
    PdfCompressEngine,
    format_bytes,
    profile_for,
)


class PdfCompressEngineTests(unittest.TestCase):
    def test_email_profile_reduces_image_heavy_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_image_pdf(root / "scan.pdf")
            output = root / "out" / "scan_comprimido.pdf"

            result = PdfCompressEngine().run_job(
                CompressJob(
                    pdf_path=str(source),
                    output_path=str(output),
                    profile_id="email",
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertTrue(output.exists())
            self.assertLess(result.output_bytes, result.input_bytes)
            self.assertGreater(result.reduction_pct, 20.0)
            self.assertIn("menos", result.meta_text)

    def test_small_pdf_does_not_grow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "simple.pdf")
            output = root / "out" / "simple_comprimido.pdf"

            result = PdfCompressEngine().run_job(
                CompressJob(
                    pdf_path=str(source),
                    output_path=str(output),
                    profile_id="balanced",
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertTrue(output.exists())
            self.assertLessEqual(result.output_bytes, result.input_bytes)

    def test_unknown_profile_falls_back_to_balanced(self) -> None:
        self.assertEqual(profile_for("nope").id, "balanced")

    def test_format_bytes_is_human_readable(self) -> None:
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1536), "1.5 KB")

    @staticmethod
    def _make_text_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((36, 72), "PDF pequeno")
        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _make_image_pdf(path: Path) -> Path:
        image = Image.effect_noise((1200, 1200), 100).convert("RGB")
        png = path.with_suffix(".png")
        image.save(png, format="PNG")

        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        rect = fitz.Rect(36, 72, 576, 612)
        page.insert_image(rect, filename=str(png))
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
