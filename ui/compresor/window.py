"""CompresorWindow — compresion y optimizacion de PDFs por lote."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QSpinBox,
    QScrollArea, QSizePolicy, QFrame,
)

from core.output_naming import unique_output_path_for_source
from core.output_paths import make_run_dir
from core.pdf_compress_engine import (
    PROFILES,
    CompressJob,
    CompressOptions,
    CompressResult,
    PdfCompressEngine,
    available_optional_engines,
    format_bytes,
    optional_engine_status,
    profile_for,
)
from core.pdf_page_rules import build_page_compression_plan
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
from ui.compresor.page_rules import PageRulesPanel


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
        self._profile_grid: Optional[QGridLayout] = None
        self._profile_cards: list[QWidget] = []
        self._profile_card_refs: dict[str, QWidget] = {}
        self._profile_grid_columns = 0
        self._profile_scroll: Optional[QScrollArea] = None

        self._build_pages()
        self.setMinimumSize(785, 540)
        self._switch_section(0)
        self.setAcceptDrops(True)

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
        self._profile_combo.addItem("Correo", "email")
        self._profile_combo.addItem("Equilibrado", "balanced")
        self._profile_combo.addItem("Alta calidad", "quality")
        self._profile_combo.setToolTip("Perfil base de compresion.")
        self._profile_combo.setCurrentIndex(1)
        self._profile_combo.currentIndexChanged.connect(self._sync_controls_from_profile)
        card_layout(profile_card).addWidget(self._profile_combo)

        engine_card = make_card(
            "Motor",
            "Automatico prueba los candidatos disponibles y elige el menor que pase validacion.",
        )
        self._engine_combo = QComboBox()
        self._engine_combo.addItem("Automatico", "auto")
        self._engine_combo.addItem("PyMuPDF", "pymupdf")
        self._engine_combo.addItem("QPDF", "qpdf")
        self._engine_combo.addItem("Ghostscript", "ghostscript")
        self._engine_combo.setToolTip("Motor de compresion a usar.")
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
            "Correo prioriza peso bajo. Equilibrado suele ser la mejor opcion para oficina. "
            "Alta calidad evita cambios agresivos. Si un motor externo produce cambios "
            "riesgosos, se descarta automaticamente."
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
        if count == 0:
            self._docs_summary_lbl.setText("Sin documentos cargados.")
            self._page_rules_panel.set_page_context(0, "")
            return
        total = sum(_file_size(path) for path in paths)
        self._docs_summary_lbl.setText(
            f"{count} documento{'s' if count != 1 else ''} · {format_bytes(total)} de entrada"
        )
        first = paths[0]
        self._page_rules_panel.set_page_context(_pdf_page_count(first), Path(first).name)

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
        engines = ["PyMuPDF interno", *available_optional_engines()]
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
        if engine_mode in {"qpdf", "ghostscript"}:
            missing = self._missing_selected_engine()
            if missing:
                self._profile_desc_lbl.setText(
                    self._profile_desc_lbl.text() + f"\nAtencion: {missing} no disponible."
                )
        self._engines_lbl.setText(self._engine_status_text())

    def _engine_status_text(self) -> str:
        lines = ["Disponibilidad en esta PC:", "PyMuPDF interno: disponible"]
        for engine in optional_engine_status():
            status = "disponible" if engine.available else "no detectado"
            source = f" ({_short_text(engine.source)})" if engine.available and engine.source else ""
            lines.append(f"{engine.label}: {status}{source}")
        return "\n".join(lines)

    def _refresh_summary(self) -> None:
        paths = self._docs_card.paths()
        count = len(paths)
        profile = profile_for(self._profile_id())
        total = sum(_file_size(path) for path in paths)
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
        if self._page_rules_panel.has_rules() and self._engine_mode() in {"qpdf", "ghostscript"}:
            return "Las reglas por pagina requieren motor Automatico o PyMuPDF interno."
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
        statuses = {engine.id: engine.available for engine in optional_engine_status()}
        if mode == "qpdf" and not statuses.get("qpdf", False):
            return "QPDF"
        if mode == "ghostscript" and not statuses.get("ghostscript", False):
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
        queued = Qt.ConnectionType.QueuedConnection
        self._worker.progress.connect(self._on_progress, queued)
        self._worker.finished.connect(self._on_finished, queued)
        self._worker.error.connect(self._on_error, queued)
        self._worker_thread.finished.connect(self._on_thread_finished, queued)
        self._worker_thread.finished.connect(self._worker.deleteLater, queued)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater, queued)
        self._worker_thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._proc_step.set_progress(self._current_progress(), "Cancelando...")

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        self._proc_step.set_progress(int(current / max(1, total) * 100), msg)

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
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al comprimir PDFs", msg)

    def _on_thread_finished(self) -> None:
        self._worker = None
        self._worker_thread = None
        self._apply_primary_glows()

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
        from ui.common.open_utils import open_folder
        open_folder(self, path, title="Abrir carpeta")

    def _reset_session(self) -> None:
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


def _pdf_page_count(path: str) -> int:
    try:
        import fitz
        doc = fitz.open(path)
        try:
            return int(doc.page_count)
        finally:
            doc.close()
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
