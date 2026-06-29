"""QuitarLogosWindow - hybrid logo removal for PDF batches."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import fitz
from PyQt6.QtCore import QObject, QThread, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QImage, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from core.logo_removal_engine import (
    LogoRemovalEngine,
    LogoRemovalJob,
    LogoRemovalOptions,
    LogoRemovalResult,
    SUPPORTED_LOGO_EXTENSIONS,
    parse_page_selection,
)
from core.media_conversion import DOCUMENT_EXTENSIONS
from core.output_naming import unique_output_path_for_source
from core.output_paths import make_run_dir
from shell.context import ShellContext
from ui.common.cards import card_layout, make_card, make_page_header
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.document_workspace import DocumentWorkspace as DocumentsCard
from ui.common.file_dialogs import get_open_file_names
from ui.common.icons import set_button_icon
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.process_step import ProcessStep
from ui.common.send_to_tool import SendToToolButton
from ui.common.slider import SliderWithValue
from ui.common.tool_scaffold import PipelineWindow, RunnerThread
from ui.imgs_a_pdf.window import ImageListCard


LOGO_FILTER = (
    "Logos, PDF y Word (*.png *.jpg *.jpeg *.webp *.pdf *.doc *.docx);;"
    "Logos (*.png *.jpg *.jpeg *.webp);;"
    "PDF (*.pdf);;"
    "Word (*.doc *.docx);;"
    "PNG (*.png);;"
    "JPEG (*.jpg *.jpeg);;"
    "WebP (*.webp)"
)


class LogoListCard(ImageListCard):
    """Image list restricted to logo formats supported by the engine."""

    def __init__(self, parent=None, *, ctx=None) -> None:
        super().__init__(
            parent,
            accepted_exts=SUPPORTED_LOGO_EXTENSIONS,
            ctx=ctx,
        )

    def _on_browse(self) -> None:
        files, _ = get_open_file_names(
            self.window(),
            "Seleccionar logos, PDF o Word",
            "",
            LOGO_FILTER,
        )
        if files:
            self.add_paths(files)


class LogoRemovalWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[LogoRemovalJob]) -> None:
        super().__init__()
        self.jobs = jobs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = LogoRemovalEngine().run_batch(
                self.jobs,
                progress=lambda current, total, message: self.progress.emit(
                    current, total, message
                ),
                should_cancel=lambda: self._cancel,
            )
            if self._cancel:
                self.error.emit("Operación cancelada.")
            else:
                self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


class LogoPreviewWorker(QObject):
    ready = pyqtSignal(object, list, int, int)
    failed = pyqtSignal(str, int)

    def __init__(
        self,
        pdf_path: str,
        page_index: int,
        logo_paths: List[str],
        options: LogoRemovalOptions,
        guard: int,
    ) -> None:
        super().__init__()
        self._pdf_path = pdf_path
        self._page_index = page_index
        self._logo_paths = logo_paths
        self._options = options
        self._guard = guard
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            image, matches, total_pages = LogoRemovalEngine().build_preview(
                self._pdf_path,
                self._page_index,
                self._logo_paths,
                self._options,
                max_side=1300,
                should_cancel=lambda: self._cancel,
            )
            rgba = image.convert("RGBA")
            data = rgba.tobytes("raw", "RGBA")
            qimage = QImage(
                data,
                rgba.width,
                rgba.height,
                QImage.Format.Format_RGBA8888,
            )
            self.ready.emit(qimage.copy(), matches, total_pages, self._guard)
        except Exception as exc:
            self.failed.emit(str(exc), self._guard)


class QuitarLogosWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documentos", "Carga los PDFs a limpiar"),
        ("02", "Logos", "Agrega logos desde imagen, PDF o Word"),
        ("03", "Detección", "Configura y revisa coincidencias"),
        ("04", "Procesar", "Elimina logos por lote"),
        ("05", "Resultados", "Revisa los PDFs generados"),
    ]
    BRAND = "Quitar logos"
    TAGLINE = "Detecta imágenes iguales y las elimina"
    ACCENT_COLOR = "#14B8A6"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[LogoRemovalResult] = []
        self._worker: Optional[LogoRemovalWorker] = None
        self._worker_thread: Optional[QThread] = None
        self._preview_worker: Optional[LogoPreviewWorker] = None
        self._preview_thread: Optional[QThread] = None
        self._preview_guard = 0
        self._page_counts: dict[str, int] = {}

        self._build_pages()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_logos_section())
        self.stack.addWidget(self._build_detection_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)
        outer.addLayout(
            make_page_header(
                "Documentos a limpiar",
                "Carga uno o varios PDFs. Los originales nunca se modifican.",
            )
        )

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
        outer.addWidget(self._docs_summary_lbl)
        return page

    def _build_logos_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)
        outer.addLayout(
            make_page_header(
                "Logos de referencia",
                "Agrega cada logo que quieras localizar. Se aceptan imágenes, PDF y Word.",
            )
        )

        self._logo_card = LogoListCard(ctx=self.ctx)
        self._logo_card.files_changed.connect(self._on_logos_changed)
        outer.addWidget(self._logo_card, 1)

        self._logos_summary_lbl = QLabel("Sin logos cargados.")
        self._logos_summary_lbl.setProperty("class", "CardHint")
        outer.addWidget(self._logos_summary_lbl)
        return page

    def _build_detection_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 28, 36, 28)
        outer.setSpacing(16)
        outer.addLayout(
            make_page_header(
                "Detección y vista previa",
                "El modo híbrido reconoce recursos embebidos y logos integrados en escaneos.",
            )
        )

        body = QHBoxLayout()
        body.setSpacing(16)

        settings = make_card("Ajustes de detección")
        settings.setFixedWidth(350)
        sl = card_layout(settings)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Híbrida - recomendada", "hybrid")
        self._mode_combo.addItem("Solo imágenes embebidas", "embedded")
        self._mode_combo.addItem("Solo análisis visual", "visual")
        sl.addWidget(QLabel("Método"))
        sl.addWidget(self._mode_combo)

        sl.addWidget(QLabel("Similitud mínima"))
        self._similarity_slider = SliderWithValue(
            35.0,
            98.0,
            88.0,
            step=1.0,
            suffix="%",
            decimals=0,
        )
        sl.addWidget(self._similarity_slider)

        size_row = QHBoxLayout()
        self._min_size_spin = QSpinBox()
        self._min_size_spin.setRange(1, 90)
        self._min_size_spin.setValue(2)
        self._min_size_spin.setSuffix(" % mín.")
        self._max_size_spin = QSpinBox()
        self._max_size_spin.setRange(2, 98)
        self._max_size_spin.setValue(40)
        self._max_size_spin.setSuffix(" % máx.")
        size_row.addWidget(self._min_size_spin)
        size_row.addWidget(self._max_size_spin)
        sl.addWidget(QLabel("Ancho esperado respecto a la página"))
        sl.addLayout(size_row)

        self._dpi_combo = QComboBox()
        for dpi in (96, 120, 150, 180):
            self._dpi_combo.addItem(f"{dpi} DPI", dpi)
        self._dpi_combo.setCurrentIndex(1)
        sl.addWidget(QLabel("Resolución de análisis visual"))
        sl.addWidget(self._dpi_combo)

        self._rotations_check = QCheckBox("Buscar también giros de 90°, 180° y 270°")
        self._rotations_check.setChecked(False)
        self._rotations_check.setToolTip(
            "Aumenta el tiempo de análisis visual cuando el logo puede aparecer girado."
        )
        sl.addWidget(self._rotations_check)

        self._vectors_check = QCheckBox("Eliminar gráficos vectoriales contenidos")
        self._vectors_check.setChecked(True)
        self._vectors_check.setToolTip(
            "Permite borrar logos vectoriales detectados visualmente sin eliminar texto."
        )
        sl.addWidget(self._vectors_check)

        self._padding_slider = SliderWithValue(
            0.0,
            12.0,
            1.0,
            step=0.5,
            suffix=" pt",
            decimals=1,
        )
        sl.addWidget(QLabel("Margen de eliminación"))
        sl.addWidget(self._padding_slider)

        self._fill_combo = QComboBox()
        self._fill_combo.addItem("Sin relleno - conserva el fondo", "none")
        self._fill_combo.addItem("Relleno blanco", "white")
        sl.addWidget(QLabel("Área eliminada"))
        sl.addWidget(self._fill_combo)

        self._scope_combo = QComboBox()
        self._scope_combo.addItem("Todas las páginas", "all")
        self._scope_combo.addItem("Solo primera página", "first")
        self._scope_combo.addItem("Rango personalizado", "custom")
        self._scope_combo.currentIndexChanged.connect(self._sync_scope_visibility)
        sl.addWidget(QLabel("Páginas"))
        sl.addWidget(self._scope_combo)

        self._pages_edit = QLineEdit()
        self._pages_edit.setPlaceholderText("Ejemplo: 1-3, 5, 8-")
        sl.addWidget(self._pages_edit)
        sl.addStretch(1)
        body.addWidget(settings)

        preview_card = make_card(
            "Vista previa",
            "Las cajas verdes son coincidencias embebidas; las ámbar, visuales.",
        )
        pl = card_layout(preview_card)

        preview_controls = QHBoxLayout()
        self._preview_doc_combo = QComboBox()
        self._preview_doc_combo.currentIndexChanged.connect(self._on_preview_doc_changed)
        preview_controls.addWidget(self._preview_doc_combo, 1)

        self._preview_page_spin = QSpinBox()
        self._preview_page_spin.setRange(1, 1)
        self._preview_page_spin.setPrefix("Pág. ")
        preview_controls.addWidget(self._preview_page_spin)

        self._preview_btn = QPushButton("Detectar en esta página")
        self._preview_btn.setProperty("class", "Primary")
        set_button_icon(self._preview_btn, "refresh-cw")
        self._preview_btn.clicked.connect(self._refresh_preview)
        preview_controls.addWidget(self._preview_btn)
        pl.addLayout(preview_controls)

        self._preview_scroll = QScrollArea()
        self._preview_scroll.setWidgetResizable(False)
        self._preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_lbl = QLabel("Carga PDFs y logos para analizar una página.")
        self._preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_lbl.setMinimumSize(560, 420)
        self._preview_lbl.setStyleSheet(
            "background:#0D0D10; border:1px solid #26262C; color:#9094A0;"
        )
        self._preview_scroll.setWidget(self._preview_lbl)
        pl.addWidget(self._preview_scroll, 1)

        self._preview_status_lbl = QLabel("Vista previa pendiente.")
        self._preview_status_lbl.setProperty("class", "CardHint")
        pl.addWidget(self._preview_status_lbl)
        body.addWidget(preview_card, 1)

        outer.addLayout(body, 1)
        self._sync_scope_visibility()
        self._connect_detection_signals()
        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)
        outer.addLayout(
            make_page_header(
                "Procesar documentos",
                "PDFlex detectará y eliminará cada coincidencia sin modificar los originales.",
            )
        )

        self._proc_step = ProcessStep(
            run_label="Eliminar logos",
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
        outer.addLayout(
            make_page_header(
                "Resultados",
                "Revisa las páginas procesadas antes de guardar o enviar los PDFs.",
            )
        )
        self._result_viewer = GenericPdfViewer("PDFs sin logos")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)
        return page

    def _build_action_buttons(self) -> None:
        self._run_btn = QPushButton("Eliminar logos")
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

        self._send_btn = SendToToolButton(self.ctx, "quitar_logos")
        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _connect_detection_signals(self) -> None:
        widgets = [
            self._mode_combo,
            self._dpi_combo,
            self._fill_combo,
            self._scope_combo,
        ]
        for widget in widgets:
            widget.currentIndexChanged.connect(self._mark_preview_stale)
        for widget in (
            self._min_size_spin,
            self._max_size_spin,
            self._preview_page_spin,
        ):
            widget.valueChanged.connect(self._mark_preview_stale)
        self._rotations_check.toggled.connect(self._mark_preview_stale)
        self._vectors_check.toggled.connect(self._mark_preview_stale)
        self._pages_edit.textChanged.connect(self._mark_preview_stale)
        self._similarity_slider.valueChanged.connect(self._mark_preview_stale)
        self._padding_slider.valueChanged.connect(self._mark_preview_stale)

    def _on_section_activated(self, idx: int) -> None:
        if idx == 2:
            self._sync_preview_documents()
        if idx == 3:
            self._refresh_summary()

    def set_inputs(self, paths: List[str]) -> None:
        docs = [
            path
            for path in paths
            if Path(path).suffix.lower() in DOCUMENT_EXTENSIONS
        ]
        logos = [
            path
            for path in paths
            if Path(path).suffix.lower() in SUPPORTED_LOGO_EXTENSIONS
        ]
        if docs:
            self._docs_card.add_paths(docs)
        if logos:
            self._logo_card.add_paths(logos)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        if self.stack.currentIndex() == 1:
            self._logo_card.add_paths(paths)
            return

        docs = [
            path
            for path in paths
            if Path(path).suffix.lower() in DOCUMENT_EXTENSIONS
        ]
        logos = [
            path
            for path in paths
            if Path(path).suffix.lower() in SUPPORTED_LOGO_EXTENSIONS
        ]
        if docs:
            self._docs_card.add_paths(docs)
        if logos:
            self._logo_card.add_paths(logos)

    def _on_docs_changed(self, paths: List[str]) -> None:
        count = len(paths)
        self._docs_summary_lbl.setText(
            "Sin documentos cargados."
            if count == 0
            else f"{count} PDF{'s' if count != 1 else ''} listo{'s' if count != 1 else ''}."
        )
        self._page_counts = {
            path: self._read_page_count(path)
            for path in paths
        }
        self._sync_preview_documents()
        self._sync_run_enabled()
        self._mark_preview_stale()

    def _on_logos_changed(self, paths: List[str]) -> None:
        count = len(paths)
        self._logos_summary_lbl.setText(
            "Sin logos cargados."
            if count == 0
            else f"{count} referencia{'s' if count != 1 else ''} de logo cargada"
            f"{'s' if count != 1 else ''}."
        )
        self._sync_run_enabled()
        self._mark_preview_stale()

    def _sync_preview_documents(self) -> None:
        if not hasattr(self, "_preview_doc_combo"):
            return
        current_path = self._preview_doc_combo.currentData()
        self._preview_doc_combo.blockSignals(True)
        self._preview_doc_combo.clear()
        for path in self._docs_card.paths():
            self._preview_doc_combo.addItem(Path(path).name, path)
        if current_path:
            index = self._preview_doc_combo.findData(current_path)
            if index >= 0:
                self._preview_doc_combo.setCurrentIndex(index)
        self._preview_doc_combo.blockSignals(False)
        self._on_preview_doc_changed()

    def _on_preview_doc_changed(self) -> None:
        path = str(self._preview_doc_combo.currentData() or "")
        pages = self._page_counts.get(path, 0)
        self._preview_page_spin.setRange(1, max(1, pages))
        self._preview_page_spin.setEnabled(pages > 1)
        self._mark_preview_stale()

    def _sync_scope_visibility(self) -> None:
        self._pages_edit.setVisible(self._scope_combo.currentData() == "custom")
        self._sync_run_enabled()

    def _build_options(self) -> LogoRemovalOptions:
        min_size = float(self._min_size_spin.value())
        max_size = float(self._max_size_spin.value())
        if max_size < min_size:
            max_size = min_size
        return LogoRemovalOptions(
            detection_mode=str(self._mode_combo.currentData() or "hybrid"),
            similarity=float(self._similarity_slider.value()) / 100.0,
            page_scope=str(self._scope_combo.currentData() or "all"),
            custom_pages=self._pages_edit.text().strip(),
            min_width_pct=min_size,
            max_width_pct=max_size,
            render_dpi=int(self._dpi_combo.currentData() or 120),
            detect_quarter_turns=self._rotations_check.isChecked(),
            padding_pt=float(self._padding_slider.value()),
            fill_mode=str(self._fill_combo.currentData() or "none"),
            remove_vector_graphics=self._vectors_check.isChecked(),
        )

    def _validate_ready(self) -> Optional[str]:
        if self._docs_card.is_empty():
            return "Agrega al menos un PDF."
        if self._logo_card.count() == 0:
            return "Agrega al menos un logo desde imagen, PDF o Word."
        if self._max_size_spin.value() < self._min_size_spin.value():
            return "El tamaño máximo debe ser mayor o igual al mínimo."
        if self._scope_combo.currentData() == "custom":
            if not self._pages_edit.text().strip():
                return "Escribe el rango de páginas."
            for path in self._docs_card.paths():
                try:
                    parse_page_selection(
                        "custom",
                        self._pages_edit.text().strip(),
                        self._page_counts.get(path, 0),
                    )
                except Exception as exc:
                    return f"{Path(path).name}: {exc}"
        return None

    def _sync_run_enabled(self) -> None:
        if hasattr(self, "_proc_step"):
            self._proc_step.set_run_enabled(self._validate_ready() is None)

    def _mark_preview_stale(self) -> None:
        if hasattr(self, "_preview_status_lbl"):
            self._preview_status_lbl.setText("Ajustes cambiados. Actualiza la vista previa.")
        self._sync_run_enabled()

    def _refresh_preview(self) -> None:
        error = self._validate_ready()
        if error:
            show_warning(self, "Falta información", error)
            return
        if self._preview_thread is not None:
            return
        pdf_path = str(self._preview_doc_combo.currentData() or "")
        if not pdf_path:
            show_warning(self, "Falta información", "Selecciona un PDF para la vista previa.")
            return

        self._preview_guard += 1
        guard = self._preview_guard
        self._preview_btn.setEnabled(False)
        self._preview_status_lbl.setText("Analizando la página...")
        self._preview_worker = LogoPreviewWorker(
            pdf_path,
            self._preview_page_spin.value() - 1,
            self._logo_card.paths(),
            self._build_options(),
            guard,
        )
        self._preview_thread = RunnerThread(self._preview_worker.run, self)
        self._preview_worker.ready.connect(self._on_preview_ready)
        self._preview_worker.failed.connect(self._on_preview_failed)
        self._preview_worker.ready.connect(self._preview_thread.quit)
        self._preview_worker.failed.connect(self._preview_thread.quit)
        self._preview_thread.finished.connect(self._preview_worker.deleteLater)
        self._preview_thread.finished.connect(self._preview_thread.deleteLater)
        self._preview_thread.start()

    def _on_preview_ready(
        self,
        image: QImage,
        matches: list,
        total_pages: int,
        guard: int,
    ) -> None:
        self._cleanup_preview_thread()
        if guard != self._preview_guard:
            return
        pixmap = QPixmap.fromImage(image)
        self._preview_lbl.setPixmap(pixmap)
        self._preview_lbl.setFixedSize(pixmap.size())
        self._preview_page_spin.setRange(1, max(1, total_pages))
        embedded = sum(match.method == "embedded" for match in matches)
        visual = sum(match.method == "visual" for match in matches)
        self._preview_status_lbl.setText(
            f"{len(matches)} coincidencia{'s' if len(matches) != 1 else ''} "
            f"en esta página · {embedded} embebida{'s' if embedded != 1 else ''} "
            f"· {visual} visual{'es' if visual != 1 else ''}"
        )

    def _on_preview_failed(self, message: str, guard: int) -> None:
        self._cleanup_preview_thread()
        if guard != self._preview_guard:
            return
        self._preview_status_lbl.setText("No se pudo generar la vista previa.")
        show_error(self, "Error de detección", message)

    def _cleanup_preview_thread(self) -> None:
        self._preview_btn.setEnabled(True)
        self._preview_thread = None
        self._preview_worker = None

    def _refresh_summary(self) -> None:
        options = self._build_options()
        mode_labels = {
            "hybrid": "Híbrida",
            "embedded": "Imágenes embebidas",
            "visual": "Análisis visual",
        }
        scope_labels = {
            "all": "Todas",
            "first": "Primera",
            "custom": self._pages_edit.text().strip() or "Sin rango",
        }
        rows = [
            f"<b>PDFs:</b>&nbsp;&nbsp;{self._docs_card.count()}",
            f"<b>Logos de referencia:</b>&nbsp;&nbsp;{self._logo_card.count()}",
            f"<b>Detección:</b>&nbsp;&nbsp;{mode_labels.get(options.detection_mode, options.detection_mode)}",
            f"<b>Similitud:</b>&nbsp;&nbsp;{options.similarity * 100:.0f}%",
            f"<b>Tamaño buscado:</b>&nbsp;&nbsp;{options.min_width_pct:.0f}% a {options.max_width_pct:.0f}% del ancho",
            f"<b>Páginas:</b>&nbsp;&nbsp;{scope_labels.get(options.page_scope, options.page_scope)}",
            f"<b>Relleno:</b>&nbsp;&nbsp;{'blanco' if options.fill_mode == 'white' else 'sin relleno'}",
            "<b>Texto:</b>&nbsp;&nbsp;se conserva aunque cruce el área del logo",
        ]
        error = self._validate_ready()
        if error:
            rows.insert(0, f"<span style='color:#E5484D;'>Atención: {error}</span>")
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )

    def _build_jobs(self) -> List[LogoRemovalJob]:
        out_dir = make_run_dir("QuitarLogos")
        reserved: set[str] = set()
        add_suffix = add_tool_suffix_enabled()
        options = self._build_options()
        logo_paths = self._logo_card.paths()
        jobs: list[LogoRemovalJob] = []
        for source in self._docs_card.paths():
            output = unique_output_path_for_source(
                out_dir,
                source,
                extension=".pdf",
                tool_suffix="sin_logos",
                add_tool_suffix=add_suffix,
                reserved=reserved,
                fallback="documento",
            )
            jobs.append(
                LogoRemovalJob(
                    pdf_path=source,
                    output_path=str(output),
                    logo_paths=list(logo_paths),
                    options=options,
                )
            )
        return jobs

    def _on_run(self) -> None:
        self._stop_active_worker()
        error = self._validate_ready()
        if error:
            show_warning(self, "Falta información", error)
            return
        if self._worker_thread is not None:
            return

        self.last_results = []
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Preparando detección...")

        self._worker = LogoRemovalWorker(self._build_jobs())
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

    def _on_progress(self, current: int, total: int, message: str) -> None:
        self._proc_step.set_progress(
            int(current / max(1, total) * 100),
            message,
        )

    def _on_finished(self, results: list) -> None:
        self._cleanup_worker_thread()
        self.last_results = list(results)
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Eliminación completada")

        output_paths = [
            result.output_path
            for result in self.last_results
            if result.success and result.output_path
        ]
        self.ctx.tray.add_items(output_paths, "Quitar logos")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        self._result_viewer.set_results(self.last_results)
        self._result_viewer.set_source_dirs(
            [str(Path(result.job.pdf_path).parent) for result in self.last_results]
        )

        ok = sum(result.success for result in self.last_results)
        failed = len(self.last_results) - ok
        removed = sum(
            result.match_count for result in self.last_results if result.success
        )
        message = (
            f"Se generaron {ok} PDF{'s' if ok != 1 else ''}.\n"
            f"Logos eliminados: {removed}"
        )
        if failed:
            message += f"\nCon error: {failed}"
            failed_results = [result for result in self.last_results if not result.success]
            details = [
                f"{Path(result.job.pdf_path).name}: "
                f"{result.error or 'Error desconocido'}"
                for result in failed_results[:5]
            ]
            if len(failed_results) > len(details):
                details.append(f"... y {len(failed_results) - len(details)} más")
            if details:
                message += "\n\nDetalle:\n" + "\n".join(details)
            show_warning(self, "Proceso completado con avisos", message)
        else:
            show_success(self, "Logos eliminados", message)
        self._switch_section(4)

    def _on_error(self, message: str) -> None:
        self._cleanup_worker_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, "Proceso detenido")
        show_error(self, "Error al eliminar logos", message)

    def _cleanup_worker_thread(self) -> None:
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
        self._worker_thread = None
        self._worker = None

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()

    def _current_progress(self) -> int:
        bar = getattr(self._proc_step, "_prog_bar", None)
        return int(bar.value()) if bar is not None else 0

    def _open_in_explorer(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _reset_session(self) -> None:
        self._preview_guard += 1
        self.last_results = []
        self._docs_card.clear()
        self._logo_card.clear()
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._preview_lbl.clear()
        self._preview_lbl.setText("Carga PDFs y logos para analizar una página.")
        self._preview_lbl.setMinimumSize(560, 420)
        self._preview_status_lbl.setText("Vista previa pendiente.")
        self._proc_step.reset()
        self._switch_section(0)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.handle_drop([url.toLocalFile() for url in event.mimeData().urls()])
        event.acceptProposedAction()

    def closeEvent(self, event) -> None:
        self._preview_guard += 1
        if self._preview_worker:
            self._preview_worker.cancel()
        if self._preview_thread and self._preview_thread.isRunning():
            self._preview_thread.quit()
            self._preview_thread.wait(3000)
        if self._worker:
            self._worker.cancel()
        super().closeEvent(event)

    @staticmethod
    def _read_page_count(path: str) -> int:
        try:
            doc = fitz.open(path)
            try:
                return doc.page_count
            finally:
                doc.close()
        except Exception:
            return 0
