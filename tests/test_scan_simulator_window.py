from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtWidgets import QApplication

from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from ui.scan_simulator.window import ScanSimulatorWindow


class ScanSimulatorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_reads_preset_controls_and_builds_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = self._make_pdf(Path(tmp) / "doc.pdf")
            window = ScanSimulatorWindow(_ctx())
            try:
                window.set_inputs([str(pdf)])
                window._preset_combo.setCurrentText("Hoja movida")
                window._range_edit.setText("1-final")
                window._tone_combo.setCurrentText("Color")
                window._seed_spin.setValue(99)

                cfg = window._read_config()
                jobs = window._build_jobs()

                self.assertEqual(cfg.preset_id, "mobile")
                self.assertEqual(cfg.tone, "color")
                self.assertEqual(cfg.seed, 99)
                self.assertEqual(cfg.page_range, "1-final")
                self.assertGreater(cfg.max_perspective_pct, 0.01)
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].pdf_path, str(pdf))
                self.assertTrue(jobs[0].output_path.endswith(".pdf"))
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_selection_estimate_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = self._make_pdf(Path(tmp) / "doc.pdf", pages=3)
            window = ScanSimulatorWindow(_ctx())
            try:
                window.set_inputs([str(pdf)])
                window._range_edit.setText("2-final")
                cfg = window._read_config()

                estimate, error = window._selection_estimate(cfg)

                self.assertEqual(estimate, 2)
                self.assertEqual(error, "")
                self.assertIsNone(window._validate_ready(cfg))

                window._range_edit.setText("10")
                invalid_cfg = window._read_config()
                self.assertIn("rango", window._validate_ready(invalid_cfg).lower())
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_scan_simulator_for_pdfs(self) -> None:
        tool = get_tool("scan_simulator")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Simular escaneo")
        self.assertIn(".pdf", tool.input_extensions)

    @staticmethod
    def _make_pdf(path: Path, pages: int = 1) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=220, height=300)
            page.insert_text((32, 72), f"Pagina {index + 1}")
        doc.save(path)
        doc.close()
        return path


def _ctx() -> ShellContext:
    return ShellContext(
        tray=PdfTray(),
        word_converter=WordToPdfConverter(),
        open_tool=lambda *_: None,
    )


if __name__ == "__main__":
    unittest.main()
