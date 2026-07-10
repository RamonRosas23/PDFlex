from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtWidgets import QApplication

from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from ui.pdf_to_word.window import PdfToWordWindow


class PdfToWordWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_loads_pdf_and_builds_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "entrada.pdf")
            window = PdfToWordWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                window._precision_combo.setCurrentIndex(2)
                window._dpi_combo.setCurrentIndex(2)
                window._native_chk.setChecked(True)

                jobs = window._build_jobs()

                self.assertEqual(window._docs_card.count(), 1)
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].pdf_path, str(pdf_path))
                self.assertEqual(jobs[0].config.precision_mode, "fast")
                self.assertEqual(jobs[0].config.dpi, 240)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_pdf_to_word_for_pdfs(self) -> None:
        tool = get_tool("pdf_to_word")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "PDF a Word")
        self.assertIn(".pdf", tool.input_extensions)

    def test_input_stats_update_summary_and_detect_invalid_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = self._make_pdf(root / "entrada.pdf", pages=2)
            bad_pdf = root / "roto.pdf"
            bad_pdf.write_text("no soy un pdf", encoding="utf-8")

            window = PdfToWordWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                self.app.processEvents()

                self.assertIn("2 paginas", window._docs_summary_lbl.text())
                pages, total_size, error = window._input_stats([str(pdf_path)])
                self.assertEqual(pages, 2)
                self.assertGreater(total_size, 0)
                self.assertEqual(error, "")

                _, _, error = window._input_stats([str(bad_pdf)])
                self.assertIn("roto.pdf", error)
            finally:
                window.deleteLater()
                self.app.processEvents()

    @staticmethod
    def _make_pdf(path: Path, pages: int = 1) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=300, height=200)
            page.insert_text((36, 72), f"PDF a Word {index + 1}")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
