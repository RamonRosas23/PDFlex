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
from ui.marca_agua.window import MarcaAguaWindow


class MarcaAguaWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_loads_pdf_and_builds_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            window = MarcaAguaWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                window._text_edit.setText("RECIBIDO")
                window._rotation_spin.setValue(0)
                window._scope_combo.setCurrentIndex(1)

                jobs = window._build_jobs()

                self.assertEqual(window._docs_card.count(), 1)
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].options.mode, "text")
                self.assertEqual(jobs[0].options.text, "RECIBIDO")
                self.assertEqual(jobs[0].options.page_scope, "first")
                self.assertTrue(jobs[0].output_path.endswith(".pdf"))
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_window_generates_preview_pixmap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            window = MarcaAguaWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                window._rotation_spin.setValue(0)
                window._refresh_preview()

                # Preview now runs in a QThread — wait up to 5 s for it to finish
                import time
                deadline = time.time() + 5.0
                while (
                    window._preview_thread is not None
                    and window._preview_thread.isRunning()
                    and time.time() < deadline
                ):
                    self.app.processEvents()
                    time.sleep(0.05)
                # Drain queued signals (QueuedConnection from worker thread → main thread)
                self.app.processEvents()

                pixmap = window._preview_lbl.pixmap()
                self.assertIsNotNone(pixmap)
                self.assertFalse(pixmap.isNull())
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_run_button_follows_stamp_and_page_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = self._make_pdf(root / "input.pdf")
            image_path = root / "logo.png"
            from PIL import Image
            Image.new("RGB", (32, 24), "white").save(image_path)

            window = MarcaAguaWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                self.assertFalse(window._run_btn.isEnabled())

                window._docs_card.add_paths([str(pdf_path)])
                self.app.processEvents()
                self.assertTrue(window._run_btn.isEnabled())

                window._mode_combo.setCurrentIndex(1)
                self.app.processEvents()
                self.assertFalse(window._run_btn.isEnabled())

                window._image_edit.setText(str(image_path))
                self.app.processEvents()
                self.assertTrue(window._run_btn.isEnabled())

                window._mode_combo.setCurrentIndex(0)
                window._scope_combo.setCurrentIndex(3)
                window._pages_edit.setText("99")
                self.app.processEvents()
                self.assertFalse(window._run_btn.isEnabled())

                window._pages_edit.setText("1")
                self.app.processEvents()
                self.assertTrue(window._run_btn.isEnabled())
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_watermark_for_pdfs(self) -> None:
        tool = get_tool("marca_agua")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Marca de agua")
        self.assertIn(".pdf", tool.input_extensions)

    @staticmethod
    def _make_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((36, 72), "Marca de agua")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
