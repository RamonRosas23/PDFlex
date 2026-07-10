from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtWidgets import QApplication

from core.split_ranges import (
    SplitRange,
    generate_fixed_size_ranges,
    generate_missing_ranges,
    parse_range_list_text,
)
from shell.context import ShellContext
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from ui.separador.window import SeparadorWindow


class SeparadorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_range_list_parser_supports_visual_separator_shortcuts(self) -> None:
        self.assertEqual(
            parse_range_list_text("1-2, 4, final", total_pages=6),
            [(1, 2), (4, 4), (6, 6)],
        )
        self.assertEqual(
            parse_range_list_text("1 - 2 4-5", total_pages=6),
            [(1, 2), (4, 5)],
        )
        self.assertEqual(
            parse_range_list_text("pares", total_pages=6),
            [(2, 2), (4, 4), (6, 6)],
        )
        self.assertEqual(
            parse_range_list_text("impares", total_pages=5),
            [(1, 1), (3, 3), (5, 5)],
        )

    def test_fast_generators_cover_fixed_size_and_missing_pages(self) -> None:
        fixed = generate_fixed_size_ranges(total_pages=7, chunk_size=3)
        self.assertEqual(
            [(rng.start, rng.end, rng.name) for rng in fixed],
            [(1, 3, "bloque-01"), (4, 6, "bloque-02"), (7, 7, "bloque-03")],
        )

        missing = generate_missing_ranges(
            [SplitRange(2, 3, "a"), SplitRange(6, 6, "b")],
            total_pages=7,
        )
        self.assertEqual(
            [(rng.start, rng.end, rng.name) for rng in missing],
            [
                (1, 1, "faltante-001"),
                (4, 5, "faltante-004-005"),
                (7, 7, "faltante-007"),
            ],
        )

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

    def test_preview_panel_loads_document_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "preview.pdf", pages=3)
            window = self._make_window()
            try:
                window._load_pdf(str(pdf_path))
                self.app.processEvents()

                self.assertEqual(window._preview_panel._total_pages, 3)
                self.assertEqual(window._preview_panel._page_list.count(), 3)
                pixmap = window._preview_panel._canvas.pixmap()
                self.assertIsNotNone(pixmap)
                self.assertFalse(pixmap.isNull())
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_add_range_accepts_multiple_ranges_and_updates_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "multi.pdf", pages=5)
            window = self._make_window()
            try:
                window._load_pdf(str(pdf_path))
                window._range_input.setText("1-2, 4-final")
                window._name_input.setText("corte")
                window._on_add_range()
                self.app.processEvents()

                self.assertEqual(
                    [(rng.start, rng.end, rng.name) for rng in window._ranges],
                    [(1, 2, "corte-01"), (4, 5, "corte-02")],
                )
                self.assertEqual(len(window._preview_panel._ranges), 2)
                self.assertEqual(window._selected_range_idx, 0)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_visible_preview_page_can_be_added_as_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "visible.pdf", pages=4)
            window = self._make_window()
            try:
                window._load_pdf(str(pdf_path))
                window._preview_panel.set_page(3)
                self.app.processEvents()

                window._on_add_visible_page(window._preview_panel.current_page_number)
                self.app.processEvents()

                self.assertEqual(
                    [(rng.start, rng.end, rng.name) for rng in window._ranges],
                    [(3, 3, "pag-003")],
                )
                self.assertEqual(window._selected_range_idx, 0)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_visual_separator_does_not_force_a_giant_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "responsive.pdf", pages=4)
            window = self._make_window()
            try:
                window.resize(772, 500)
                window._switch_section(1)
                window._load_pdf(str(pdf_path))
                window._ranges = [
                    SplitRange(1, 2, "corte-inicial"),
                    SplitRange(3, 4, "nombre-largo-para-revisar-layout"),
                ]
                window._rebuild_ranges_ui()
                window.show()
                self.app.processEvents()

                self.assertLessEqual(window.minimumSizeHint().width(), 900)
                self.assertLessEqual(window.minimumSizeHint().height(), 650)
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
    def _make_window() -> SeparadorWindow:
        return SeparadorWindow(
            ShellContext(
                tray=PdfTray(),
                word_converter=WordToPdfConverter(),
                open_tool=lambda *_: None,
            )
        )

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
