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
from ui.redactor.window import RedactorWindow


class RedactorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_loads_pdf_and_builds_redaction_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            window = RedactorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                window._canvas.add_redaction_norm(0, 0.10, 0.20, 0.35, 0.32)

                jobs = window._build_jobs()

                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].pdf_path, str(pdf_path))
                self.assertEqual(len(jobs[0].rects), 1)
                self.assertTrue(jobs[0].output_path.endswith(".pdf"))
            finally:
                window._canvas.close_doc()
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_redactor_for_pdfs(self) -> None:
        tool = get_tool("redactor")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Redaccion segura")
        self.assertIn(".pdf", tool.input_extensions)

    @staticmethod
    def _make_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((36, 72), "Secreto")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
