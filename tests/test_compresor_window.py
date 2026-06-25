from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication, QScrollArea

from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from core.pdf_compress_engine import CompressJob, CompressResult
from ui.compresor.window import CompresorWindow


class CompresorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_loads_pdf_and_builds_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            window = CompresorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                self.assertEqual(window._docs_card.count(), 1)
                jobs = window._build_jobs()
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].profile_id, "balanced")
                self.assertTrue(jobs[0].output_path.endswith(".pdf"))
                self.assertEqual(jobs[0].options.engine_mode, "auto")
                self.assertEqual(jobs[0].options.validation_level, "standard")
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_window_builds_jobs_with_advanced_compression_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            window = CompresorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                window._engine_combo.setCurrentIndex(1)  # PyMuPDF interno
                window._validation_combo.setCurrentIndex(1)  # Estricta
                window._dpi_target_spin.setValue(180)
                window._dpi_threshold_spin.setValue(240)
                window._quality_spin.setValue(69)
                window._gray_check.setChecked(True)

                jobs = window._build_jobs()
                self.assertEqual(jobs[0].options.engine_mode, "pymupdf")
                self.assertEqual(jobs[0].options.validation_level, "strict")
                self.assertEqual(jobs[0].options.dpi_target, 180)
                self.assertEqual(jobs[0].options.dpi_threshold, 240)
                self.assertEqual(jobs[0].options.quality, 69)
                self.assertTrue(jobs[0].options.set_to_gray)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_profile_layout_is_scrollable_and_responsive(self) -> None:
        window = CompresorWindow(
            ShellContext(
                tray=PdfTray(),
                word_converter=WordToPdfConverter(),
                open_tool=lambda *_: None,
            )
        )
        try:
            self.assertIsNotNone(window.findChild(QScrollArea, "DocumentsScrollArea"))
            self.assertIsNotNone(window.findChild(QScrollArea, "ProfileScrollArea"))
            self.assertIsNotNone(window.findChild(QScrollArea, "ResultsScrollArea"))

            window.show()
            self.app.processEvents()
            window._switch_section(1)

            window.resize(820, 620)
            self.app.processEvents()
            window._sync_profile_grid_for_width()
            self.assertEqual(window._profile_grid_columns, 1)

            window.resize(1240, 760)
            self.app.processEvents()
            window._sync_profile_grid_for_width()
            self.assertEqual(window._profile_grid_columns, 2)
        finally:
            window.deleteLater()
            self.app.processEvents()

    def test_tool_registry_exposes_compressor_for_pdfs(self) -> None:
        tool = get_tool("compresor")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Comprimir PDF")
        self.assertIn(".pdf", tool.input_extensions)

    def test_results_summary_aggregates_savings_and_warnings(self) -> None:
        window = CompresorWindow(
            ShellContext(
                tray=PdfTray(),
                word_converter=WordToPdfConverter(),
                open_tool=lambda *_: None,
            )
        )
        try:
            html = window._results_summary_html([
                CompressResult(
                    job=CompressJob("a.pdf", "a_out.pdf"),
                    success=True,
                    input_bytes=1000,
                    output_bytes=600,
                ),
                CompressResult(
                    job=CompressJob("b.pdf", "b_out.pdf"),
                    success=True,
                    warning="ya estaba optimizado",
                    input_bytes=500,
                    output_bytes=500,
                ),
                CompressResult(
                    job=CompressJob("c.pdf", "c_out.pdf"),
                    success=False,
                    error="fallo",
                ),
            ])

            self.assertIn("2 PDFs optimizados", html)
            self.assertIn("Ahorro: 400 B (26.7%)", html)
            self.assertIn("1 ya estaba optimizado", html)
            self.assertIn("Errores: 1", html)
        finally:
            window.deleteLater()
            self.app.processEvents()

    def test_run_starts_worker_without_blocking_ui_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            started = threading.Event()
            release = threading.Event()
            finished = threading.Event()
            worker_thread_ids: list[int] = []
            main_thread_id = threading.get_ident()

            class FakeEngine:
                def run_batch(self, jobs, *, progress=None, should_cancel=None):
                    worker_thread_ids.append(threading.get_ident())
                    started.set()
                    if progress:
                        progress(10, 100, "fake async")
                    release.wait(2.0)
                    finished.set()
                    return [
                        CompressResult(
                            job=jobs[0],
                            output_path=str(pdf_path),
                            success=True,
                            input_bytes=100,
                            output_bytes=50,
                            total_pages=1,
                            strategy="fake",
                        )
                    ]

            window = CompresorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                with (
                    patch("ui.compresor.window.PdfCompressEngine", FakeEngine),
                    patch("ui.compresor.window.show_success"),
                    patch("ui.compresor.window.show_warning"),
                ):
                    started_at = time.perf_counter()
                    window._on_run()
                    elapsed = time.perf_counter() - started_at

                    self.assertLess(elapsed, 1.0)
                    self.assertTrue(started.wait(2.0))
                    self.assertNotEqual(worker_thread_ids[0], main_thread_id)
                    self.assertFalse(finished.is_set())
                    release.set()

                    deadline = time.perf_counter() + 3.0
                    while (
                        (not finished.is_set() or window._worker_thread is not None)
                        and time.perf_counter() < deadline
                    ):
                        self.app.processEvents()
                        QThread.msleep(10)
                    self.assertTrue(finished.is_set())
                    self.assertIsNotNone(window.last_results)
                    self.assertEqual(window.last_results[0].strategy, "fake")
            finally:
                window._result_viewer.clear_results()
                if window._worker:
                    window._worker.cancel()
                if window._worker_thread and window._worker_thread.isRunning():
                    window._worker_thread.wait(3000)
                window.deleteLater()
                self.app.processEvents()

    @staticmethod
    def _make_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((36, 72), "Compresor")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
