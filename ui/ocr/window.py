"""OcrWindow - pipeline de extraccion OCR precisa para PDFs.

Pipeline:
    01 Documentos  ->  02 Precision  ->  03 Procesar  ->  04 Resultados
"""
from __future__ import annotations

from dataclasses import asdict
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

from PyQt6.QtCore import Qt, QObject, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QComboBox, QCheckBox, QFrame, QGridLayout,
    QApplication, QPlainTextEdit,
)

from core.ocr_engine import (
    OcrConfig, OcrJob, OcrJobResult, ocr_job_result_from_dict,
    available_languages, describe_languages, validate_tessdata,
)
from core.output_paths import make_run_dir, sanitize_filename
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.documents_step import DocumentsCard
from ui.common.process_step import ProcessStep
from ui.common.save_utils import save_files_as_batch
from ui.common.result_ui import ElidedLabel, configure_result_list
from ui.common.tool_scaffold import PipelineWindow
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.dialogs import show_error, show_info, show_success, show_warning
from ui.common.file_dialogs import get_save_file_name
from ui.common.icons import icon, set_button_icon


# ====================================================================== #
#  Worker
# ====================================================================== #

class OcrProcessWorker(QObject):
    """Supervisa un proceso OCR independiente para proteger la interfaz."""

    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    _POLL_SECONDS = 0.10
    _FORCE_CANCEL_AFTER_SECONDS = 2.0

    def __init__(self, jobs: List[OcrJob], config: OcrConfig) -> None:
        super().__init__()
        self.jobs = jobs
        self.config = config
        self._cancel_requested = False
        self._cancel_path: Optional[Path] = None
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def cancel(self) -> None:
        """Solicita cancelacion cooperativa al proceso OCR."""

        with self._lock:
            self._cancel_requested = True
            cancel_path = self._cancel_path
        if cancel_path:
            try:
                cancel_path.touch(exist_ok=True)
            except OSError:
                pass

    def stop_now(self) -> None:
        """Detiene el proceso auxiliar al cerrar PDFlex."""

        self.cancel()
        with self._lock:
            process = self._process
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def run(self) -> None:
        work_dir = Path(tempfile.mkdtemp(prefix="PDFlex_ocr_"))
        request_path = work_dir / "request.json"
        response_path = work_dir / "response.json"
        events_path = work_dir / "events.jsonl"
        cancel_path = work_dir / "cancel.signal"
        checkpoint_results: List[OcrJobResult] = []
        event_offset = 0
        results_to_emit: Optional[List[OcrJobResult]] = None
        error_to_emit = ""

        with self._lock:
            self._cancel_path = cancel_path

        try:
            request_path.write_text(
                json.dumps(
                    {
                        "jobs": [asdict(job) for job in self.jobs],
                        "config": asdict(self.config),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            events_path.touch()
            process = subprocess.Popen(
                self._build_command(
                    request_path,
                    response_path,
                    events_path,
                    cancel_path,
                ),
                cwd=str(Path(__file__).resolve().parents[2]),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=self._creation_flags(),
            )
            with self._lock:
                self._process = process

            self.progress.emit(0, 1, "Motor OCR aislado iniciado...")
            cancel_started_at: Optional[float] = None

            while process.poll() is None:
                event_offset = self._drain_events(
                    events_path,
                    event_offset,
                    checkpoint_results,
                )
                with self._lock:
                    cancel_requested = self._cancel_requested
                if cancel_requested:
                    if cancel_started_at is None:
                        cancel_started_at = time.monotonic()
                    elif (
                        time.monotonic() - cancel_started_at
                        >= self._FORCE_CANCEL_AFTER_SECONDS
                    ):
                        process.terminate()
                time.sleep(self._POLL_SECONDS)

            self._drain_events(events_path, event_offset, checkpoint_results)

            payload = self._read_response(response_path)
            with self._lock:
                cancelled = self._cancel_requested
            if payload:
                status = payload.get("status")
                if status == "error":
                    raise RuntimeError(
                        payload.get("error") or "El proceso OCR termino con error."
                    )
                results = [
                    ocr_job_result_from_dict(result_data)
                    for result_data in payload.get("results", [])
                ]
            else:
                if not cancelled:
                    raise RuntimeError(
                        "El motor OCR aislado termino sin entregar una respuesta."
                    )
                results = checkpoint_results

            if cancelled and not any(result.cancelled for result in results):
                results.append(self._cancelled_result(len(checkpoint_results)))
            elif process.returncode not in (0, None) and not cancelled:
                raise RuntimeError("El motor OCR aislado se cerro inesperadamente.")

            results_to_emit = results
        except Exception as exc:
            error_to_emit = str(exc)
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
            self._cleanup_work_dir(work_dir)

        if error_to_emit:
            self.error.emit(error_to_emit)
        elif results_to_emit is not None:
            self.finished.emit(results_to_emit)

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
            return [sys.executable, "--pdflex-ocr-worker", *args]
        return [sys.executable, "-m", "core.ocr_process", *args]

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
        checkpoint_results: List[OcrJobResult],
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
                    if event.get("type") == "progress":
                        self.progress.emit(
                            int(event.get("current", 0)),
                            max(1, int(event.get("total", 1))),
                            str(event.get("message", "")),
                        )
                    elif event.get("type") == "result":
                        checkpoint_results.append(
                            ocr_job_result_from_dict(event["result"])
                        )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return offset

    @staticmethod
    def _read_response(path: Path) -> Optional[dict]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _cleanup_work_dir(path: Path) -> None:
        """Tolera el breve retraso de Windows al liberar archivos heredados."""

        for attempt in range(10):
            try:
                shutil.rmtree(path)
                return
            except FileNotFoundError:
                return
            except OSError:
                if attempt == 9:
                    return
                time.sleep(0.10)

    def _cancelled_result(self, completed_jobs: int) -> OcrJobResult:
        job_index = min(completed_jobs, max(0, len(self.jobs) - 1))
        job = self.jobs[job_index] if self.jobs else OcrJob("", "")
        return OcrJobResult(
            job=job,
            success=False,
            cancelled=True,
            error="Proceso cancelado por el usuario.",
        )


# ====================================================================== #
#  Visor de resultados
# ====================================================================== #

class TextResultsViewer(QWidget):
    """Lista de transcripciones, metricas y preview del texto editable."""

    openInExplorer = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._results: List[OcrJobResult] = []
        self._current: Optional[OcrJobResult] = None
        self._build()

    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        left = QFrame()
        left.setProperty("class", "Card")
        left.setFixedWidth(270)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 14, 14, 14)
        lv.setSpacing(10)

        title = QLabel("Transcripciones")
        title.setProperty("class", "CardTitle")
        lv.addWidget(title)

        self._doc_list = QListWidget()
        configure_result_list(self._doc_list)
        self._doc_list.itemSelectionChanged.connect(self._on_doc_selected)
        lv.addWidget(self._doc_list, 1)
        root.addWidget(left)

        right = QFrame()
        right.setProperty("class", "Card")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(16, 14, 16, 14)
        rv.setSpacing(10)

        header = QVBoxLayout()
        header.setSpacing(8)
        self._title_lbl = ElidedLabel("Selecciona un documento")
        self._title_lbl.setProperty("class", "CardTitle")
        header.addWidget(self._title_lbl)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        self._open_docx_btn = QPushButton("Abrir Word")
        self._open_docx_btn.setProperty("class", "Ghost")
        set_button_icon(self._open_docx_btn, "external-link")
        self._open_docx_btn.clicked.connect(self._open_docx)
        actions.addWidget(self._open_docx_btn)

        self._open_txt_btn = QPushButton("Abrir TXT")
        self._open_txt_btn.setProperty("class", "Ghost")
        set_button_icon(self._open_txt_btn, "file-text")
        self._open_txt_btn.clicked.connect(self._open_txt)
        actions.addWidget(self._open_txt_btn)

        self._open_folder_btn = QPushButton("Abrir carpeta")
        self._open_folder_btn.setProperty("class", "Ghost")
        set_button_icon(self._open_folder_btn, "folder-open")
        self._open_folder_btn.clicked.connect(self._open_folder)
        actions.addWidget(self._open_folder_btn)

        self._save_docx_btn = QPushButton("Guardar DOCX")
        self._save_docx_btn.setProperty("class", "Ghost")
        set_button_icon(self._save_docx_btn, "save")
        self._save_docx_btn.clicked.connect(self._save_docx_as)
        actions.addWidget(self._save_docx_btn)

        self._save_txt_btn = QPushButton("Guardar TXT")
        self._save_txt_btn.setProperty("class", "Ghost")
        set_button_icon(self._save_txt_btn, "save")
        self._save_txt_btn.clicked.connect(self._save_txt_as)
        actions.addWidget(self._save_txt_btn)

        self._save_all_btn = QPushButton("Guardar todo")
        self._save_all_btn.setProperty("class", "Ghost")
        set_button_icon(self._save_all_btn, "download")
        self._save_all_btn.clicked.connect(self._save_all_as)
        actions.addWidget(self._save_all_btn)
        header.addLayout(actions)
        rv.addLayout(header)

        self._stats_lbl = QLabel("")
        self._stats_lbl.setProperty("class", "CardHint")
        self._stats_lbl.setWordWrap(True)
        rv.addWidget(self._stats_lbl)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_lbl = QLabel("Vista:")
        filter_lbl.setProperty("class", "CardHint")
        filter_row.addWidget(filter_lbl)

        self._page_combo = QComboBox()
        self._page_combo.setMinimumWidth(220)
        self._page_combo.currentIndexChanged.connect(self._refresh_preview)
        filter_row.addWidget(self._page_combo)
        filter_row.addStretch()
        rv.addLayout(filter_row)

        self._page_meta_lbl = QLabel("")
        self._page_meta_lbl.setProperty("class", "CardHint")
        self._page_meta_lbl.setWordWrap(True)
        rv.addWidget(self._page_meta_lbl)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText("El texto reconocido aparecerá aquí.")
        self._preview.setStyleSheet(
            "QPlainTextEdit {"
            " background: #0D0D10; border: 1px solid #26262C;"
            " border-radius: 8px; padding: 10px; color: #ECEDEE;"
            " font-family: 'Consolas'; font-size: 12px;"
            " selection-background-color: #5E6AD2;"
            "}"
        )
        rv.addWidget(self._preview, 1)
        root.addWidget(right, 1)

        self._set_actions_enabled(False)

    def set_results(self, results: List[OcrJobResult]) -> None:
        self.clear_results()
        self._results = list(results)
        for result in results:
            name = Path(result.job.pdf_path).name
            item = QListWidgetItem(name)
            item.setToolTip(result.job.pdf_path)
            if not result.success:
                item.setIcon(icon("warning", "#E5484D", 16))
                item.setForeground(QColor("#E5484D"))
            elif result.warning_pages:
                item.setIcon(icon("warning", "#F5A623", 16))
                item.setForeground(QColor("#F5A623"))
            self._doc_list.addItem(item)
        if results:
            self._doc_list.setCurrentRow(0)

    def clear_results(self) -> None:
        self._results = []
        self._current = None
        self._doc_list.clear()
        self._page_combo.clear()
        self._preview.clear()
        self._title_lbl.setText("Selecciona un documento")
        self._stats_lbl.setText("")
        self._page_meta_lbl.setText("")
        self._set_actions_enabled(False)

    def _set_actions_enabled(self, enabled: bool) -> None:
        result = self._current if enabled else None
        has_docx = bool(result and result.docx_path and Path(result.docx_path).exists())
        has_txt = bool(result and result.txt_path and Path(result.txt_path).exists())
        has_output = has_docx or has_txt or bool(
            result and result.output_path and Path(result.output_path).exists()
        )
        self._open_docx_btn.setEnabled(has_docx)
        self._open_txt_btn.setEnabled(has_txt)
        self._open_folder_btn.setEnabled(has_output)
        self._save_docx_btn.setEnabled(has_docx)
        self._save_txt_btn.setEnabled(has_txt)
        self._save_all_btn.setEnabled(bool(self._saveable_paths()))

    def _saveable_paths(self) -> List[str]:
        paths: list[str] = []
        for result in self._results:
            if not result.success:
                continue
            for path in (result.docx_path, result.txt_path):
                if path and Path(path).exists():
                    paths.append(path)
        return paths

    def _on_doc_selected(self) -> None:
        row = self._doc_list.currentRow()
        if row < 0 or row >= len(self._results):
            return
        self._current = self._results[row]
        result = self._current
        self._title_lbl.setText(Path(result.job.pdf_path).name)
        self._set_actions_enabled(result.success)

        if not result.success:
            self._stats_lbl.setText(result.error or "No se pudo procesar este documento.")
            self._page_combo.clear()
            self._preview.clear()
            return

        quality = int(round(result.average_quality * 100))
        page_total = len(result.page_results)
        page_text = f"{page_total} página" + ("s" if page_total != 1 else "")
        warning_text = (
            f" · {result.warning_pages} página"
            + ("s" if result.warning_pages != 1 else "")
            + " para revisar"
            if result.warning_pages else ""
        )
        self._stats_lbl.setText(
            f"{page_text} · {result.word_count:,} palabras · "
            f"{result.native_pages} con texto nativo · {result.ocr_pages} con OCR · "
            f"índice de legibilidad {quality}%{warning_text}"
        )

        self._page_combo.blockSignals(True)
        self._page_combo.clear()
        self._page_combo.addItem("Documento completo")
        for page in result.page_results:
            suffix = " ! revisar" if page.warning else ""
            self._page_combo.addItem(f"Página {page.page_index + 1}{suffix}")
        self._page_combo.blockSignals(False)
        self._page_combo.setCurrentIndex(0)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if not self._current:
            return
        index = self._page_combo.currentIndex()
        if index <= 0:
            chunks = []
            for page in self._current.page_results:
                chunks.append(
                    f"==================== PÁGINA {page.page_index + 1} ====================\n\n"
                    + (page.text or "[Sin texto legible]")
                )
            self._preview.setPlainText("\n\n".join(chunks))
            self._page_meta_lbl.setText(
                "Vista completa de la transcripción. Usa el selector para revisar una página."
            )
            return

        page_index = index - 1
        if page_index >= len(self._current.page_results):
            return
        page = self._current.page_results[page_index]
        self._preview.setPlainText(page.text or "[Sin texto legible]")
        quality = int(round(page.quality_score * 100))
        detail = (
            f"{page.variant} · {page.word_count} palabras · "
            f"índice de legibilidad {quality}%"
        )
        if page.warning:
            detail += f" · Revision sugerida: {page.warning}"
        self._page_meta_lbl.setText(detail)

    def _open_docx(self) -> None:
        if self._current and self._current.docx_path and Path(self._current.docx_path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._current.docx_path))

    def _open_txt(self) -> None:
        if self._current and self._current.txt_path and Path(self._current.txt_path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._current.txt_path))

    def _open_folder(self) -> None:
        if not self._current:
            return
        for path in (self._current.output_path, self._current.docx_path, self._current.txt_path):
            if path and Path(path).exists():
                self.openInExplorer.emit(path)
                return

    def _save_docx_as(self) -> None:
        if not (self._current and self._current.docx_path):
            return
        src = Path(self._current.docx_path)
        if not src.exists():
            return
        start_dir = str(Path(self._current.job.pdf_path).parent)
        dest, _ = get_save_file_name(
            self, "Guardar DOCX como",
            str(Path(start_dir) / src.name),
            "Word (*.docx)",
        )
        if dest:
            shutil.copy2(str(src), dest)

    def _save_txt_as(self) -> None:
        if not (self._current and self._current.txt_path):
            return
        src = Path(self._current.txt_path)
        if not src.exists():
            return
        start_dir = str(Path(self._current.job.pdf_path).parent)
        dest, _ = get_save_file_name(
            self, "Guardar TXT como",
            str(Path(start_dir) / src.name),
            "Texto (*.txt)",
        )
        if dest:
            shutil.copy2(str(src), dest)

    def _save_all_as(self) -> None:
        start_dir = Path.home()
        if self._current is not None:
            start_dir = Path(self._current.job.pdf_path).parent
        save_files_as_batch(
            self,
            self._saveable_paths(),
            title="Guardar todo",
            start_dir=start_dir,
        )


# ====================================================================== #
#  Ventana OCR
# ====================================================================== #

class OcrWindow(PipelineWindow):

    SECTIONS = [
        ("01", "Documentos", "Carga los PDFs a transcribir"),
        ("02", "Precisión",  "Configura idioma y estrategia OCR"),
        ("03", "Procesar",   "Ejecuta la extracción local"),
        ("04", "Resultados", "Revisa y abre las transcripciones"),
    ]
    BRAND = "OCR de PDF"
    TAGLINE = "Escaneos a texto editable"
    ACCENT_COLOR = "#FF6B9A"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[OcrJobResult] = []
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[OcrProcessWorker] = None
        self._shutting_down = False

        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._shutdown_worker)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_precision_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    # ------------------------------------------------------------------ #
    # Paso 01: Documentos
    # ------------------------------------------------------------------ #

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documentos para OCR",
            "Carga uno o varios PDFs. La extracción ocurre localmente en tu equipo; "
            "los archivos no se suben a internet.",
        ))

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=True,
            show_thumbnails=True,
            thumb_size=(64, 82),
            file_filter="PDF (*.pdf)",
        )
        outer.addWidget(self._docs_card, 1)

        nav = QHBoxLayout()
        nav.addStretch()
        nxt = QPushButton("Continuar")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        set_button_icon(nxt, "arrow-right")
        nxt.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(nxt)
        outer.addLayout(nav)
        return page

    # ------------------------------------------------------------------ #
    # Paso 02: Precision
    # ------------------------------------------------------------------ #

    def _build_precision_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Precisión del reconocimiento",
            "El modo recomendado combina texto nativo exacto con OCR neuronal local "
            "para escaneos, fotografías y páginas convertidas a imagen.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        language_card = make_card(
            "Idiomas del documento",
            "Elegir solo los idiomas necesarios mejora la precisión.",
        )
        self._language_combo = QComboBox()
        self._language_combo.addItem("Español + Inglés (recomendado)", "spa+eng")
        self._language_combo.addItem("Solo español", "spa")
        self._language_combo.addItem("Solo inglés", "eng")
        card_layout(language_card).addWidget(self._language_combo)
        grid.addWidget(language_card, 0, 0)

        dpi_card = make_card(
            "Resolucion de analisis",
            "300 DPI es el punto óptimo habitual. Usa 400 DPI para originales pequeños.",
        )
        self._dpi_combo = QComboBox()
        self._dpi_combo.addItem("300 DPI - Alta calidad (recomendado)", 300)
        self._dpi_combo.addItem("400 DPI - Texto pequeño o escaneo fino", 400)
        self._dpi_combo.addItem("240 DPI - Más rápido", 240)
        card_layout(dpi_card).addWidget(self._dpi_combo)
        grid.addWidget(dpi_card, 0, 1)

        strategy_card = make_card(
            "Estrategia",
            "Máxima precisión compara variantes y recupera páginas difíciles.",
        )
        self._precision_combo = QComboBox()
        self._precision_combo.addItem("Máxima precisión (recomendado)", "maximum")
        self._precision_combo.addItem("Equilibrado", "balanced")
        self._precision_combo.addItem("Rápido", "fast")
        self._precision_combo.currentIndexChanged.connect(self._sync_precision_options)
        card_layout(strategy_card).addWidget(self._precision_combo)
        grid.addWidget(strategy_card, 1, 0)

        output_card = make_card(
            "Entregable",
            "Word ofrece lectura y edicion; TXT conserva una copia simple y universal.",
        )
        self._output_combo = QComboBox()
        self._output_combo.addItem("Word editable + TXT (recomendado)", "docx_txt")
        self._output_combo.addItem("Solo Word editable", "docx")
        self._output_combo.addItem("Solo TXT", "txt")
        card_layout(output_card).addWidget(self._output_combo)
        grid.addWidget(output_card, 1, 1)

        options_card = make_card(
            "Optimizaciones automáticas",
            "Las opciones activas priorizan fidelidad incluso si el proceso tarda mas.",
        )
        options_layout = card_layout(options_card)
        self._native_chk = QCheckBox(
            "Conservar texto nativo confiable (exactitud maxima y menor tiempo)"
        )
        self._native_chk.setChecked(True)
        options_layout.addWidget(self._native_chk)

        self._enhance_chk = QCheckBox(
            "Comparar una variante mejorada para escaneos tenues o poco contrastados"
        )
        self._enhance_chk.setChecked(True)
        options_layout.addWidget(self._enhance_chk)

        self._rotation_chk = QCheckBox(
            "Recuperar automáticamente páginas giradas cuando la lectura sea débil"
        )
        self._rotation_chk.setChecked(True)
        options_layout.addWidget(self._rotation_chk)
        grid.addWidget(options_card, 2, 0, 1, 2)

        status_card = make_card("Motor OCR local")
        status_layout = card_layout(status_card)
        languages = set(available_languages())
        ready = {"spa", "eng"}.issubset(languages)
        status = QLabel(
            "Listo: motor aislado y modelos oficiales de máxima calidad para español e inglés."
            if ready else
            "Atención: faltan modelos OCR. Reinstala PDFlex antes de procesar."
        )
        status.setWordWrap(True)
        status.setStyleSheet(
            "color: #3BD37C; font-size: 12px;"
            if ready else
            "color: #E5484D; font-size: 12px;"
        )
        status_layout.addWidget(status)
        grid.addWidget(status_card, 3, 0, 1, 2)

        outer.addLayout(grid)
        outer.addStretch(1)

        nav = QHBoxLayout()
        back = QPushButton("Documentos")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(0))
        nav.addWidget(back)
        nav.addStretch()
        nxt = QPushButton("Continuar")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        set_button_icon(nxt, "arrow-right")
        nxt.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(nxt)
        outer.addLayout(nav)

        self._sync_precision_options()
        return page

    # ------------------------------------------------------------------ #
    # Paso 03: Procesar
    # ------------------------------------------------------------------ #

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar OCR",
            "Genera transcripciones temporales; usa \"Guardar como\" para conservarlas.",
        ))

        self._proc_step = ProcessStep(
            run_label="Extraer texto con OCR",
            show_output_dir=False,
        )
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Precisión")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(back)
        outer.addLayout(nav)
        return page

    # ------------------------------------------------------------------ #
    # Paso 04: Resultados
    # ------------------------------------------------------------------ #

    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultados",
            "Revisa la transcripción, identifica páginas para validar y abre el Word o TXT.",
        ))

        self._results_viewer = TextResultsViewer()
        self._results_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._results_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        nav.addStretch()

        restart = QPushButton("Nueva sesión")
        restart.setProperty("class", "Primary")
        restart.setMinimumWidth(180)
        set_button_icon(restart, "refresh-cw")
        restart.clicked.connect(self._reset_session)
        nav.addWidget(restart)
        outer.addLayout(nav)
        return page

    # ------------------------------------------------------------------ #
    # Navegacion y configuracion
    # ------------------------------------------------------------------ #

    def _on_section_activated(self, idx: int) -> None:
        if idx == 2:
            self._refresh_summary()

    def _sync_precision_options(self) -> None:
        fast = self._precision_combo.currentData() == "fast"
        self._enhance_chk.setEnabled(not fast)
        self._rotation_chk.setEnabled(not fast)

    def _read_config(self) -> OcrConfig:
        return OcrConfig(
            languages=str(self._language_combo.currentData()),
            dpi=int(self._dpi_combo.currentData()),
            precision_mode=str(self._precision_combo.currentData()),
            preserve_native_text=self._native_chk.isChecked(),
            enhance_scans=self._enhance_chk.isChecked(),
            recover_rotated_pages=self._rotation_chk.isChecked(),
            output_mode=str(self._output_combo.currentData()),
        )

    def _refresh_summary(self) -> None:
        cfg = self._read_config()
        mode_names = {
            "maximum": "Máxima precisión",
            "balanced": "Equilibrado",
            "fast": "Rápido",
        }
        output_names = {
            "docx_txt": "Word editable + TXT",
            "docx": "Word editable",
            "txt": "TXT",
        }
        rows = [
            f"<b>Documentos:</b> &nbsp; {self._docs_card.count()}",
            f"<b>Idiomas:</b> &nbsp; {describe_languages(cfg.languages)}",
            f"<b>Resolucion:</b> &nbsp; {cfg.dpi} DPI",
            f"<b>Estrategia:</b> &nbsp; {mode_names[cfg.precision_mode]}",
            f"<b>Entregable:</b> &nbsp; {output_names[cfg.output_mode]}",
            f"<b>Texto nativo:</b> &nbsp; {'Conservar cuando sea confiable' if cfg.preserve_native_text else 'Forzar OCR'}",
            "<b>Aislamiento:</b> &nbsp; Proceso independiente con prioridad reducida",
        ]
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )

    def _validate_ready(self) -> Optional[str]:
        if self._docs_card.is_empty():
            return "Agrega al menos un documento PDF."
        cfg = self._read_config()
        model_error = validate_tessdata(cfg.languages)
        if model_error:
            return model_error
        if cfg.export_docx:
            try:
                import docx  # noqa: F401
            except ImportError:
                return (
                    "Falta python-docx para exportar Word. "
                    "Ejecuta: pip install -r requirements.txt"
                )
        return None

    # ------------------------------------------------------------------ #
    # Procesamiento
    # ------------------------------------------------------------------ #

    def _build_jobs(self) -> List[OcrJob]:
        output_dir = str(make_run_dir("OCR"))
        used_names = set()
        jobs = []
        add_suffix = add_tool_suffix_enabled()
        for pdf_path in self._docs_card.paths():
            base = sanitize_filename(Path(pdf_path).stem, fallback="documento")
            unique = base
            suffix = 2
            while unique.casefold() in used_names:
                unique = f"{base}_{suffix}"
                suffix += 1
            used_names.add(unique.casefold())
            jobs.append(OcrJob(
                pdf_path=pdf_path,
                output_dir=output_dir,
                base_name=unique,
                tool_suffix="OCR",
                add_tool_suffix=add_suffix,
            ))
        return jobs

    def _on_run(self) -> None:
        error = self._validate_ready()
        if error:
            show_warning(self, "Falta información", error)
            return
        if self._worker_thread is not None:
            return

        self._results_viewer.clear_results()
        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Preparando motor OCR aislado...")

        self._worker_thread = QThread(self)
        self._worker = OcrProcessWorker(self._build_jobs(), self._read_config())
        self._worker.moveToThread(self._worker_thread)

        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._proc_step.set_progress(
            self._proc_step._prog_bar.value(),
            "Deteniendo motor OCR aislado...",
        )

    def _on_progress(self, current: int, total: int, message: str) -> None:
        self._proc_step.set_progress(int(current / max(1, total) * 100), message)

    def _on_finished(self, results: list) -> None:
        self.last_results = list(results)
        self._proc_step.set_running(False)
        self._worker_thread = None
        self._worker = None

        cancelled = any(result.cancelled for result in results)
        successful = [result for result in results if result.success]
        failed = [result for result in results if not result.success and not result.cancelled]

        if self._shutting_down:
            return

        if cancelled:
            self._proc_step.set_progress(
                self._proc_step._prog_bar.value(),
                "Proceso cancelado",
            )
            show_info(
                self,
                "OCR cancelado",
                "El proceso OCR aislado se detuvo de forma segura.",
            )
        else:
            self._proc_step.set_progress(100, "Extracción completada")
            extra = f"\nCon error: {len(failed)}" if failed else ""
            transcript_text = (
                "transcripción" if len(successful) == 1 else "transcripciones"
            )
            show_success(
                self,
                "OCR completado",
                f"Se generaron {len(successful)} {transcript_text}.{extra}",
            )

        self._results_viewer.set_results(self.last_results)
        self._switch_section(3)

    def _on_worker_error(self, message: str) -> None:
        self._proc_step.set_running(False)
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
            self._worker_thread.deleteLater()
            self._worker_thread = None
            self._worker = None
        if not self._shutting_down:
            show_error(self, "Error OCR", message)

    def _open_in_explorer(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _shutdown_worker(self) -> None:
        """Finaliza el proceso OCR antes de destruir la aplicacion."""

        self._shutting_down = True
        if self._worker:
            self._worker.stop_now()
        if self._worker_thread and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait(4000)

    def _reset_session(self) -> None:
        self.last_results = []
        self._results_viewer.clear_results()
        self._docs_card.clear()
        self._proc_step.reset()
        self._switch_section(0)

    # ------------------------------------------------------------------ #
    # API PipelineWindow y drag & drop
    # ------------------------------------------------------------------ #

    def set_inputs(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self.handle_drop(paths)
