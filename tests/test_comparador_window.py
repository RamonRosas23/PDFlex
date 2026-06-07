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
from ui.comparador.window import ComparadorWindow


class ComparadorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_builds_compare_job_from_two_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._make_pdf(root / "base.pdf", "Original")
            revised = self._make_pdf(root / "revisado.pdf", "Revisado")
            window = ComparadorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(base), str(revised)])
                window._precision_combo.setCurrentIndex(2)
                window._include_equal_chk.setChecked(True)

                self.assertIsNone(window._validate_ready())
                jobs = window._build_jobs()

                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].base_pdf, str(base))
                self.assertEqual(jobs[0].compare_pdf, str(revised))
                self.assertEqual(jobs[0].options.dpi, 150)
                self.assertTrue(jobs[0].options.compare_text)
                self.assertTrue(jobs[0].options.include_equal_pages)
                self.assertTrue(jobs[0].output_path.endswith(".pdf"))
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_comparator_for_pdfs(self) -> None:
        tool = get_tool("comparador")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Comparar PDFs")
        self.assertIn(".pdf", tool.input_extensions)

    @staticmethod
    def _make_pdf(path: Path, text: str) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=180)
        page.insert_text((36, 72), text)
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
