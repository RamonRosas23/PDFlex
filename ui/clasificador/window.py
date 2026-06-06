"""ClasificadorWindow - classify PDFs and rename by content."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QCheckBox, QGridLayout, QLineEdit, QSpinBox, QTextEdit,
)

from core.document_classifier_engine import (
    DEFAULT_RULES_TEXT,
    DEFAULT_TEMPLATE,
    ClassifierConfig,
    ClassifierJob,
    ClassifierResult,
    DocumentClassifierEngine,
    parse_classification_rules,
)
from core.output_paths import make_run_dir
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.documents_step import DocumentsCard
from ui.common.icons import set_button_icon
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.process_step import ProcessStep
from ui.common.send_to_tool import SendToToolButton
from ui.common.tool_scaffold import PipelineWindow


class ClassifierWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[ClassifierJob]) -> None:
        super().__init__()
        self.jobs = jobs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = DocumentClassifierEngine().run_batch(
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


class ClasificadorWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documentos", "Carga PDFs a clasificar"),
        ("02", "Reglas", "Define tipos y nombre final"),
        ("03", "Procesar", "Detecta campos y renombra"),
        ("04", "Resultados", "Revisa PDFs renombrados"),
    ]
    BRAND = "Clasificador OCR"
    TAGLINE = "Renombra PDFs por contenido"
    ACCENT_COLOR = "#22C55E"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[ClassifierResult] = []
        self._worker: Optional[ClassifierWorker] = None
        self._worker_thread: Optional[QThread] = None

        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_rules_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documentos a clasificar",
            "Carga PDFs; PDFlex detectara tipo, RFC, fecha, folio y cliente cuando existan.",
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

    def _build_rules_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Reglas y plantilla",
            "Configura como se detecta el tipo de documento y como se arma el nombre final.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        template_card = make_card("Plantilla de nombre")
        self._template_edit = QLineEdit(DEFAULT_TEMPLATE)
        self._template_edit.setPlaceholderText("{tipo}_{cliente}_{fecha}_{folio}")
        card_layout(template_card).addWidget(self._template_edit)
        fields = QLabel("Campos: {tipo}, {cliente}, {rfc}, {fecha}, {folio}, {original}")
        fields.setProperty("class", "CardHint")
        fields.setWordWrap(True)
        card_layout(template_card).addWidget(fields)
        grid.addWidget(template_card, 0, 0)

        extraction_card = make_card("Extraccion")
        self._max_pages_spin = QSpinBox()
        self._max_pages_spin.setRange(1, 20)
        self._max_pages_spin.setValue(3)
        self._max_pages_spin.setSuffix(" paginas")
        card_layout(extraction_card).addWidget(self._max_pages_spin)
        self._ocr_chk = QCheckBox("Usar OCR si no hay texto nativo")
        self._ocr_chk.setChecked(True)
        card_layout(extraction_card).addWidget(self._ocr_chk)
        grid.addWidget(extraction_card, 0, 1)

        rules_card = make_card("Reglas de tipo", "Formato: Tipo=palabra clave, otra palabra clave")
        self._rules_edit = QTextEdit()
        self._rules_edit.setPlainText(DEFAULT_RULES_TEXT)
        self._rules_edit.setMinimumHeight(230)
        card_layout(rules_card).addWidget(self._rules_edit, 1)
        grid.addWidget(rules_card, 1, 0, 1, 2)

        outer.addLayout(grid, 1)

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
            "Procesar clasificacion",
            "Genera copias temporales con nombres armados desde el contenido detectado.",
        ))

        self._proc_step = ProcessStep(
            run_label="Clasificar y renombrar",
            show_output_dir=False,
        )
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Reglas")
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
            "Revisa los PDFs clasificados, guardalos o envialos a otra herramienta.",
        ))

        self._result_viewer = GenericPdfViewer("PDFs renombrados")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        nav.addStretch()

        self._send_btn = SendToToolButton(self.ctx, "clasificador")
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
            f"{count} documento{'s' if count != 1 else ''} listo{'s' if count != 1 else ''} para clasificar."
        )

    def _build_config(self) -> ClassifierConfig:
        return ClassifierConfig(
            template=self._template_edit.text().strip() or DEFAULT_TEMPLATE,
            rules_text=self._rules_edit.toPlainText(),
            max_pages=self._max_pages_spin.value(),
            use_ocr_fallback=self._ocr_chk.isChecked(),
            add_tool_suffix=add_tool_suffix_enabled(),
        )

    def _validate_ready(self) -> Optional[str]:
        if self._docs_card.is_empty():
            return "Agrega al menos un PDF."
        if not self._template_edit.text().strip():
            return "Escribe una plantilla de nombre."
        if not parse_classification_rules(self._rules_edit.toPlainText()):
            return "Agrega al menos una regla de tipo."
        return None

    def _refresh_summary(self) -> None:
        config = self._build_config()
        rules = parse_classification_rules(config.rules_text)
        rows = [
            f"<b>Documentos:</b>&nbsp;&nbsp;{len(self._docs_card.paths())}",
            f"<b>Plantilla:</b>&nbsp;&nbsp;{config.template}",
            f"<b>Reglas:</b>&nbsp;&nbsp;{len(rules)} tipos",
            f"<b>Paginas por PDF:</b>&nbsp;&nbsp;{config.max_pages}",
            f"<b>OCR:</b>&nbsp;&nbsp;{'fallback activado' if config.use_ocr_fallback else 'solo texto nativo'}",
            "<b>Salida:</b>&nbsp;&nbsp;copias temporales renombradas",
        ]
        error = self._validate_ready()
        if error:
            rows.insert(0, f"<span style='color:#E5484D;'>Atencion: {error}</span>")
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )

    def _build_jobs(self) -> List[ClassifierJob]:
        out_dir = make_run_dir("Clasificador")
        config = self._build_config()
        return [
            ClassifierJob(pdf_path=path, output_dir=str(out_dir), config=config)
            for path in self._docs_card.paths()
        ]

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
        self._proc_step.set_progress(0, "Preparando clasificacion...")

        self._worker = ClassifierWorker(self._build_jobs())
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
        self._proc_step.set_progress(100, "Clasificacion completada")

        output_paths = [
            result.output_path
            for result in self.last_results
            if result.success and result.output_path
        ]
        self.ctx.tray.add_items(output_paths, "Clasificador OCR")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        self._result_viewer.set_results(self.last_results)
        self._result_viewer.set_source_dirs([
            str(Path(result.job.pdf_path).parent)
            for result in self.last_results
        ])

        ok = sum(1 for result in self.last_results if result.success)
        failed = len(self.last_results) - ok
        msg = f"Se clasificaron {ok} PDF{'s' if ok != 1 else ''}."
        if failed:
            msg += f"\nCon error: {failed}"
            show_warning(self, "Clasificacion completada con avisos", msg)
        else:
            show_success(self, "Clasificacion completa", msg)
        self._switch_section(3)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al clasificar PDFs", msg)

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
        self._template_edit.setText(DEFAULT_TEMPLATE)
        self._rules_edit.setPlainText(DEFAULT_RULES_TEXT)
        self._max_pages_spin.setValue(3)
        self._ocr_chk.setChecked(True)
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
