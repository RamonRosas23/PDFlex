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
from ui.organizador.window import OrganizadorWindow
from ui.organizador.thumb_cache import ThumbnailCache, ThumbnailKey, render_page_thumb


class OrganizadorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_page_grid_rotates_duplicates_and_removes_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf", pages=2)
            window = OrganizadorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._page_grid.add_paths([str(pdf_path)])
                self.assertEqual(window._page_grid.count(), 2)

                window._page_grid.list_widget.setCurrentRow(0)
                window._page_grid.rotate_selected(90)
                self.assertEqual(window._page_grid.page_refs()[0].rotation_deg, 90)

                window._page_grid.duplicate_selected()
                self.assertEqual(window._page_grid.count(), 3)

                window._page_grid.list_widget.clearSelection()
                window._page_grid.list_widget.setCurrentRow(1)
                window._page_grid.remove_selected()
                self.assertEqual(window._page_grid.count(), 2)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_organizer_for_pdfs(self) -> None:
        tool = get_tool("organizador")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Organizador visual")
        self.assertIn(".pdf", tool.input_extensions)

    @staticmethod
    def _make_pdf(path: Path, pages: int) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=300, height=200)
            page.insert_text((36, 72), f"Pagina {index + 1}")
        doc.save(path)
        doc.close()
        return path


class ThumbnailCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_cache_hit_returns_same_pixmap(self) -> None:
        cache = ThumbnailCache(max_size=10)
        key = ThumbnailKey(source_path="/fake.pdf", page_index=0, rotation_deg=0, width=116)
        # Initially empty
        self.assertIsNone(cache.get(key))
        # Create a dummy pixmap
        from PyQt6.QtGui import QPixmap
        pix = QPixmap(116, 150)
        cache.put(key, pix)
        result = cache.get(key)
        self.assertIsNotNone(result)
        self.assertEqual(result.width(), 116)

    def test_render_page_thumb_returns_pixmap_for_valid_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "test.pdf"
            doc = fitz.open()
            page = doc.new_page(width=300, height=200)
            page.insert_text((36, 72), "Hello")
            doc.save(pdf)
            doc.close()

            result = render_page_thumb(str(pdf), 0, 0, 116)
            self.assertIsNotNone(result)
            self.assertGreater(result.width(), 0)


if __name__ == "__main__":
    unittest.main()
