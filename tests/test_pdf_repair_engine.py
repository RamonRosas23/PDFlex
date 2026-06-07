from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz

from core.pdf_repair_engine import (
    PdfRepairEngine,
    PdfRepairJob,
    PdfRepairOptions,
)


class PdfRepairEngineTests(unittest.TestCase):
    def test_normalizes_pdf_without_changing_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "entrada.pdf", ["Uno", "Dos"])
            original_bytes = source.read_bytes()
            output = root / "normalizado.pdf"

            result = PdfRepairEngine().run_job(
                PdfRepairJob(str(source), str(output), PdfRepairOptions())
            )

            self.assertTrue(result.success, result.error)
            self.assertTrue(output.exists())
            self.assertEqual(result.page_count, 2)
            self.assertGreater(result.output_size, 0)
            self.assertEqual(source.read_bytes(), original_bytes)

            doc = fitz.open(str(output))
            try:
                self.assertEqual(doc.page_count, 2)
                self.assertIn("Uno", doc[0].get_text("text"))
            finally:
                doc.close()

    def test_repairs_pdf_with_broken_startxref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "entrada.pdf", ["Documento reparable"])
            broken = root / "roto.pdf"
            broken.write_bytes(source.read_bytes().replace(b"startxref", b"startxxxxx"))
            output = root / "reparado.pdf"

            result = PdfRepairEngine().run_job(
                PdfRepairJob(str(broken), str(output), PdfRepairOptions())
            )

            self.assertTrue(result.success, result.error)
            self.assertTrue(result.repaired_on_open)
            self.assertTrue(output.exists())

            doc = fitz.open(str(output))
            try:
                self.assertEqual(doc.page_count, 1)
                self.assertIn("Documento reparable", doc[0].get_text("text"))
            finally:
                doc.close()

    def test_rejects_invalid_pdf_with_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            invalid = root / "invalido.pdf"
            invalid.write_text("esto no es un pdf", encoding="utf-8")

            result = PdfRepairEngine().run_job(
                PdfRepairJob(str(invalid), str(root / "out.pdf"))
            )

            self.assertFalse(result.success)
            self.assertTrue(result.error)

    def test_rejects_same_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = self._make_pdf(Path(tmp) / "entrada.pdf", ["Contenido"])

            result = PdfRepairEngine().run_job(
                PdfRepairJob(str(source), str(source))
            )

            self.assertFalse(result.success)
            self.assertIn("mismo archivo", result.error.lower())

    @staticmethod
    def _make_pdf(path: Path, pages: list[str]) -> Path:
        doc = fitz.open()
        for text in pages:
            page = doc.new_page(width=300, height=180)
            page.insert_text((36, 72), text)
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
