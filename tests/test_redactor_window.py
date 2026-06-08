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

    def test_redaction_controls_follow_canvas_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf", pages=2)
            window = RedactorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                self.assertFalse(window._prev_page_btn.isEnabled())
                self.assertFalse(window._next_page_btn.isEnabled())
                self.assertFalse(window._undo_btn.isEnabled())
                self.assertFalse(window._clear_page_btn.isEnabled())
                self.assertFalse(window._clear_all_btn.isEnabled())

                window._docs_card.add_paths([str(pdf_path)])
                self.app.processEvents()

                self.assertFalse(window._prev_page_btn.isEnabled())
                self.assertTrue(window._next_page_btn.isEnabled())
                self.assertFalse(window._undo_btn.isEnabled())
                self.assertFalse(window._clear_page_btn.isEnabled())
                self.assertFalse(window._clear_all_btn.isEnabled())
                self.assertFalse(window._run_btn.isEnabled())

                window._canvas.add_redaction_norm(0, 0.10, 0.20, 0.35, 0.32)
                self.app.processEvents()

                self.assertTrue(window._undo_btn.isEnabled())
                self.assertTrue(window._clear_page_btn.isEnabled())
                self.assertTrue(window._clear_all_btn.isEnabled())
                self.assertTrue(window._run_btn.isEnabled())

                window._canvas.next_page()
                self.app.processEvents()

                self.assertTrue(window._prev_page_btn.isEnabled())
                self.assertFalse(window._next_page_btn.isEnabled())
                self.assertFalse(window._undo_btn.isEnabled())
                self.assertFalse(window._clear_page_btn.isEnabled())
                self.assertTrue(window._clear_all_btn.isEnabled())
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
    def _make_pdf(path: Path, pages: int = 1) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=300, height=200)
            page.insert_text((36, 72), f"Secreto {index + 1}")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
