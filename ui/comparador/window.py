"""ComparadorWindow - compare two PDF versions."""
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
from core.pdf_compare_engine import (
    PdfCompareEngine,
    PdfCompareJob,
    PdfCompareOptions,
    PdfCompareResult,
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


class CompareWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[PdfCompareJob]) -> None:
        super().__init__()
        self.jobs = jobs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = PdfCompareEngine().run_batch(
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


class ComparadorWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documentos", "Carga base y revisado"),
        ("02", "Comparacion", "Ajusta sensibilidad"),
        ("03", "Procesar", "Genera reporte"),
        ("04", "Resultados", "Revisa diferencias"),
    ]
    BRAND = "Comparar PDFs"
    TAGLINE = "Detecta cambios visuales y de texto"
    ACCENT_COLOR = "#F59E0B"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[PdfCompareResult] = []
        self._worker: Optional[CompareWorker] = None
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
            "PDF base y PDF revisado",
            "Carga exactamente dos PDFs. El primero es la version base y el segundo la version revisada.",
        ))

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=True,
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
            "Opciones de comparacion",
            "Ajusta el nivel de detalle del analisis y del reporte final.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        precision_card = make_card("Sensibilidad visual")
        self._precision_combo = QComboBox()
        self._precision_combo.addItem(
            "Equilibrado - recomendado",
            {"dpi": 110, "pixel_threshold": 24, "min_change_ratio": 0.001},
        )
        self._precision_combo.addItem(
            "Rapido - cambios grandes",
            {"dpi": 72, "pixel_threshold": 32, "min_change_ratio": 0.002},
        )
        self._precision_combo.addItem(
            "Detallado - cambios pequenos",
            {"dpi": 150, "pixel_threshold": 16, "min_change_ratio": 0.0005},
        )
        card_layout(precision_card).addWidget(self._precision_combo)
        grid.addWidget(precision_card, 0, 0)

        content_card = make_card("Contenido")
        self._compare_text_chk = QCheckBox("Comparar texto nativo")
        self._compare_text_chk.setChecked(True)
        card_layout(content_card).addWidget(self._compare_text_chk)

        self._include_equal_chk = QCheckBox("Incluir paginas iguales en el reporte")
        self._include_equal_chk.setChecked(False)
        card_layout(content_card).addWidget(self._include_equal_chk)
        grid.addWidget(content_card, 0, 1)

        order_card = make_card("Orden de comparacion")
        self._order_lbl = QLabel("Carga dos PDFs para definir base y revisado.")
        self._order_lbl.setProperty("class", "CardHint")
        self._order_lbl.setWordWrap(True)
        card_layout(order_card).addWidget(self._order_lbl)
        grid.addWidget(order_card, 1, 0, 1, 2)

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
            "Generar reporte",
            "PDFlex creara un reporte temporal con resumen y paginas afectadas.",
        ))

        self._proc_step = ProcessStep(
            run_label="Comparar PDFs",
            show_output_dir=False,
        )
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Comparacion")
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
            "Revisa el reporte, guardalo o envia el PDF a otra herramienta.",
        ))

        self._result_viewer = GenericPdfViewer("Reportes de comparacion")
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

        self._run_btn = QPushButton("Comparar PDFs")
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

        self._restart_btn = QPushButton("Nueva comparacion")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "comparador")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()

    def _on_section_activated(self, idx: int) -> None:
        if idx == 1:
            self._refresh_order_label()
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
            self._docs_summary_lbl.setText("Agrega un segundo PDF para comparar.")
        elif count == 2:
            self._docs_summary_lbl.setText("2 documentos listos. Puedes arrastrar para corregir el orden.")
        else:
            self._docs_summary_lbl.setText("Carga exactamente dos PDFs; quita los sobrantes antes de procesar.")
        self._refresh_order_label()
        if hasattr(self, "_proc_step"):
            self._proc_step.set_run_enabled(count == 2)

    def _refresh_order_label(self) -> None:
        paths = self._docs_card.paths()
        if len(paths) >= 2:
            self._order_lbl.setText(
                f"<b>Base:</b>&nbsp;&nbsp;{Path(paths[0]).name}<br>"
                f"<b>Revisado:</b>&nbsp;&nbsp;{Path(paths[1]).name}"
            )
        elif len(paths) == 1:
            self._order_lbl.setText(f"<b>Base:</b>&nbsp;&nbsp;{Path(paths[0]).name}<br><b>Revisado:</b>&nbsp;&nbsp;pendiente")
        else:
            self._order_lbl.setText("Carga dos PDFs para definir base y revisado.")

    def _validate_ready(self) -> Optional[str]:
        paths = self._docs_card.paths()
        if len(paths) != 2:
            return "Carga exactamente dos PDFs: primero base, segundo revisado."
        if paths[0] == paths[1]:
            return "Selecciona dos archivos distintos."
        return None

    def _build_options(self) -> PdfCompareOptions:
        data = self._precision_combo.currentData() or {}
        return PdfCompareOptions(
            dpi=int(data.get("dpi", 110)),
            pixel_threshold=int(data.get("pixel_threshold", 24)),
            min_change_ratio=float(data.get("min_change_ratio", 0.001)),
            compare_text=self._compare_text_chk.isChecked(),
            include_equal_pages=self._include_equal_chk.isChecked(),
        )

    def _build_jobs(self) -> List[PdfCompareJob]:
        paths = self._docs_card.paths()
        out_dir = make_run_dir("Comparar")
        add_suffix = add_tool_suffix_enabled()
        out_path = unique_output_path_for_source(
            out_dir,
            paths[1],
            extension=".pdf",
            tool_suffix="comparacion",
            technical_suffix="reporte",
            add_tool_suffix=add_suffix,
            fallback="reporte",
        )
        return [
            PdfCompareJob(
                base_pdf=paths[0],
                compare_pdf=paths[1],
                output_path=str(out_path),
                options=self._build_options(),
            )
        ]

    def _refresh_summary(self) -> None:
        paths = self._docs_card.paths()
        options = self._build_options()
        rows = [
            f"<b>Base:</b>&nbsp;&nbsp;{Path(paths[0]).name if len(paths) >= 1 else 'Pendiente'}",
            f"<b>Revisado:</b>&nbsp;&nbsp;{Path(paths[1]).name if len(paths) >= 2 else 'Pendiente'}",
            f"<b>Sensibilidad:</b>&nbsp;&nbsp;{options.dpi} DPI / umbral {options.pixel_threshold}",
            f"<b>Texto nativo:</b>&nbsp;&nbsp;{'Si' if options.compare_text else 'No'}",
            f"<b>Reporte:</b>&nbsp;&nbsp;{'incluye paginas iguales' if options.include_equal_pages else 'solo diferencias'}",
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
        self._proc_step.set_progress(0, "Preparando comparacion...")

        self._worker = CompareWorker(self._build_jobs())
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
        self._proc_step.set_progress(100, "Comparacion finalizada")

        output_paths = [
            result.output_path
            for result in self.last_results
            if result.success and result.output_path
        ]
        self.ctx.tray.add_items(output_paths, "Comparar PDFs")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        self._result_viewer.set_results(self.last_results)
        self._result_viewer.set_source_dirs([
            str(Path(result.job.compare_pdf).parent)
            for result in self.last_results
        ])

        ok = sum(1 for result in self.last_results if result.success)
        changes = sum(result.changed_pages for result in self.last_results if result.success)
        if ok and changes:
            show_success(self, "Reporte listo", f"Se detectaron diferencias en {changes} pagina(s).")
        elif ok:
            show_success(self, "Reporte listo", "No se detectaron diferencias con la sensibilidad actual.")
        else:
            show_warning(self, "Comparacion con avisos", "No se pudo generar el reporte.")
        self._switch_section(3)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al comparar PDFs", msg)

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
        self._compare_text_chk.setChecked(True)
        self._include_equal_chk.setChecked(False)
        self._precision_combo.setCurrentIndex(0)
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
