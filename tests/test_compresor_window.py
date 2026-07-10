from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QScrollArea

from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from core.pdf_compress_engine import CompressJob, CompressResult
from core.pdf_page_rules import PageCompressionRule
from ui.compresor.window import CompressWorker, CompresorWindow


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

    def test_window_builds_jobs_with_fast_and_turbo_engines(self) -> None:
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

                fast_idx = window._engine_combo.findData("fast")
                window._engine_combo.setCurrentIndex(fast_idx)
                self.assertEqual(window._build_jobs()[0].options.engine_mode, "fast")

                turbo_idx = window._engine_combo.findData("turbo")
                window._engine_combo.setCurrentIndex(turbo_idx)
                self.assertEqual(window._build_jobs()[0].options.engine_mode, "turbo")
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_window_builds_jobs_with_page_rules(self) -> None:
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
                window._page_rules_panel._pages_edit.setText("1")
                idx = window._page_rules_panel._preset_combo.findData("exclude")
                window._page_rules_panel._preset_combo.setCurrentIndex(idx)
                window._page_rules_panel._save_rule()

                jobs = window._build_jobs()
                self.assertEqual(len(jobs[0].page_rules), 1)
                self.assertEqual(jobs[0].page_rules[0].page_spec, "1")
                self.assertEqual(jobs[0].page_rules[0].preset, "exclude")
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_window_builds_jobs_with_custom_page_rule_options(self) -> None:
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
                panel = window._page_rules_panel
                panel._pages_edit.setText("1")
                idx = panel._preset_combo.findData("custom")
                panel._preset_combo.setCurrentIndex(idx)
                panel._dpi_target_spin.setValue(190)
                panel._dpi_threshold_spin.setValue(260)
                panel._quality_spin.setValue(71)
                panel._gray_check.setChecked(True)
                validation_idx = panel._validation_combo.findData("strict")
                panel._validation_combo.setCurrentIndex(validation_idx)
                panel._save_rule()

                rule = window._build_jobs()[0].page_rules[0]
                self.assertEqual(rule.preset, "custom")
                self.assertEqual(rule.options["dpi_target"], 190)
                self.assertEqual(rule.options["dpi_threshold"], 260)
                self.assertEqual(rule.options["quality"], 71)
                self.assertTrue(rule.options["set_to_gray"])
                self.assertEqual(rule.options["validation_level"], "strict")
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_window_rejects_page_rules_outside_document_range(self) -> None:
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
                window._page_rules_panel._rules = [
                    PageCompressionRule("2", "exclude")
                ]

                error = window._validate_ready()
                self.assertIsNotNone(error)
                self.assertIn("fuera de rango", error)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_window_rejects_invalid_custom_page_rule_dpi(self) -> None:
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
                window._page_rules_panel._rules = [
                    PageCompressionRule(
                        "1",
                        "custom",
                        options={
                            "dpi_target": 260,
                            "dpi_threshold": 180,
                            "quality": 70,
                        },
                    )
                ]

                error = window._validate_ready()
                self.assertIsNotNone(error)
                self.assertIn("DPI objetivo", error)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_window_rejects_document_level_engine_with_page_rules(self) -> None:
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
                window._page_rules_panel._rules = [
                    PageCompressionRule("1", "exclude")
                ]
                idx = window._engine_combo.findData("qpdf")
                window._engine_combo.setCurrentIndex(idx)

                error = window._validate_ready()
                self.assertIsNotNone(error)
                self.assertIn("Automatico o PyMuPDF", error)
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
                    patch("ui.compresor.window._ISOLATED_COMPRESSION_ENABLED", False),
                    patch("ui.compresor.window.PdfCompressEngine", FakeEngine),
                    patch("ui.compresor.window.show_success"),
                    patch("ui.compresor.window.show_warning"),
                ):
                    started_at = time.perf_counter()
                    window._on_run()
                    elapsed = time.perf_counter() - started_at

                    self.assertLess(elapsed, 1.0)
                    deadline = time.perf_counter() + 2.0
                    while not started.is_set() and time.perf_counter() < deadline:
                        self.app.processEvents()
                        QThread.msleep(10)
                    self.assertTrue(started.is_set())
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

    def test_run_prepares_jobs_without_blocking_ui_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            prepare_started = threading.Event()
            prepare_release = threading.Event()
            prepare_thread_ids: list[int] = []
            main_thread_id = threading.get_ident()

            def fake_prepare(request, *, should_cancel):
                prepare_thread_ids.append(threading.get_ident())
                prepare_started.set()
                prepare_release.wait(2.0)
                return [
                    CompressJob(
                        pdf_path=request.paths[0],
                        output_path=str(Path(tmp) / "out.pdf"),
                        profile_id=request.profile_id,
                        options=request.options,
                        page_rules=request.page_rules,
                    )
                ]

            class FakeEngine:
                def run_batch(self, jobs, *, progress=None, should_cancel=None):
                    return [
                        CompressResult(
                            job=jobs[0],
                            output_path=jobs[0].output_path,
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
                    patch("ui.compresor.window._ISOLATED_COMPRESSION_ENABLED", False),
                    patch("ui.compresor.window._prepare_compress_jobs", fake_prepare),
                    patch("ui.compresor.window.PdfCompressEngine", FakeEngine),
                    patch("ui.compresor.window.show_success"),
                    patch("ui.compresor.window.show_warning"),
                ):
                    started_at = time.perf_counter()
                    window._on_run()
                    elapsed = time.perf_counter() - started_at

                    self.assertLess(elapsed, 1.0)
                    self.assertTrue(prepare_started.wait(2.0))
                    self.assertNotEqual(prepare_thread_ids[0], main_thread_id)
                    self.assertIsNotNone(window._prepare_thread)
                    self.assertIsNone(window._worker_thread)

                    prepare_release.set()
                    deadline = time.perf_counter() + 3.0
                    while (
                        window._prepare_thread is not None
                        or window._worker_thread is not None
                    ) and time.perf_counter() < deadline:
                        self.app.processEvents()
                        QThread.msleep(10)
                    self.assertEqual(window.last_results[0].strategy, "fake")
            finally:
                window._cleanup_thread()
                window._result_viewer.clear_results()
                window.deleteLater()
                self.app.processEvents()

    def test_recompress_button_reuses_successful_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = self._make_pdf(root / "input.pdf")
            output_path = self._make_pdf(root / "input_comprimido.pdf")
            window = CompresorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window.last_results = [
                    CompressResult(
                        job=CompressJob(
                            pdf_path=str(source_path),
                            output_path=str(output_path),
                            profile_id="balanced",
                        ),
                        output_path=str(output_path),
                        success=True,
                        input_bytes=100,
                        output_bytes=50,
                        total_pages=1,
                        strategy="fake",
                    )
                ]
                window._sync_recompress_button()
                self.assertTrue(window._recompress_btn.isEnabled())

                run_paths: list[list[str]] = []
                window._on_run = lambda: run_paths.append(window._docs_card.paths())

                window._on_recompress_results()
                self.app.processEvents()

                self.assertEqual(window._docs_card.paths(), [str(output_path)])
                self.assertEqual(run_paths, [[str(output_path)]])
                self.assertFalse(window._recompress_btn.isEnabled())
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_worker_falls_back_if_isolated_process_does_not_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            output_path = Path(tmp) / "out.pdf"
            finished: list[CompressResult] = []
            errors: list[str] = []

            class FakeEngine:
                def run_batch(self, jobs, *, progress=None, should_cancel=None):
                    return [
                        CompressResult(
                            job=jobs[0],
                            output_path=jobs[0].output_path,
                            success=True,
                            input_bytes=100,
                            output_bytes=80,
                            total_pages=1,
                            strategy="fallback",
                        )
                    ]

            worker = CompressWorker([
                CompressJob(str(pdf_path), str(output_path), "balanced")
            ])
            worker.finished.connect(lambda results: finished.extend(results))
            worker.error.connect(errors.append)

            with (
                patch("ui.compresor.window.PdfCompressEngine", FakeEngine),
                patch.object(
                    CompressWorker,
                    "_build_command",
                    return_value=[
                        sys.executable,
                        "-c",
                        "import sys; sys.exit(3)",
                    ],
                ),
            ):
                worker.run()

            self.assertFalse(errors)
            self.assertEqual(len(finished), 1)
            self.assertEqual(finished[0].strategy, "fallback")

    def test_worker_marks_native_crash_as_failed_result_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            output_path = Path(tmp) / "out.pdf"
            finished: list[CompressResult] = []
            errors: list[str] = []

            class FakeEngine:
                def run_batch(self, jobs, *, progress=None, should_cancel=None):
                    raise AssertionError("native crashes must not fall back in-process")

            worker = CompressWorker([
                CompressJob(str(pdf_path), str(output_path), "balanced")
            ])
            worker.finished.connect(lambda results: finished.extend(results))
            worker.error.connect(errors.append)

            with (
                patch("ui.compresor.window.PdfCompressEngine", FakeEngine),
                patch.object(
                    CompressWorker,
                    "_build_command",
                    return_value=[
                        sys.executable,
                        "-c",
                        "import os; os._exit(-1073741819)",
                    ],
                ),
            ):
                worker.run()

            self.assertFalse(errors)
            self.assertEqual(len(finished), 1)
            self.assertFalse(finished[0].success)
            self.assertIn("access violation", finished[0].error)
            self.assertIn("3221225477", finished[0].error)

    def test_worker_continues_after_one_pdf_native_crashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first_pdf = self._make_pdf(Path(tmp) / "first.pdf")
            second_pdf = self._make_pdf(Path(tmp) / "second.pdf")
            first_out = Path(tmp) / "first_out.pdf"
            second_out = Path(tmp) / "second_out.pdf"
            finished: list[CompressResult] = []
            errors: list[str] = []
            original_build_command = CompressWorker._build_command
            calls = 0

            def build_command(request_path, response_path, events_path, cancel_path):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return [
                        sys.executable,
                        "-c",
                        "import os; os._exit(-1073741819)",
                    ]
                return original_build_command(
                    request_path,
                    response_path,
                    events_path,
                    cancel_path,
                )

            worker = CompressWorker([
                CompressJob(str(first_pdf), str(first_out), "balanced"),
                CompressJob(str(second_pdf), str(second_out), "balanced"),
            ])
            worker.finished.connect(lambda results: finished.extend(results))
            worker.error.connect(errors.append)

            with patch.object(CompressWorker, "_build_command", side_effect=build_command):
                worker.run()

            self.assertFalse(errors)
            self.assertEqual(len(finished), 2)
            self.assertFalse(finished[0].success)
            self.assertTrue(finished[1].success, finished[1].error)
            self.assertTrue(second_out.exists())

    def test_worker_heartbeat_refreshes_long_stage_message(self) -> None:
        worker = CompressWorker([])
        progress_events: list[tuple[int, int, str]] = []
        worker.progress.connect(
            lambda current, total, message: progress_events.append(
                (current, total, message)
            )
        )

        worker._emit_progress(72, 100, "Probando compresion fuerte con Ghostscript...")
        worker._last_stage_started_at -= 3.0
        worker._last_heartbeat_at -= 3.0
        worker._emit_progress_heartbeat(100)

        self.assertGreaterEqual(len(progress_events), 2)
        self.assertEqual(progress_events[-1][0], 72)
        self.assertIn("Ghostscript", progress_events[-1][2])
        self.assertIn("s)", progress_events[-1][2])

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
