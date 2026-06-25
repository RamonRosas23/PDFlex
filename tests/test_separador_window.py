from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PyQt6.QtWidgets import QApplication

from core.split_ranges import SplitRange
from shell.context import ShellContext
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from ui.separador.window import SeparadorWindow


class SeparadorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_run_button_requires_document_and_valid_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "entrada.pdf", pages=2)
            window = SeparadorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                self.assertFalse(window._run_btn.isEnabled())

                window._load_pdf(str(pdf_path))
                self.app.processEvents()
                self.assertFalse(window._run_btn.isEnabled())

                window._ranges = [SplitRange(1, 1, "parte-01")]
                window._rebuild_ranges_ui()
                self.app.processEvents()
                self.assertTrue(window._run_btn.isEnabled())

                window._ranges = [SplitRange(2, 4, "invalido")]
                window._rebuild_ranges_ui()
                self.app.processEvents()
                self.assertFalse(window._run_btn.isEnabled())
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tray_selection_loads_the_single_work_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "desde_bandeja.pdf", pages=2)
            ctx = ShellContext(
                tray=PdfTray(),
                word_converter=WordToPdfConverter(),
                open_tool=lambda *_: None,
            )
            ctx.tray.add_items([str(pdf_path)], "Compresor")
            window = SeparadorWindow(ctx)
            try:
                window._document_workspace._tray_list.item(0).setSelected(True)
                window._document_workspace._add_selected_to_work()
                self.app.processEvents()

                self.assertEqual(window._document_workspace.paths(), [str(pdf_path)])
                self.assertEqual(window._pdf_path, str(pdf_path))
                self.assertEqual(ctx.tray.items[0].status, "in_work")
            finally:
                window.deleteLater()
                self.app.processEvents()

    @staticmethod
    def _make_pdf(path: Path, pages: int = 1) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=300, height=200)
            page.insert_text((36, 72), f"Separador {index + 1}")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
