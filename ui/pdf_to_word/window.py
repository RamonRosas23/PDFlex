"""PdfToWordWindow - convert PDFs to editable DOCX files."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import fitz
from PyQt6.QtCore import QObject, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QCheckBox, QComboBox, QGridLayout,
)

from core.output_paths import make_run_dir
from core.pdf_to_word_engine import (
    PdfToWordConfig,
    PdfToWordEngine,
    PdfToWordJob,
    make_pdf_to_word_jobs,
)
from core.ocr_engine import available_languages, describe_languages, validate_tessdata
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.documents_step import DocumentsCard
from ui.common.icons import set_button_icon
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.process_step import ProcessStep
from ui.common.tool_scaffold import PipelineWindow, RunnerThread
from ui.ocr.window import TextResultsViewer


class PdfToWordWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[PdfToWordJob]) -> None:
        super().__init__()
        self.jobs = jobs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = PdfToWordEngine().run_batch(
                self.jobs,
                progress=lambda c, t, m: self.progress.emit(c, t, m),
                should_cancel=lambda: self._cancel,
            )
            if self._cancel:
                self.error.emit("Operacion cancelada.")
            else:
                self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


class PdfToWordWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documentos", "Carga PDFs a convertir"),
        ("02", "Conversion", "Configura texto nativo y OCR"),
        ("03", "Procesar", "Genera Word editable"),
        ("04", "Resultados", "Revisa y guarda DOCX"),
    ]
    BRAND = "PDF a Word"
    TAGLINE = "Convierte PDFs a DOCX editable"
    ACCENT_COLOR = "#2563EB"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results = []
        self._worker: Optional[PdfToWordWorker] = None
        self._worker_thread: Optional[QThread] = None
        self._pdf_page_cache: dict[str, int] = {}

        self._build_pages()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_conversion_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "PDFs a convertir",
            "Carga documentos con texto nativo o escaneos; PDFlex generara Word editable.",
        ))

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=False,
            show_thumbnails=True,
            thumb_size=(64, 82),
            file_filter="PDF (*.pdf)",
        )
        self._docs_card.files_changed.connect(self._on_docs_changed)
        outer.addWidget(self._docs_card, 1)

        self._docs_summary_lbl = QLabel("Sin documentos cargados.")
        self._docs_summary_lbl.setProperty("class", "CardHint")
        self._docs_summary_lbl.setWordWrap(True)
        outer.addWidget(self._docs_summary_lbl)

        return page

    def _build_conversion_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Conversion a Word",
            "Elige idioma, precision y fallback OCR para obtener texto editable.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        lang_card = make_card("Idioma")
        self._language_combo = QComboBox()
        self._language_combo.addItem("Español + Inglés (recomendado)", "spa+eng")
        self._language_combo.addItem("Solo español", "spa")
        self._language_combo.addItem("Solo inglés", "eng")
        card_layout(lang_card).addWidget(self._language_combo)
        grid.addWidget(lang_card, 0, 0)

        quality_card = make_card("Calidad")
        self._precision_combo = QComboBox()
        self._precision_combo.addItem("Equilibrado - recomendado", "balanced")
        self._precision_combo.addItem("Máxima precisión", "maximum")
        self._precision_combo.addItem("Rápido", "fast")
        self._precision_combo.currentIndexChanged.connect(self._sync_precision_options)
        card_layout(quality_card).addWidget(self._precision_combo)

        self._dpi_combo = QComboBox()
        self._dpi_combo.addItem("300 DPI - recomendado", 300)
        self._dpi_combo.addItem("400 DPI - texto pequeño", 400)
        self._dpi_combo.addItem("240 DPI - más rápido", 240)
        card_layout(quality_card).addWidget(self._dpi_combo)
        grid.addWidget(quality_card, 0, 1)

        options_card = make_card("Opciones")
        self._native_chk = QCheckBox("Usar texto nativo cuando sea confiable")
        self._native_chk.setChecked(True)
        card_layout(options_card).addWidget(self._native_chk)

        self._enhance_chk = QCheckBox("Mejorar escaneos tenues antes de OCR")
        self._enhance_chk.setChecked(True)
        card_layout(options_card).addWidget(self._enhance_chk)

        self._rotation_chk = QCheckBox("Recuperar paginas giradas automaticamente")
        self._rotation_chk.setChecked(True)
        card_layout(options_card).addWidget(self._rotation_chk)
        grid.addWidget(options_card, 1, 0)

        status_card = make_card("Motor local")
        languages = set(available_languages())
        ready = {"spa", "eng"}.issubset(languages)
        status = QLabel(
            "Listo para convertir PDFs nativos y escaneados a Word."
            if ready else
            "Faltan modelos OCR locales para algunos idiomas."
        )
        status.setWordWrap(True)
        status.setStyleSheet(
            "color:#3BD37C; font-size:12px;" if ready else "color:#E5484D; font-size:12px;"
        )
        card_layout(status_card).addWidget(status)
        grid.addWidget(status_card, 1, 1)

        outer.addLayout(grid)
        outer.addStretch(1)

        self._sync_precision_options()
        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Genera documentos Word temporales; usa Guardar DOCX o Guardar todo para conservarlos.",
        ))

        self._proc_step = ProcessStep(
            run_label="Convertir a Word",
            show_output_dir=False,
        )
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        return page

    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultados",
            "Abre los DOCX generados, revisa el texto editable y guarda el lote.",
        ))

        self._results_viewer = TextResultsViewer()
        self._results_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._results_viewer, 1)

        return page

    def _build_action_buttons(self) -> None:
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Convertir a Word")
        self._run_btn.setProperty("class", "Primary")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setMinimumWidth(160)
        set_button_icon(self._run_btn, "play")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        self._cancel_btn.setFixedHeight(36)
        set_button_icon(self._cancel_btn, "square", color="#E5484D")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._restart_btn = QPushButton("Nueva sesion")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "pdf_to_word")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()

    def _on_section_activated(self, idx: int) -> None:
        if idx == 2:
            self._refresh_summary()

    def set_inputs(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def _on_docs_changed(self, paths: List[str]) -> None:
        count = len(paths)
        if count == 0:
            self._docs_summary_lbl.setText("Sin documentos cargados.")
            return
        pages, total_size, error = self._input_stats(paths)
        if error:
            self._docs_summary_lbl.setText(f"{count} documento{'s' if count != 1 else ''} · {error}")
            return
        self._docs_summary_lbl.setText(
            f"{count} documento{'s' if count != 1 else ''} · "
            f"{pages} pagina{'s' if pages != 1 else ''} · "
            f"{_format_bytes(total_size)} de entrada"
        )

    def _sync_precision_options(self) -> None:
        fast = self._precision_combo.currentData() == "fast"
        self._enhance_chk.setEnabled(not fast)
        self._rotation_chk.setEnabled(not fast)

    def _build_config(self) -> PdfToWordConfig:
        return PdfToWordConfig(
            languages=str(self._language_combo.currentData()),
            dpi=int(self._dpi_combo.currentData()),
            precision_mode=str(self._precision_combo.currentData()),
            preserve_native_text=self._native_chk.isChecked(),
            enhance_scans=self._enhance_chk.isChecked(),
            recover_rotated_pages=self._rotation_chk.isChecked(),
            add_tool_suffix=add_tool_suffix_enabled(),
        )

    def _validate_ready(self) -> Optional[str]:
        if self._docs_card.is_empty():
            return "Agrega al menos un PDF."
        _, _, input_error = self._input_stats(self._docs_card.paths())
        if input_error:
            return input_error
        config = self._build_config()
        model_error = validate_tessdata(config.languages)
        if model_error:
            return model_error
        try:
            import docx  # noqa: F401
        except ImportError:
            return "Falta python-docx para exportar Word. Ejecuta: pip install -r requirements.txt"
        return None

    def _refresh_summary(self) -> None:
        config = self._build_config()
        pages, total_size, input_error = self._input_stats(self._docs_card.paths())
        mode_names = {
            "maximum": "Maxima precision",
            "balanced": "Equilibrado",
            "fast": "Rapido",
        }
        rows = [
            f"<b>Documentos:</b>&nbsp;&nbsp;{len(self._docs_card.paths())}",
            f"<b>Paginas estimadas:</b>&nbsp;&nbsp;{pages}",
            f"<b>Peso de entrada:</b>&nbsp;&nbsp;{_format_bytes(total_size)}",
            f"<b>Idiomas:</b>&nbsp;&nbsp;{describe_languages(config.languages)}",
            f"<b>Resolucion OCR:</b>&nbsp;&nbsp;{config.dpi} DPI",
            f"<b>Estrategia:</b>&nbsp;&nbsp;{mode_names.get(config.precision_mode, 'Equilibrado')}",
            f"<b>Texto nativo:</b>&nbsp;&nbsp;{'conservar cuando sea confiable' if config.preserve_native_text else 'forzar OCR'}",
            "<b>Salida:</b>&nbsp;&nbsp;Word editable temporal por documento",
        ]
        error = self._validate_ready()
        if input_error:
            error = input_error
        if error:
            rows.insert(0, f"<span style='color:#E5484D;'>Atencion: {error}</span>")
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )

    def _input_stats(self, paths: List[str]) -> tuple[int, int, str]:
        pages = 0
        total_size = 0
        for raw_path in paths:
            path = Path(raw_path)
            total_size += _file_size(path)
            if raw_path in self._pdf_page_cache:
                pages += self._pdf_page_cache[raw_path]
            else:
                doc = None
                try:
                    doc = fitz.open(str(path))
                    count = doc.page_count
                    self._pdf_page_cache[raw_path] = count
                    pages += count
                except Exception as exc:
                    return pages, total_size, f"No se pudo leer {path.name}: {exc}"
                finally:
                    if doc is not None:
                        try:
                            doc.close()
                        except Exception:
                            pass
        return pages, total_size, ""

    def _build_jobs(self) -> List[PdfToWordJob]:
        return make_pdf_to_word_jobs(
            self._docs_card.paths(),
            str(make_run_dir("PDFaWord")),
            self._build_config(),
        )

    def _on_run(self) -> None:
        self._stop_active_worker()
        error = self._validate_ready()
        if error:
            show_warning(self, "Falta informacion", error)
            return
        if self._worker_thread is not None:
            return

        self._results_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []

        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Preparando conversion...")

        self._worker = PdfToWordWorker(self._build_jobs())
        self._worker_thread = RunnerThread(self._worker.run, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._proc_step.set_progress(self._current_progress(), "Cancelando...")

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        self._proc_step.set_progress(int(current / max(1, total) * 100), msg)

    def _on_finished(self, results: list) -> None:
        self._cleanup_thread()
        self.last_results = list(results)
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Conversion completada")

        docx_paths = [
            result.docx_path
            for result in self.last_results
            if result.success and result.docx_path
        ]
        self.ctx.tray.add_items(docx_paths, "PDF a Word")
        self._send_btn.set_output_paths(docx_paths)
        self.outputs_ready.emit(docx_paths)

        self._results_viewer.set_results(self.last_results)

        ok = sum(1 for result in self.last_results if result.success)
        failed = len(self.last_results) - ok
        msg = f"Se generaron {ok} DOCX."
        if failed:
            msg += f"\nCon error: {failed}"
            show_warning(self, "Conversion completada con avisos", msg)
        else:
            show_success(self, "Conversion completa", msg)
        self._switch_section(3)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al convertir PDF a Word", msg)

    def _cleanup_thread(self) -> None:
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
            self._worker_thread = None
        self._worker = None

    def _current_progress(self) -> int:
        bar = getattr(self._proc_step, "_prog_bar", None)
        return int(bar.value()) if bar is not None else 0

    def _open_in_explorer(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _reset_session(self) -> None:
        self.last_results = []
        self._docs_card.clear()
        self._docs_summary_lbl.setText("Sin documentos cargados.")
        self._language_combo.setCurrentIndex(0)
        self._precision_combo.setCurrentIndex(0)
        self._dpi_combo.setCurrentIndex(0)
        self._native_chk.setChecked(True)
        self._enhance_chk.setChecked(True)
        self._rotation_chk.setChecked(True)
        self._results_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._proc_step.reset()
        self._switch_section(0)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.handle_drop([url.toLocalFile() for url in event.mimeData().urls()])
        event.acceptProposedAction()


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"
