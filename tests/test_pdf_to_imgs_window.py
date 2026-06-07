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
from ui.pdf_to_imgs.window import PdfToImgsWindow


class PdfToImgsWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_reads_presets_and_page_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = self._make_pdf(Path(tmp) / "doc.pdf")
            window = PdfToImgsWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window.set_inputs([str(pdf)])
                window._preset_combo.setCurrentText("Correo - JPG 120 DPI")
                window._range_edit.setText("1-final")

                cfg = window._read_config()
                jobs = window._build_jobs(cfg)

                self.assertEqual(cfg.format, "jpg")
                self.assertEqual(cfg.dpi, 120)
                self.assertEqual(cfg.jpg_quality, 82)
                self.assertEqual(cfg.page_range, "1-final")
                self.assertFalse(cfg.panoramic)
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].pdf_path, str(pdf))
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_panoramic_preset_sets_mode(self) -> None:
        window = PdfToImgsWindow(
            ShellContext(
                tray=PdfTray(),
                word_converter=WordToPdfConverter(),
                open_tool=lambda *_: None,
            )
        )
        try:
            window._preset_combo.setCurrentText("Panorámica - JPG 150 DPI")
            cfg = window._read_config()

            self.assertTrue(cfg.panoramic)
            self.assertEqual(cfg.format, "jpg")
            self.assertEqual(cfg.dpi, 150)
        finally:
            window.deleteLater()
            self.app.processEvents()

    def test_tool_registry_exposes_pdf_to_images_for_pdfs(self) -> None:
        tool = get_tool("pdf_to_imgs")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "PDF a Imágenes")
        self.assertIn(".pdf", tool.input_extensions)

    @staticmethod
    def _make_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=200, height=260)
        page.insert_text((36, 72), "Pagina 1")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
