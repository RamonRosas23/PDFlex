from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz
from docx import Document

from core.pdf_to_word_engine import (
    PdfToWordConfig,
    PdfToWordEngine,
    PdfToWordJob,
    make_pdf_to_word_jobs,
)


class PdfToWordEngineTests(unittest.TestCase):
    def test_native_text_pdf_generates_editable_docx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "entrada.pdf")
            out_dir = root / "out"
            job = PdfToWordJob(
                pdf_path=str(source),
                output_dir=str(out_dir),
                base_name="salida",
                config=PdfToWordConfig(
                    precision_mode="fast",
                    preserve_native_text=True,
                    add_tool_suffix=False,
                ),
            )

            result = PdfToWordEngine().run_job(job)

            self.assertTrue(result.success, result.error)
            self.assertTrue(result.docx_path.endswith("salida.docx"))
            self.assertTrue(Path(result.docx_path).exists())
            self.assertEqual(result.native_pages, 1)

            docx = Document(result.docx_path)
            full_text = "\n".join(p.text for p in docx.paragraphs)
            self.assertIn("Contrato de prueba", full_text)
            self.assertIn("Clausula editable", full_text)

    def test_make_jobs_disambiguates_duplicate_names(self) -> None:
        jobs = make_pdf_to_word_jobs(
            ["C:/tmp/doc.pdf", "D:/otros/doc.pdf"],
            "C:/out",
            PdfToWordConfig(add_tool_suffix=False),
        )

        self.assertEqual(jobs[0].base_name, "doc")
        self.assertEqual(jobs[1].base_name, "doc_2")

    @staticmethod
    def _make_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=420, height=260)
        page.insert_text((36, 72), "Contrato de prueba")
        page.insert_text((36, 106), "Clausula editable")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
