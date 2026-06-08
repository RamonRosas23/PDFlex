"""CompresorWindow — compresion y optimizacion de PDFs por lote."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
    QComboBox, QGridLayout,
)

from core.output_naming import unique_output_path_for_source
from core.output_paths import make_run_dir
from core.pdf_compress_engine import (
    PROFILES,
    CompressJob,
    CompressResult,
    PdfCompressEngine,
    format_bytes,
    profile_for,
)
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.documents_step import DocumentsCard
from ui.common.icons import set_button_icon
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.process_step import ProcessStep
from ui.common.send_to_tool import SendToToolButton
from ui.common.tool_scaffold import PipelineWindow, RunnerThread


class CompressWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[CompressJob]) -> None:
        super().__init__()
        self.jobs = jobs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = PdfCompressEngine().run_batch(
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
        self._worker: Optional[CompressWorker] = None
        self._worker_thread: Optional[QThread] = None

        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_profile_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())
        self._build_action_buttons()

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
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
        outer.addWidget(self._docs_card, 1)

        self._docs_summary_lbl = QLabel("Sin documentos cargados.")
        self._docs_summary_lbl.setProperty("class", "CardHint")
        self._docs_summary_lbl.setWordWrap(True)
        outer.addWidget(self._docs_summary_lbl)

        return page

    def _build_profile_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Perfil de compresion",
            "Elige un perfil segun el destino del documento.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        profile_card = make_card(
            "Perfil",
            "Los perfiles ajustan resolucion y calidad de imagen sin tocar el PDF original.",
        )
        self._profile_combo = QComboBox()
        self._profile_combo.addItem("Correo - maxima reduccion razonable", "email")
        self._profile_combo.addItem("Equilibrado - recomendado", "balanced")
        self._profile_combo.addItem("Alta calidad - conservador", "quality")
        self._profile_combo.setCurrentIndex(1)
        self._profile_combo.currentIndexChanged.connect(self._sync_profile_desc)
        card_layout(profile_card).addWidget(self._profile_combo)
        grid.addWidget(profile_card, 0, 0)

        details_card = make_card("Detalle tecnico")
        self._profile_desc_lbl = QLabel("")
        self._profile_desc_lbl.setProperty("class", "Mono")
        self._profile_desc_lbl.setWordWrap(True)
        card_layout(details_card).addWidget(self._profile_desc_lbl)
        grid.addWidget(details_card, 0, 1)

        guidance_card = make_card(
            "Lectura rapida",
            "Si el PDF ya esta optimizado, PDFlex conservara una copia sin aumentar el peso.",
        )
        guidance = QLabel(
            "Correo prioriza peso bajo. Equilibrado suele ser la mejor opcion para oficina. "
            "Alta calidad evita cambios agresivos en escaneos finos."
        )
        guidance.setProperty("class", "CardHint")
        guidance.setWordWrap(True)
        card_layout(guidance_card).addWidget(guidance)
        grid.addWidget(guidance_card, 1, 0, 1, 2)

        outer.addLayout(grid)
        outer.addStretch(1)

        self._sync_profile_desc()
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
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultados",
            "Compara el peso de cada PDF optimizado y revisa el documento final.",
        ))

        self._result_viewer = GenericPdfViewer("PDFs comprimidos")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        self._send_btn = SendToToolButton(self.ctx, "compresor")
        # _send_btn is exposed via _get_step_actions for the navbar; no inline row needed.

        return page

    def _build_action_buttons(self) -> None:
        self._run_btn = QPushButton("Comprimir PDFs")
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

        self._restart_btn = QPushButton("Nueva sesión")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        # Wire signals from ProcessStep
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
        total = sum(_file_size(path) for path in paths)
        self._docs_summary_lbl.setText(
            f"{count} documento{'s' if count != 1 else ''} · {format_bytes(total)} de entrada"
        )

    def _profile_id(self) -> str:
        return str(self._profile_combo.currentData() or "balanced")

    def _sync_profile_desc(self) -> None:
        profile = profile_for(self._profile_id())
        self._profile_desc_lbl.setText(
            f"{profile.label}\n"
            f"DPI objetivo: {profile.dpi_target}\n"
            f"Procesa imagenes sobre: {profile.dpi_threshold} DPI\n"
            f"Calidad JPEG: {profile.quality}%\n"
            f"{profile.description}"
        )

    def _refresh_summary(self) -> None:
        paths = self._docs_card.paths()
        count = len(paths)
        profile = profile_for(self._profile_id())
        total = sum(_file_size(path) for path in paths)
        rows = [
            f"<b>Documentos:</b>&nbsp;&nbsp;{count}",
            f"<b>Peso de entrada:</b>&nbsp;&nbsp;{format_bytes(total)}",
            f"<b>Perfil:</b>&nbsp;&nbsp;{profile.label}",
            "<b>Salida:</b>&nbsp;&nbsp;PDF temporal por documento",
        ]
        if count == 0:
            rows.insert(0, "<span style='color:#E5484D;'>Atencion: no hay documentos cargados.</span>")
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )

    def _validate_ready(self) -> Optional[str]:
        if self._docs_card.is_empty():
            return "Agrega al menos un PDF."
        return None

    def _build_jobs(self) -> List[CompressJob]:
        out_dir = make_run_dir("ComprimirPDF")
        reserved: set[str] = set()
        add_suffix = add_tool_suffix_enabled()
        profile_id = self._profile_id()
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
                )
            )
        return jobs

    def _on_run(self) -> None:
        self._stop_active_worker()
        error = self._validate_ready()
        if error:
            show_warning(self, "Falta informacion", error)
            return
        if self._worker_thread is not None:
            return

        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []

        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Preparando compresion...")

        self._worker = CompressWorker(self._build_jobs())
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
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al comprimir PDFs", msg)

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
        self._profile_combo.setCurrentIndex(1)
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._proc_step.reset()
        self._switch_section(0)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.handle_drop([url.toLocalFile() for url in event.mimeData().urls()])
        event.acceptProposedAction()


def _file_size(path: str) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0
