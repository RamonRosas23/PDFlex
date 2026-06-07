from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw
from PyQt6.QtWidgets import QApplication

from core.background_removal_engine import BackgroundRemovalEngine, BackgroundRemovalJob
from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from ui.common.image_results_viewer import ImageResultsViewer, _transparent_png_on_checkerboard
from ui.quitar_fondo.window import QuitarFondoWindow


class QuitarFondoWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_result_viewer_shows_before_after_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = self._make_logo(root / "logo.png")
            result = BackgroundRemovalEngine().run_batch([
                BackgroundRemovalJob(str(image_path), str(root / "out"), tolerance=35)
            ])[0]

            viewer = ImageResultsViewer("Comparacion", comparison_mode=True)
            try:
                viewer.resize(900, 520)
                viewer.show()
                viewer.set_results([result])
                self.app.processEvents()

                self.assertTrue(viewer.compare_widget.isVisible())
                self.assertFalse(viewer.preview_lbl.isVisible())
                self.assertFalse(viewer.before_preview_lbl.pixmap().isNull())
                self.assertFalse(viewer.after_preview_lbl.pixmap().isNull())
            finally:
                viewer.deleteLater()
                self.app.processEvents()

    def test_checkerboard_preview_for_transparent_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "transparent.png"
            img = Image.new("RGBA", (60, 40), (255, 255, 255, 0))
            draw = ImageDraw.Draw(img)
            draw.rectangle((16, 10, 44, 30), fill=(20, 20, 20, 255))
            img.save(png)

            pixmap = _transparent_png_on_checkerboard(png)

            self.assertFalse(pixmap.isNull())
            self.assertEqual(pixmap.width(), 60)
            self.assertEqual(pixmap.height(), 40)

    def test_window_uses_comparison_viewer_and_builds_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = self._make_logo(Path(tmp) / "logo.png")
            window = QuitarFondoWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window.set_inputs([str(image_path)])
                window._tolerance_slider.setValue(42)

                jobs = window._build_jobs()

                self.assertTrue(window._img_viewer._comparison_mode)
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].image_path, str(image_path))
                self.assertEqual(jobs[0].tolerance, 42)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_background_removal_for_images(self) -> None:
        tool = get_tool("quitar_fondo")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Quitar fondo")
        self.assertIn(".png", tool.input_extensions)

    @staticmethod
    def _make_logo(path: Path) -> Path:
        img = Image.new("RGB", (120, 90), "white")
        draw = ImageDraw.Draw(img)
        draw.ellipse((32, 20, 88, 76), fill=(30, 120, 180))
        img.save(path)
        return path


if __name__ == "__main__":
    unittest.main()
