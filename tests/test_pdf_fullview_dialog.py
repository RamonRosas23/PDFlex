"""Tests para PdfFullViewDialog."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PyQt6.QtWidgets import QApplication

from ui.common.pdf_fullview_dialog import PdfFullViewDialog, ZOOM_LEVELS


def _make_pdf(path: Path, pages: int = 3) -> Path:
    """Crea un PDF mínimo con N páginas para tests."""
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Página {i + 1}")
    doc.save(str(path))
    doc.close()
    return path


def _ok_result(path: str) -> SimpleNamespace:
    return SimpleNamespace(output_path=path, success=True, error="")


def _err_result() -> SimpleNamespace:
    return SimpleNamespace(output_path="", success=False, error="Fallo simulado")


class TestPdfFullViewDialogSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pdf1 = str(_make_pdf(Path(cls.tmp.name) / "a.pdf", pages=5))
        cls.pdf2 = str(_make_pdf(Path(cls.tmp.name) / "b.pdf", pages=2))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def _make_dlg(self, results=None, idx=0) -> PdfFullViewDialog:
        if results is None:
            results = [_ok_result(self.pdf1)]
        dlg = PdfFullViewDialog(None, results=results, current_index=idx)
        self.app.processEvents()
        return dlg

    # ── Smoke ────────────────────────────────────────────────────────────────

    def test_instantiates_without_error(self) -> None:
        dlg = self._make_dlg()
        self.assertIsNotNone(dlg)
        dlg.close()
        self.app.processEvents()

    def test_has_all_toolbar_controls(self) -> None:
        dlg = self._make_dlg()
        self.app.processEvents()
        self.assertTrue(hasattr(dlg, "_page_spin"))
        self.assertTrue(hasattr(dlg, "_prev_page_btn"))
        self.assertTrue(hasattr(dlg, "_next_page_btn"))
        self.assertTrue(hasattr(dlg, "_prev_doc_btn"))
        self.assertTrue(hasattr(dlg, "_next_doc_btn"))
        self.assertTrue(hasattr(dlg, "_zoom_out_btn"))
        self.assertTrue(hasattr(dlg, "_zoom_in_btn"))
        self.assertTrue(hasattr(dlg, "_toggle_btn"))
        dlg.close()
        self.app.processEvents()

    def test_doc_nav_label_shows_correct_index(self) -> None:
        results = [_ok_result(self.pdf1), _ok_result(self.pdf2)]
        dlg = self._make_dlg(results, idx=0)
        self.app.processEvents()
        self.assertIn("1", dlg._doc_nav_lbl.text())
        self.assertIn("2", dlg._doc_nav_lbl.text())
        dlg.close()
        self.app.processEvents()

    # ── Navigation ───────────────────────────────────────────────────────────

    def test_navigate_doc_forward(self) -> None:
        results = [_ok_result(self.pdf1), _ok_result(self.pdf2)]
        dlg = self._make_dlg(results, idx=0)
        self.app.processEvents()
        self.assertEqual(dlg._current_doc_idx, 0)
        dlg._navigate_doc(1)
        self.app.processEvents()
        self.assertEqual(dlg._current_doc_idx, 1)
        dlg.close()
        self.app.processEvents()

    def test_navigate_doc_backward(self) -> None:
        results = [_ok_result(self.pdf1), _ok_result(self.pdf2)]
        dlg = self._make_dlg(results, idx=1)
        self.app.processEvents()
        self.assertEqual(dlg._current_doc_idx, 1)
        dlg._navigate_doc(-1)
        self.app.processEvents()
        self.assertEqual(dlg._current_doc_idx, 0)
        dlg.close()
        self.app.processEvents()

    def test_navigate_doc_clamps_at_bounds(self) -> None:
        results = [_ok_result(self.pdf1)]
        dlg = self._make_dlg(results, idx=0)
        self.app.processEvents()
        dlg._navigate_doc(-1)   # no debe moverse
        self.assertEqual(dlg._current_doc_idx, 0)
        dlg._navigate_doc(1)    # no debe moverse
        self.assertEqual(dlg._current_doc_idx, 0)
        dlg.close()
        self.app.processEvents()

    def test_prev_doc_btn_disabled_at_first(self) -> None:
        results = [_ok_result(self.pdf1), _ok_result(self.pdf2)]
        dlg = self._make_dlg(results, idx=0)
        self.app.processEvents()
        self.assertFalse(dlg._prev_doc_btn.isEnabled())
        self.assertTrue(dlg._next_doc_btn.isEnabled())
        dlg.close()
        self.app.processEvents()

    def test_next_doc_btn_disabled_at_last(self) -> None:
        results = [_ok_result(self.pdf1), _ok_result(self.pdf2)]
        dlg = self._make_dlg(results, idx=1)
        self.app.processEvents()
        self.assertTrue(dlg._prev_doc_btn.isEnabled())
        self.assertFalse(dlg._next_doc_btn.isEnabled())
        dlg.close()
        self.app.processEvents()

    # ── Page navigation ──────────────────────────────────────────────────────

    def test_page_spin_range_matches_doc_pages(self) -> None:
        dlg = self._make_dlg([_ok_result(self.pdf1)])  # 5 páginas
        self.app.processEvents()
        self.assertEqual(dlg._page_spin.maximum(), 5)
        dlg.close()
        self.app.processEvents()

    def test_prev_page_decrements_current_page(self) -> None:
        dlg = self._make_dlg([_ok_result(self.pdf1)])
        self.app.processEvents()
        # Ir a página 3 primero
        dlg._current_page = 2
        dlg._prev_page()
        self.app.processEvents()
        self.assertEqual(dlg._current_page, 1)
        dlg.close()
        self.app.processEvents()

    def test_next_page_increments_current_page(self) -> None:
        dlg = self._make_dlg([_ok_result(self.pdf1)])
        self.app.processEvents()
        dlg._current_page = 0
        dlg._next_page()
        self.app.processEvents()
        self.assertEqual(dlg._current_page, 1)
        dlg.close()
        self.app.processEvents()

    def test_on_page_jump_clamps(self) -> None:
        dlg = self._make_dlg([_ok_result(self.pdf1)])  # 5 páginas
        self.app.processEvents()
        dlg._page_spin.setValue(999)
        dlg._on_page_jump()
        self.app.processEvents()
        self.assertEqual(dlg._current_page, 4)  # índice 0-based de página 5
        dlg.close()
        self.app.processEvents()

    # ── Zoom ─────────────────────────────────────────────────────────────────

    def test_zoom_in_increments_index(self) -> None:
        dlg = self._make_dlg()
        self.app.processEvents()
        initial = dlg._zoom_index
        dlg._zoom_in()
        self.app.processEvents()
        self.assertEqual(dlg._zoom_index, initial + 1)
        dlg.close()
        self.app.processEvents()

    def test_zoom_out_decrements_index(self) -> None:
        dlg = self._make_dlg()
        self.app.processEvents()
        dlg._zoom_index = 5  # en el medio para tener espacio
        dlg._zoom_out()
        self.app.processEvents()
        self.assertEqual(dlg._zoom_index, 4)
        dlg.close()
        self.app.processEvents()

    def test_zoom_clamps_at_boundaries(self) -> None:
        dlg = self._make_dlg()
        self.app.processEvents()
        dlg._zoom_index = 0
        dlg._zoom_out()
        self.assertEqual(dlg._zoom_index, 0)  # no baja de 0
        dlg._zoom_index = len(ZOOM_LEVELS) - 1
        dlg._zoom_in()
        self.assertEqual(dlg._zoom_index, len(ZOOM_LEVELS) - 1)  # no sube del máximo
        dlg.close()
        self.app.processEvents()

    def test_fit_width_resets_fit_mode(self) -> None:
        dlg = self._make_dlg()
        self.app.processEvents()
        dlg._fit_mode = "manual"
        dlg._fit_width()
        self.app.processEvents()
        self.assertEqual(dlg._fit_mode, "width")
        dlg.close()
        self.app.processEvents()

    # ── Error result ─────────────────────────────────────────────────────────

    def test_error_result_does_not_crash(self) -> None:
        dlg = self._make_dlg([_err_result()])
        self.app.processEvents()
        # No debe haber doc cargado
        self.assertIsNone(dlg._current_doc)
        dlg.close()
        self.app.processEvents()

    def test_mixed_results_loads_ok_doc(self) -> None:
        results = [_err_result(), _ok_result(self.pdf2)]
        dlg = self._make_dlg(results, idx=1)
        self.app.processEvents()
        self.assertIsNotNone(dlg._current_doc)
        dlg.close()
        self.app.processEvents()

    # ── Chips ────────────────────────────────────────────────────────────────

    def test_chips_count_matches_results(self) -> None:
        results = [_ok_result(self.pdf1), _ok_result(self.pdf2), _err_result()]
        dlg = self._make_dlg(results)
        self.app.processEvents()
        self.assertEqual(len(dlg._doc_chips), 3)
        dlg.close()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
