from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PyQt6.QtWidgets import QApplication

from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from ui.subrayador.window import SubrayadorWindow


class SubrayadorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_loads_pdf_and_builds_highlight_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            window = SubrayadorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                window._canvas.add_highlight_norm(0, 0.10, 0.25, 0.65, 0.34)
                window._profile_combo.setCurrentIndex(window._profile_combo.findData("seco_textura"))

                jobs = window._build_jobs()

                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].pdf_path, str(pdf_path))
                self.assertEqual(len(jobs[0].marks), 1)
                self.assertEqual(jobs[0].options.profile_id, "seco_textura")
                self.assertGreater(jobs[0].options.roughness, 0.60)
                self.assertTrue(jobs[0].output_path.endswith(".pdf"))
            finally:
                window._canvas.close_doc()
                window.deleteLater()
                self.app.processEvents()

    def test_highlight_controls_follow_canvas_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf", pages=2)
            window = SubrayadorWindow(
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
                self.assertFalse(window._run_btn.isEnabled())

                window._canvas.add_highlight_norm(0, 0.10, 0.25, 0.65, 0.34)
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

    def test_controls_panel_scrolls_in_short_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            window = SubrayadorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window.resize(900, 420)
                window.show()
                window._docs_card.add_paths([str(pdf_path)])
                window._switch_section(1)
                self.app.processEvents()

                self.assertLessEqual(window.height(), 460)
                self.assertGreater(window._controls_scroll.verticalScrollBar().maximum(), 0)
            finally:
                window._canvas.close_doc()
                window.deleteLater()
                self.app.processEvents()

    def test_page_viewer_fits_page_and_can_scroll_at_fit_width(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "tall.pdf", size=(260, 900))
            window = SubrayadorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window.resize(1100, 620)
                window.show()
                window._docs_card.add_paths([str(pdf_path)])
                window._switch_section(1)
                self._wait_for_canvas_render(window)

                viewport = window._page_scroll.viewport().size()
                self.assertLessEqual(window._canvas.width(), viewport.width())
                self.assertLessEqual(window._canvas.height(), viewport.height())
                self.assertEqual(window._canvas.fit_mode(), "page")

                window._fit_width()
                self.app.processEvents()

                self.assertEqual(window._canvas.fit_mode(), "width")
                self.assertGreater(window._page_scroll.verticalScrollBar().maximum(), 0)

                window._set_canvas_mode("pan")
                self.assertEqual(window._canvas.interaction_mode(), "pan")
            finally:
                window._canvas.close_doc()
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_subrayador_for_pdfs(self) -> None:
        tool = get_tool("subrayador")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Subrayador realista")
        self.assertIn(".pdf", tool.input_extensions)

    def _wait_for_canvas_render(self, window: SubrayadorWindow) -> None:
        deadline = time.time() + 5.0
        while window._canvas._base_pixmap.isNull() and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertFalse(window._canvas._base_pixmap.isNull())

    @staticmethod
    def _make_pdf(path: Path, pages: int = 1, size: tuple[int, int] = (300, 200)) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=size[0], height=size[1])
            page.insert_text((36, 72), f"Texto {index + 1}", fontsize=16)
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
