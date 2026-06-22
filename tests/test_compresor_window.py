from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PyQt6.QtWidgets import QApplication

from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from core.pdf_compress_engine import CompressJob, CompressResult
from ui.compresor.window import CompresorWindow


class CompresorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_loads_pdf_and_builds_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            window = CompresorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                self.assertEqual(window._docs_card.count(), 1)
                jobs = window._build_jobs()
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].profile_id, "balanced")
                self.assertTrue(jobs[0].output_path.endswith(".pdf"))
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_compressor_for_pdfs(self) -> None:
        tool = get_tool("compresor")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Comprimir PDF")
        self.assertIn(".pdf", tool.input_extensions)

    def test_results_summary_aggregates_savings_and_warnings(self) -> None:
        window = CompresorWindow(
            ShellContext(
                tray=PdfTray(),
                word_converter=WordToPdfConverter(),
                open_tool=lambda *_: None,
            )
        )
        try:
            html = window._results_summary_html([
                CompressResult(
                    job=CompressJob("a.pdf", "a_out.pdf"),
                    success=True,
                    input_bytes=1000,
                    output_bytes=600,
                ),
                CompressResult(
                    job=CompressJob("b.pdf", "b_out.pdf"),
                    success=True,
                    warning="ya estaba optimizado",
                    input_bytes=500,
                    output_bytes=500,
                ),
                CompressResult(
                    job=CompressJob("c.pdf", "c_out.pdf"),
                    success=False,
                    error="fallo",
                ),
            ])

            self.assertIn("2 PDFs optimizados", html)
            self.assertIn("Ahorro: 400 B (26.7%)", html)
            self.assertIn("1 ya estaba optimizado", html)
            self.assertIn("Errores: 1", html)
        finally:
            window.deleteLater()
            self.app.processEvents()

    @staticmethod
    def _make_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((36, 72), "Compresor")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
