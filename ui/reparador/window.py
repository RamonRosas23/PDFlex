"""ReparadorWindow - repair and normalize PDFs."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QCheckBox, QComboBox, QGridLayout,
)

from core.output_naming import unique_output_path_for_source
from core.output_paths import make_run_dir
from core.pdf_repair_engine import (
    PdfRepairEngine,
    PdfRepairJob,
    PdfRepairOptions,
    PdfRepairResult,
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


class RepairWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[PdfRepairJob]) -> None:
        super().__init__()
        self.jobs = jobs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = PdfRepairEngine().run_batch(
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


class ReparadorWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documentos", "Carga PDFs problematicos"),
        ("02", "Normalizacion", "Elige perfil"),
        ("03", "Procesar", "Reescribe PDFs"),
        ("04", "Resultados", "Revisa salidas"),
    ]
    BRAND = "Reparar PDF"
    TAGLINE = "Reescribe y normaliza documentos"
    ACCENT_COLOR = "#84CC16"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[PdfRepairResult] = []
        self._worker: Optional[RepairWorker] = None
        self._worker_thread: Optional[QThread] = None

        self._build_pages()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_options_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "PDFs a reparar o normalizar",
            "Carga documentos que no abren bien, pesan raro o necesitan reescritura limpia.",
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

    def _build_options_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Perfil de normalizacion",
            "Elige cuanto reescribir el PDF. Los originales nunca se modifican.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        profile_card = make_card("Perfil")
        self._profile_combo = QComboBox()
        self._profile_combo.addItem(
            "Limpieza segura - recomendado",
            {
                "key": "seguro",
                "clean": True,
                "garbage": 4,
                "deflate": True,
                "deflate_images": True,
                "deflate_fonts": True,
                "use_objstms": True,
            },
        )
        self._profile_combo.addItem(
            "Compatibilidad maxima",
            {
                "key": "compatible",
                "clean": True,
                "garbage": 4,
                "deflate": True,
                "deflate_images": True,
                "deflate_fonts": True,
                "use_objstms": False,
            },
        )
        self._profile_combo.addItem(
            "Reescritura ligera",
            {
                "key": "ligero",
                "clean": False,
                "garbage": 2,
                "deflate": True,
                "deflate_images": False,
                "deflate_fonts": False,
                "use_objstms": False,
            },
        )
        card_layout(profile_card).addWidget(self._profile_combo)
        grid.addWidget(profile_card, 0, 0)

        options_card = make_card("Opciones")
        self._metadata_chk = QCheckBox("Conservar metadatos")
        self._metadata_chk.setChecked(True)
        card_layout(options_card).addWidget(self._metadata_chk)

        self._fallback_chk = QCheckBox("Reconstruir paginas si el guardado falla")
        self._fallback_chk.setChecked(True)
        card_layout(options_card).addWidget(self._fallback_chk)
        grid.addWidget(options_card, 0, 1)

        info_card = make_card("Resultado")
        info = QLabel(
            "La salida se guarda temporalmente como una copia nueva. El visor confirma que el PDF resultante abre y conserva el numero de paginas."
        )
        info.setProperty("class", "CardHint")
        info.setWordWrap(True)
        card_layout(info_card).addWidget(info)
        grid.addWidget(info_card, 1, 0, 1, 2)

        outer.addLayout(grid)
        outer.addStretch(1)

        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar PDFs",
            "Reescribe cada PDF con limpieza estructural y verificacion posterior.",
        ))

        self._proc_step = ProcessStep(
            run_label="Reparar / normalizar",
            show_output_dir=False,
        )
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Normalizacion")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(back)
        outer.addLayout(nav)
        return page

    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultados",
            "Revisa los PDFs normalizados y conservalos con Guardar como o Guardar todo.",
        ))

        self._result_viewer = GenericPdfViewer("PDFs normalizados")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        outer.addLayout(nav)
        return page

    def _build_action_buttons(self) -> None:
        from ui.common.icons import set_button_icon
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Reparar / normalizar")
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

        self._restart_btn = QPushButton("Nueva reparacion")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "reparador")

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
        elif count == 1:
            self._docs_summary_lbl.setText("1 documento listo para normalizar.")
        else:
            self._docs_summary_lbl.setText(f"{count} documentos listos para normalizar.")
        if hasattr(self, "_proc_step"):
            self._proc_step.set_run_enabled(count > 0)

    def _validate_ready(self) -> Optional[str]:
        if not self._docs_card.paths():
            return "Carga al menos un PDF."
        return None

    def _build_options(self) -> PdfRepairOptions:
        data = self._profile_combo.currentData() or {}
        return PdfRepairOptions(
            clean=bool(data.get("clean", True)),
            garbage=int(data.get("garbage", 4)),
            deflate=bool(data.get("deflate", True)),
            deflate_images=bool(data.get("deflate_images", True)),
            deflate_fonts=bool(data.get("deflate_fonts", True)),
            use_objstms=bool(data.get("use_objstms", True)),
            preserve_metadata=self._metadata_chk.isChecked(),
            fallback_rebuild=self._fallback_chk.isChecked(),
        )

    def _profile_key(self) -> str:
        data = self._profile_combo.currentData() or {}
        return str(data.get("key", "seguro"))

    def _build_jobs(self) -> List[PdfRepairJob]:
        out_dir = make_run_dir("Reparar")
        add_suffix = add_tool_suffix_enabled()
        reserved: set[str] = set()
        options = self._build_options()
        jobs: list[PdfRepairJob] = []
        for source in self._docs_card.paths():
            out_path = unique_output_path_for_source(
                out_dir,
                source,
                extension=".pdf",
                tool_suffix="normalizado",
                technical_suffix=self._profile_key(),
                add_tool_suffix=add_suffix,
                reserved=reserved,
                fallback="documento",
            )
            jobs.append(PdfRepairJob(source, str(out_path), options))
        return jobs

    def _refresh_summary(self) -> None:
        count = self._docs_card.count()
        options = self._build_options()
        rows = [
            f"<b>Documentos:</b>&nbsp;&nbsp;{count}",
            f"<b>Perfil:</b>&nbsp;&nbsp;{self._profile_combo.currentText()}",
            f"<b>Limpieza de estructura:</b>&nbsp;&nbsp;{'Si' if options.clean else 'No'}",
            f"<b>Compresion interna:</b>&nbsp;&nbsp;{'Si' if options.deflate else 'No'}",
            f"<b>Object streams:</b>&nbsp;&nbsp;{'Si' if options.use_objstms else 'No'}",
            f"<b>Metadatos:</b>&nbsp;&nbsp;{'conservar' if options.preserve_metadata else 'limpiar'}",
            f"<b>Fallback:</b>&nbsp;&nbsp;{'reconstruir paginas' if options.fallback_rebuild else 'desactivado'}",
        ]
        error = self._validate_ready()
        if error:
            rows.insert(0, f"<span style='color:#E5484D;'>Atencion: {error}</span>")
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )
        self._proc_step.set_run_enabled(error is None)

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
        self._proc_step.set_progress(0, "Preparando normalizacion...")

        self._worker = RepairWorker(self._build_jobs())
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
        self._proc_step.set_progress(100, "Normalizacion finalizada")

        output_paths = [
            result.output_path
            for result in self.last_results
            if result.success and result.output_path
        ]
        self.ctx.tray.add_items(output_paths, "Reparar PDF")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        self._result_viewer.set_results(self.last_results)
        self._result_viewer.set_source_dirs([
            str(Path(result.job.pdf_path).parent)
            for result in self.last_results
        ])

        ok = sum(1 for result in self.last_results if result.success)
        failed = len(self.last_results) - ok
        repaired = sum(1 for result in self.last_results if result.success and result.repaired_on_open)
        if ok and not failed:
            msg = f"{ok} PDF(s) normalizado(s)."
            if repaired:
                msg += f" {repaired} requirio reparacion al abrir."
            show_success(self, "PDFs listos", msg)
        elif ok:
            show_warning(self, "Proceso con avisos", f"{ok} PDF(s) listo(s), {failed} con error.")
        else:
            show_warning(self, "Sin salidas", "No se pudo normalizar ningun PDF.")
        self._switch_section(3)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al reparar PDF", msg)

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
        self._profile_combo.setCurrentIndex(0)
        self._metadata_chk.setChecked(True)
        self._fallback_chk.setChecked(True)
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._proc_step.reset()
        self._proc_step.set_run_enabled(False)
        self._switch_section(0)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.handle_drop([url.toLocalFile() for url in event.mimeData().urls()])
        event.acceptProposedAction()
