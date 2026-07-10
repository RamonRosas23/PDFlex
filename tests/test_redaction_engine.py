from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from PIL import ImageStat
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from core.pdf_backend import PdfRenderDocument, Rect
from core.redaction_engine import RedactionEngine, RedactionJob, RedactionRect


class RedactionEngineTests(unittest.TestCase):
    def test_redaction_removes_recoverable_content_but_keeps_public_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "input.pdf")
            output = root / "out" / "input_redactado.pdf"
            rect, public_rect = self._redaction_and_public_rects(source)

            result = RedactionEngine().run_job(
                RedactionJob(str(source), str(output), [rect])
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.redaction_count, 1)
            with PdfRenderDocument(output) as redacted:
                # Affected pages are image-only: no hidden secret survives and
                # a PDF extractor cannot recover adjacent text either.
                self.assertEqual(redacted.extract_text(0).strip(), "")
                rendered = redacted.render_page(0, scale=2).to_pil()
            public_crop = rendered.crop(
                tuple(round(value * 2) for value in (
                    public_rect.x0, public_rect.y0, public_rect.x1, public_rect.y1
                ))
            )
            self.assertLess(ImageStat.Stat(public_crop.convert("L")).mean[0], 245)

    def test_requires_at_least_one_rect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "input.pdf")
            result = RedactionEngine().run_job(
                RedactionJob(str(source), str(root / "out.pdf"), [])
            )
            self.assertFalse(result.success)
            self.assertIn("zona", result.error.lower())

    def test_rotated_page_uses_display_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "rotated.pdf", rotation=90)
            output = root / "out" / "rotated_redactado.pdf"
            rect, public_rect = self._redaction_and_public_rects(source)

            result = RedactionEngine().run_job(
                RedactionJob(str(source), str(output), [rect])
            )

            self.assertTrue(result.success, result.error)
            with PdfRenderDocument(output) as redacted:
                self.assertEqual(redacted.extract_text(0).strip(), "")
                rendered = redacted.render_page(0, scale=2).to_pil()
            public_crop = rendered.crop(
                tuple(round(value * 2) for value in (
                    public_rect.x0, public_rect.y0, public_rect.x1, public_rect.y1
                ))
            )
            self.assertLess(ImageStat.Stat(public_crop.convert("L")).mean[0], 245)

    def test_unaffected_pages_keep_native_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "two-pages.pdf", pages=2)
            output = root / "redacted.pdf"
            rect, _ = self._redaction_and_public_rects(source)

            result = RedactionEngine().run_job(
                RedactionJob(str(source), str(output), [rect])
            )

            self.assertTrue(result.success, result.error)
            with PdfRenderDocument(output) as document:
                self.assertEqual(document.extract_text(0).strip(), "")
                self.assertIn("PAGINA DOS VECTORIAL", document.extract_text(1))

    @staticmethod
    def _make_pdf(path: Path, rotation: int = 0, pages: int = 1) -> Path:
        canvas = Canvas(str(path), pagesize=(420, 260))
        canvas.setFont("Helvetica", 14)
        canvas.drawString(48, 170, "SECRETO")
        canvas.drawString(180, 110, "PUBLICO")
        canvas.showPage()
        if pages > 1:
            canvas.drawString(48, 170, "PAGINA DOS VECTORIAL")
            canvas.showPage()
        canvas.save()
        if rotation:
            writer = PdfWriter(clone_from=PdfReader(path))
            writer.pages[0].rotate(rotation)
            rotated = path.with_name(f".{path.name}.rotated")
            writer.write(rotated)
            rotated.replace(path)
        return path

    @staticmethod
    def _redaction_and_public_rects(source: Path) -> tuple[RedactionRect, Rect]:
        with PdfRenderDocument(source) as document:
            info = document.page_info(0)
            blocks = document.text_blocks(0)
            secret = next(block for block in blocks if "SECRETO" in block.text)
            public = next(block for block in blocks if "PUBLICO" in block.text)
            secret_rect = Rect(
                secret.left - 2,
                secret.top - 2,
                secret.right + 2,
                secret.bottom + 2,
            )
            return (
                RedactionRect.from_page_rect(
                    0, secret_rect, info.width_pt, info.height_pt
                ),
                Rect(public.left - 2, public.top - 2, public.right + 2, public.bottom + 2),
            )


if __name__ == "__main__":
    unittest.main()
