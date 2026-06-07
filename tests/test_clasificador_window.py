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
from ui.clasificador.window import ClasificadorWindow


class ClasificadorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_loads_pdfs_and_builds_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            window = ClasificadorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                window._template_edit.setText("{tipo}_{original}")
                window._ocr_chk.setChecked(False)

                jobs = window._build_jobs()

                self.assertEqual(window._docs_card.count(), 1)
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].pdf_path, str(pdf_path))
                self.assertEqual(jobs[0].config.template, "{tipo}_{original}")
                self.assertFalse(jobs[0].config.use_ocr_fallback)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_classifier_for_pdfs(self) -> None:
        tool = get_tool("clasificador")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Clasificador OCR")
        self.assertIn(".pdf", tool.input_extensions)

    @staticmethod
    def _make_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((36, 72), "Factura Folio: F-1")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
