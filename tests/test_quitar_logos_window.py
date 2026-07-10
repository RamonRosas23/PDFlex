from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from ui.quitar_logos.window import QuitarLogosWindow


class QuitarLogosWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_accepts_supported_logos_and_builds_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = self._make_pdf(root / "input.pdf")
            png = self._make_logo(root / "logo.png")
            jpg = self._make_logo(root / "logo.jpg")
            webp = self._make_logo(root / "logo.webp")
            ignored = root / "logo.bmp"
            Image.new("RGB", (20, 20), "white").save(ignored)

            window = QuitarLogosWindow(self._context())
            try:
                window.set_inputs([str(pdf_path)])
                window._logo_card.add_paths(
                    [str(png), str(jpg), str(webp), str(ignored)]
                )
                window._similarity_slider.setValue(91)
                window._scope_combo.setCurrentIndex(1)
                self.app.processEvents()

                jobs = window._build_jobs()

                self.assertEqual(window._docs_card.count(), 1)
                self.assertEqual(window._logo_card.count(), 3)
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].options.similarity, 0.91)
                self.assertEqual(jobs[0].options.page_scope, "first")
                self.assertTrue(jobs[0].output_path.endswith(".pdf"))
                self.assertTrue(window._run_btn.isEnabled())
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_custom_range_validation_disables_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = QuitarLogosWindow(self._context())
            try:
                window.set_inputs([str(self._make_pdf(root / "input.pdf"))])
                window._logo_card.add_paths([str(self._make_logo(root / "logo.png"))])
                window._scope_combo.setCurrentIndex(2)
                window._pages_edit.setText("99")
                self.app.processEvents()
                self.assertFalse(window._run_btn.isEnabled())

                window._pages_edit.setText("1")
                self.app.processEvents()
                self.assertTrue(window._run_btn.isEnabled())
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_set_inputs_routes_images_to_logo_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logo = self._make_logo(Path(tmp) / "logo.png")
            window = QuitarLogosWindow(self._context())
            try:
                window.set_inputs([str(logo)])

                self.assertEqual(window._docs_card.count(), 0)
                self.assertEqual(window._logo_card.count(), 1)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_logo_removal(self) -> None:
        tool = get_tool("quitar_logos")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Quitar logos")
        self.assertIn(".pdf", tool.input_extensions)
        self.assertIn(".png", tool.input_extensions)

    @staticmethod
    def _context() -> ShellContext:
        return ShellContext(
            tray=PdfTray(),
            word_converter=WordToPdfConverter(),
            open_tool=lambda *_: None,
        )

    @staticmethod
    def _make_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=360, height=260)
        page.insert_text((36, 72), "Documento")
        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _make_logo(path: Path) -> Path:
        image = Image.new("RGB", (120, 50), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((4, 4, 116, 46), fill=(20, 130, 190))
        draw.ellipse((12, 10, 42, 40), fill=(245, 195, 30))
        if path.suffix.lower() == ".webp":
            image.save(path, format="WEBP", quality=94)
        elif path.suffix.lower() in {".jpg", ".jpeg"}:
            image.save(path, quality=94)
        else:
            image.save(path)
        return path


if __name__ == "__main__":
    unittest.main()
