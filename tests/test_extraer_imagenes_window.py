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
from ui.extraer_imagenes.window import ExtraerImagenesWindow


class ExtraerImagenesWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_loads_pdf_and_builds_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "entrada.pdf")
            window = ExtraerImagenesWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                window._dedupe_chk.setChecked(False)
                window._min_width_spin.setValue(10)
                window._min_height_spin.setValue(12)

                jobs = window._build_jobs()
                config = window._build_config()

                self.assertEqual(window._docs_card.count(), 1)
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].pdf_path, str(pdf_path))
                self.assertFalse(config.deduplicate)
                self.assertEqual(config.min_width, 10)
                self.assertEqual(config.min_height, 12)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_extractor_for_pdfs(self) -> None:
        tool = get_tool("extraer_imagenes")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Extraer imágenes")
        self.assertIn(".pdf", tool.input_extensions)

    @staticmethod
    def _make_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((36, 72), "Extraer imagenes")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
