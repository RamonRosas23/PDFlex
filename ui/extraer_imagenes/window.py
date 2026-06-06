"""ExtraerImagenesWindow - extract embedded PDF image resources."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QCheckBox, QGridLayout, QSpinBox,
)

from core.output_paths import make_run_dir, unique_name
from core.pdf_extract_images_engine import (
    ExtractImagesConfig,
    ExtractImagesJob,
    ExtractImagesJobResult,
    PdfExtractImagesEngine,
)
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.documents_step import DocumentsCard
from ui.common.icons import set_button_icon
from ui.common.image_results_viewer import ImageResultsViewer
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.process_step import ProcessStep
from ui.common.send_to_tool import SendToToolButton
from ui.common.tool_scaffold import PipelineWindow


class ExtractImagesWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[ExtractImagesJob], config: ExtractImagesConfig) -> None:
        super().__init__()
        self.jobs = jobs
        self.config = config
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = PdfExtractImagesEngine().run_batch(
                self.jobs,
                self.config,
                progress=lambda c, t, m: self.progress.emit(c, t, m),
                should_cancel=lambda: self._cancel,
            )
            if self._cancel:
                self.error.emit("Operacion cancelada.")
            else:
                self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


class ExtraerImagenesWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documentos", "Carga PDFs con recursos"),
        ("02", "Filtros", "Elige duplicados y tamano minimo"),
        ("03", "Procesar", "Extrae imagenes embebidas"),
        ("04", "Resultados", "Revisa recursos extraidos"),
    ]
    BRAND = "Extraer imagenes"
    TAGLINE = "Saca recursos embebidos del PDF"
    ACCENT_COLOR = "#06B6D4"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[ExtractImagesJobResult] = []
        self._worker: Optional[ExtractImagesWorker] = None
        self._worker_thread: Optional[QThread] = None

        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_filters_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "PDFs con imagenes embebidas",
            "Extrae logos, fotos, escaneos y recursos internos sin renderizar paginas completas.",
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

        nav = QHBoxLayout()
        nav.addStretch()
        next_btn = QPushButton("Continuar")
        next_btn.setProperty("class", "Primary")
        next_btn.setMinimumWidth(160)
        set_button_icon(next_btn, "arrow-right")
        next_btn.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(next_btn)
        outer.addLayout(nav)
        return page

    def _build_filters_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Filtros de extraccion",
            "Evita duplicados y filtra iconos pequenos cuando busques recursos utiles.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        behavior = make_card("Comportamiento")
        self._dedupe_chk = QCheckBox("Evitar recursos duplicados por xref")
        self._dedupe_chk.setChecked(True)
        card_layout(behavior).addWidget(self._dedupe_chk)
        hint = QLabel("Cuando un logo se repite en muchas paginas, se extrae una sola vez.")
        hint.setProperty("class", "CardHint")
        hint.setWordWrap(True)
        card_layout(behavior).addWidget(hint)
        grid.addWidget(behavior, 0, 0)

        size_card = make_card("Tamano minimo")
        self._min_width_spin = QSpinBox()
        self._min_width_spin.setRange(1, 5000)
        self._min_width_spin.setValue(1)
        self._min_width_spin.setSuffix(" px ancho")
        card_layout(size_card).addWidget(self._min_width_spin)

        self._min_height_spin = QSpinBox()
        self._min_height_spin.setRange(1, 5000)
        self._min_height_spin.setValue(1)
        self._min_height_spin.setSuffix(" px alto")
        card_layout(size_card).addWidget(self._min_height_spin)
        grid.addWidget(size_card, 0, 1)

        info_card = make_card("Diferencia con PDF a Imagenes")
        info = QLabel(
            "Esta herramienta guarda los recursos internos originales. "
            "Si necesitas una imagen de cada pagina completa, usa PDF a Imagenes."
        )
        info.setProperty("class", "CardHint")
        info.setWordWrap(True)
        card_layout(info_card).addWidget(info)
        grid.addWidget(info_card, 1, 0, 1, 2)

        outer.addLayout(grid)
        outer.addStretch(1)

        nav = QHBoxLayout()
        back = QPushButton("Documentos")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(0))
        nav.addWidget(back)
        nav.addStretch()
        next_btn = QPushButton("Continuar")
        next_btn.setProperty("class", "Primary")
        next_btn.setMinimumWidth(160)
        set_button_icon(next_btn, "arrow-right")
        next_btn.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(next_btn)
        outer.addLayout(nav)
        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Extrae recursos a temporal; usa Guardar todo para conservarlos.",
        ))

        self._proc_step = ProcessStep(
            run_label="Extraer imagenes",
            show_output_dir=False,
        )
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Filtros")
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
            "Revisa las imagenes extraidas agrupadas por PDF origen.",
        ))

        self._img_viewer = ImageResultsViewer("Recursos extraidos")
        self._img_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._img_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        nav.addStretch()

        self._send_btn = SendToToolButton(self.ctx, "extraer_imagenes")
        nav.addWidget(self._send_btn)

        restart = QPushButton("Nueva sesion")
        restart.setProperty("class", "Primary")
        restart.setMinimumWidth(180)
        set_button_icon(restart, "refresh-cw")
        restart.clicked.connect(self._reset_session)
        nav.addWidget(restart)
        outer.addLayout(nav)
        return page

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
        self._docs_summary_lbl.setText(
            f"{count} documento{'s' if count != 1 else ''} listo{'s' if count != 1 else ''} para extraer recursos."
        )

    def _build_config(self) -> ExtractImagesConfig:
        return ExtractImagesConfig(
            deduplicate=self._dedupe_chk.isChecked(),
            min_width=self._min_width_spin.value(),
            min_height=self._min_height_spin.value(),
        )

    def _validate_ready(self) -> Optional[str]:
        if self._docs_card.is_empty():
            return "Agrega al menos un PDF."
        return None

    def _refresh_summary(self) -> None:
        config = self._build_config()
        rows = [
            f"<b>Documentos:</b>&nbsp;&nbsp;{len(self._docs_card.paths())}",
            f"<b>Duplicados:</b>&nbsp;&nbsp;{'evitar por xref' if config.deduplicate else 'extraer cada aparicion'}",
            f"<b>Tamano minimo:</b>&nbsp;&nbsp;{config.min_width} x {config.min_height} px",
            "<b>Salida:</b>&nbsp;&nbsp;subcarpeta temporal por PDF",
        ]
        error = self._validate_ready()
        if error:
            rows.insert(0, f"<span style='color:#E5484D;'>Atencion: {error}</span>")
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )

    def _build_jobs(self) -> List[ExtractImagesJob]:
        base_dir = make_run_dir("ExtraerImagenes")
        reserved: set[str] = set()
        add_suffix = add_tool_suffix_enabled()
        jobs: List[ExtractImagesJob] = []
        for path in self._docs_card.paths():
            stem = unique_name(
                Path(path).stem,
                reserved=reserved,
                directory=base_dir,
                fallback="documento",
            )
            out_dir = base_dir / stem
            out_dir.mkdir(parents=True, exist_ok=True)
            jobs.append(
                ExtractImagesJob(
                    pdf_path=path,
                    output_dir=str(out_dir),
                    base_name=stem,
                    add_tool_suffix=add_suffix,
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

        self._img_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []

        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Preparando extraccion...")

        self._worker = ExtractImagesWorker(self._build_jobs(), self._build_config())
        self._worker_thread = QThread(self)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
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
        self._proc_step.set_progress(100, "Extraccion completada")

        output_paths = [
            result.output_path
            for job_result in self.last_results
            for result in job_result.image_results
            if result.success and result.output_path
        ]
        self.ctx.tray.add_items(output_paths, "Extraer imagenes")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        self._img_viewer.set_grouped_results(self.last_results)

        ok = len(output_paths)
        failed_docs = sum(1 for result in self.last_results if not result.success)
        msg = f"Se extrajeron {ok} imagen{'es' if ok != 1 else ''}."
        if failed_docs:
            msg += f"\nPDFs sin recursos o con error: {failed_docs}"
            show_warning(self, "Extraccion completada con avisos", msg)
        else:
            show_success(self, "Extraccion completa", msg)
        self._switch_section(3)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al extraer imagenes", msg)

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
        self._dedupe_chk.setChecked(True)
        self._min_width_spin.setValue(1)
        self._min_height_spin.setValue(1)
        self._img_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._proc_step.reset()
        self._switch_section(0)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.handle_drop([url.toLocalFile() for url in event.mimeData().urls()])
        event.acceptProposedAction()
