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
from ui.unir.window import UnirWindow


class UnirWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _make_ctx(self, opened: list | None = None) -> ShellContext:
        return ShellContext(
            tray=PdfTray(),
            word_converter=WordToPdfConverter(),
            open_tool=lambda tool_id, paths=None: opened.append((tool_id, paths)) if opened is not None else None,
        )

    def test_loaded_pdfs_update_merge_order_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._make_pdf(root / "a.pdf", "A")
            second = self._make_pdf(root / "b.pdf", "B")
            window = UnirWindow(self._make_ctx())
            try:
                window.set_inputs([str(first), str(second)])

                self.assertEqual(window._pdf_paths, [str(first), str(second)])
                self.assertEqual(window._docs_card.paths(), [str(first), str(second)])
                self.assertIn("2 documentos", window._docs_summary_lbl.text())
                self.assertIn("páginas", window._docs_summary_lbl.text())
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_documents_card_reorder_updates_merge_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._make_pdf(root / "a.pdf", "A")
            second = self._make_pdf(root / "b.pdf", "B")
            window = UnirWindow(self._make_ctx())
            try:
                window.set_inputs([str(first), str(second)])
                window._docs_card.reorder_paths([str(second), str(first)])

                self.assertEqual(window._pdf_paths, [str(second), str(first)])
                self.assertEqual(window._docs_card.paths(), [str(second), str(first)])
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_merge_for_pdfs(self) -> None:
        tool = get_tool("unir")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Unir PDFs")
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
