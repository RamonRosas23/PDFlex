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

    def test_selection_estimate_and_range_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = self._make_pdf(Path(tmp) / "doc.pdf", pages=3)
            window = PdfToImgsWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window.set_inputs([str(pdf)])
                window._range_edit.setText("2-final")

                cfg = window._read_config()
                estimate, error = window._selection_estimate(cfg)

                self.assertEqual(estimate, 2)
                self.assertEqual(error, "")
                self.assertIsNone(window._validate_ready(cfg))

                window._panoramic_chk.setChecked(True)
                panoramic_cfg = window._read_config()
                estimate, error = window._selection_estimate(panoramic_cfg)

                self.assertEqual(estimate, 1)
                self.assertEqual(error, "")

                window._range_edit.setText("10")
                invalid_cfg = window._read_config()

                self.assertIn("rango", window._validate_ready(invalid_cfg).lower())
                self.assertIn("doc.pdf", window._selection_estimate(invalid_cfg)[1])
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
    def _make_pdf(path: Path, pages: int = 1) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=200, height=260)
            page.insert_text((36, 72), f"Pagina {index + 1}")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
