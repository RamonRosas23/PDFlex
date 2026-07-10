"""MarcaAguaWindow - text and image stamps for PDFs."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QComboBox, QGridLayout, QLineEdit, QSlider, QSpinBox,
)

from core.pdf_backend import PdfRenderDocument, extract_pages, pdf_page_count
from core.output_naming import unique_output_path_for_source
from core.output_paths import make_run_dir
from core.media_conversion import (
    IMAGE_EXTENSIONS,
    IMAGE_IMPORT_FILTER,
    pdfs_to_images_exact,
    suffix_for,
)
from core.watermark_engine import (
    COLOR_CHOICES,
    POSITIONS,
    PRESETS,
    WatermarkEngine,
    WatermarkJob,
    WatermarkOptions,
    WatermarkResult,
    parse_page_selection,
    preset_for,
)
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.dialogs import show_error, show_info, show_success, show_warning
from ui.common.document_workspace import DocumentWorkspace as DocumentsCard
from ui.common.file_dialogs import get_open_file_name
from ui.common.icons import set_button_icon
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.pdf_render_utils import rendered_page_to_qimage
from ui.common.process_step import ProcessStep
from ui.common.send_to_tool import SendToToolButton
from ui.common.tool_scaffold import PipelineWindow, RunnerThread


class WatermarkPreviewWorker(QObject):
    """Genera preview de marca de agua en hilo secundario. Emite QImage."""
    ready = Signal(object)   # QImage
    failed = Signal(str)

    def __init__(
        self,
        source_path: str,
        options: "WatermarkOptions",
        preview_dir: "Path",
        target_w: int,
        target_h: int,
    ) -> None:
        super().__init__()
        self._source_path = source_path
        self._options = options
        self._preview_dir = preview_dir
        self._target_w = target_w
        self._target_h = target_h

    def run(self) -> None:
        try:
            sample_source = self._preview_dir / "preview_source.pdf"
            sample_output = self._preview_dir / "preview_sellado.pdf"
            page_count = pdf_page_count(self._source_path)
            pages = parse_page_selection(
                self._options.page_scope, self._options.custom_pages, page_count
            )
            page_index = pages[0] if pages else 0
            extract_pages(self._source_path, [page_index], sample_source)
            preview_options = replace(self._options, page_scope="all", custom_pages="")
            result = WatermarkEngine().run_job(
                WatermarkJob(str(sample_source), str(sample_output), preview_options)
            )
            if not result.success:
                self.failed.emit(result.error or "No se pudo generar el preview.")
                return
            with PdfRenderDocument(result.output_path) as document:
                qimage = _render_preview_qimage(
                    document, 0, self._target_w, self._target_h
                )
                self.ready.emit(qimage)
        except Exception as exc:
            self.failed.emit(str(exc))


class WatermarkWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, jobs: List[WatermarkJob]) -> None:
        super().__init__()
        self.jobs = jobs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = WatermarkEngine().run_batch(
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


class MarcaAguaWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documentos", "Carga PDFs a sellar"),
        ("02", "Sello", "Configura texto, imagen y alcance"),
        ("03", "Procesar", "Aplica la marca de agua"),
        ("04", "Resultados", "Revisa documentos sellados"),
    ]
    BRAND = "Marca de agua"
    TAGLINE = "Sellos de texto o imagen por lote"
    ACCENT_COLOR = "#F97316"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[WatermarkResult] = []
        self._worker: Optional[WatermarkWorker] = None
        self._worker_thread: Optional[QThread] = None
        self._pdf_page_cache: dict[str, int] = {}
        self._preview_worker: Optional[WatermarkPreviewWorker] = None
        self._preview_thread: Optional[QThread] = None
        self._stamp_conv_thread: Optional[QThread] = None
        self._stamp_conv_worker = None
        self._stamp_conv_dlg = None

        self._build_pages()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_stamp_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_action_buttons(self) -> None:
        self._run_btn = QPushButton("Aplicar sello")
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

        self._send_btn = SendToToolButton(self.ctx, "marca_agua")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documentos a sellar",
            "Carga PDFs y aplica sellos sin modificar los originales.",
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

    def _build_stamp_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Sello o marca de agua",
            "Usa presets rapidos o ajusta opacidad, posicion, rotacion y paginas.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        type_card = make_card("Tipo")
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Texto / sello", "text")
        self._mode_combo.addItem("Imagen / logo", "image")
        self._mode_combo.currentIndexChanged.connect(self._sync_mode_visibility)
        card_layout(type_card).addWidget(self._mode_combo)

        self._preset_combo = QComboBox()
        for preset in PRESETS.values():
            self._preset_combo.addItem(preset.label, preset.id)
        self._preset_combo.addItem("Personalizado", "custom")
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        card_layout(type_card).addWidget(self._preset_combo)
        grid.addWidget(type_card, 0, 0)

        self._text_card = make_card("Texto")
        self._text_edit = QLineEdit("CONFIDENCIAL")
        self._text_edit.setPlaceholderText("Texto del sello")
        card_layout(self._text_card).addWidget(self._text_edit)

        self._color_combo = QComboBox()
        for color_id, (label, _rgb) in COLOR_CHOICES.items():
            self._color_combo.addItem(label, color_id)
        card_layout(self._text_card).addWidget(self._color_combo)

        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(8, 160)
        self._font_size_spin.setValue(62)
        self._font_size_spin.setSuffix(" pt")
        card_layout(self._text_card).addWidget(self._font_size_spin)
        grid.addWidget(self._text_card, 0, 1)

        self._image_card = make_card("Imagen", "Imagen, PDF o Word.")
        image_row = QHBoxLayout()
        self._image_edit = QLineEdit()
        self._image_edit.setPlaceholderText("Selecciona una imagen, PDF o Word")
        image_row.addWidget(self._image_edit, 1)
        browse_img = QPushButton("Examinar")
        browse_img.setProperty("class", "Ghost")
        set_button_icon(browse_img, "folder-open")
        browse_img.clicked.connect(self._browse_image)
        image_row.addWidget(browse_img)
        card_layout(self._image_card).addLayout(image_row)

        self._image_width_spin = QSpinBox()
        self._image_width_spin.setRange(5, 90)
        self._image_width_spin.setValue(38)
        self._image_width_spin.setSuffix(" % ancho")
        card_layout(self._image_card).addWidget(self._image_width_spin)
        grid.addWidget(self._image_card, 1, 1)

        placement_card = make_card("Apariencia")
        self._position_combo = QComboBox()
        for position_id, label in POSITIONS.items():
            self._position_combo.addItem(label, position_id)
        card_layout(placement_card).addWidget(self._position_combo)

        self._rotation_spin = QSpinBox()
        self._rotation_spin.setRange(-180, 180)
        self._rotation_spin.setValue(-35)
        self._rotation_spin.setSuffix(" grados")
        card_layout(placement_card).addWidget(self._rotation_spin)

        opacity_row = QHBoxLayout()
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(5, 100)
        self._opacity_slider.setValue(18)
        self._opacity_slider.valueChanged.connect(self._sync_opacity_label)
        self._opacity_lbl = QLabel("18 %")
        self._opacity_lbl.setMinimumWidth(48)
        self._opacity_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        opacity_row.addWidget(self._opacity_slider, 1)
        opacity_row.addWidget(self._opacity_lbl)
        card_layout(placement_card).addLayout(opacity_row)
        grid.addWidget(placement_card, 1, 0)

        pages_card = make_card("Paginas")
        self._scope_combo = QComboBox()
        self._scope_combo.addItem("Todas las paginas", "all")
        self._scope_combo.addItem("Primera pagina", "first")
        self._scope_combo.addItem("Ultima pagina", "last")
        self._scope_combo.addItem("Rango personalizado", "custom")
        self._scope_combo.currentIndexChanged.connect(self._sync_scope_visibility)
        card_layout(pages_card).addWidget(self._scope_combo)

        self._pages_edit = QLineEdit()
        self._pages_edit.setPlaceholderText("Ejemplo: 1-3, 5, 8-")
        card_layout(pages_card).addWidget(self._pages_edit)
        grid.addWidget(pages_card, 2, 0)

        preview_card = make_card("Preview", "Renderiza una pagina de muestra con la configuracion actual.")
        self._preview_lbl = QLabel("Carga un PDF y actualiza el preview.")
        self._preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_lbl.setMinimumHeight(220)
        self._preview_lbl.setStyleSheet(
            "background:#0D0D10; border:1px solid #26262C; border-radius:8px; color:#9094A0;"
        )
        card_layout(preview_card).addWidget(self._preview_lbl, 1)
        preview_btn = QPushButton("Actualizar preview")
        preview_btn.setProperty("class", "Ghost")
        set_button_icon(preview_btn, "refresh-cw")
        preview_btn.clicked.connect(self._refresh_preview)
        card_layout(preview_card).addWidget(preview_btn)
        grid.addWidget(preview_card, 2, 1)

        outer.addLayout(grid)
        outer.addStretch(1)

        self._on_preset_changed()
        self._sync_mode_visibility()
        self._sync_scope_visibility()
        self._connect_preview_stale_signals()
        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Genera PDFs sellados en temporal; usa Guardar como para conservarlos.",
        ))

        self._proc_step = ProcessStep(
            run_label="Aplicar sello",
            show_output_dir=False,
        )
        self._proc_step.set_run_enabled(False)
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
            "Revisa los PDFs sellados y guardalos o envialos a otra herramienta.",
        ))

        self._result_viewer = GenericPdfViewer("PDFs sellados")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        return page

    def _on_section_activated(self, idx: int) -> None:
        if idx == 1:
            self._mark_preview_stale()
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
            self._mark_preview_stale()
            self._sync_run_enabled()
            return
        self._docs_summary_lbl.setText(
            f"{count} documento{'s' if count != 1 else ''} listo{'s' if count != 1 else ''} para sellar."
        )
        for p in paths:
            if p not in self._pdf_page_cache:
                try:
                    self._pdf_page_cache[p] = pdf_page_count(p)
                except Exception:
                    self._pdf_page_cache[p] = 0
        self._mark_preview_stale()
        self._sync_run_enabled()

    def _on_preset_changed(self) -> None:
        preset_id = str(self._preset_combo.currentData() or "custom")
        if preset_id == "custom":
            return
        preset = preset_for(preset_id)
        self._text_edit.setText(preset.text)
        self._font_size_spin.setValue(round(preset.font_size))
        self._rotation_spin.setValue(round(preset.rotation_deg))
        self._opacity_slider.setValue(round(preset.opacity * 100))
        self._set_combo_data(self._position_combo, preset.position)
        self._set_color_by_rgb(preset.color)

    def _sync_mode_visibility(self) -> None:
        mode = self._mode()
        self._text_card.setVisible(mode == "text")
        self._image_card.setVisible(mode == "image")
        self._preset_combo.setEnabled(mode == "text")
        self._mark_preview_stale()

    def _sync_scope_visibility(self) -> None:
        self._pages_edit.setVisible(self._page_scope() == "custom")
        self._mark_preview_stale()

    def _sync_opacity_label(self) -> None:
        self._opacity_lbl.setText(f"{self._opacity_slider.value()} %")
        self._mark_preview_stale()

    def _browse_image(self) -> None:
        path, _ = get_open_file_name(
            self,
            "Seleccionar imagen, PDF o Word para sello",
            str(Path.home()),
            IMAGE_IMPORT_FILTER + ";;Todos los archivos (*)",
        )
        if path:
            self._load_stamp_image_input(path)

    def _load_stamp_image_input(self, path: str) -> None:
        suffix = suffix_for(path)
        if suffix in IMAGE_EXTENSIONS:
            self._set_stamp_image_path(path)
        elif suffix == ".pdf":
            self._set_stamp_image_from_pdf(path)
        elif suffix in {".doc", ".docx"}:
            self._convert_word_stamp_to_image(path)
        else:
            show_warning(
                self,
                "Archivo no compatible",
                "Selecciona una imagen, PDF o Word para usarlo como sello.",
            )

    def _set_stamp_image_path(self, path: str) -> None:
        self._image_edit.setText(path)
        self._mark_preview_stale()

    def _set_stamp_image_from_pdf(self, path: str) -> None:
        try:
            images = pdfs_to_images_exact([path], out_dir=make_run_dir("converted"))
        except Exception as exc:
            show_error(self, "No se pudo convertir el PDF", str(exc))
            return
        if images:
            self._set_stamp_image_path(images[0])

    def _convert_word_stamp_to_image(self, path: str) -> None:
        converter = getattr(self.ctx, "word_converter", None)
        if converter is None or not converter.is_available():
            show_info(
                self,
                "Microsoft Office requerido",
                "Para convertir archivos Word a imagen se necesita Microsoft Office.",
            )
            return

        from shell.word_to_pdf import WordConvertWorker
        from ui.common.word_convert_dialog import WordConvertDialog

        paths = [path]
        self._stamp_conv_dlg = WordConvertDialog(self, paths)
        worker = WordConvertWorker(converter, paths, make_run_dir("converted"))
        self._stamp_conv_thread = RunnerThread(worker.run, self)
        self._stamp_conv_worker = worker
        worker.progress.connect(self._stamp_conv_dlg.on_progress)
        worker.finished.connect(self._on_stamp_word_done)
        worker.finished.connect(self._stamp_conv_dlg.on_finished)
        worker.error.connect(self._on_stamp_word_error)
        worker.error.connect(self._stamp_conv_dlg.on_error)
        worker.finished.connect(self._stamp_conv_thread.quit)
        worker.error.connect(self._stamp_conv_thread.quit)
        self._stamp_conv_thread.finished.connect(worker.deleteLater)
        self._stamp_conv_thread.finished.connect(self._stamp_conv_thread.deleteLater)
        self._stamp_conv_dlg.cancel_requested.connect(worker.cancel)
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self._stamp_conv_thread.start)
        self._stamp_conv_dlg.exec()

    def _on_stamp_word_done(self, converted_pdfs: List[str]) -> None:
        self._stamp_conv_thread = None
        self._stamp_conv_worker = None
        if converted_pdfs:
            self._set_stamp_image_from_pdf(converted_pdfs[0])

    def _on_stamp_word_error(self, msg: str) -> None:
        self._stamp_conv_thread = None
        self._stamp_conv_worker = None

    def _mode(self) -> str:
        return str(self._mode_combo.currentData() or "text")

    def _page_scope(self) -> str:
        return str(self._scope_combo.currentData() or "all")

    def _position(self) -> str:
        return str(self._position_combo.currentData() or "center")

    def _color(self) -> tuple[float, float, float]:
        color_id = str(self._color_combo.currentData() or "red")
        return COLOR_CHOICES.get(color_id, COLOR_CHOICES["red"])[1]

    def _build_options(self) -> WatermarkOptions:
        return WatermarkOptions(
            mode=self._mode(),
            text=self._text_edit.text().strip(),
            image_path=self._image_edit.text().strip(),
            position=self._position(),
            opacity=self._opacity_slider.value() / 100.0,
            rotation_deg=float(self._rotation_spin.value()),
            font_size=float(self._font_size_spin.value()),
            image_width_pct=float(self._image_width_spin.value()),
            color=self._color(),
            page_scope=self._page_scope(),
            custom_pages=self._pages_edit.text().strip(),
        )

    def _validate_ready(self) -> Optional[str]:
        if self._docs_card.is_empty():
            return "Agrega al menos un PDF."
        options = self._build_options()
        if options.mode == "text" and not options.text:
            return "Escribe el texto del sello."
        if options.mode == "image":
            if not options.image_path:
                return "Selecciona una imagen."
            if not Path(options.image_path).exists():
                return "La imagen seleccionada no existe."
        if options.page_scope == "custom" and not options.custom_pages:
            return "Escribe el rango de paginas."
        if options.page_scope == "custom":
            range_error = self._custom_page_range_error(options)
            if range_error:
                return range_error
        return None

    def _custom_page_range_error(self, options: WatermarkOptions) -> str:
        for raw_path in self._docs_card.paths():
            page_count = self._pdf_page_cache.get(raw_path)
            if page_count is None:
                continue  # Aún cargando en background — omitir validación por ahora
            try:
                parse_page_selection("custom", options.custom_pages, page_count)
            except Exception as exc:
                return f"Rango de paginas no valido en {Path(raw_path).name}: {exc}"
        return ""

    def _refresh_summary(self) -> None:
        paths = self._docs_card.paths()
        options = self._build_options()
        mode = "Texto" if options.mode == "text" else "Imagen"
        stamp = options.text if options.mode == "text" else Path(options.image_path).name or "Sin imagen"
        scope_labels = {
            "all": "Todas las paginas",
            "first": "Primera pagina",
            "last": "Ultima pagina",
            "custom": options.custom_pages or "Rango pendiente",
        }
        rows = [
            f"<b>Documentos:</b>&nbsp;&nbsp;{len(paths)}",
            f"<b>Tipo:</b>&nbsp;&nbsp;{mode}",
            f"<b>Sello:</b>&nbsp;&nbsp;{stamp}",
            f"<b>Posicion:</b>&nbsp;&nbsp;{POSITIONS.get(options.position, 'Centro')}",
            f"<b>Opacidad:</b>&nbsp;&nbsp;{round(options.opacity * 100)} %",
            f"<b>Paginas:</b>&nbsp;&nbsp;{scope_labels.get(options.page_scope, 'Todas')}",
            "<b>Salida:</b>&nbsp;&nbsp;PDF temporal por documento",
        ]
        error = self._validate_ready()
        if error:
            rows.insert(0, f"<span style='color:#E5484D;'>Atencion: {error}</span>")
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )
        self._sync_run_enabled()

    def _mark_preview_stale(self) -> None:
        if hasattr(self, "_preview_lbl"):
            self._preview_lbl.setText("Actualiza el preview para ver la configuracion actual.")
            self._preview_lbl.setPixmap(QPixmap())
        self._sync_run_enabled()

    def _sync_run_enabled(self) -> None:
        if hasattr(self, "_proc_step"):
            self._proc_step.set_run_enabled(self._validate_ready() is None)

    def _refresh_preview(self) -> None:
        if self._preview_thread and self._preview_thread.isRunning():
            return  # Ya hay un preview en curso
        if self._docs_card.is_empty():
            self._preview_lbl.setText("Carga un PDF para generar preview.")
            self._preview_lbl.setPixmap(QPixmap())
            return
        validation = self._validate_ready()
        if validation:
            self._preview_lbl.setText(validation)
            self._preview_lbl.setPixmap(QPixmap())
            return

        self._preview_lbl.setText("Generando preview…")
        self._preview_lbl.setPixmap(QPixmap())

        source_path = self._docs_card.paths()[0]
        options = self._build_options()
        preview_dir = make_run_dir("MarcaAguaPreview", cleanup_days=1)
        target_w = max(120, self._preview_lbl.width())
        target_h = max(220, self._preview_lbl.height())

        self._preview_worker = WatermarkPreviewWorker(
            source_path, options, preview_dir, target_w, target_h
        )
        self._preview_thread = RunnerThread(self._preview_worker.run, self)
        self._preview_worker.ready.connect(self._on_preview_ready)
        self._preview_worker.failed.connect(self._on_preview_failed)
        self._preview_worker.ready.connect(self._preview_thread.quit)
        self._preview_worker.failed.connect(self._preview_thread.quit)
        self._preview_thread.finished.connect(self._preview_worker.deleteLater)
        self._preview_thread.finished.connect(self._preview_thread.deleteLater)
        self._preview_thread.start()

    def _on_preview_ready(self, qimage: "QImage") -> None:
        self._preview_worker = None
        self._preview_thread = None
        if qimage is None or qimage.isNull():
            self._preview_lbl.setPixmap(QPixmap())
            self._preview_lbl.setText("No se pudo generar el preview.")
            return
        qpix = QPixmap.fromImage(qimage)
        scaled = qpix.scaled(
            max(120, self._preview_lbl.width() - 24),
            max(220, self._preview_lbl.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_lbl.setPixmap(scaled)
        self._preview_lbl.setText("")

    def _on_preview_failed(self, msg: str) -> None:
        self._preview_worker = None
        self._preview_thread = None
        self._preview_lbl.setPixmap(QPixmap())
        self._preview_lbl.setText(f"No se pudo generar preview: {msg}")

    def _connect_preview_stale_signals(self) -> None:
        self._text_edit.textChanged.connect(lambda _value: self._mark_preview_stale())
        self._image_edit.textChanged.connect(lambda _value: self._mark_preview_stale())
        self._color_combo.currentIndexChanged.connect(lambda _idx: self._mark_preview_stale())
        self._position_combo.currentIndexChanged.connect(lambda _idx: self._mark_preview_stale())
        self._rotation_spin.valueChanged.connect(lambda _value: self._mark_preview_stale())
        self._font_size_spin.valueChanged.connect(lambda _value: self._mark_preview_stale())
        self._image_width_spin.valueChanged.connect(lambda _value: self._mark_preview_stale())
        self._pages_edit.textChanged.connect(lambda _value: self._mark_preview_stale())

    def _build_jobs(self) -> List[WatermarkJob]:
        out_dir = make_run_dir("MarcaAgua")
        reserved: set[str] = set()
        add_suffix = add_tool_suffix_enabled()
        options = self._build_options()
        jobs: List[WatermarkJob] = []
        for path in self._docs_card.paths():
            out_path = unique_output_path_for_source(
                out_dir,
                path,
                extension=".pdf",
                tool_suffix="sellado",
                add_tool_suffix=add_suffix,
                reserved=reserved,
                fallback="documento",
            )
            jobs.append(WatermarkJob(pdf_path=path, output_path=str(out_path), options=options))
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
        self._proc_step.set_progress(0, "Preparando sellos...")

        self._worker = WatermarkWorker(self._build_jobs())
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
        self._proc_step.set_progress(100, "Sellado completado")

        output_paths = [
            result.output_path
            for result in self.last_results
            if result.success and result.output_path
        ]
        self.ctx.tray.add_items(output_paths, "Marca de agua")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        self._result_viewer.set_results(self.last_results)
        self._result_viewer.set_source_dirs([
            str(Path(result.job.pdf_path).parent)
            for result in self.last_results
        ])

        ok = sum(1 for result in self.last_results if result.success)
        failed = len(self.last_results) - ok
        stamped = sum(result.stamped_pages for result in self.last_results if result.success)
        msg = (
            f"Se sellaron {ok} PDF{'s' if ok != 1 else ''}.\n"
            f"Paginas selladas: {stamped}"
        )
        if failed:
            msg += f"\nCon error: {failed}"
            show_warning(self, "Sellado completado con avisos", msg)
        else:
            show_success(self, "Sellado completo", msg)
        self._switch_section(3)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al aplicar sello", msg)

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
        self._mode_combo.setCurrentIndex(0)
        self._preset_combo.setCurrentIndex(0)
        self._image_edit.clear()
        self._scope_combo.setCurrentIndex(0)
        self._pages_edit.clear()
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._proc_step.reset()
        self._switch_section(0)

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _set_color_by_rgb(self, rgb: tuple[float, float, float]) -> None:
        best_index = 0
        best_delta = 999.0
        for index in range(self._color_combo.count()):
            color_id = str(self._color_combo.itemData(index))
            candidate = COLOR_CHOICES.get(color_id, COLOR_CHOICES["red"])[1]
            delta = sum(abs(candidate[i] - rgb[i]) for i in range(3))
            if delta < best_delta:
                best_delta = delta
                best_index = index
        self._color_combo.setCurrentIndex(best_index)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        from ui.common.file_ordering import paths_from_mime_data

        self.handle_drop(paths_from_mime_data(event.mimeData()))
        event.acceptProposedAction()


def _render_preview_qimage(
    document: PdfRenderDocument,
    page_index: int,
    target_width: int,
    target_height: int,
) -> QImage:
    """Renderiza página como QImage — thread-safe, sin QPixmap."""
    info = document.page_info(page_index)
    page_long = max(1.0, info.width_pt, info.height_pt)
    target_long = max(180, min(520, max(target_width - 24, target_height)))
    dpi = max(24.0, min(130.0, target_long * 72.0 / page_long))
    return rendered_page_to_qimage(
        document.render_page(page_index, scale=dpi / 72.0)
    ).convertToFormat(QImage.Format.Format_RGBA8888)


def _render_preview_page(
    document: PdfRenderDocument,
    page_index: int,
    target_width: int,
    target_height: int,
) -> QPixmap:
    qimage = _render_preview_qimage(
        document, page_index, target_width, target_height
    )
    qpix = QPixmap.fromImage(qimage)
    return qpix.scaled(
        max(120, target_width - 24),
        max(120, target_height),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
