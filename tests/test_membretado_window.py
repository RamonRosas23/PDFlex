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

    # ------------------------------------------------------------------
    # Helper: espera a que termine la carga asíncrona del membrete
    # ------------------------------------------------------------------
    def _wait_for_membrete_load(self, window: MembretadoWindow, timeout_ms: int = 3000) -> None:
        """Bombea el event loop hasta que _lh_path quede seteado (carga async terminó)
        o hasta que se agote el timeout."""
        import time
        deadline = time.monotonic() + timeout_ms / 1000.0
        # Bombear eventos hasta que el slot _on_membrete_loaded haya corrido
        while window._lh_path is None and time.monotonic() < deadline:
            self.app.processEvents()
        # Una pasada extra para señales de seguimiento
        self.app.processEvents()

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
                self._wait_for_membrete_load(window)

                self.assertEqual(window._lh_path, entry.path)
                self.assertEqual(window._lh_source_name, "Oficial")
                self.assertGreater(window._lh_page_w_pt, 0)
                self.assertGreater(window._lh_page_h_pt, 0)
                self.assertTrue(window._nav_next_btn.isEnabled())
            finally:
                window.deleteLater()
                self.app.processEvents()
                os.environ.pop("PDFLEX_MEMBRETE_LIBRARY_DIR", None)

    def test_library_letterhead_restores_saved_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.environ["PDFLEX_MEMBRETE_LIBRARY_DIR"] = str(root / "library")
            pdf = self._make_pdf(root / "membrete.pdf")
            add_letterhead_to_library(
                pdf,
                label="Config",
                config={
                    "version": 1,
                    "margins": {
                        "top_pt": 111,
                        "bottom_pt": 44,
                        "left_pt": 22,
                        "right_pt": 33,
                    },
                    "scope": {
                        "mode": "exclude",
                        "pages": "1",
                        "preserve_unselected": True,
                    },
                },
            )

            window = MembretadoWindow(self._make_ctx())
            try:
                window._library_list.setCurrentRow(0)
                window._on_use_library_membrete()
                self._wait_for_membrete_load(window)

                self.assertEqual(window._s_top.value(), 111)
                self.assertEqual(window._s_bottom.value(), 44)
                self.assertEqual(window._s_left.value(), 22)
                self.assertEqual(window._s_right.value(), 33)
                self.assertEqual(window._global_scope_combo.currentData(), "exclude")
                self.assertEqual(window._global_pages_edit.text(), "1")
                self.assertTrue(window._preserve_unselected_chk.isChecked())
            finally:
                window.deleteLater()
                self.app.processEvents()
                os.environ.pop("PDFLEX_MEMBRETE_LIBRARY_DIR", None)

    def test_continue_stays_disabled_until_letterhead_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = self._make_pdf(Path(tmp) / "membrete.pdf")
            window = MembretadoWindow(self._make_ctx())
            try:
                self.assertFalse(window._nav_next_btn.isEnabled())

                window._load_membrete(str(pdf), source_name="Membrete")
                self._wait_for_membrete_load(window)

                self.assertTrue(window._nav_next_btn.isEnabled())
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
                self._wait_for_membrete_load(window)

                self.assertEqual(window._lh_path, str(letterhead))
                self.assertEqual(window._docs_card.paths(), [str(document)])
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_build_jobs_uses_scope_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            letterhead = self._make_pdf(root / "membrete.pdf")
            document = self._make_pdf(root / "documento.pdf", pages=4)
            window = MembretadoWindow(self._make_ctx())
            try:
                window._load_membrete(str(letterhead), source_name="Membrete")
                self._wait_for_membrete_load(window)
                window._docs_card.add_paths([str(document)])

                window._global_scope_combo.setCurrentIndex(
                    window._global_scope_combo.findData("include")
                )
                window._global_pages_edit.setText("2-final")

                jobs = window._build_jobs()

                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].pages_to_letterhead, [1, 2, 3])
                self.assertTrue(jobs[0].preserve_unselected)
            finally:
                window.deleteLater()
                self.app.processEvents()

    @staticmethod
    def _make_pdf(path: Path, pages: int = 1) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=300, height=420)
            page.insert_text((36, 36), f"{path.stem} {index + 1}")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
