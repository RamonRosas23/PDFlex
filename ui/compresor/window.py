"""CompresorWindow — compresion y optimizacion de PDFs por lote."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import List, Optional

from PySide6.QtCore import QObject, QThread, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QSpinBox,
    QScrollArea, QSizePolicy, QFrame,
)

from core.output_naming import unique_output_path_for_source
from core.output_paths import make_run_dir
from core.pdf_backend import pdf_page_count
from core.pdf_compress_engine import (
    PROFILES,
    CompressJob,
    CompressOptions,
    CompressResult,
    OptionalEngineStatus,
    PdfCompressEngine,
    compress_job_to_dict,
    compress_result_from_dict,
    format_bytes,
    optional_engine_status,
    profile_for,
)
from core.pdf_page_rules import PageCompressionRule, build_page_compression_plan
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.document_workspace import DocumentWorkspace as DocumentsCard
from ui.common.icons import set_button_icon
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.process_step import ProcessStep
from ui.common.send_to_tool import SendToToolButton
from ui.common.tool_scaffold import PipelineWindow, RunnerThread
from ui.compresor.page_rules import PageRulesPanel, _custom_rules_error


@dataclass(frozen=True)
class _CompressRunRequest:
    paths: List[str]
    profile_id: str
    options: CompressOptions
    page_rules: List[PageCompressionRule]
    add_tool_suffix: bool


_ISOLATED_COMPRESSION_ENABLED = True


class _IsolatedCompressionError(RuntimeError):
    def __init__(self, message: str, *, allow_fallback: bool = False) -> None:
        super().__init__(message)
        self.allow_fallback = allow_fallback


class CompressWorker(QObject):
    """Supervises PDF compression without running native work in the UI process."""

    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    _POLL_SECONDS = 0.10
    _FORCE_CANCEL_AFTER_SECONDS = 2.0
    _HEARTBEAT_SECONDS = 2.0

    def __init__(
        self,
        jobs: List[CompressJob],
        *,
        isolated_process: bool = True,
    ) -> None:
        super().__init__()
        self.jobs = jobs
        self.isolated_process = isolated_process
        self._cancel = False
        self._cancel_path: Path | None = None
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._event_error = ""
        self._isolated_stage_progress = False
        self._last_progress_current = 0
        self._last_progress_total = 1
        self._last_progress_message = ""
        self._last_stage_started_at = 0.0
        self._last_heartbeat_at = 0.0

    def cancel(self) -> None:
        with self._lock:
            self._cancel = True
            cancel_path = self._cancel_path
        if cancel_path:
            try:
                cancel_path.touch(exist_ok=True)
            except OSError:
                pass

    def stop_now(self) -> None:
        self.cancel()
        with self._lock:
            process = self._process
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def run(self) -> None:
        try:
            if self.isolated_process:
                try:
                    results = self._run_isolated_process()
                except OSError as exc:
                    self.progress.emit(
                        0,
                        max(1, len(self.jobs)) * 100,
                        f"Motor aislado no disponible; usando hilo interno... {_short_text(str(exc), 80)}",
                    )
                    results = self._run_in_thread()
                except _IsolatedCompressionError as exc:
                    if not exc.allow_fallback:
                        raise
                    self.progress.emit(
                        0,
                        max(1, len(self.jobs)) * 100,
                        "Motor aislado no arranco; usando hilo interno...",
                    )
                    results = self._run_in_thread()
            else:
                results = self._run_in_thread()
            if self._cancel:
                self.error.emit("Operacion cancelada.")
            else:
                self.finished.emit(results)
        except Exception as exc:
            self.error.emit("Operacion cancelada." if self._cancel else str(exc))

    def _run_in_thread(self) -> List[CompressResult]:
        return PdfCompressEngine().run_batch(
            self.jobs,
            progress=lambda c, t, m: self.progress.emit(c, t, m),
            should_cancel=lambda: self._cancel,
        )

    def _run_isolated_process(self) -> List[CompressResult]:
        total = len(self.jobs)
        total_units = max(1, total) * 100
        results: List[CompressResult] = []
        self._emit_progress(0, total_units, "Motor aislado iniciado...")
        for index, job in enumerate(self.jobs):
            if self._cancel:
                raise RuntimeError("Operacion cancelada.")
            try:
                result = self._run_single_job_isolated(job, index, total, total_units)
            except _IsolatedCompressionError:
                if index == 0 and not results:
                    raise
                result = self._failed_result(
                    job,
                    "No se pudo iniciar el motor aislado para este documento.",
                )
            results.append(result)
            self._emit_progress(
                (index + 1) * 100,
                total_units,
                f"{index + 1}/{total} PDFs procesados",
            )
        return results

    def _run_single_job_isolated(
        self,
        job: CompressJob,
        index: int,
        total: int,
        total_units: int,
    ) -> CompressResult:
        work_dir = Path(tempfile.mkdtemp(prefix="PDFlex_compress_"))
        request_path = work_dir / "request.json"
        response_path = work_dir / "response.json"
        events_path = work_dir / "events.jsonl"
        cancel_path = work_dir / "cancel.signal"
        stdout_path = work_dir / "stdout.log"
        stderr_path = work_dir / "stderr.log"
        checkpoint_results: List[CompressResult] = []
        event_offset = 0
        process: subprocess.Popen | None = None
        self._event_error = ""
        self._isolated_stage_progress = False

        with self._lock:
            self._cancel_path = cancel_path

        try:
            request_path.write_text(
                json.dumps(
                    {"jobs": [compress_job_to_dict(job)]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            events_path.touch()
            stdout_stream = stdout_path.open("wb")
            stderr_stream = stderr_path.open("wb")
            try:
                process = subprocess.Popen(
                    self._build_command(
                        request_path,
                        response_path,
                        events_path,
                        cancel_path,
                    ),
                    cwd=str(Path(__file__).resolve().parents[2]),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    creationflags=self._creation_flags(),
                )
            finally:
                stdout_stream.close()
                stderr_stream.close()
            with self._lock:
                self._process = process

            self._emit_progress(
                index * 100,
                total_units,
                f"Preparando {Path(job.pdf_path).name}...",
            )
            cancel_started_at: float | None = None

            while process.poll() is None:
                event_offset = self._drain_events(
                    events_path,
                    event_offset,
                    checkpoint_results,
                    base_current=index * 100,
                    total_units=total_units,
                    doc_index=index,
                    total_docs=total,
                )
                with self._lock:
                    cancel_requested = self._cancel
                if cancel_requested:
                    if cancel_started_at is None:
                        cancel_started_at = time.monotonic()
                    elif (
                        time.monotonic() - cancel_started_at
                        >= self._FORCE_CANCEL_AFTER_SECONDS
                    ):
                        process.terminate()
                else:
                    self._emit_progress_heartbeat(total_units)
                time.sleep(self._POLL_SECONDS)

            self._drain_events(
                events_path,
                event_offset,
                checkpoint_results,
                base_current=index * 100,
                total_units=total_units,
                doc_index=index,
                total_docs=total,
            )
            payload = self._read_response(response_path)
            with self._lock:
                cancelled = self._cancel

            if cancelled:
                raise RuntimeError("Operacion cancelada.")
            if payload:
                status = payload.get("status")
                if status == "error":
                    message = (
                        payload.get("error")
                        or self._event_error
                        or self._process_failure_details(process, stdout_path, stderr_path)
                        or "El proceso de compresion termino con error."
                    )
                    if not self._isolated_stage_progress:
                        raise _IsolatedCompressionError(message, allow_fallback=True)
                    return self._failed_result(
                        job,
                        _native_crash_message(message),
                    )
                results = [
                    compress_result_from_dict(result_data)
                    for result_data in payload.get("results", [])
                ]
                if results:
                    return results[0]
                return self._failed_result(
                    job,
                    "El motor aislado no entrego resultado para este documento.",
                )
            if process.returncode not in (0, None):
                details = self._process_failure_details(process, stdout_path, stderr_path)
                message = (
                    self._event_error
                    or details
                    or "El motor aislado de compresion se cerro inesperadamente."
                )
                if (
                    not self._isolated_stage_progress
                    and not _is_native_crash_returncode(process.returncode)
                ):
                    raise _IsolatedCompressionError(message, allow_fallback=True)
                return self._failed_result(
                    job,
                    _native_crash_message(message),
                )
            if checkpoint_results:
                return checkpoint_results[0]
            return self._failed_result(
                job,
                "El motor aislado termino sin entregar resultado para este documento.",
            )
        finally:
            with self._lock:
                process = self._process
                self._process = None
                self._cancel_path = None
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    try:
                        process.kill()
                    except OSError:
                        pass
            if self._cancel:
                self._cleanup_cancelled_outputs(checkpoint_results)
            self._cleanup_work_dir(work_dir)

    @staticmethod
    def _failed_result(job: CompressJob, error: str) -> CompressResult:
        return CompressResult(
            job=job,
            success=False,
            error=error,
            profile_label=profile_for(job.profile_id).label,
            input_bytes=_file_size(job.pdf_path),
        )

    @staticmethod
    def _build_command(
        request_path: Path,
        response_path: Path,
        events_path: Path,
        cancel_path: Path,
    ) -> List[str]:
        args = [
            "--request", str(request_path),
            "--response", str(response_path),
            "--events", str(events_path),
            "--cancel", str(cancel_path),
        ]
        if getattr(sys, "frozen", False):
            return [sys.executable, "--pdflex-compress-worker", *args]
        return [sys.executable, "-m", "core.pdf_compress_process", *args]

    @staticmethod
    def _creation_flags() -> int:
        if os.name != "nt":
            return 0
        return (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        )

    def _drain_events(
        self,
        events_path: Path,
        offset: int,
        checkpoint_results: List[CompressResult],
        *,
        base_current: int,
        total_units: int,
        doc_index: int,
        total_docs: int,
    ) -> int:
        try:
            with events_path.open("rb") as stream:
                stream.seek(offset)
                while True:
                    line_start = stream.tell()
                    line = stream.readline()
                    if not line:
                        return stream.tell()
                    if not line.endswith(b"\n"):
                        return line_start
                    event = json.loads(line.decode("utf-8"))
                    event_type = event.get("type")
                    if event_type == "progress":
                        local_current = int(event.get("current", 0))
                        local_total = max(1, int(event.get("total", 1)))
                        local_pct = int(local_current / local_total * 100)
                        global_current = base_current + max(0, min(100, local_pct))
                        if global_current > base_current:
                            self._isolated_stage_progress = True
                        message = str(event.get("message", ""))
                        if local_current >= local_total:
                            message = f"{doc_index + 1}/{total_docs} PDFs procesados"
                        self._emit_progress(
                            global_current,
                            total_units,
                            message,
                        )
                    elif event_type == "result":
                        checkpoint_results.append(
                            compress_result_from_dict(event["result"])
                        )
                    elif event_type == "error":
                        self._event_error = str(event.get("message", ""))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return offset

    def _emit_progress(self, current: int, total: int, message: str) -> None:
        now = time.monotonic()
        self._last_progress_current = int(current)
        self._last_progress_total = max(1, int(total))
        self._last_progress_message = message
        self._last_stage_started_at = now
        self._last_heartbeat_at = now
        self.progress.emit(current, total, message)

    def _emit_progress_heartbeat(self, total_units: int) -> None:
        if not self._last_progress_message:
            return
        if self._last_progress_current >= max(1, total_units):
            return
        now = time.monotonic()
        if now - self._last_heartbeat_at < self._HEARTBEAT_SECONDS:
            return
        elapsed = int(now - self._last_stage_started_at)
        if elapsed < self._HEARTBEAT_SECONDS:
            return
        self._last_heartbeat_at = now
        self.progress.emit(
            self._last_progress_current,
            self._last_progress_total,
            f"{self._last_progress_message} ({elapsed} s)",
        )

    def _process_failure_details(
        self,
        process: subprocess.Popen | None,
        stdout_path: Path,
        stderr_path: Path,
    ) -> str:
        parts: list[str] = []
        if process and process.returncode not in (None, 0):
            parts.append(f"codigo {process.returncode}")
        stderr = self._read_log_tail(stderr_path)
        stdout = self._read_log_tail(stdout_path)
        if stderr:
            parts.append(f"stderr: {stderr}")
        if stdout:
            parts.append(f"stdout: {stdout}")
        return " | ".join(parts)

    @staticmethod
    def _read_log_tail(path: Path, limit: int = 1200) -> str:
        try:
            data = path.read_bytes()
        except OSError:
            return ""
        text = data[-limit:].decode("utf-8", errors="replace").strip()
        return " ".join(text.split())

    @staticmethod
    def _read_response(path: Path) -> dict | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _cleanup_work_dir(path: Path) -> None:
        for _attempt in range(10):
            try:
                shutil.rmtree(path)
                return
            except FileNotFoundError:
                return
            except OSError:
                time.sleep(0.05)

    def _cleanup_cancelled_outputs(self, completed_results: List[CompressResult]) -> None:
        completed_outputs = {
            _resolved_path(result.output_path)
            for result in completed_results
            if result.success and result.output_path
        }
        for job in self.jobs:
            output = Path(job.output_path)
            suffix = output.suffix or ".pdf"
            try:
                for temp_path in output.parent.glob(f"{output.stem}.tmp-*{suffix}"):
                    temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            if _resolved_path(str(output)) in completed_outputs:
                continue
            try:
                if output.exists():
                    output.unlink()
            except OSError:
                pass


class CompressPrepareWorker(QObject):
    progress = Signal(str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, request: _CompressRunRequest) -> None:
        super().__init__()
        self.request = request
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            self.progress.emit("Validando configuracion...")
            jobs = _prepare_compress_jobs(self.request, should_cancel=lambda: self._cancel)
        except Exception as exc:
            self.error.emit(str(exc))
            return
        if self._cancel:
            self.error.emit("Operacion cancelada.")
        else:
            self.finished.emit(jobs)


class EngineStatusWorker(QObject):
    finished = Signal(list)

    def run(self) -> None:
        self.finished.emit(optional_engine_status())


class DocsInfoWorker(QObject):
    finished = Signal(int, int, int, str)

    def __init__(self, paths: List[str], token: int) -> None:
        super().__init__()
        self.paths = list(paths)
        self.token = token

    def run(self) -> None:
        total = sum(_file_size(path) for path in self.paths)
        first = self.paths[0] if self.paths else ""
        page_count = _pdf_page_count(first) if first else 0
        label = Path(first).name if first else ""
        self.finished.emit(self.token, total, page_count, label)


class CompresorWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documentos", "Carga PDFs a optimizar"),
        ("02", "Perfil", "Elige reduccion y calidad"),
        ("03", "Procesar", "Ejecuta la compresion"),
        ("04", "Resultados", "Compara peso antes y despues"),
    ]
    BRAND = "Comprimir PDF"
    TAGLINE = "Reduce peso con perfiles seguros"
    ACCENT_COLOR = "#2DD4BF"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[CompressResult] = []
        self._prepare_worker: Optional[CompressPrepareWorker] = None
        self._prepare_thread: Optional[QThread] = None
        self._worker: Optional[CompressWorker] = None
        self._worker_thread: Optional[QThread] = None
        self._engine_status_worker: Optional[EngineStatusWorker] = None
        self._engine_status_thread: Optional[QThread] = None
        self._docs_info_worker: Optional[DocsInfoWorker] = None
        self._docs_info_thread: Optional[QThread] = None
        self._docs_info_token = 0
        self._docs_total_bytes = 0
        self._engine_statuses: list[OptionalEngineStatus] = []
        self._engine_status_loading = False
        self._profile_grid: Optional[QGridLayout] = None
        self._profile_cards: list[QWidget] = []
        self._profile_card_refs: dict[str, QWidget] = {}
        self._profile_grid_columns = 0
        self._profile_scroll: Optional[QScrollArea] = None
        self._closing = False

        self._build_pages()
        self.setMinimumSize(785, 540)
        self._switch_section(0)
        self.setAcceptDrops(True)
        QTimer.singleShot(0, self._refresh_engine_status_async)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_profile_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())
        self.stack.setMinimumSize(0, 0)
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._build_action_buttons()

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = _make_scroll_area("DocumentsScrollArea", horizontal=True)
        content = QWidget()
        content.setProperty("class", "PageContainer")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(36, 32, 36, 32)
        content_layout.setSpacing(24)

        content_layout.addLayout(make_page_header(
            "Documentos a comprimir",
            "Carga PDFs grandes o escaneados. Los originales nunca se modifican.",
        ))

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=False,
            show_thumbnails=True,
            thumb_size=(64, 82),
            file_filter="PDF (*.pdf)",
        )
        self._docs_card.files_changed.connect(self._on_docs_changed)
        content_layout.addWidget(self._docs_card, 1)

        self._docs_summary_lbl = QLabel("Sin documentos cargados.")
        self._docs_summary_lbl.setProperty("class", "CardHint")
        self._docs_summary_lbl.setWordWrap(True)
        content_layout.addWidget(self._docs_summary_lbl)

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        return page

    def _build_profile_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("ProfileScrollArea")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea#ProfileScrollArea { border: none; background: transparent; }"
            "QScrollArea#ProfileScrollArea > QWidget { background: transparent; }"
        )
        scroll.viewport().setStyleSheet("background: transparent;")
        self._profile_scroll = scroll

        content = QWidget()
        content.setProperty("class", "PageContainer")
        outer_content = QVBoxLayout(content)
        outer_content.setContentsMargins(30, 28, 30, 28)
        outer_content.setSpacing(18)

        outer_content.addLayout(make_page_header(
            "Perfil de compresion",
            "Elige un perfil segun el destino del documento.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self._profile_grid = grid

        profile_card = make_card(
            "Perfil",
            "Los perfiles ajustan resolucion y calidad de imagen sin tocar el PDF original.",
        )
        self._profile_combo = QComboBox()
        self._profile_combo.addItem("Máxima reducción", "email")
        self._profile_combo.addItem("Equilibrado", "balanced")
        self._profile_combo.addItem("Alta calidad", "quality")
        self._profile_combo.setToolTip("Perfil base de compresion.")
        self._profile_combo.setCurrentIndex(1)
        self._profile_combo.currentIndexChanged.connect(self._sync_controls_from_profile)
        card_layout(profile_card).addWidget(self._profile_combo)

        engine_card = make_card(
            "Motor",
            "Automatico prioriza rutas rapidas en PDFs visuales grandes y valida antes de aceptar.",
        )
        self._engine_combo = QComboBox()
        self._engine_combo.addItem("Automático recomendado", "auto")
        self._engine_combo.addItem("Motor interno libre", "internal")
        self._engine_combo.addItem("QPDF reforzado", "qpdf")
        self._engine_combo.addItem("Ghostscript visual", "ghostscript")
        self._engine_combo.addItem("Rápido visual", "fast")
        self._engine_combo.addItem("Turbo libre aislado", "turbo")
        self._engine_combo.setToolTip(
            "Rapido visual usa Ghostscript /printer; Turbo usa un proceso aislado con el backend libre."
        )
        self._engine_combo.currentIndexChanged.connect(self._sync_profile_desc)
        card_layout(engine_card).addWidget(self._engine_combo)

        image_card = make_card(
            "Imagenes",
            "Ajusta cuanto se reducen escaneos y fotografias dentro del PDF.",
        )
        self._dpi_target_spin = _make_spin(50, 600, " DPI")
        self._dpi_threshold_spin = _make_spin(72, 900, " DPI")
        self._quality_spin = _make_spin(35, 100, "%")
        self._gray_check = QCheckBox("Escala de grises")
        self._gray_check.setToolTip("Reduce mas en documentos sin color importante.")
        for widget in (
            self._dpi_target_spin,
            self._dpi_threshold_spin,
            self._quality_spin,
            self._gray_check,
        ):
            signal = getattr(widget, "valueChanged", None) or getattr(widget, "stateChanged", None)
            if signal:
                signal.connect(self._sync_profile_desc)
        img_layout = card_layout(image_card)
        img_layout.addLayout(_option_row("DPI objetivo", self._dpi_target_spin))
        img_layout.addLayout(_option_row("Procesar sobre", self._dpi_threshold_spin))
        img_layout.addLayout(_option_row("Calidad JPEG", self._quality_spin))
        img_layout.addWidget(self._gray_check)

        safety_card = make_card(
            "Validacion",
            "Controla que tan estricta es la comparacion visual antes de aceptar la salida.",
        )
        self._validation_combo = QComboBox()
        self._validation_combo.addItem("Normal", "standard")
        self._validation_combo.addItem("Estricta", "strict")
        self._validation_combo.addItem("Flexible", "relaxed")
        self._validation_combo.setToolTip("Nivel de validacion visual antes de aceptar la salida.")
        self._validation_combo.currentIndexChanged.connect(self._sync_profile_desc)
        card_layout(safety_card).addWidget(self._validation_combo)

        self._page_rules_panel = PageRulesPanel()
        self._page_rules_panel.rulesChanged.connect(self._on_page_rules_changed)

        details_card = make_card("Detalle tecnico")
        self._profile_desc_lbl = QLabel("")
        self._profile_desc_lbl.setProperty("class", "Mono")
        self._profile_desc_lbl.setWordWrap(True)
        card_layout(details_card).addWidget(self._profile_desc_lbl)

        guidance_card = make_card(
            "Lectura rapida",
            "PDFlex prueba candidatos y solo conserva resultados validados.",
        )
        guidance = QLabel(
            "Maxima reduccion prioriza peso bajo. Equilibrado suele ser la mejor opcion para oficina. "
            "Alta calidad conserva legibilidad con reduccion real. Si un motor externo produce cambios "
            "riesgosos, se descarta automaticamente. Para escaneos grandes, Rapido visual evita la ruta "
            "fuerte lenta cuando la ganancia ya es suficiente."
        )
        guidance.setProperty("class", "CardHint")
        guidance.setWordWrap(True)
        card_layout(guidance_card).addWidget(guidance)
        self._engines_lbl = QLabel("")
        self._engines_lbl.setProperty("class", "Mono")
        self._engines_lbl.setWordWrap(True)
        card_layout(guidance_card).addWidget(self._engines_lbl)

        self._profile_cards = [
            profile_card,
            engine_card,
            image_card,
            safety_card,
            self._page_rules_panel,
            details_card,
            guidance_card,
        ]
        self._profile_card_refs = {
            "profile": profile_card,
            "engine": engine_card,
            "image": image_card,
            "safety": safety_card,
            "rules": self._page_rules_panel,
            "details": details_card,
            "guidance": guidance_card,
        }
        for card in self._profile_cards:
            card.setMinimumWidth(0)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        outer_content.addLayout(grid)
        outer_content.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self._sync_profile_grid_for_width()

        self._sync_controls_from_profile()
        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Genera PDFs optimizados en temporal; usa Guardar como para conservarlos.",
        ))

        self._proc_step = ProcessStep(
            run_label="Comprimir PDFs",
            show_output_dir=False,
        )
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        return page

    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = _make_scroll_area("ResultsScrollArea", horizontal=True)
        content = QWidget()
        content.setProperty("class", "PageContainer")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(36, 32, 36, 32)
        content_layout.setSpacing(20)

        content_layout.addLayout(make_page_header(
            "Resultados",
            "Compara el peso de cada PDF optimizado y revisa el documento final.",
        ))

        self._result_viewer = GenericPdfViewer("PDFs comprimidos")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        content_layout.addWidget(self._result_viewer, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)
        self._recompress_btn = QPushButton("Recomprimir")
        self._recompress_btn.setProperty("class", "Primary")
        self._recompress_btn.setFixedHeight(36)
        self._recompress_btn.setMinimumWidth(200)
        self._recompress_btn.setEnabled(False)
        set_button_icon(self._recompress_btn, "refresh-cw")
        self._recompress_btn.clicked.connect(self._on_recompress_results)
        actions.addWidget(self._recompress_btn)
        content_layout.addLayout(actions)

        self._send_btn = SendToToolButton(self.ctx, "compresor")
        # _send_btn is exposed via _get_step_actions for the navbar; no inline row needed.

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        return page

    def _build_action_buttons(self) -> None:
        self._run_btn = QPushButton("Comprimir PDFs")
        self._run_btn.setProperty("class", "Primary")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setFixedWidth(178)
        set_button_icon(self._run_btn, "play")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        self._cancel_btn.setFixedHeight(36)
        self._cancel_btn.setFixedWidth(116)
        set_button_icon(self._cancel_btn, "square", color="#E5484D")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._restart_btn = QPushButton("Nueva sesión")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setFixedWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        # Wire signals from ProcessStep
        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._sync_recompress_button(running=running)
        self._apply_primary_glows()

    def _on_section_activated(self, idx: int) -> None:
        if idx == 1:
            self._sync_profile_grid_for_width()
        if idx == 2:
            self._refresh_summary()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_profile_grid_for_width()

    def _sync_profile_grid_for_width(self) -> None:
        if self._profile_grid is None or not self._profile_cards:
            return

        viewport_width = 0
        if self._profile_scroll is not None:
            viewport_width = self._profile_scroll.viewport().width()
        if viewport_width <= 0:
            viewport_width = self.stack.width() if hasattr(self, "stack") else self.width()

        columns = 1 if viewport_width < 860 else 2
        if columns == self._profile_grid_columns and self._profile_grid.count() == len(self._profile_cards):
            return

        while self._profile_grid.count():
            self._profile_grid.takeAt(0)

        if columns == 1:
            self._profile_grid.setColumnStretch(0, 1)
            self._profile_grid.setColumnStretch(1, 0)
            self._profile_grid.setColumnMinimumWidth(0, 0)
            self._profile_grid.setColumnMinimumWidth(1, 0)
            for row, card in enumerate(self._profile_cards):
                self._profile_grid.addWidget(card, row, 0)
        else:
            self._profile_grid.setColumnStretch(0, 1)
            self._profile_grid.setColumnStretch(1, 1)
            self._profile_grid.setColumnMinimumWidth(0, 0)
            self._profile_grid.setColumnMinimumWidth(1, 0)
            refs = self._profile_card_refs
            placements = [
                ("profile", 0, 0, 1, 1),
                ("engine", 0, 1, 1, 1),
                ("image", 1, 0, 1, 1),
                ("safety", 1, 1, 1, 1),
                ("rules", 2, 0, 1, 2),
                ("details", 3, 0, 1, 1),
                ("guidance", 3, 1, 1, 1),
            ]
            for key, row, col, row_span, col_span in placements:
                card = refs.get(key)
                if card is not None:
                    self._profile_grid.addWidget(card, row, col, row_span, col_span)
        self._profile_grid_columns = columns

    def set_inputs(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def _on_docs_changed(self, paths: List[str]) -> None:
        count = len(paths)
        self._docs_info_token += 1
        if count == 0:
            self._docs_total_bytes = 0
            self._docs_summary_lbl.setText("Sin documentos cargados.")
            self._page_rules_panel.set_page_context(0, "")
            return
        self._docs_summary_lbl.setText(
            f"{count} documento{'s' if count != 1 else ''} · calculando peso..."
        )
        self._page_rules_panel.set_page_context(0, Path(paths[0]).name)
        self._refresh_docs_info_async(paths, self._docs_info_token)

    def _refresh_docs_info_async(self, paths: List[str], token: int) -> None:
        if self._closing:
            return
        self._docs_info_worker = DocsInfoWorker(paths, token)
        self._docs_info_thread = RunnerThread(self._docs_info_worker.run, self)
        queued = Qt.ConnectionType.QueuedConnection
        self._docs_info_worker.finished.connect(self._on_docs_info_ready, queued)
        self._docs_info_worker.finished.connect(self._docs_info_thread.quit, queued)
        self._docs_info_thread.finished.connect(
            self._docs_info_worker.deleteLater, queued
        )
        self._docs_info_thread.finished.connect(
            self._docs_info_thread.deleteLater, queued
        )
        self._docs_info_thread.start()

    def _on_docs_info_ready(
        self,
        token: int,
        total_bytes: int,
        first_page_count: int,
        first_label: str,
    ) -> None:
        if self._closing:
            return
        if token != self._docs_info_token:
            return
        self._docs_total_bytes = int(total_bytes)
        paths = self._docs_card.paths()
        count = len(paths)
        if count:
            self._docs_summary_lbl.setText(
                f"{count} documento{'s' if count != 1 else ''} · "
                f"{format_bytes(self._docs_total_bytes)} de entrada"
            )
        self._page_rules_panel.set_page_context(first_page_count, first_label)
        if self.stack.currentIndex() == 2:
            self._refresh_summary()

    def _on_page_rules_changed(self) -> None:
        self._sync_profile_desc()
        if self.stack.currentIndex() == 2:
            self._refresh_summary()

    def _profile_id(self) -> str:
        return str(self._profile_combo.currentData() or "balanced")

    def _engine_mode(self) -> str:
        return str(self._engine_combo.currentData() or "auto")

    def _validation_level(self) -> str:
        return str(self._validation_combo.currentData() or "standard")

    def _compression_options(self) -> CompressOptions:
        return CompressOptions(
            engine_mode=self._engine_mode(),
            dpi_target=int(self._dpi_target_spin.value()),
            dpi_threshold=int(self._dpi_threshold_spin.value()),
            quality=int(self._quality_spin.value()),
            set_to_gray=self._gray_check.isChecked(),
            validation_level=self._validation_level(),
        )

    def _sync_controls_from_profile(self) -> None:
        profile = profile_for(self._profile_id())
        for widget, value in (
            (self._dpi_target_spin, profile.dpi_target),
            (self._dpi_threshold_spin, profile.dpi_threshold),
            (self._quality_spin, profile.quality),
        ):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self._gray_check.blockSignals(True)
        self._gray_check.setChecked(profile.set_to_gray)
        self._gray_check.blockSignals(False)
        self._page_rules_panel.set_global_profile(profile.id)
        self._sync_profile_desc()

    def _sync_profile_desc(self) -> None:
        profile = profile_for(self._profile_id())
        engines = [
            "Motor interno libre",
            "Turbo libre aislado",
            *self._available_optional_engine_labels(),
        ]
        engine_mode = self._engine_mode()
        validation = self._validation_combo.currentText()
        self._profile_desc_lbl.setText(
            f"{profile.label}\n"
            f"Motor: {self._engine_combo.currentText()}\n"
            f"Candidatos: {', '.join(engines)}\n"
            f"DPI objetivo: {self._dpi_target_spin.value()}\n"
            f"Procesa imagenes sobre: {self._dpi_threshold_spin.value()} DPI\n"
            f"Calidad JPEG: {self._quality_spin.value()}%\n"
            f"Grises: {'si' if self._gray_check.isChecked() else 'no'}\n"
            f"Validacion: {validation}\n"
            f"Reglas: {self._page_rules_panel.summary_text()}\n"
            f"{profile.description}"
        )
        if engine_mode in {"qpdf", "ghostscript", "fast"}:
            missing = self._missing_selected_engine()
            if missing:
                self._profile_desc_lbl.setText(
                    self._profile_desc_lbl.text() + f"\nAtencion: {missing} no disponible."
                )
        self._engines_lbl.setText(self._engine_status_text())

    def _available_optional_engine_labels(self) -> list[str]:
        return [engine.label for engine in self._engine_statuses if engine.available]

    def _engine_status_text(self) -> str:
        lines = [
            "Disponibilidad en esta PC:",
            "Motor interno libre: disponible",
            "Turbo libre aislado: disponible",
        ]
        if self._engine_status_loading and not self._engine_statuses:
            lines.append("Motores externos: detectando...")
            return "\n".join(lines)
        if not self._engine_statuses:
            lines.append("Motores externos: pendientes de detectar")
            return "\n".join(lines)
        for engine in self._engine_statuses:
            status = "disponible" if engine.available else "no detectado"
            source = f" ({_short_text(engine.source)})" if engine.available and engine.source else ""
            lines.append(f"{engine.label}: {status}{source}")
        return "\n".join(lines)

    def _refresh_engine_status_async(self) -> None:
        if self._closing:
            return
        if self._engine_status_thread is not None:
            return
        self._engine_status_loading = True
        if hasattr(self, "_engines_lbl"):
            self._engines_lbl.setText(self._engine_status_text())
        self._engine_status_worker = EngineStatusWorker()
        self._engine_status_thread = RunnerThread(self._engine_status_worker.run, self)
        queued = Qt.ConnectionType.QueuedConnection
        self._engine_status_worker.finished.connect(
            self._on_engine_status_ready, queued
        )
        self._engine_status_worker.finished.connect(
            self._engine_status_thread.quit, queued
        )
        self._engine_status_thread.finished.connect(
            self._engine_status_worker.deleteLater, queued
        )
        self._engine_status_thread.finished.connect(
            self._engine_status_thread.deleteLater, queued
        )
        self._engine_status_thread.start()

    def _on_engine_status_ready(self, statuses: list) -> None:
        if self._closing:
            return
        self._engine_statuses = list(statuses)
        self._engine_status_loading = False
        self._engine_status_worker = None
        self._engine_status_thread = None
        self._sync_profile_desc()

    def _refresh_summary(self) -> None:
        paths = self._docs_card.paths()
        count = len(paths)
        profile = profile_for(self._profile_id())
        total = self._docs_total_bytes
        options = self._compression_options()
        rows = [
            f"<b>Documentos:</b> {count}",
            f"<b>Peso de entrada:</b> {format_bytes(total)}",
            f"<b>Perfil:</b> {profile.label}",
            f"<b>Motor:</b> {self._engine_combo.currentText()}",
            f"<b>Imagenes:</b> {options.dpi_target} DPI / JPEG {options.quality}%",
            f"<b>Validacion:</b> {self._validation_combo.currentText()}",
            f"<b>Reglas:</b> {self._page_rules_panel.summary_text()}",
            "<b>Salida:</b> PDF temporal por documento",
        ]
        if count == 0:
            rows.insert(0, "<span style='color:#E5484D;'>Atencion: no hay documentos cargados.</span>")
        self._proc_step.set_summary_html(
            "<div style='line-height:165%;'>" + "<br>".join(rows) + "</div>"
        )

    def _validate_ready(self) -> Optional[str]:
        if self._docs_card.is_empty():
            return "Agrega al menos un PDF."
        if self._page_rules_panel.has_rules() and self._engine_mode() in {
            "qpdf",
            "ghostscript",
            "fast",
            "turbo",
        }:
            return "Las reglas por pagina requieren motor Automatico o Motor interno libre."
        missing = self._missing_selected_engine()
        if missing:
            return f"{missing} no esta disponible en esta PC."
        if self._dpi_target_spin.value() >= self._dpi_threshold_spin.value():
            return "El DPI objetivo debe ser menor que el umbral de procesamiento."
        rules_error = self._page_rules_error_for_paths(self._docs_card.paths())
        if rules_error:
            return rules_error
        return None

    def _page_rules_error_for_paths(self, paths: List[str]) -> str:
        rules = self._page_rules_panel.rules()
        if not rules:
            return ""
        panel_error = self._page_rules_panel.validation_error()
        if panel_error:
            return panel_error
        for path in paths:
            page_count = _pdf_page_count(path)
            if page_count <= 0:
                return f"No se pudo leer el numero de paginas de {Path(path).name}."
            try:
                build_page_compression_plan(page_count, self._profile_id(), rules)
            except ValueError as exc:
                return f"{Path(path).name}: {exc}"
        return ""

    def _missing_selected_engine(self) -> str:
        mode = self._engine_mode()
        if not self._engine_statuses:
            return ""
        statuses = {engine.id: engine.available for engine in self._engine_statuses}
        if mode == "qpdf" and not statuses.get("qpdf", False):
            return "QPDF"
        if mode in {"ghostscript", "fast"} and not statuses.get("ghostscript", False):
            return "Ghostscript"
        return ""

    def _build_jobs(self) -> List[CompressJob]:
        out_dir = make_run_dir("ComprimirPDF")
        reserved: set[str] = set()
        add_suffix = add_tool_suffix_enabled()
        profile_id = self._profile_id()
        options = self._compression_options()
        jobs: List[CompressJob] = []
        for path in self._docs_card.paths():
            out_path = unique_output_path_for_source(
                out_dir,
                path,
                extension=".pdf",
                tool_suffix="comprimido",
                add_tool_suffix=add_suffix,
                reserved=reserved,
                fallback="documento",
            )
            jobs.append(
                CompressJob(
                    pdf_path=path,
                    output_path=str(out_path),
                    profile_id=profile_id,
                    options=options,
                    page_rules=self._page_rules_panel.rules(),
                )
            )
        return jobs

    def _on_run(self) -> None:
        self._stop_active_worker()
        if self._worker_thread is not None or self._prepare_thread is not None:
            return
        if self._docs_card.is_empty():
            show_warning(self, "Falta informacion", "Agrega al menos un PDF.")
            return

        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []
        self._sync_recompress_button(running=True)

        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Preparando compresion...")

        request = _CompressRunRequest(
            paths=self._docs_card.paths(),
            profile_id=self._profile_id(),
            options=self._compression_options(),
            page_rules=self._page_rules_panel.rules(),
            add_tool_suffix=add_tool_suffix_enabled(),
        )
        self._prepare_worker = CompressPrepareWorker(request)
        self._prepare_thread = RunnerThread(self._prepare_worker.run, self)
        queued = Qt.ConnectionType.QueuedConnection
        self._prepare_worker.progress.connect(self._on_prepare_progress, queued)
        self._prepare_worker.finished.connect(self._on_prepare_finished, queued)
        self._prepare_worker.error.connect(self._on_prepare_error, queued)
        self._prepare_worker.finished.connect(self._prepare_thread.quit, queued)
        self._prepare_worker.error.connect(self._prepare_thread.quit, queued)
        self._prepare_thread.finished.connect(
            self._on_prepare_thread_finished, queued
        )
        self._prepare_thread.finished.connect(
            self._prepare_worker.deleteLater, queued
        )
        self._prepare_thread.finished.connect(
            self._prepare_thread.deleteLater, queued
        )
        self._prepare_thread.start()

    def _on_prepare_progress(self, msg: str) -> None:
        self._proc_step.set_progress(self._current_progress(), msg)

    def _on_prepare_finished(self, jobs: list) -> None:
        if not jobs:
            self._on_prepare_error("No hay documentos para comprimir.")
            return
        self._proc_step.set_progress(0, "Iniciando compresion...")
        self._start_compress_worker(list(jobs))

    def _on_prepare_error(self, msg: str) -> None:
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        self._sync_recompress_button(running=False)
        show_warning(self, "Falta informacion", msg)

    def _on_prepare_thread_finished(self) -> None:
        self._prepare_worker = None
        self._prepare_thread = None
        self._sync_recompress_button()
        self._apply_primary_glows()

    def _start_compress_worker(self, jobs: List[CompressJob]) -> None:
        self._worker = CompressWorker(
            jobs,
            isolated_process=_ISOLATED_COMPRESSION_ENABLED,
        )
        self._worker_thread = RunnerThread(self._worker.run, self)
        queued = Qt.ConnectionType.QueuedConnection
        self._worker.progress.connect(self._on_progress, queued)
        self._worker.finished.connect(self._on_finished, queued)
        self._worker.error.connect(self._on_error, queued)
        self._worker_thread.finished.connect(self._on_thread_finished, queued)
        self._worker_thread.finished.connect(self._worker.deleteLater, queued)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater, queued)
        self._worker_thread.start()

    def _on_cancel(self) -> None:
        if self._prepare_worker:
            self._prepare_worker.cancel()
        if self._worker:
            self._worker.cancel()
        self._proc_step.set_progress(self._current_progress(), "Cancelando...")

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        value = int(current / max(1, total) * 100)
        self._proc_step.set_progress(max(self._current_progress(), value), msg)

    def _on_finished(self, results: list) -> None:
        self.last_results = list(results)
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Compresion completada")

        output_paths = [
            result.output_path
            for result in self.last_results
            if result.success and result.output_path
        ]
        self.ctx.tray.add_items(output_paths, "Comprimir PDF")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        self._result_viewer.set_results(self.last_results)
        self._result_viewer.set_source_dirs([
            str(Path(result.job.pdf_path).parent)
            for result in self.last_results
        ])
        self._sync_recompress_button()

        ok = sum(1 for result in self.last_results if result.success)
        failed = len(self.last_results) - ok
        before = sum(result.input_bytes for result in self.last_results if result.success)
        after = sum(result.output_bytes for result in self.last_results if result.success)
        reduction = 0.0 if before <= 0 else max(0.0, (1.0 - after / before) * 100.0)
        saved = max(0, before - after)
        from ui.styles import COLORS as _C

        self._result_viewer.set_extra_stats([
            {
                "value": f"{reduction:.1f}%",
                "label": "reducción",
                "color": _C["success"] if reduction >= 5 else _C["text_muted"],
            },
            {
                "value": format_bytes(saved),
                "label": "ahorrado",
                "color": _C["accent"],
            },
            {
                "value": format_bytes(after),
                "label": "peso final",
                "color": _C["text"],
            },
        ])

        msg = (
            f"Se comprimieron {ok} PDF{'s' if ok != 1 else ''}.\n"
            f"Entrada: {format_bytes(before)}\n"
            f"Salida: {format_bytes(after)}\n"
            f"Reduccion: {reduction:.1f}%"
        )
        if failed:
            msg += f"\nCon error: {failed}"
            show_warning(self, "Compresion completada con avisos", msg)
        else:
            show_success(self, "Compresion completa", msg)
        self._switch_section(3)

    def _successful_output_paths(self) -> List[str]:
        paths: List[str] = []
        for result in self.last_results:
            output_path = result.output_path
            if result.success and output_path and Path(output_path).is_file():
                paths.append(output_path)
        return paths

    def _sync_recompress_button(self, *, running: Optional[bool] = None) -> None:
        button = getattr(self, "_recompress_btn", None)
        if button is None:
            return
        if running is None:
            running = self._prepare_thread is not None or self._worker_thread is not None
        button.setEnabled((not running) and bool(self._successful_output_paths()))

    def _on_recompress_results(self) -> None:
        output_paths = self._successful_output_paths()
        if not output_paths:
            self._sync_recompress_button()
            show_warning(
                self,
                "Sin PDF para recomprimir",
                "No hay resultados comprimidos disponibles para volver a procesar.",
            )
            return
        self._stop_active_worker()
        if self._worker_thread is not None or self._prepare_thread is not None:
            return

        self._docs_card.clear()
        self._docs_card.add_paths(output_paths)
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []
        self._proc_step.reset()
        self._sync_recompress_button()
        self._switch_section(2)
        QTimer.singleShot(0, self._on_run)

    def _results_summary_html(self, results: List[CompressResult]) -> str:
        ok = [result for result in results if result.success]
        failed = len(results) - len(ok)
        before = sum(result.input_bytes for result in ok)
        after = sum(result.output_bytes for result in ok)
        reduction = 0.0 if before <= 0 else max(0.0, (1.0 - after / before) * 100.0)
        saved = max(0, before - after)
        warnings = sum(1 for result in ok if result.warning)
        pieces = [
            f"<b>{len(ok)} PDF{'s' if len(ok) != 1 else ''} optimizado{'s' if len(ok) != 1 else ''}</b>",
            f"Entrada: {format_bytes(before)}",
            f"Salida: {format_bytes(after)}",
            f"Ahorro: {format_bytes(saved)} ({reduction:.1f}%)",
        ]
        if warnings:
            pieces.append(
                f"{warnings} ya estaba{'n' if warnings != 1 else ''} optimizado"
                + ("s" if warnings != 1 else "")
            )
        if failed:
            pieces.append(f"<span style='color:#E5484D;'>Errores: {failed}</span>")
        if not results:
            return "Sin resultados."
        return " &nbsp; · &nbsp; ".join(pieces)

    def _on_error(self, msg: str) -> None:
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        self._sync_recompress_button(running=False)
        show_error(self, "Error al comprimir PDFs", msg)

    def _on_thread_finished(self) -> None:
        self._worker = None
        self._worker_thread = None
        self._sync_recompress_button()
        self._apply_primary_glows()

    def _cleanup_thread(self) -> None:
        if self._prepare_worker:
            self._prepare_worker.cancel()
        if self._prepare_thread:
            _quit_thread(self._prepare_thread)
            self._prepare_thread = None
        self._prepare_worker = None
        if self._worker_thread:
            if self._worker:
                stop_now = getattr(self._worker, "stop_now", None)
                if callable(stop_now):
                    stop_now()
                else:
                    self._worker.cancel()
            _quit_thread(self._worker_thread)
            self._worker_thread = None
        self._worker = None
        if self._engine_status_thread:
            _quit_thread(self._engine_status_thread)
            self._engine_status_thread = None
        self._engine_status_worker = None
        if self._docs_info_thread:
            _quit_thread(self._docs_info_thread)
            self._docs_info_thread = None
        self._docs_info_worker = None

    def _current_progress(self) -> int:
        bar = getattr(self._proc_step, "_prog_bar", None)
        return int(bar.value()) if bar is not None else 0

    def _open_in_explorer(self, path: str) -> None:
        from ui.common.open_utils import open_folder
        open_folder(self, path, title="Abrir carpeta")

    def _reset_session(self) -> None:
        self._cleanup_thread()
        self.last_results = []
        self._docs_card.clear()
        self._docs_summary_lbl.setText("Sin documentos cargados.")
        self._profile_combo.setCurrentIndex(1)
        self._engine_combo.setCurrentIndex(0)
        self._validation_combo.setCurrentIndex(0)
        self._page_rules_panel.clear_rules()
        self._sync_controls_from_profile()
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._sync_recompress_button()
        self._proc_step.reset()
        self._switch_section(0)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        from ui.common.file_ordering import paths_from_mime_data

        self.handle_drop(paths_from_mime_data(event.mimeData()))
        event.acceptProposedAction()

    def closeEvent(self, event) -> None:
        self._closing = True
        self._cleanup_thread()
        super().closeEvent(event)

    def deleteLater(self) -> None:  # type: ignore[override]
        self._closing = True
        self._cleanup_thread()
        super().deleteLater()


def _file_size(path: str) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def _resolved_path(path: str) -> str:
    try:
        return str(Path(path).resolve())
    except Exception:
        return str(path)


def _is_native_crash_returncode(returncode: int | None) -> bool:
    if returncode is None or returncode == 0:
        return False
    if returncode < 0:
        return True
    return returncode >= 0xC0000000


def _native_crash_message(details: str) -> str:
    detail_text = _short_text(details.strip(), 180) if details else ""
    if "3221225477" in detail_text or "0xC0000005" in detail_text.upper():
        reason = "access violation del motor nativo"
    else:
        reason = "cierre inesperado del motor nativo"
    if detail_text:
        return (
            f"No se pudo comprimir este PDF: {reason}. "
            f"El documento se omitio para proteger la aplicacion. Detalle: {detail_text}"
        )
    return (
        f"No se pudo comprimir este PDF: {reason}. "
        "El documento se omitio para proteger la aplicacion."
    )


def _quit_thread(thread: QThread, timeout_ms: int = 2000) -> None:
    try:
        if thread.isRunning():
            thread.quit()
            thread.wait(timeout_ms)
    except RuntimeError:
        pass


def _prepare_compress_jobs(
    request: _CompressRunRequest,
    *,
    should_cancel,
) -> List[CompressJob]:
    if should_cancel():
        return []
    if not request.paths:
        raise RuntimeError("Agrega al menos un PDF.")
    if request.page_rules and request.options.engine_mode in {
        "qpdf",
        "ghostscript",
        "fast",
        "turbo",
    }:
        raise RuntimeError(
            "Las reglas por pagina requieren motor Automatico o Motor interno libre."
        )
    if request.options.dpi_target is not None and request.options.dpi_threshold is not None:
        if request.options.dpi_target >= request.options.dpi_threshold:
            raise RuntimeError("El DPI objetivo debe ser menor que el umbral de procesamiento.")

    missing = _missing_engine_for_options(request.options)
    if missing:
        raise RuntimeError(f"{missing} no esta disponible en esta PC.")

    rules_error = _page_rules_error_for_request(request)
    if rules_error:
        raise RuntimeError(rules_error)

    out_dir = make_run_dir("ComprimirPDF")
    reserved: set[str] = set()
    jobs: List[CompressJob] = []
    for path in request.paths:
        if should_cancel():
            break
        out_path = unique_output_path_for_source(
            out_dir,
            path,
            extension=".pdf",
            tool_suffix="comprimido",
            add_tool_suffix=request.add_tool_suffix,
            reserved=reserved,
            fallback="documento",
        )
        jobs.append(
            CompressJob(
                pdf_path=path,
                output_path=str(out_path),
                profile_id=request.profile_id,
                options=request.options,
                page_rules=list(request.page_rules),
            )
        )
    return jobs


def _missing_engine_for_options(options: CompressOptions) -> str:
    mode = options.engine_mode
    if mode not in {"qpdf", "ghostscript", "fast"}:
        return ""
    statuses = {engine.id: engine.available for engine in optional_engine_status()}
    if mode == "qpdf" and not statuses.get("qpdf", False):
        return "QPDF"
    if mode in {"ghostscript", "fast"} and not statuses.get("ghostscript", False):
        return "Ghostscript"
    return ""


def _page_rules_error_for_request(request: _CompressRunRequest) -> str:
    rules = list(request.page_rules)
    if not rules:
        return ""
    custom_error = _custom_rules_error(rules)
    if custom_error:
        return custom_error
    for path in request.paths:
        page_count = _pdf_page_count(path)
        if page_count <= 0:
            return f"No se pudo leer el numero de paginas de {Path(path).name}."
        try:
            build_page_compression_plan(page_count, request.profile_id, rules)
        except ValueError as exc:
            return f"{Path(path).name}: {exc}"
    return ""


def _pdf_page_count(path: str) -> int:
    try:
        return pdf_page_count(path)
    except Exception:
        return 0


def _make_scroll_area(object_name: str, *, horizontal: bool) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setObjectName(object_name)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
        if horizontal
        else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setStyleSheet(
        f"QScrollArea#{object_name} {{ border: none; background: transparent; }}"
        f"QScrollArea#{object_name} > QWidget {{ background: transparent; }}"
    )
    scroll.viewport().setStyleSheet("background: transparent;")
    return scroll


def _make_spin(minimum: int, maximum: int, suffix: str) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSuffix(suffix)
    spin.setFixedHeight(32)
    spin.setMinimumWidth(96)
    spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return spin


def _option_row(label: str, widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    lbl = QLabel(label)
    lbl.setProperty("class", "CardHint")
    lbl.setWordWrap(True)
    lbl.setMinimumWidth(0)
    lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    row.addWidget(lbl, 1)
    row.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
    return row


def _short_text(value: str, limit: int = 46) -> str:
    if len(value) <= limit:
        return value
    return "..." + value[-(limit - 3):]
