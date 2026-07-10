"""MembretadoWindow — pipeline de membretado masivo de PDFs.

Pipeline:
    01 Membrete  →  02 Documentos  →  03 Márgenes  →  04 Alcance  →  05 Procesar  →  06 Resultados
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QObject, QThread, Signal, QRectF, QSize
from PySide6.QtGui import (
    QPixmap, QPainter, QPen, QColor, QBrush,
    QDragEnterEvent, QDropEvent, QDesktopServices,
)
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QFrame,
    QScrollArea, QListWidget, QListWidgetItem,
    QComboBox, QLineEdit, QCheckBox,
    QSizePolicy, QGridLayout,
)

from core.margin_detector import MembreteMargins, detect_margins
from core.pdf_backend import PdfRenderDocument, pdf_page_count
from core.membrete_library import (
    SavedLetterhead,
    add_letterhead_to_library,
    load_letterhead_library,
    remove_letterhead_from_library,
    update_letterhead_config,
)
from core.membrete_engine import (
    MembreteJob,
    MembreteEngine,
    MembreteJobResult,
    compact_page_indexes,
    parse_membrete_page_scope,
)
from core.output_paths import make_run_dir
from core.output_naming import unique_output_path_for_source
from core.media_conversion import (
    DOCUMENT_IMPORT_EXTENSIONS,
    DOCUMENT_IMPORT_FILTER,
    IMAGE_EXTENSIONS,
    images_to_pdf_exact,
)
from shell.context import ShellContext
from shell.word_to_pdf import WordConvertWorker
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.slider import SliderWithValue
from ui.common.tool_scaffold import PipelineWindow, RunnerThread
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.document_workspace import DocumentWorkspace as DocumentsCard
from ui.common.process_step import ProcessStep
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.dialogs import ask_question, show_error, show_info, show_success, show_warning
from ui.common.file_dialogs import get_open_file_name
from ui.common.icons import set_button_icon
from ui.common.pdf_render_utils import rendered_page_to_qimage
from ui.common.result_ui import ElidedLabel, configure_file_list, elide_middle_text


# ====================================================================== #
#  Cargador asíncrono de membrete (preview + thumbnail en hilo de fondo)
# ====================================================================== #

class _MembretePageLoader(QObject):
    """Carga un PDF de membrete: valida, renderiza thumbnail y preview,
    detecta márgenes.  Emite QImage (nunca QPixmap) para ser convertido a
    QPixmap únicamente en el hilo GUI.

    Se usa junto con _MembretaLoadThread que llama run() en background.
    El objeto NO se mueve al hilo (moveToThread) — las señales cruzan al
    hilo GUI vía QueuedConnection automáticamente.
    """

    # path, source_name, QImage_thumb, QImage_prev, pw, ph, page_count, MembreteMargins
    loaded = Signal(str, str, object, object, float, float, int, object)
    error = Signal(str, str)  # path, error_msg

    def __init__(self, path: str, source_name: str) -> None:
        super().__init__()
        self._path = path
        self._source_name = source_name

    def run(self) -> None:
        try:
            with PdfRenderDocument(self._path) as doc:
                if doc.page_count <= 0:
                    self.error.emit(self._path, "El PDF no tiene paginas.")
                    return
                page_count = doc.page_count
                page = doc.page_info(0)
                pw, ph = page.width_pt, page.height_pt

                # Thumbnail 0.4× (~30 ms)
                qimg_thumb = rendered_page_to_qimage(
                    doc.render_page(0, scale=0.4)
                )

                # Preview 1.5× (puede ser 200–500 ms en PDFs complejos)
                qimg_prev = rendered_page_to_qimage(
                    doc.render_page(0, scale=1.5)
                )

        except Exception as e:
            self.error.emit(self._path, str(e))
            return

        # detect_margins abre el PDF de nuevo (rápido pero bloquea si se hace en GUI)
        margins = detect_margins(self._path)

        self.loaded.emit(
            self._path, self._source_name,
            qimg_thumb, qimg_prev,
            pw, ph, page_count,
            margins,
        )


class _MembretaLoadThread(QThread):
    """Hilo que ejecuta _MembretePageLoader.run() en background.

    Usar una subclase de QThread en vez de moveToThread+started.connect
    conserva una ejecución determinista cuando el QThread tiene padre.
    El loader permanece en el hilo GUI: sus señales llegarán al slot receptor
    vía QueuedConnection automáticamente.
    """

    def __init__(self, loader: _MembretePageLoader, parent=None) -> None:
        super().__init__(parent)
        self._loader = loader

    def run(self) -> None:
        self._loader.run()


# ====================================================================== #
#  Worker
# ====================================================================== #

class MembreteWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        jobs: List[MembreteJob],
        letterhead_path: str,
        margins: MembreteMargins,
    ) -> None:
        super().__init__()
        self.jobs = jobs
        self.letterhead_path = letterhead_path
        self.margins = margins
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            engine = MembreteEngine()
            results = engine.run_batch(
                self.jobs,
                self.letterhead_path,
                self.margins,
                progress=lambda c, t, m: self.progress.emit(c, t, m),
                should_cancel=lambda: self._cancel,
            )
            if self._cancel:
                self.error.emit("Operación cancelada.")
            else:
                self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


# ====================================================================== #
#  Widget de preview de márgenes
# ====================================================================== #

class MarginPreviewWidget(QWidget):
    """Renderiza el membrete con overlay semitransparente mostrando los márgenes."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lh_pixmap: Optional[QPixmap] = None
        self._page_w_pt: float = 0.0
        self._page_h_pt: float = 0.0
        self._top: float = 72.0
        self._bottom: float = 54.0
        self._left: float = 18.0
        self._right: float = 18.0
        self.setMinimumSize(200, 260)
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_letterhead(self, pixmap: QPixmap, page_w_pt: float, page_h_pt: float) -> None:
        self._lh_pixmap = pixmap
        self._page_w_pt = page_w_pt
        self._page_h_pt = page_h_pt
        self.update()

    def clear_letterhead(self) -> None:
        self._lh_pixmap = None
        self._page_w_pt = 0.0
        self._page_h_pt = 0.0
        self.update()

    def set_margins(self, top: float, bottom: float, left: float, right: float) -> None:
        self._top = top
        self._bottom = bottom
        self._left = left
        self._right = right
        self.update()

    def paintEvent(self, event) -> None:
        if not self._lh_pixmap or self._page_w_pt <= 0:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor("#111114"))
            painter.setPen(QColor("#33333B"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Sin membrete cargado")
            painter.end()
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Escalar membrete para que quepa en el widget (con margen interno)
        pad = 12
        available_w = self.width() - 2 * pad
        available_h = self.height() - 2 * pad
        scaled = self._lh_pixmap.scaled(
            available_w, available_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x0 = (self.width() - scaled.width()) // 2
        y0 = (self.height() - scaled.height()) // 2
        sw = scaled.width()
        sh = scaled.height()

        # Sombra sutil
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawRect(QRectF(x0 + 3, y0 + 3, sw, sh))

        p.drawPixmap(x0, y0, scaled)

        pw = self._page_w_pt
        ph = self._page_h_pt

        # Factores de escala pt → píxeles del pixmap escalado
        sx = sw / pw
        sy = sh / ph

        t = self._top
        b = self._bottom
        le = self._left
        ri = self._right

        # Coordenadas en píxeles del widget
        safe_x0 = x0 + le * sx
        safe_y0 = y0 + t * sy
        safe_x1 = x0 + (pw - ri) * sx
        safe_y1 = y0 + (ph - b) * sy

        # Overlay oscuro en zonas de margen
        overlay = QColor(0, 0, 0, 100)
        # Superior
        p.fillRect(QRectF(x0, y0, sw, t * sy), overlay)
        # Inferior
        p.fillRect(QRectF(x0, safe_y1, sw, b * sy + 1), overlay)
        # Izquierdo (solo franja central)
        p.fillRect(QRectF(x0, safe_y0, le * sx, safe_y1 - safe_y0), overlay)
        # Derecho
        p.fillRect(QRectF(safe_x1, safe_y0, ri * sx + 1, safe_y1 - safe_y0), overlay)

        # Borde de la zona segura (línea punteada accent)
        pen = QPen(QColor(94, 106, 210), 1.5)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(safe_x0, safe_y0, safe_x1 - safe_x0, safe_y1 - safe_y0))

        # Etiquetas de margen
        p.setPen(QColor(255, 255, 255, 180))
        font = p.font()
        font.setPointSize(8)
        p.setFont(font)

        if t * sy > 14:
            p.drawText(
                QRectF(x0, y0, sw, t * sy),
                Qt.AlignmentFlag.AlignCenter,
                f"Sup. {t:.0f} pt",
            )
        if b * sy > 14:
            p.drawText(
                QRectF(x0, safe_y1, sw, b * sy),
                Qt.AlignmentFlag.AlignCenter,
                f"Inf. {b:.0f} pt",
            )

        p.end()


# ====================================================================== #
#  Ventana de Membretado
# ====================================================================== #

class MembretadoWindow(PipelineWindow):

    LETTERHEAD_EXTS = tuple(DOCUMENT_IMPORT_EXTENSIONS)

    SECTIONS = [
        ("01", "Membrete",   "Carga la hoja membretada"),
        ("02", "Documentos", "Carga los PDFs a membretar"),
        ("03", "Márgenes",   "Ajusta los márgenes de seguridad"),
        ("04", "Alcance",    "Define páginas incluidas o excluidas"),
        ("05", "Procesar",   "Ejecuta el membretado"),
        ("06", "Resultados", "Revisa los documentos membretados"),
    ]
    BRAND = "Membretado"
    TAGLINE = "Superpone PDFs sobre hojas membretadas"
    ACCENT_COLOR = "#B87FF5"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)

        self._lh_path: Optional[str] = None
        self._lh_source_name = ""
        self._lh_preview_pixmap: Optional[QPixmap] = None
        self._lh_page_w_pt = 0.0
        self._lh_page_h_pt = 0.0
        self._margins = MembreteMargins()
        self.last_results: List[MembreteJobResult] = []
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[MembreteWorker] = None
        self._conv_thread: Optional[QThread] = None
        self._conv_dlg = None
        self._letterhead_library: list[SavedLetterhead] = []
        self._active_library_id: Optional[str] = None
        self._lh_loading_library_entry: Optional[SavedLetterhead] = None
        self._suppress_library_persist = False
        self._page_count_cache: dict[str, int] = {}
        self._active_scope_doc_path: Optional[str] = None
        self._doc_scope_enabled: set[str] = set()
        self._doc_scope_modes: dict[str, str] = {}
        self._doc_scope_texts: dict[str, str] = {}
        self._updating_scope_ui = False
        # Carga asíncrona de membrete
        self._lh_load_thread: Optional[QThread] = None
        self._lh_loading_path: Optional[str] = None  # guard contra resultados obsoletos

        self._build_pages()
        self._build_action_buttons()
        self._refresh_letterhead_library()
        self._switch_section(0)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_membrete_section())
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_margins_section())
        self.stack.addWidget(self._build_scope_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    # ------------------------------------------------------------------ #
    # Paso 01: Membrete
    # ------------------------------------------------------------------ #

    def _build_membrete_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(18)

        outer.addLayout(make_page_header(
            "Hoja membretada",
            "Carga un PDF, Word o imagen que contiene tu membrete (encabezado/pie). "
            "Se usará siempre la primera página.",
        ))

        body = QHBoxLayout()
        body.setSpacing(18)

        active_card = make_card(
            "Membrete activo",
            "PDF, Word o imagen. Word e imágenes se convierten a PDF de forma temporal.",
        )
        active_l = card_layout(active_card)
        active_l.setSpacing(14)
        active_l.setAlignment(Qt.AlignmentFlag.AlignTop)

        active_body = QHBoxLayout()
        active_body.setSpacing(18)
        active_body.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._lh_thumb = QLabel("Sin membrete")
        self._lh_thumb.setFixedSize(176, 226)
        self._lh_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lh_thumb.setStyleSheet(
            "background: #16161A; border: 1px dashed #33333B; "
            "border-radius: 8px; color: #6B6F7A; font-size: 11px;"
        )
        active_body.addWidget(self._lh_thumb)

        info_col = QVBoxLayout()
        info_col.setSpacing(8)
        self._lh_name_lbl = ElidedLabel("Ningun membrete seleccionado")
        self._lh_name_lbl.setObjectName("CardTitle")
        self._lh_pages_lbl = QLabel("Selecciona una hoja o usa una guardada en biblioteca.")
        self._lh_pages_lbl.setProperty("class", "CardHint")
        self._lh_pages_lbl.setWordWrap(True)
        self._lh_margins_lbl = QLabel("")
        self._lh_margins_lbl.setProperty("class", "CardHint")
        self._lh_margins_lbl.setWordWrap(True)
        info_col.addWidget(self._lh_name_lbl)
        info_col.addWidget(self._lh_pages_lbl)
        info_col.addWidget(self._lh_margins_lbl)
        info_col.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        open_btn = QPushButton("Seleccionar archivo")
        open_btn.setProperty("class", "Primary")
        set_button_icon(open_btn, "folder-open")
        open_btn.clicked.connect(self._on_open_membrete)
        self._membrete_tray_btn = QPushButton("Bandeja")
        self._membrete_tray_btn.setProperty("class", "Ghost")
        set_button_icon(self._membrete_tray_btn, "folder-open")
        self._membrete_tray_btn.clicked.connect(self._on_membrete_from_tray)
        self.ctx.tray.changed.connect(
            lambda: self._membrete_tray_btn.setVisible(self.ctx.tray.count() > 0)
        )
        self._membrete_tray_btn.setVisible(self.ctx.tray.count() > 0)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(self._membrete_tray_btn)
        btn_row.addStretch()

        self._save_library_btn = QPushButton("Guardar en biblioteca")
        self._save_library_btn.setProperty("class", "Ghost")
        set_button_icon(self._save_library_btn, "save")
        self._save_library_btn.clicked.connect(self._on_save_membrete_to_library)
        btn_row.addWidget(self._save_library_btn)
        info_col.addLayout(btn_row)
        active_body.addLayout(info_col, 1)
        active_l.addLayout(active_body)
        active_l.addStretch(1)
        body.addWidget(active_card, 3)

        library_card = make_card("Biblioteca", "Membretes frecuentes listos para reutilizar.")
        lib_l = card_layout(library_card)
        lib_l.setSpacing(12)
        self._library_list = QListWidget()
        configure_file_list(self._library_list)
        self._library_list.setMinimumHeight(254)
        self._library_list.setAlternatingRowColors(True)
        self._library_list.setStyleSheet(
            "QListWidget {"
            "background: #101116;"
            "border: 1px solid #262832;"
            "border-radius: 8px;"
            "padding: 6px;"
            "}"
            "QListWidget::item {"
            "padding: 8px 10px;"
            "border-radius: 6px;"
            "color: #C8CBD2;"
            "}"
            "QListWidget::item:selected {"
            "background: rgba(184, 127, 245, 0.18);"
            "color: #FFFFFF;"
            "}"
        )
        self._library_list.itemSelectionChanged.connect(self._update_library_actions)
        self._library_list.itemDoubleClicked.connect(lambda _: self._on_use_library_membrete())
        lib_l.addWidget(self._library_list, 1)

        lib_btns = QHBoxLayout()
        lib_btns.setSpacing(8)
        self._use_library_btn = QPushButton("Usar")
        self._use_library_btn.setProperty("class", "Primary")
        set_button_icon(self._use_library_btn, "check")
        self._use_library_btn.clicked.connect(self._on_use_library_membrete)
        lib_btns.addWidget(self._use_library_btn)

        self._remove_library_btn = QPushButton("Quitar")
        self._remove_library_btn.setProperty("class", "Ghost")
        set_button_icon(self._remove_library_btn, "trash-2")
        self._remove_library_btn.clicked.connect(self._on_remove_library_membrete)
        lib_btns.addWidget(self._remove_library_btn)
        lib_btns.addStretch()
        lib_l.addLayout(lib_btns)
        body.addWidget(library_card, 2)

        outer.addLayout(body, 1)

        return page

    # ------------------------------------------------------------------ #
    # Paso 02: Documentos (via DocumentsCard compartida — ahora con miniaturas)
    # ------------------------------------------------------------------ #

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documentos a membretar",
            "Carga PDF, Word o imágenes; todo se normaliza a PDF antes de pegarse sobre el membrete.",
        ))

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=True,
            show_thumbnails=True,
            thumb_size=(64, 82),
        )
        self._docs_card.files_changed.connect(self._on_docs_changed)
        outer.addWidget(self._docs_card, 1)

        return page

    # ------------------------------------------------------------------ #
    # Paso 03: Márgenes
    # ------------------------------------------------------------------ #

    def _build_margins_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Ajuste de márgenes",
            "Define el espacio que respeta el membrete. "
            "El recuadro azul muestra la zona donde se colocará cada página.",
        ))

        body = QHBoxLayout()
        body.setSpacing(20)

        # ---- Columna izquierda: card unificada con sliders ─────────
        ctrl_card = make_card("Márgenes de seguridad")
        ll = card_layout(ctrl_card)
        ll.setSpacing(14)

        def _row_slider(label_text: str, tooltip: str, default: float):
            """Fila compacta: etiqueta + slider + valor."""
            row_w = QWidget()
            row_w.setStyleSheet("background: transparent;")
            row_l = QVBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #9094A0; font-size: 11px; font-weight: 600; "
                              "letter-spacing: 0.6px; text-transform: uppercase; "
                              "background: transparent;")
            lbl.setToolTip(tooltip)
            s = SliderWithValue(
                0.0,
                250.0,
                default,
                step=1.0,
                suffix="pt",
                decimals=0,
                spin_width=112,
            )
            row_l.addWidget(lbl)
            row_l.addWidget(s)
            ll.addWidget(row_w)
            return s

        self._s_top    = _row_slider("Superior",    "Espacio para encabezado (logo, empresa)", 72.0)
        self._s_bottom = _row_slider("Inferior",    "Espacio para pie de página (dirección, tel.)", 54.0)

        # Divisor lateral
        hor_div = QFrame()
        hor_div.setFixedHeight(1)
        hor_div.setStyleSheet("background: #1E1E24; border: none;")
        ll.addWidget(hor_div)

        self._s_left  = _row_slider("Izquierdo", "Margen lateral izquierdo", 18.0)
        self._s_right = _row_slider("Derecho",   "Margen lateral derecho", 18.0)

        ll.addSpacing(4)
        reset_btn = QPushButton("Autodetectar")
        reset_btn.setProperty("class", "Ghost")
        reset_btn.setToolTip("Restablecer detección automática de márgenes")
        set_button_icon(reset_btn, "refresh-cw")
        reset_btn.clicked.connect(self._on_reset_margins)
        ll.addWidget(reset_btn)
        ll.addStretch()

        # Conectar sliders al preview
        for s in (self._s_top, self._s_bottom, self._s_left, self._s_right):
            s.valueChanged.connect(self._on_margin_slider_changed)

        left_scroll = QScrollArea()
        ctrl_card.setMinimumWidth(0)
        ctrl_card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        left_scroll.setWidget(ctrl_card)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(360)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.addWidget(left_scroll)

        # ---- Columna derecha: preview ─────────────────────────────
        right_col = QVBoxLayout()
        right_col.setSpacing(10)

        prev_card = make_card("Vista previa")
        pc = card_layout(prev_card)
        self._margin_preview = MarginPreviewWidget()
        self._margin_preview.setMinimumWidth(260)
        pc.addWidget(self._margin_preview, 1)
        right_col.addWidget(prev_card, 1)

        body.addLayout(right_col, 1)
        outer.addLayout(body, 1)

        return page

    # ------------------------------------------------------------------ #
    # Paso 04: Alcance
    # ------------------------------------------------------------------ #

    def _build_scope_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Alcance de membretado",
            "Define qué páginas reciben membrete. Las páginas fuera del alcance pueden conservarse sin cambios.",
        ))

        body = QHBoxLayout()
        body.setSpacing(16)

        left_col = QVBoxLayout()
        left_col.setSpacing(16)

        global_card = make_card("Regla global")
        gl = card_layout(global_card)
        gl.setSpacing(10)

        self._global_scope_combo = self._make_scope_combo()
        self._global_scope_combo.currentIndexChanged.connect(self._on_global_scope_changed)
        gl.addWidget(self._global_scope_combo)

        self._global_pages_edit = QLineEdit()
        self._global_pages_edit.setPlaceholderText("Ej. 1-3, 5, 8-final")
        self._global_pages_edit.setClearButtonEnabled(True)
        self._global_pages_edit.textChanged.connect(self._on_global_scope_changed)
        gl.addWidget(self._global_pages_edit)

        quick_row = QGridLayout()
        quick_row.setHorizontalSpacing(8)
        quick_row.setVerticalSpacing(8)
        for i, (label, value) in enumerate((
            ("Primera", "1"),
            ("Última", "final"),
            ("Todo", "1-final"),
            ("Pares", "pares"),
            ("Impares", "impares"),
        )):
            btn = QPushButton(label)
            btn.setProperty("class", "Ghost")
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _, v=value: self._set_scope_text(self._global_pages_edit, v))
            quick_row.addWidget(btn, i // 3, i % 3)
        for col in range(3):
            quick_row.setColumnStretch(col, 1)
        gl.addLayout(quick_row)

        self._preserve_unselected_chk = QCheckBox("Conservar páginas sin membretar")
        self._preserve_unselected_chk.setChecked(True)
        self._preserve_unselected_chk.toggled.connect(self._on_global_scope_changed)
        gl.addWidget(self._preserve_unselected_chk)

        self._preserve_source_background_chk = QCheckBox("Conservar fondo del PDF original")
        self._preserve_source_background_chk.setChecked(True)
        self._preserve_source_background_chk.toggled.connect(self._on_global_scope_changed)
        gl.addWidget(self._preserve_source_background_chk)

        self._global_scope_status_lbl = QLabel("")
        self._global_scope_status_lbl.setProperty("class", "CardHint")
        self._global_scope_status_lbl.setWordWrap(True)
        gl.addWidget(self._global_scope_status_lbl)
        left_col.addWidget(global_card)

        docs_card = make_card("Documentos")
        dl = card_layout(docs_card)
        dl.setSpacing(10)
        self._scope_docs_list = QListWidget()
        configure_file_list(self._scope_docs_list)
        self._scope_docs_list.setSpacing(3)
        self._scope_docs_list.currentRowChanged.connect(self._on_scope_doc_row_changed)
        dl.addWidget(self._scope_docs_list, 1)
        self._scope_docs_stats_lbl = QLabel("Sin documentos")
        self._scope_docs_stats_lbl.setProperty("class", "CardHint")
        self._scope_docs_stats_lbl.setWordWrap(True)
        dl.addWidget(self._scope_docs_stats_lbl)
        left_col.addWidget(docs_card, 1)
        body.addLayout(left_col, 2)

        right_col = QVBoxLayout()
        right_col.setSpacing(16)

        doc_card = make_card("Excepción del documento")
        ed = card_layout(doc_card)
        ed.setSpacing(10)
        self._scope_doc_title = ElidedLabel("Selecciona un documento")
        self._scope_doc_title.setMinimumWidth(0)
        self._scope_doc_title.setStyleSheet("color:#ECEDEE; font-size:15px; font-weight:600;")
        ed.addWidget(self._scope_doc_title)

        self._scope_doc_meta = QLabel("—")
        self._scope_doc_meta.setProperty("class", "CardHint")
        ed.addWidget(self._scope_doc_meta)

        self._doc_override_chk = QCheckBox("Usar regla propia para este documento")
        self._doc_override_chk.toggled.connect(self._on_doc_override_toggled)
        ed.addWidget(self._doc_override_chk)

        self._doc_scope_combo = self._make_scope_combo()
        self._doc_scope_combo.currentIndexChanged.connect(self._on_doc_scope_changed)
        ed.addWidget(self._doc_scope_combo)

        self._doc_pages_edit = QLineEdit()
        self._doc_pages_edit.setPlaceholderText("Ej. 1-3, 5, 8-final")
        self._doc_pages_edit.setClearButtonEnabled(True)
        self._doc_pages_edit.textChanged.connect(self._on_doc_scope_changed)
        ed.addWidget(self._doc_pages_edit)

        doc_quick = QGridLayout()
        doc_quick.setHorizontalSpacing(8)
        doc_quick.setVerticalSpacing(8)
        self._doc_scope_quick_buttons = []
        for i, (label, value) in enumerate((
            ("Primera", "1"),
            ("Última", "final"),
            ("Todo", "1-final"),
            ("Pares", "pares"),
            ("Impares", "impares"),
        )):
            btn = QPushButton(label)
            btn.setProperty("class", "Ghost")
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _, v=value: self._set_scope_text(self._doc_pages_edit, v))
            doc_quick.addWidget(btn, i // 3, i % 3)
            self._doc_scope_quick_buttons.append(btn)
        for col in range(3):
            doc_quick.setColumnStretch(col, 1)
        ed.addLayout(doc_quick)

        self._doc_scope_status_lbl = QLabel("")
        self._doc_scope_status_lbl.setProperty("class", "CardHint")
        self._doc_scope_status_lbl.setWordWrap(True)
        ed.addWidget(self._doc_scope_status_lbl)
        right_col.addWidget(doc_card)

        preview_card = make_card("Vista de alcance")
        pv = card_layout(preview_card)
        self._scope_preview_lbl = QLabel("Carga documentos para calcular el alcance.")
        self._scope_preview_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._scope_preview_lbl.setWordWrap(True)
        self._scope_preview_lbl.setStyleSheet("color:#ECEDEE; font-size:13px; line-height:150%;")
        pv.addWidget(self._scope_preview_lbl)
        right_col.addWidget(preview_card)
        right_col.addStretch()

        body.addLayout(right_col, 3)
        outer.addLayout(body, 1)

        self._refresh_scope_controls()
        return page

    def _make_scope_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.addItem("Todas las páginas", "all")
        combo.addItem("Solo páginas indicadas", "include")
        combo.addItem("Todas excepto indicadas", "exclude")
        combo.addItem("Páginas pares", "even")
        combo.addItem("Páginas impares", "odd")
        return combo

    # ------------------------------------------------------------------ #
    # Paso 05: Procesar (via ProcessStep compartido)
    # ------------------------------------------------------------------ #

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Genera los documentos en temporal; usa \"Guardar como\" para conservarlos.",
        ))

        self._proc_step = ProcessStep(
            run_label="Membretar documentos",
            show_output_dir=False,
        )
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        return page

    # ------------------------------------------------------------------ #
    # Paso 06: Resultados
    # ------------------------------------------------------------------ #

    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultados",
            "Revisa los documentos membretados.",
        ))

        self._results_viewer = GenericPdfViewer("Documentos membretados")
        self._results_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._results_viewer, 1)

        return page

    # ------------------------------------------------------------------ #
    # Action buttons (navbar footer)
    # ------------------------------------------------------------------ #

    def _build_action_buttons(self) -> None:
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Membretar documentos")
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

        self._restart_btn = QPushButton("Nueva sesion")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "membretado")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()

    # ------------------------------------------------------------------ #
    # Hooks de navegación
    # ------------------------------------------------------------------ #

    def _on_section_activated(self, idx: int) -> None:
        if idx == 0 and hasattr(self, "_nav_next_btn"):
            self._nav_next_btn.setEnabled(bool(self._lh_path))
        elif hasattr(self, "_nav_next_btn"):
            self._nav_next_btn.setEnabled(True)
        if idx == 2:
            self._sync_preview_pixmap()
        elif idx == 3:
            self._refresh_scope_documents()
            self._refresh_scope_controls()
        elif idx == 4:
            self._refresh_summary()

    # ------------------------------------------------------------------ #
    # API PipelineWindow
    # ------------------------------------------------------------------ #

    def set_inputs(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(1)

    def handle_drop(self, paths: List[str]) -> None:
        self._add_file_paths_smart(paths)

    # ------------------------------------------------------------------ #
    # Membrete
    # ------------------------------------------------------------------ #

    def _on_open_membrete(self) -> None:
        path, _ = get_open_file_name(
            self, "Seleccionar membrete", "",
            DOCUMENT_IMPORT_FILTER,
        )
        if path:
            self._load_membrete_input(path)

    def _on_membrete_from_tray(self) -> None:
        paths = [
            p for p in self.ctx.tray.paths()
            if Path(p).suffix.lower() in self.LETTERHEAD_EXTS
        ]
        if paths:
            self._load_membrete_input(paths[0])
        else:
            show_info(
                self,
                "Sin archivos compatibles",
                "La bandeja no contiene un PDF, Word o imagen para usar como membrete.",
            )

    def _load_membrete_input(self, path: str) -> None:
        suffix = Path(path).suffix.lower()
        if suffix == ".pdf":
            self._load_membrete(path, source_name=Path(path).name)
        elif suffix in (".doc", ".docx"):
            self._handle_word_membrete([path])
        elif suffix in IMAGE_EXTENSIONS:
            try:
                converted = images_to_pdf_exact(
                    [path],
                    output_name=f"{Path(path).stem}_membrete.pdf",
                )
            except Exception as exc:
                show_error(self, "No se pudo convertir la imagen", str(exc))
                return
            if converted:
                self._load_membrete(converted, source_name=Path(path).name)
        else:
            show_info(self, "Archivo no compatible", "Selecciona un PDF, Word o imagen.")

    def _load_membrete(
        self,
        path: str,
        *,
        source_name: str = "",
        library_entry: Optional[SavedLetterhead] = None,
    ) -> None:
        """Inicia carga asíncrona del membrete (thumbnail + preview + márgenes)."""
        self._lh_loading_path = path  # guard: resultados de cargas anteriores serán ignorados
        self._lh_loading_library_entry = library_entry
        if library_entry is None:
            self._active_library_id = None

        # Estado de "cargando" inmediato en la UI
        self._lh_thumb.setText("Cargando...")
        self._lh_thumb.setPixmap(QPixmap())
        self._lh_thumb.setStyleSheet(
            "background: #16161A; border: 1px dashed #33333B; "
            "border-radius: 8px; color: #6B6F7A; font-size: 11px;"
        )

        loader = _MembretePageLoader(path, source_name or Path(path).name)
        thread = _MembretaLoadThread(loader, self)
        loader.loaded.connect(self._on_membrete_loaded)
        loader.error.connect(self._on_membrete_load_error)
        thread.finished.connect(loader.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._lh_load_thread = thread  # mantiene referencia mientras carga
        thread.start()

    def _on_membrete_loaded(
        self,
        path: str,
        source_name: str,
        qimg_thumb: object,
        qimg_prev: object,
        pw: float,
        ph: float,
        page_count: int,
        margins: object,
    ) -> None:
        """Slot GUI: recibe QImages del worker y convierte a QPixmap aquí."""
        if path != self._lh_loading_path:
            return  # resultado obsoleto de carga anterior

        # Conversión QImage → QPixmap exclusivamente en hilo GUI
        thumb = QPixmap.fromImage(qimg_thumb).scaled(
            164, 214,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._lh_preview_pixmap = QPixmap.fromImage(qimg_prev)
        self._lh_page_w_pt = pw
        self._lh_page_h_pt = ph
        self._lh_path = path
        self._lh_source_name = source_name

        self._lh_thumb.setPixmap(thumb)
        self._lh_thumb.setStyleSheet(
            "background: #111114; border: 1px solid #26262C; border-radius: 8px;"
        )
        self._lh_name_lbl.setText(self._lh_source_name)
        self._lh_name_lbl.setToolTip(self._lh_source_name or path)
        self._lh_pages_lbl.setText(
            f"{page_count} pagina{'s' if page_count != 1 else ''} · "
            f"{pw:.0f} x {ph:.0f} pt"
        )

        library_entry = self._lh_loading_library_entry if path == self._lh_loading_path else None
        self._active_library_id = library_entry.id if library_entry else None
        self._margins = self._apply_letterhead_config(
            library_entry.config if library_entry else {},
            margins,
        )
        self._lh_margins_lbl.setText(
            f"Márgenes activos: sup. {self._margins.top_pt:.0f} pt  "
            f"inf. {self._margins.bottom_pt:.0f} pt"
        )
        self._update_library_actions()

    def _on_membrete_load_error(self, path: str, msg: str) -> None:
        """Slot GUI: maneja errores de carga del membrete."""
        if path != self._lh_loading_path:
            return  # error obsoleto de carga anterior
        # Limpia estado
        self._lh_path = None
        self._lh_preview_pixmap = None
        self._lh_thumb.setText("Sin membrete")
        self._lh_thumb.setPixmap(QPixmap())
        self._lh_thumb.setStyleSheet(
            "background: #16161A; border: 1px dashed #33333B; "
            "border-radius: 8px; color: #6B6F7A; font-size: 11px;"
        )
        self._active_library_id = None
        self._lh_loading_library_entry = None
        self._update_library_actions()
        show_warning(self, "Error al abrir membrete", msg)

    def _refresh_letterhead_library(self) -> None:
        if not hasattr(self, "_library_list"):
            return
        self._letterhead_library = load_letterhead_library()
        self._library_list.clear()
        for entry in self._letterhead_library:
            meta = entry.source_name
            if entry.page_width_pt and entry.page_height_pt:
                meta += f" · {entry.page_width_pt:.0f} x {entry.page_height_pt:.0f} pt"
            if entry.config:
                meta += " · config"
            item = QListWidgetItem(f"{entry.label}\n{meta}")
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setSizeHint(QSize(260, 54))
            size_text = ""
            if entry.page_width_pt and entry.page_height_pt:
                size_text = f"\n{entry.page_width_pt:.0f} x {entry.page_height_pt:.0f} pt"
            item.setToolTip(f"{entry.source_name}{size_text}\n{entry.path}")
            self._library_list.addItem(item)
        if not self._letterhead_library:
            item = QListWidgetItem("Sin membretes guardados")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            item.setSizeHint(QSize(260, 46))
            self._library_list.addItem(item)
        elif self._library_list.count() > 0:
            self._library_list.setCurrentRow(0)
        self._update_library_actions()

    def _selected_library_entry(self) -> Optional[SavedLetterhead]:
        if not hasattr(self, "_library_list"):
            return None
        item = self._library_list.currentItem()
        if not item:
            return None
        letterhead_id = item.data(Qt.ItemDataRole.UserRole)
        return next(
            (entry for entry in self._letterhead_library if entry.id == letterhead_id),
            None,
        )

    def _update_library_actions(self) -> None:
        selected = self._selected_library_entry() is not None
        if hasattr(self, "_use_library_btn"):
            self._use_library_btn.setEnabled(selected)
        if hasattr(self, "_remove_library_btn"):
            self._remove_library_btn.setEnabled(selected)
        if hasattr(self, "_save_library_btn"):
            self._save_library_btn.setEnabled(bool(self._lh_path))
        if hasattr(self, "_nav_next_btn") and self.stack.currentIndex() == 0:
            self._nav_next_btn.setEnabled(bool(self._lh_path))

    def _on_use_library_membrete(self) -> None:
        entry = self._selected_library_entry()
        if not entry:
            return
        if not Path(entry.path).exists():
            show_warning(
                self,
                "Membrete no encontrado",
                "El archivo guardado en la biblioteca ya no existe. Se actualizará la lista.",
            )
            self._refresh_letterhead_library()
            return
        self._load_membrete(entry.path, source_name=entry.label, library_entry=entry)

    def _on_save_membrete_to_library(self) -> None:
        if not self._lh_path:
            show_info(self, "Sin membrete", "Carga primero un membrete para guardarlo.")
            return
        try:
            entry = add_letterhead_to_library(
                self._lh_path,
                label=self._lh_source_name or Path(self._lh_path).stem,
                config=self._current_letterhead_config(),
            )
        except Exception as exc:
            show_warning(self, "No se pudo guardar", str(exc))
            return
        self._refresh_letterhead_library()
        self._select_library_entry(entry.id)
        self._active_library_id = entry.id
        show_success(self, "Membrete guardado", "El membrete quedó disponible en la biblioteca.")

    def _on_remove_library_membrete(self) -> None:
        entry = self._selected_library_entry()
        if not entry:
            return
        if not ask_question(
            self,
            "Quitar de biblioteca",
            f"Se quitará \"{entry.label}\" de la biblioteca.\n\nNo se borrará el archivo original.",
            accept_text="Quitar",
            cancel_text="Cancelar",
            danger=True,
        ):
            return
        remove_letterhead_from_library(entry.id)
        self._refresh_letterhead_library()

    def _select_library_entry(self, letterhead_id: str) -> None:
        if not hasattr(self, "_library_list"):
            return
        for index in range(self._library_list.count()):
            item = self._library_list.item(index)
            if item and item.data(Qt.ItemDataRole.UserRole) == letterhead_id:
                self._library_list.setCurrentRow(index)
                return

    # ------------------------------------------------------------------ #
    # Word -> PDF para membrete
    # ------------------------------------------------------------------ #

    def _handle_word_membrete(self, paths: List[str]) -> None:
        if self._conv_thread is not None:
            return
        if not self.ctx.word_converter.is_available():
            show_info(
                self,
                "Microsoft Office requerido",
                "Para convertir el membrete Word a PDF se necesita Microsoft Office instalado.",
            )
            return

        from ui.common.word_convert_dialog import WordConvertDialog

        self._conv_dlg = WordConvertDialog(self, paths)
        worker = WordConvertWorker(
            self.ctx.word_converter,
            paths,
            make_run_dir("converted"),
        )
        thread = RunnerThread(worker.run, self)
        worker.progress.connect(self._conv_dlg.on_progress)
        worker.finished.connect(self._conv_dlg.on_finished)
        worker.error.connect(self._conv_dlg.on_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        worker.finished.connect(
            lambda converted, source=Path(paths[0]).name: self._on_word_membrete_done(converted, source)
        )
        worker.error.connect(self._on_word_membrete_error)
        self._conv_thread = thread
        thread.start()
        self._conv_dlg.exec()

    def _on_word_membrete_done(self, paths: List[str], source_name: str) -> None:
        self._conv_thread = None
        if paths:
            self._load_membrete(paths[0], source_name=source_name)

    def _on_word_membrete_error(self, msg: str) -> None:
        self._conv_thread = None

    def _sync_preview_pixmap(self) -> None:
        if hasattr(self, "_lh_preview_pixmap") and self._lh_preview_pixmap:
            self._margin_preview.set_letterhead(
                self._lh_preview_pixmap,
                self._lh_page_w_pt,
                self._lh_page_h_pt,
            )
            self._on_margin_slider_changed()
        else:
            self._margin_preview.clear_letterhead()

    def _get_doc_paths(self) -> List[str]:
        return self._docs_card.paths()

    # ------------------------------------------------------------------ #
    # Alcance
    # ------------------------------------------------------------------ #

    def _on_docs_changed(self, paths: List[str]) -> None:
        valid = set(paths)
        self._doc_scope_enabled.intersection_update(valid)
        self._doc_scope_modes = {
            path: mode for path, mode in self._doc_scope_modes.items()
            if path in valid
        }
        self._doc_scope_texts = {
            path: text for path, text in self._doc_scope_texts.items()
            if path in valid
        }
        self._page_count_cache = {
            path: count for path, count in self._page_count_cache.items()
            if path in valid
        }
        self._refresh_scope_documents()
        if hasattr(self, "_proc_step"):
            self._refresh_summary()

    def _page_count_for_doc(self, path: str) -> int:
        if path not in self._page_count_cache:
            try:
                self._page_count_cache[path] = pdf_page_count(path)
            except Exception:
                self._page_count_cache[path] = 0
        return self._page_count_cache[path]

    def _scope_mode_from_combo(self, combo: QComboBox) -> str:
        return str(combo.currentData() or "all")

    @staticmethod
    def _scope_needs_text(mode: str) -> bool:
        return mode in {"include", "exclude"}

    def _set_scope_combo_mode(self, combo: QComboBox, mode: str) -> None:
        idx = combo.findData(mode)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _set_scope_text(self, edit: QLineEdit, value: str) -> None:
        edit.setFocus()
        edit.setText(value)

    def _global_scope_config(self) -> tuple[str, str]:
        return (
            self._scope_mode_from_combo(self._global_scope_combo),
            self._global_pages_edit.text().strip(),
        )

    def _scope_config_for_doc(self, path: str) -> tuple[str, str]:
        if path in self._doc_scope_enabled:
            return (
                self._doc_scope_modes.get(path, "all"),
                self._doc_scope_texts.get(path, ""),
            )
        return self._global_scope_config()

    def _refresh_scope_controls(self) -> None:
        if not hasattr(self, "_global_scope_combo"):
            return
        global_mode = self._scope_mode_from_combo(self._global_scope_combo)
        self._global_pages_edit.setEnabled(self._scope_needs_text(global_mode))
        self._refresh_global_scope_status()
        self._refresh_doc_scope_editor()
        self._persist_active_library_config()

    def _on_global_scope_changed(self, *_) -> None:
        if self._updating_scope_ui:
            return
        self._refresh_scope_controls()
        self._refresh_scope_documents()

    def _refresh_global_scope_status(self) -> None:
        if not hasattr(self, "_global_scope_status_lbl"):
            return
        paths = self._get_doc_paths()
        if not paths:
            self._global_scope_status_lbl.setText("Carga documentos para calcular el alcance.")
            self._global_scope_status_lbl.setStyleSheet("color:#9094A0;")
            return
        invalid = self._first_scope_error(paths, global_only=True)
        if invalid:
            self._global_scope_status_lbl.setText(invalid)
            self._global_scope_status_lbl.setStyleSheet("color:#E5484D;")
            return
        total_letterheaded = 0
        total_pages = 0
        for path in paths:
            count = self._page_count_for_doc(path)
            total_pages += count
            try:
                pages = parse_membrete_page_scope(
                    *self._global_scope_config(),
                    count,
                )
            except ValueError:
                pages = []
            total_letterheaded += len(pages)
        self._global_scope_status_lbl.setText(
            f"Regla válida: {total_letterheaded}/{total_pages} páginas recibirán membrete."
        )
        self._global_scope_status_lbl.setStyleSheet("color:#3BD37C;")

    def _refresh_scope_documents(self) -> None:
        if not hasattr(self, "_scope_docs_list"):
            return
        paths = self._get_doc_paths()
        valid = set(paths)
        preferred = self._active_scope_doc_path if self._active_scope_doc_path in valid else None
        if preferred is None and paths:
            preferred = paths[0]

        self._scope_docs_list.blockSignals(True)
        self._scope_docs_list.clear()
        for path in paths:
            item = QListWidgetItem(self._scope_item_text(path))
            item.setSizeHint(QSize(320, 54))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            item.setForeground(QBrush(QColor("#E5484D" if self._scope_error_for_doc(path) else "#ECEDEE")))
            self._scope_docs_list.addItem(item)
        if preferred in valid:
            self._scope_docs_list.setCurrentRow(paths.index(preferred))
        self._scope_docs_list.blockSignals(False)

        self._active_scope_doc_path = preferred if preferred in valid else None
        self._refresh_doc_scope_editor()
        self._refresh_scope_stats()

    def _scope_item_text(self, path: str) -> str:
        count = self._page_count_for_doc(path)
        mode, text = self._scope_config_for_doc(path)
        try:
            pages = parse_membrete_page_scope(mode, text, count)
            summary = compact_page_indexes(pages)
        except ValueError:
            summary = "Revisar alcance"
        override = " · propio" if path in self._doc_scope_enabled else ""
        pages_text = f"{count} página" + ("" if count == 1 else "s")
        return f"{Path(path).name}\n{pages_text} · {summary}{override}"

    def _scope_error_for_doc(self, path: str) -> str:
        count = self._page_count_for_doc(path)
        if count <= 0:
            return f"No se pudo leer {Path(path).name}."
        try:
            pages = parse_membrete_page_scope(*self._scope_config_for_doc(path), count)
        except ValueError as exc:
            return str(exc)
        if not pages and not self._preserve_unselected_chk.isChecked():
            return "La selección no produciría páginas de salida."
        return ""

    def _first_scope_error(self, paths: List[str], *, global_only: bool = False) -> str:
        for path in paths:
            count = self._page_count_for_doc(path)
            if count <= 0:
                return f"No se pudo leer {Path(path).name}."
            mode, text = self._global_scope_config() if global_only else self._scope_config_for_doc(path)
            try:
                pages = parse_membrete_page_scope(mode, text, count)
            except ValueError as exc:
                return f"{Path(path).name}: {exc}"
            if not pages and not self._preserve_unselected_chk.isChecked():
                return f"{Path(path).name}: la selección no produciría páginas de salida."
        return ""

    def _refresh_scope_stats(self) -> None:
        if not hasattr(self, "_scope_docs_stats_lbl"):
            return
        paths = self._get_doc_paths()
        if not paths:
            self._scope_docs_stats_lbl.setText("Sin documentos")
            return
        invalid = sum(1 for path in paths if self._scope_error_for_doc(path))
        overrides = sum(1 for path in paths if path in self._doc_scope_enabled)
        text = (
            f"{len(paths)} documento" + ("" if len(paths) == 1 else "s")
            + f" · {overrides} con regla propia"
        )
        if invalid:
            text += f" · {invalid} por revisar"
        self._scope_docs_stats_lbl.setText(text)

    def _on_scope_doc_row_changed(self, row: int) -> None:
        if row < 0 or row >= self._scope_docs_list.count():
            self._active_scope_doc_path = None
        else:
            item = self._scope_docs_list.item(row)
            self._active_scope_doc_path = item.data(Qt.ItemDataRole.UserRole) if item else None
        self._refresh_doc_scope_editor()

    def _refresh_doc_scope_editor(self) -> None:
        if not hasattr(self, "_doc_override_chk"):
            return
        path = self._active_scope_doc_path
        self._updating_scope_ui = True
        try:
            enabled = bool(path)
            for widget in (
                self._doc_override_chk,
                self._doc_scope_combo,
                self._doc_pages_edit,
            ):
                widget.setEnabled(enabled)
            for btn in getattr(self, "_doc_scope_quick_buttons", []):
                btn.setEnabled(enabled)

            if not path:
                self._scope_doc_title.setText("Selecciona un documento")
                self._scope_doc_title.setToolTip("")
                self._scope_doc_meta.setText("—")
                self._doc_override_chk.setChecked(False)
                self._set_scope_combo_mode(self._doc_scope_combo, "all")
                self._doc_pages_edit.setText("")
                self._doc_scope_status_lbl.setText("Carga documentos para configurar excepciones.")
                self._doc_scope_status_lbl.setStyleSheet("color:#9094A0;")
                self._scope_preview_lbl.setText("Sin documento seleccionado")
                return

            count = self._page_count_for_doc(path)
            override = path in self._doc_scope_enabled
            mode, text = self._scope_config_for_doc(path)
            self._scope_doc_title.setText(Path(path).name)
            self._scope_doc_title.setToolTip(path)
            self._scope_doc_meta.setText(f"{count} página" + ("" if count == 1 else "s"))
            self._doc_override_chk.setChecked(override)
            self._set_scope_combo_mode(self._doc_scope_combo, mode)
            self._doc_pages_edit.setText(text)
            self._doc_scope_combo.setEnabled(enabled and override)
            self._doc_pages_edit.setEnabled(
                enabled and override and self._scope_needs_text(mode)
            )
            for btn in getattr(self, "_doc_scope_quick_buttons", []):
                btn.setEnabled(enabled and override)
        finally:
            self._updating_scope_ui = False
        self._update_doc_scope_validation()

    def _on_doc_override_toggled(self, checked: bool) -> None:
        if self._updating_scope_ui:
            return
        path = self._active_scope_doc_path
        if not path:
            return
        if checked:
            self._doc_scope_enabled.add(path)
            if path not in self._doc_scope_modes:
                mode, text = self._global_scope_config()
                self._doc_scope_modes[path] = mode
                self._doc_scope_texts[path] = text
        else:
            self._doc_scope_enabled.discard(path)
        self._refresh_doc_scope_editor()
        self._refresh_scope_documents()

    def _on_doc_scope_changed(self, *_) -> None:
        if self._updating_scope_ui:
            return
        path = self._active_scope_doc_path
        if not path:
            return
        self._doc_scope_enabled.add(path)
        self._doc_scope_modes[path] = self._scope_mode_from_combo(self._doc_scope_combo)
        self._doc_scope_texts[path] = self._doc_pages_edit.text().strip()
        self._update_doc_scope_validation()
        self._refresh_scope_documents()

    def _update_doc_scope_validation(self) -> None:
        path = self._active_scope_doc_path
        if not path:
            return
        mode, text = self._scope_config_for_doc(path)
        count = self._page_count_for_doc(path)
        error = self._scope_error_for_doc(path)
        if error:
            self._doc_scope_status_lbl.setText(error)
            self._doc_scope_status_lbl.setStyleSheet("color:#E5484D;")
            name = elide_middle_text(Path(path).name, 64)
            self._scope_preview_lbl.setText(
                f"<b>{name}</b><br>"
                "<span style='color:#E5484D'>Revisa el alcance antes de procesar.</span>"
            )
            return
        pages = parse_membrete_page_scope(mode, text, count)
        label = "página" if len(pages) == 1 else "páginas"
        compact = compact_page_indexes(pages)
        self._doc_scope_status_lbl.setText(
            f"{len(pages)} {label} recibirán membrete: {compact}"
        )
        self._doc_scope_status_lbl.setStyleSheet("color:#3BD37C;")
        untouched = count - len(pages)
        untouched_text = ""
        if untouched and self._preserve_unselected_chk.isChecked():
            untouched_text = f"<br>{untouched} página{'s' if untouched != 1 else ''} se conservarán sin cambios."
        elif untouched:
            untouched_text = f"<br>{untouched} página{'s' if untouched != 1 else ''} se omitirán."
        name = elide_middle_text(Path(path).name, 64)
        self._scope_preview_lbl.setText(
            f"<b>{name}</b><br>"
            f"{len(pages)} {label}: <span style='color:#B8BDF8'>{compact}</span>"
            f"{untouched_text}"
        )

    def _pages_for_job(self, path: str) -> List[int]:
        return parse_membrete_page_scope(
            *self._scope_config_for_doc(path),
            self._page_count_for_doc(path),
        )

    def _scope_summary_text(self) -> str:
        paths = self._get_doc_paths()
        if not paths:
            return "Sin documentos"
        total = 0
        selected = 0
        invalid = self._first_scope_error(paths)
        if invalid:
            return f"Revisar: {invalid}"
        for path in paths:
            count = self._page_count_for_doc(path)
            total += count
            selected += len(self._pages_for_job(path))
        overrides = len([p for p in paths if p in self._doc_scope_enabled])
        base = f"{selected}/{total} páginas con membrete"
        if overrides:
            base += f" · {overrides} regla{'s' if overrides != 1 else ''} propia{'s' if overrides != 1 else ''}"
        return base

    def _current_letterhead_config(self) -> dict:
        margins = self._read_margins() if hasattr(self, "_s_top") else self._margins
        mode, text = self._global_scope_config() if hasattr(self, "_global_scope_combo") else ("all", "")
        return {
            "version": 1,
            "margins": {
                "top_pt": float(margins.top_pt),
                "bottom_pt": float(margins.bottom_pt),
                "left_pt": float(margins.left_pt),
                "right_pt": float(margins.right_pt),
            },
            "scope": {
                "mode": mode,
                "pages": text,
                "preserve_unselected": bool(
                    self._preserve_unselected_chk.isChecked()
                    if hasattr(self, "_preserve_unselected_chk")
                    else True
                ),
            },
            "content": {
                "preserve_source_background": bool(
                    self._preserve_source_background_chk.isChecked()
                    if hasattr(self, "_preserve_source_background_chk")
                    else True
                ),
            },
        }

    def _apply_letterhead_config(
        self,
        config: dict,
        detected_margins: MembreteMargins,
    ) -> MembreteMargins:
        self._suppress_library_persist = True
        try:
            margins = self._margins_from_config(config) or detected_margins
            self._apply_margins_to_sliders(margins)

            scope = config.get("scope") if isinstance(config, dict) else {}
            if not isinstance(scope, dict):
                scope = {}
            self._set_scope_combo_mode(self._global_scope_combo, str(scope.get("mode") or "all"))
            self._global_pages_edit.setText(str(scope.get("pages") or ""))
            self._preserve_unselected_chk.setChecked(
                bool(scope.get("preserve_unselected", True))
            )
            content = config.get("content") if isinstance(config, dict) else {}
            if not isinstance(content, dict):
                content = {}
            self._preserve_source_background_chk.setChecked(
                bool(content.get("preserve_source_background", True))
            )
            self._doc_scope_enabled.clear()
            self._doc_scope_modes.clear()
            self._doc_scope_texts.clear()
            self._refresh_scope_controls()
            self._refresh_scope_documents()
            return margins
        finally:
            self._suppress_library_persist = False

    @staticmethod
    def _margins_from_config(config: dict) -> Optional[MembreteMargins]:
        if not isinstance(config, dict):
            return None
        raw = config.get("margins")
        if not isinstance(raw, dict):
            return None
        try:
            return MembreteMargins(
                top_pt=float(raw.get("top_pt", 72.0)),
                bottom_pt=float(raw.get("bottom_pt", 54.0)),
                left_pt=float(raw.get("left_pt", 18.0)),
                right_pt=float(raw.get("right_pt", 18.0)),
            )
        except (TypeError, ValueError):
            return None

    def _persist_active_library_config(self) -> None:
        if self._suppress_library_persist or not self._active_library_id:
            return
        updated = update_letterhead_config(
            self._active_library_id,
            self._current_letterhead_config(),
        )
        if updated is None:
            return
        for idx, entry in enumerate(self._letterhead_library):
            if entry.id == updated.id:
                self._letterhead_library[idx] = updated
                break

    # ------------------------------------------------------------------ #
    # Márgenes
    # ------------------------------------------------------------------ #

    def _on_margin_slider_changed(self, *_) -> None:
        self._margin_preview.set_margins(
            self._s_top.value(),
            self._s_bottom.value(),
            self._s_left.value(),
            self._s_right.value(),
        )
        self._margins = self._read_margins()
        self._persist_active_library_config()

    def _on_reset_margins(self) -> None:
        if not self._lh_path:
            show_info(self, "Sin membrete", "Carga primero un membrete.")
            return
        self._margins = detect_margins(self._lh_path)
        self._apply_margins_to_sliders(self._margins)

    def _apply_margins_to_sliders(self, m: MembreteMargins) -> None:
        self._s_top.setValue(m.top_pt)
        self._s_bottom.setValue(m.bottom_pt)
        self._s_left.setValue(m.left_pt)
        self._s_right.setValue(m.right_pt)

    def _read_margins(self) -> MembreteMargins:
        return MembreteMargins(
            top_pt=self._s_top.value(),
            bottom_pt=self._s_bottom.value(),
            left_pt=self._s_left.value(),
            right_pt=self._s_right.value(),
        )

    # ------------------------------------------------------------------ #
    # Procesar
    # ------------------------------------------------------------------ #

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._proc_step.set_progress(self._proc_step._prog_bar.value(), "Cancelando…")

    def _refresh_summary(self) -> None:
        m = self._read_margins()
        n = self._docs_card.count()
        rows = []
        if self._lh_path:
            rows.append(f"<b>Membrete:</b> &nbsp; {self._lh_source_name or Path(self._lh_path).name}")
        rows.append(f"<b>Documentos:</b> &nbsp; {n}")
        rows.append(f"<b>Alcance:</b> &nbsp; {self._scope_summary_text()}")
        rows.append(
            "<b>Páginas fuera de alcance:</b> &nbsp; "
            + ("conservar sin cambios" if self._preserve_unselected_chk.isChecked() else "omitir")
        )
        rows.append(
            "<b>Fondo del documento:</b> &nbsp; "
            + ("conservar" if self._preserve_source_background_chk.isChecked() else "transparentar")
        )
        rows.append(
            f"<b>Márgenes:</b> &nbsp; "
            f"sup. {m.top_pt:.0f} pt &nbsp;·&nbsp; inf. {m.bottom_pt:.0f} pt &nbsp;·&nbsp; "
            f"izq. {m.left_pt:.0f} pt &nbsp;·&nbsp; der. {m.right_pt:.0f} pt"
        )
        html = "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        self._proc_step.set_summary_html(html)

    def _validate_ready(self) -> Optional[str]:
        if not self._lh_path:
            return "Carga primero la hoja membretada (Paso 01)."
        if self._docs_card.is_empty():
            return "Agrega al menos un documento a membretar (Paso 02)."
        m = self._read_margins()
        page_w = getattr(self, "_lh_page_w_pt", 0.0)
        page_h = getattr(self, "_lh_page_h_pt", 0.0)
        if page_w > 0 and m.left_pt + m.right_pt >= page_w:
            return "Los márgenes izquierdo y derecho dejan la zona útil sin ancho."
        if page_h > 0 and m.top_pt + m.bottom_pt >= page_h:
            return "Los márgenes superior e inferior dejan la zona útil sin alto."
        scope_error = self._first_scope_error(self._get_doc_paths())
        if scope_error:
            return f"Revisa el alcance de páginas:\n\n{scope_error}"
        return None

    def _build_jobs(self) -> List[MembreteJob]:
        out_dir = make_run_dir("Membretado")
        jobs = []
        reserved: set[str] = set()
        add_suffix = add_tool_suffix_enabled()
        for p in self._get_doc_paths():
            in_path = Path(p)
            out_path = unique_output_path_for_source(
                out_dir,
                in_path,
                extension=".pdf",
                tool_suffix="membretado",
                add_tool_suffix=add_suffix,
                reserved=reserved,
                fallback="documento",
            )
            pages = self._pages_for_job(str(in_path))
            page_count = self._page_count_for_doc(str(in_path))
            jobs.append(MembreteJob(
                pdf_path=str(in_path),
                output_path=str(out_path),
                pages_to_letterhead=None if len(pages) == page_count else pages,
                preserve_unselected=self._preserve_unselected_chk.isChecked(),
                preserve_source_background=self._preserve_source_background_chk.isChecked(),
            ))
        return jobs

    def _on_run(self) -> None:
        self._stop_active_worker()
        err = self._validate_ready()
        if err:
            show_warning(self, "Falta información", err)
            return
        if self._worker_thread is not None:
            return

        self._results_viewer.clear_results()
        self._send_btn.set_output_paths([])
        jobs = self._build_jobs()
        margins = self._read_margins()

        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Iniciando…")

        self._worker = MembreteWorker(jobs, self._lh_path, margins)
        self._worker_thread = RunnerThread(self._worker.run, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)

        self._worker_thread.start()

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        self._proc_step.set_progress(int(current / max(1, total) * 100), msg)

    def _on_finished(self, results: list) -> None:
        self.last_results = list(results)
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Completado")
        self._worker_thread = None
        self._worker = None

        ok = sum(1 for r in results if r.success)
        fail = len(results) - ok

        output_paths = [r.output_path for r in results if r.success and r.output_path]
        self.ctx.tray.add_items(output_paths, "Membretado")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        show_success(
            self, "Hecho",
            f"Se membretaron {ok} documento{'s' if ok != 1 else ''}.\n"
            + (f"Con error: {fail}" if fail else ""),
        )
        self._results_viewer.set_results(results)
        self._switch_section(5)

    def _on_worker_error(self, msg: str) -> None:
        show_error(self, "Error", msg)
        self._proc_step.set_running(False)
        # thread.quit + deleteLater happen automatically via signal connections in _on_run
        self._worker_thread = None
        self._worker = None

    def _open_in_explorer(self, path: str) -> None:
        from ui.common.open_utils import open_folder
        open_folder(self, path, title="Abrir carpeta")

    # ------------------------------------------------------------------ #
    # Reset
    # ------------------------------------------------------------------ #

    def _reset_session(self) -> None:
        self._results_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []
        self._lh_path = None
        self._lh_source_name = ""
        self._lh_preview_pixmap = None
        self._active_library_id = None
        self._lh_loading_library_entry = None
        self._lh_page_w_pt = 0.0
        self._lh_page_h_pt = 0.0
        self._margins = MembreteMargins()
        self._page_count_cache.clear()
        self._active_scope_doc_path = None
        self._doc_scope_enabled.clear()
        self._doc_scope_modes.clear()
        self._doc_scope_texts.clear()
        self._lh_thumb.clear()
        self._lh_thumb.setText("Sin membrete")
        self._lh_thumb.setStyleSheet(
            "background: #16161A; border: 1px dashed #33333B; "
            "border-radius: 8px; color: #6B6F7A; font-size: 11px;"
        )
        self._lh_name_lbl.setText("Ningun membrete seleccionado")
        self._lh_name_lbl.setToolTip("")
        self._lh_pages_lbl.setText("Selecciona una hoja o usa una guardada en biblioteca.")
        self._lh_margins_lbl.setText("")
        self._margin_preview.clear_letterhead()
        self._apply_margins_to_sliders(self._margins)
        self._suppress_library_persist = True
        try:
            self._set_scope_combo_mode(self._global_scope_combo, "all")
            self._global_pages_edit.clear()
            self._preserve_unselected_chk.setChecked(True)
            self._preserve_source_background_chk.setChecked(True)
        finally:
            self._suppress_library_persist = False
        self._refresh_scope_documents()
        self._refresh_scope_controls()
        self._update_library_actions()
        self._docs_card.clear()
        self._proc_step.reset()
        self._switch_section(0)

    # ------------------------------------------------------------------ #
    # Drag & drop
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        from ui.common.file_ordering import paths_from_mime_data

        paths = paths_from_mime_data(event.mimeData())
        self._add_file_paths_smart(paths)

    def _add_file_paths_smart(self, paths: List[str]) -> None:
        if not paths:
            return

        current_idx = self.stack.currentIndex()
        letterheads = [
            p for p in paths
            if Path(p).suffix.lower() in self.LETTERHEAD_EXTS
        ]

        if current_idx == 0 and not self._lh_path and letterheads:
            self._load_membrete_input(letterheads[0])
            remaining = [p for p in paths if p != letterheads[0]]
            if remaining:
                self._docs_card.add_paths(remaining)
                self._switch_section(1)
            return

        self._docs_card.add_paths(paths)
        self._switch_section(1)
