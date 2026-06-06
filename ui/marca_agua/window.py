"""MarcaAguaWindow - text and image stamps for PDFs."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QThread, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QImage, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QComboBox, QGridLayout, QLineEdit, QSlider, QSpinBox,
)

import fitz
from PIL import Image

from core.output_naming import unique_output_path_for_source
from core.output_paths import make_run_dir
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
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.documents_step import DocumentsCard
from ui.common.file_dialogs import get_open_file_name
from ui.common.icons import set_button_icon
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.process_step import ProcessStep
from ui.common.send_to_tool import SendToToolButton
from ui.common.tool_scaffold import PipelineWindow


class WatermarkWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

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

        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_stamp_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

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

        self._image_card = make_card("Imagen", "PNG, JPG, WebP, BMP o TIFF.")
        image_row = QHBoxLayout()
        self._image_edit = QLineEdit()
        self._image_edit.setPlaceholderText("Selecciona una imagen")
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
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Sello")
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
            "Revisa los PDFs sellados y guardalos o envialos a otra herramienta.",
        ))

        self._result_viewer = GenericPdfViewer("PDFs sellados")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        nav.addStretch()

        self._send_btn = SendToToolButton(self.ctx, "marca_agua")
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
            return
        self._docs_summary_lbl.setText(
            f"{count} documento{'s' if count != 1 else ''} listo{'s' if count != 1 else ''} para sellar."
        )
        self._mark_preview_stale()

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
            "Seleccionar imagen de sello",
            str(Path.home()),
            "Imagenes (*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif);;Todos los archivos (*)",
        )
        if path:
            self._image_edit.setText(path)
            self._mark_preview_stale()

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
            try:
                parse_page_selection("custom", options.custom_pages, 999999)
            except Exception as exc:
                return f"Rango de paginas no valido: {exc}"
        return None

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

    def _mark_preview_stale(self) -> None:
        if hasattr(self, "_preview_lbl"):
            self._preview_lbl.setText("Actualiza el preview para ver la configuracion actual.")
            self._preview_lbl.setPixmap(QPixmap())

    def _refresh_preview(self) -> None:
        if self._docs_card.is_empty():
            self._preview_lbl.setText("Carga un PDF para generar preview.")
            self._preview_lbl.setPixmap(QPixmap())
            return
        validation = self._validate_ready()
        if validation:
            self._preview_lbl.setText(validation)
            self._preview_lbl.setPixmap(QPixmap())
            return

        source_path = self._docs_card.paths()[0]
        options = self._build_options()
        try:
            preview_dir = make_run_dir("MarcaAguaPreview", cleanup_days=1)
            sample_source = preview_dir / "preview_source.pdf"
            sample_output = preview_dir / "preview_sellado.pdf"
            page_index = self._preview_page_index(source_path, options)

            src = fitz.open(source_path)
            try:
                sample_doc = fitz.open()
                sample_doc.insert_pdf(src, from_page=page_index, to_page=page_index)
                sample_doc.save(sample_source)
                sample_doc.close()
            finally:
                src.close()

            preview_options = replace(options, page_scope="all", custom_pages="")
            result = WatermarkEngine().run_job(
                WatermarkJob(str(sample_source), str(sample_output), preview_options)
            )
            if not result.success:
                raise RuntimeError(result.error or "No se pudo generar el preview.")

            doc = fitz.open(result.output_path)
            try:
                pix = _render_preview_page(doc[0], self._preview_lbl.width(), 220)
                self._preview_lbl.setPixmap(pix)
                self._preview_lbl.setText("")
            finally:
                doc.close()
        except Exception as exc:
            self._preview_lbl.setPixmap(QPixmap())
            self._preview_lbl.setText(f"No se pudo generar preview: {exc}")

    def _preview_page_index(self, source_path: str, options: WatermarkOptions) -> int:
        doc = fitz.open(source_path)
        try:
            pages = parse_page_selection(options.page_scope, options.custom_pages, doc.page_count)
            return pages[0] if pages else 0
        finally:
            doc.close()

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
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

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
        self.handle_drop([url.toLocalFile() for url in event.mimeData().urls()])
        event.acceptProposedAction()


def _render_preview_page(page: fitz.Page, target_width: int, target_height: int) -> QPixmap:
    page_long = max(1.0, page.rect.width, page.rect.height)
    target_long = max(180, min(520, max(target_width - 24, target_height)))
    dpi = max(24.0, min(130.0, target_long * 72.0 / page_long))
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
    data = image.tobytes("raw", "RGBA")
    qimage = QImage(data, image.width, image.height, QImage.Format.Format_RGBA8888)
    qpix = QPixmap.fromImage(qimage.copy())
    return qpix.scaled(
        max(120, target_width - 24),
        max(120, target_height),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
