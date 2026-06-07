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
from ui.reparador.window import ReparadorWindow


class ReparadorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_builds_repair_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._make_pdf(root / "uno.pdf", "Uno")
            second = self._make_pdf(root / "dos.pdf", "Dos")
            window = ReparadorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(first), str(second)])
                window._profile_combo.setCurrentIndex(1)
                window._metadata_chk.setChecked(False)
                window._fallback_chk.setChecked(False)

                self.assertIsNone(window._validate_ready())
                jobs = window._build_jobs()

                self.assertEqual(len(jobs), 2)
                self.assertEqual(jobs[0].pdf_path, str(first))
                self.assertEqual(jobs[1].pdf_path, str(second))
                self.assertFalse(jobs[0].options.use_objstms)
                self.assertFalse(jobs[0].options.preserve_metadata)
                self.assertFalse(jobs[0].options.fallback_rebuild)
                self.assertTrue(jobs[0].output_path.endswith(".pdf"))
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_repair_for_pdfs(self) -> None:
        tool = get_tool("reparador")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Reparar PDF")
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
