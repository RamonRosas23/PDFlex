from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz

from core.pdf_compare_engine import (
    PdfCompareEngine,
    PdfCompareJob,
    PdfCompareOptions,
)


class PdfCompareEngineTests(unittest.TestCase):
    def test_detects_visual_and_text_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._make_pdf(root / "base.pdf", ["Contrato version A"])
            revised = self._make_pdf(root / "revisado.pdf", ["Contrato version B"])
            output = root / "reporte.pdf"

            result = PdfCompareEngine().run_job(
                PdfCompareJob(
                    base_pdf=str(base),
                    compare_pdf=str(revised),
                    output_path=str(output),
                    options=PdfCompareOptions(dpi=90, pixel_threshold=12, min_change_ratio=0.0001),
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertTrue(output.exists())
            self.assertEqual(result.total_pages, 1)
            self.assertEqual(result.changed_pages, 1)
            self.assertEqual(result.text_changed_pages, 1)
            self.assertEqual(result.visual_changed_pages, 1)
            self.assertIn("version A", result.page_results[0].text_delta)
            self.assertIn("version B", result.page_results[0].text_delta)

            report = fitz.open(str(output))
            try:
                self.assertGreaterEqual(report.page_count, 2)
                self.assertIn("Reporte de comparacion PDF", report[0].get_text("text"))
            finally:
                report.close()

    def test_identical_pdfs_create_clean_report_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._make_pdf(root / "base.pdf", ["Mismo contenido"])
            revised = self._make_pdf(root / "revisado.pdf", ["Mismo contenido"])
            output = root / "reporte.pdf"

            result = PdfCompareEngine().run_job(
                PdfCompareJob(str(base), str(revised), str(output))
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.changed_pages, 0)
            self.assertEqual(result.visual_changed_pages, 0)
            self.assertEqual(result.text_changed_pages, 0)

            report = fitz.open(str(output))
            try:
                self.assertEqual(report.page_count, 1)
                self.assertIn("Sin diferencias", report[0].get_text("text"))
            finally:
                report.close()

    def test_detects_added_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._make_pdf(root / "base.pdf", ["Pagina uno"])
            revised = self._make_pdf(root / "revisado.pdf", ["Pagina uno", "Pagina dos"])
            output = root / "reporte.pdf"

            result = PdfCompareEngine().run_job(
                PdfCompareJob(str(base), str(revised), str(output))
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.total_pages, 2)
            self.assertEqual(result.changed_pages, 1)
            self.assertEqual(result.added_pages, 1)
            self.assertEqual(result.page_results[1].status_label, "Agregada")

    def test_missing_input_returns_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            revised = self._make_pdf(root / "revisado.pdf", ["Documento"])

            result = PdfCompareEngine().run_job(
                PdfCompareJob(str(root / "no_existe.pdf"), str(revised), str(root / "out.pdf"))
            )

            self.assertFalse(result.success)
            self.assertIn("base", result.error.lower())

    @staticmethod
    def _make_pdf(path: Path, pages: list[str]) -> Path:
        doc = fitz.open()
        for text in pages:
            page = doc.new_page(width=360, height=220)
            page.insert_text((36, 74), text, fontsize=18)
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
