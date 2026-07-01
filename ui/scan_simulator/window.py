"""ScanSimulatorWindow - simulate realistic scanned PDFs."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import List, Optional

import fitz
from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.output_paths import make_run_dir
from core.pdf_scan_simulator_engine import (
    SCAN_PRESETS,
    PdfScanSimulatorEngine,
    ScanSimulationConfig,
    ScanSimulationJob,
    ScanSimulationResult,
    build_output_path,
    config_for_preset,
)
from core.pdf_to_images_engine import parse_page_selection
from shell.context import ShellContext
from ui.common.cards import card_layout, make_card, make_page_header
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.document_workspace import DocumentWorkspace as DocumentsCard
from ui.common.icons import set_button_icon
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.process_step import ProcessStep
from ui.common.send_to_tool import SendToToolButton
from ui.common.slider import SliderWithValue
from ui.common.tool_scaffold import PipelineWindow, RunnerThread
from ui.styles import COLORS


_TONE_ITEMS = (
    ("Grises", "gray"),
    ("Color", "color"),
    ("Blanco y negro", "bw"),
)


class ScanSimulatorWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(
        self,
        jobs: List[ScanSimulationJob],
        config: ScanSimulationConfig,
    ) -> None:
        super().__init__()
        self.jobs = jobs
        self.config = config
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            engine = PdfScanSimulatorEngine()
            results = engine.run_batch(
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


class ScanSimulatorWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documentos", "Carga los PDFs a escanear"),
        ("02", "Realismo", "Preset, calidad y variacion visual"),
        ("03", "Procesar", "Genera el PDF escaneado"),
        ("04", "Resultados", "Revisa los PDFs generados"),
    ]
    BRAND = "Simular escaneo"
    TAGLINE = "Convierte PDFs limpios en escaneos realistas"
    ACCENT_COLOR = "#38BDF8"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[ScanSimulationResult] = []
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[ScanSimulatorWorker] = None
        self._pdf_page_cache: dict[str, int] = {}
        self._loading_preset = False

        self._build_pages()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_realism_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(
            make_page_header(
                "Documentos a procesar",
                "Carga uno o varios PDFs para generar copias con apariencia de escaneo.",
            )
        )

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=True,
            show_thumbnails=True,
            thumb_size=(64, 82),
            file_filter="PDF (*.pdf)",
        )
        self._docs_card.files_changed.connect(self._on_docs_changed)
        outer.addWidget(self._docs_card, 1)
        return page

    def _build_realism_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(
            make_page_header(
                "Realismo del escaneo",
                "Elige un preset y ajusta la firma visual de la corrida.",
            )
        )

        scroll = QScrollArea()
        scroll.setObjectName("ScanRealismScrollArea")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(16)

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        preset_card = make_card(
            "Preset de escaneo",
            "Cada preset calibra una sesion completa: crop, textura, movimiento y compresion.",
        )
        pl = card_layout(preset_card)
        pl.setSpacing(10)
        self._preset_combo = QComboBox()
        for preset in SCAN_PRESETS:
            self._preset_combo.addItem(preset.label, preset.id)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        pl.addWidget(self._preset_combo)
        self._preset_desc_lbl = QLabel("")
        self._preset_desc_lbl.setProperty("class", "CardHint")
        self._preset_desc_lbl.setWordWrap(True)
        pl.addWidget(self._preset_desc_lbl)
        grid.addWidget(preset_card, 0, 0)

        range_card = make_card(
            "Paginas",
            "Vacio procesa todas. Ej: 1-3,5,final.",
        )
        rl = card_layout(range_card)
        self._range_edit = QLineEdit()
        self._range_edit.setPlaceholderText("Todas las paginas")
        self._range_edit.setClearButtonEnabled(True)
        rl.addWidget(self._range_edit)
        grid.addWidget(range_card, 0, 1)

        output_card = make_card(
            "Calidad de salida",
            "Resolucion, color y compresion final del PDF imagen.",
        )
        ol = card_layout(output_card)
        ol.setSpacing(12)
        self._dpi_slider = SliderWithValue(96.0, 400.0, 220.0, step=1.0, suffix="DPI", decimals=0)
        ol.addLayout(_labeled_control("Resolucion", self._dpi_slider))

        tone_row = QHBoxLayout()
        tone_row.setSpacing(8)
        tone_lbl = QLabel("Tono")
        tone_lbl.setStyleSheet("color: #9094A0;")
        self._tone_combo = QComboBox()
        for label, value in _TONE_ITEMS:
            self._tone_combo.addItem(label, value)
        tone_row.addWidget(tone_lbl)
        tone_row.addWidget(self._tone_combo, 1)
        ol.addLayout(tone_row)

        self._quality_slider = SliderWithValue(45.0, 96.0, 82.0, step=1.0, suffix="%", decimals=0)
        ol.addLayout(_labeled_control("Calidad JPEG", self._quality_slider))
        grid.addWidget(output_card, 1, 0)

        realism_card = make_card(
            "Movimiento de hoja",
            "Controla borde/crop visible, inclinacion base y microvariacion.",
        )
        ml = card_layout(realism_card)
        ml.setSpacing(12)
        self._intensity_slider = SliderWithValue(0.0, 100.0, 66.0, step=1.0, suffix="%", decimals=0)
        ml.addLayout(_labeled_control("Intensidad", self._intensity_slider))
        self._margin_slider = SliderWithValue(0.0, 10.0, 3.6, step=0.1, suffix="%", decimals=1)
        ml.addLayout(_labeled_control("Margen", self._margin_slider))
        self._rotation_slider = SliderWithValue(0.0, 4.0, 0.95, step=0.05, suffix="deg", decimals=2)
        ml.addLayout(_labeled_control("Rotacion", self._rotation_slider))
        self._perspective_slider = SliderWithValue(0.0, 6.0, 1.4, step=0.05, suffix="%", decimals=2)
        ml.addLayout(_labeled_control("Perspectiva", self._perspective_slider))
        grid.addWidget(realism_card, 1, 1)

        texture_card = make_card(
            "Textura optica",
            "Ruido de papel, fondo del escaner y difuminado del lente.",
        )
        tl = card_layout(texture_card)
        tl.setSpacing(12)
        self._paper_noise_slider = SliderWithValue(0.0, 100.0, 56.0, step=1.0, suffix="%", decimals=0)
        tl.addLayout(_labeled_control("Papel", self._paper_noise_slider))
        self._background_noise_slider = SliderWithValue(0.0, 100.0, 42.0, step=1.0, suffix="%", decimals=0)
        tl.addLayout(_labeled_control("Fondo", self._background_noise_slider))
        self._blur_slider = SliderWithValue(0.0, 1.2, 0.24, step=0.02, suffix="px", decimals=2)
        tl.addLayout(_labeled_control("Lente", self._blur_slider))
        grid.addWidget(texture_card, 2, 0)

        details_card = make_card(
            "Detalles fisicos",
            "Elementos compartidos por la corrida, con microvariacion por pagina.",
        )
        dl = card_layout(details_card)
        dl.setSpacing(8)
        self._border_chk = QCheckBox("Borde visible de hoja")
        self._shadow_chk = QCheckBox("Sombra natural")
        self._bands_chk = QCheckBox("Bandas de escaner")
        self._dust_chk = QCheckBox("Polvo y micro manchas")
        self._seed_spin = QSpinBox()
        self._seed_spin.setRange(0, 2_147_483_647)
        self._seed_spin.setValue(20260626)
        self._seed_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._seed_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        for chk in (self._border_chk, self._shadow_chk, self._bands_chk, self._dust_chk):
            dl.addWidget(chk)
        seed_row = QHBoxLayout()
        seed_row.setSpacing(8)
        seed_lbl = QLabel("Sesion")
        seed_lbl.setStyleSheet("color: #9094A0;")
        seed_row.addWidget(seed_lbl)
        seed_row.addWidget(self._seed_spin, 1)
        dl.addLayout(seed_row)
        grid.addWidget(details_card, 2, 1)

        inner_layout.addLayout(grid)
        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        self._apply_preset(config_for_preset("office"))
        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(
            make_page_header(
                "Procesar",
                "Genera copias temporales; usa Guardar como para conservarlas.",
            )
        )
        self._proc_step = ProcessStep(
            run_label="Simular escaneo",
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

        outer.addLayout(
            make_page_header(
                "Resultados",
                "Revisa el acabado visual antes de guardar.",
            )
        )
        self._result_viewer = GenericPdfViewer("PDFs escaneados")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)
        return page

    def _build_action_buttons(self) -> None:
        self._run_btn = QPushButton("Simular escaneo")
        self._run_btn.setProperty("class", "Primary")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setMinimumWidth(170)
        set_button_icon(self._run_btn, "play")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        self._cancel_btn.setFixedHeight(36)
        set_button_icon(self._cancel_btn, "square", color=COLORS["danger"])
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._restart_btn = QPushButton("Nueva sesion")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "scan_simulator")

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
        for path in paths:
            if path not in self._pdf_page_cache:
                try:
                    with fitz.open(path) as doc:
                        self._pdf_page_cache[path] = doc.page_count
                except Exception:
                    self._pdf_page_cache[path] = 0

    def _on_preset_changed(self, idx: int) -> None:
        if self._loading_preset:
            return
        preset_id = self._preset_combo.currentData() or "office"
        self._apply_preset(config_for_preset(str(preset_id)))

    def _apply_preset(self, cfg: ScanSimulationConfig) -> None:
        self._loading_preset = True
        try:
            preset = next((p for p in SCAN_PRESETS if p.id == cfg.preset_id), SCAN_PRESETS[1])
            self._preset_desc_lbl.setText(preset.description)
            self._dpi_slider.setValue(float(cfg.dpi))
            self._quality_slider.setValue(float(cfg.jpeg_quality))
            self._intensity_slider.setValue(cfg.intensity * 100.0)
            self._margin_slider.setValue(cfg.margin_pct * 100.0)
            self._rotation_slider.setValue(cfg.max_rotation_deg)
            self._perspective_slider.setValue(cfg.max_perspective_pct * 100.0)
            self._paper_noise_slider.setValue(cfg.paper_noise * 100.0)
            self._background_noise_slider.setValue(cfg.background_noise * 100.0)
            self._blur_slider.setValue(cfg.blur_radius)
            _set_combo_data(self._tone_combo, cfg.tone)
            self._border_chk.setChecked(cfg.show_page_border)
            self._shadow_chk.setChecked(cfg.add_shadow)
            self._bands_chk.setChecked(cfg.add_scan_bands)
            self._dust_chk.setChecked(cfg.add_dust)
            self._seed_spin.setValue(cfg.seed)
        finally:
            self._loading_preset = False

    def _read_config(self) -> ScanSimulationConfig:
        preset_id = str(self._preset_combo.currentData() or "office")
        base = config_for_preset(preset_id)
        return replace(
            base,
            dpi=int(self._dpi_slider.value()),
            tone=str(self._tone_combo.currentData() or "gray"),
            intensity=self._intensity_slider.value() / 100.0,
            margin_pct=self._margin_slider.value() / 100.0,
            max_rotation_deg=self._rotation_slider.value(),
            max_perspective_pct=self._perspective_slider.value() / 100.0,
            background_noise=self._background_noise_slider.value() / 100.0,
            paper_noise=self._paper_noise_slider.value() / 100.0,
            blur_radius=self._blur_slider.value(),
            jpeg_quality=int(self._quality_slider.value()),
            show_page_border=self._border_chk.isChecked(),
            add_shadow=self._shadow_chk.isChecked(),
            add_scan_bands=self._bands_chk.isChecked(),
            add_dust=self._dust_chk.isChecked(),
            seed=int(self._seed_spin.value()),
            page_range=self._range_edit.text().strip(),
        )

    def _selection_estimate(self, cfg: ScanSimulationConfig) -> tuple[int, str]:
        total = 0
        for raw_path in self._docs_card.paths():
            path = Path(raw_path)
            if raw_path in self._pdf_page_cache:
                page_count = self._pdf_page_cache[raw_path]
            else:
                try:
                    with fitz.open(str(path)) as doc:
                        page_count = doc.page_count
                        self._pdf_page_cache[raw_path] = page_count
                except Exception as exc:
                    return 0, f"{path.name}: {exc}"
            try:
                pages = parse_page_selection(cfg.page_range, page_count)
            except Exception as exc:
                return 0, f"{path.name}: {exc}"
            if not pages:
                return 0, f"{path.name}: el rango no selecciona paginas"
            total += len(pages)
        return total, ""

    def _validate_ready(self, cfg: ScanSimulationConfig | None = None) -> Optional[str]:
        if self._docs_card.is_empty():
            return "Agrega al menos un PDF."
        cfg = cfg or self._read_config()
        _, estimate_error = self._selection_estimate(cfg)
        if estimate_error:
            return f"Revisa el rango de paginas. {estimate_error}"
        return None

    def _build_jobs(self) -> List[ScanSimulationJob]:
        base_dir = make_run_dir("SimularEscaneo")
        reserved: set[str] = set()
        add_suffix = add_tool_suffix_enabled()
        jobs: list[ScanSimulationJob] = []
        for path in self._docs_card.paths():
            output = build_output_path(
                base_dir,
                path,
                tool_suffix="escaneado",
                add_tool_suffix=add_suffix,
                reserved=reserved,
            )
            jobs.append(
                ScanSimulationJob(
                    pdf_path=path,
                    output_path=str(output),
                    tool_suffix="escaneado",
                    add_tool_suffix=add_suffix,
                )
            )
        return jobs

    def _refresh_summary(self) -> None:
        cfg = self._read_config()
        n = self._docs_card.count()
        estimate, estimate_error = self._selection_estimate(cfg) if n else (0, "")
        preset_label = self._preset_combo.currentText()
        tone_label = self._tone_combo.currentText()
        rows = [
            f"<b>Documentos:</b> &nbsp; {n}",
            f"<b>Preset:</b> &nbsp; {preset_label}",
            f"<b>Paginas:</b> &nbsp; {cfg.page_range or 'Todas'}",
            f"<b>Salida:</b> &nbsp; {cfg.dpi} DPI | {tone_label} | JPEG {cfg.jpeg_quality}%",
            f"<b>Realismo:</b> &nbsp; intensidad {int(cfg.intensity * 100)}% | margen {cfg.margin_pct * 100:.1f}%",
            f"<b>Variacion:</b> &nbsp; rotacion +/-{cfg.max_rotation_deg:.2f} deg | perspectiva {cfg.max_perspective_pct * 100:.2f}%",
            f"<b>Sesion:</b> &nbsp; {cfg.seed}",
        ]
        if estimate_error:
            rows.insert(0, f"<span style='color:#E5484D;'>Rango invalido: {estimate_error}</span>")
        elif n:
            rows.append(f"<b>Paginas estimadas:</b> &nbsp; {estimate}")
        self._proc_step.set_summary_html("<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>")

    def _on_run(self) -> None:
        self._stop_active_worker()
        cfg = self._read_config()
        err = self._validate_ready(cfg)
        if err:
            show_warning(self, "Falta informacion", err)
            return
        if self._worker_thread is not None:
            return

        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        jobs = self._build_jobs()

        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Iniciando simulacion...")

        self._worker = ScanSimulatorWorker(jobs, cfg)
        self._worker_thread = RunnerThread(self._worker.run, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._proc_step.set_progress(self._proc_step._prog_bar.value(), "Cancelando...")

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        self._proc_step.set_progress(int(current / max(1, total) * 100), msg)

    def _on_finished(self, results: list) -> None:
        self.last_results = list(results)
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Completado")
        self._worker_thread = None
        self._worker = None

        output_paths = [
            result.output_path
            for result in self.last_results
            if result.success and result.output_path
        ]
        ok = len(output_paths)
        pages = sum(result.page_count for result in self.last_results if result.success)

        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)
        self.ctx.tray.add_items(output_paths, "Simular escaneo")

        self._result_viewer.set_results(self.last_results)
        self._result_viewer.set_extra_stats(
            [
                {"value": pages, "label": "paginas", "color": COLORS["text"]},
                {"value": ok, "label": "escaneados", "color": COLORS["success"]},
            ]
        )
        show_success(
            self,
            "Simulacion completa",
            f"Se generaron {ok} PDF{'s' if ok != 1 else ''} escaneado{'s' if ok != 1 else ''}.",
        )
        self._switch_section(3)

    def _on_worker_error(self, msg: str) -> None:
        show_error(self, "Error", msg)
        self._proc_step.set_running(False)
        self._worker_thread = None
        self._worker = None

    def _reset_session(self) -> None:
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []
        self._docs_card.clear()
        self._range_edit.clear()
        _set_combo_data(self._preset_combo, "office")
        self._apply_preset(config_for_preset("office"))
        self._proc_step.reset()
        self._switch_section(0)

    def _open_in_explorer(self, path: str) -> None:
        from ui.common.open_utils import open_folder
        open_folder(self, path, title="Abrir carpeta")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        from ui.common.file_ordering import paths_from_mime_data

        paths = paths_from_mime_data(event.mimeData())
        self._docs_card.add_paths(paths)
        self._switch_section(0)


def _labeled_control(label: str, widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    lbl = QLabel(label)
    lbl.setStyleSheet("color: #9094A0; min-width: 86px;")
    row.addWidget(lbl)
    row.addWidget(widget, 1)
    return row


def _set_combo_data(combo: QComboBox, value: str) -> None:
    for index in range(combo.count()):
        if str(combo.itemData(index)) == str(value):
            combo.setCurrentIndex(index)
            return
