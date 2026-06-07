from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PyQt6.QtWidgets import QApplication

from core.membrete_library import add_letterhead_to_library
from shell.context import ShellContext
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from ui.membretado.window import MembretadoWindow


class MembretadoWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _make_ctx(self) -> ShellContext:
        return ShellContext(
            tray=PdfTray(),
            word_converter=WordToPdfConverter(),
            open_tool=lambda *_: None,
        )

    def test_loads_letterhead_from_library(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.environ["PDFLEX_MEMBRETE_LIBRARY_DIR"] = str(root / "library")
            pdf = self._make_pdf(root / "membrete.pdf")
            entry = add_letterhead_to_library(pdf, label="Oficial")

            window = MembretadoWindow(self._make_ctx())
            try:
                self.assertEqual(window._library_list.count(), 1)
                window._library_list.setCurrentRow(0)
                window._on_use_library_membrete()

                self.assertEqual(window._lh_path, entry.path)
                self.assertEqual(window._lh_source_name, "Oficial")
                self.assertGreater(window._lh_page_w_pt, 0)
                self.assertGreater(window._lh_page_h_pt, 0)
                self.assertTrue(window._membrete_next_btn.isEnabled())
            finally:
                window.deleteLater()
                self.app.processEvents()
                os.environ.pop("PDFLEX_MEMBRETE_LIBRARY_DIR", None)

    def test_continue_stays_disabled_until_letterhead_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = self._make_pdf(Path(tmp) / "membrete.pdf")
            window = MembretadoWindow(self._make_ctx())
            try:
                self.assertFalse(window._membrete_next_btn.isEnabled())

                window._load_membrete(str(pdf), source_name="Membrete")

                self.assertTrue(window._membrete_next_btn.isEnabled())
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_word_letterhead_is_routed_to_conversion(self) -> None:
        window = MembretadoWindow(self._make_ctx())
        captured: list[list[str]] = []
        try:
            window._handle_word_membrete = lambda paths: captured.append(paths)  # type: ignore[method-assign]
            window._load_membrete_input(r"C:\tmp\membrete.docx")

            self.assertEqual(captured, [[r"C:\tmp\membrete.docx"]])
        finally:
            window.deleteLater()
            self.app.processEvents()

    def test_drop_on_letterhead_step_uses_first_pdf_as_letterhead(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            letterhead = self._make_pdf(root / "membrete.pdf")
            document = self._make_pdf(root / "documento.pdf")
            window = MembretadoWindow(self._make_ctx())
            try:
                window._switch_section(0)
                window._add_file_paths_smart([str(letterhead), str(document)])

                self.assertEqual(window._lh_path, str(letterhead))
                self.assertEqual(window._docs_card.paths(), [str(document)])
            finally:
                window.deleteLater()
                self.app.processEvents()

    @staticmethod
    def _make_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=420)
        page.insert_text((36, 36), path.stem)
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
