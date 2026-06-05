"""FoleadorWindow — pipeline de foliado masivo de PDFs.

Pipeline:
    01 Documentos  →  02 Formato  →  03 Estilo  →  04 Posición
    →  05 Procesar  →  06 Resultados

El Formato va primero (define QUÉ texto se muestra), Estilo después
(define CÓMO se ve), y Posición al final (el preview usa ya el texto
y el estilo definitivos).  Los tres pasos son reactivos entre sí:
- Cambios en Formato actualizan preview de Estilo y placeholder de Posición.
- Cambios en Estilo actualizan el placeholder de Posición.
- Redimensionar el placeholder en Posición retroalimenta el fontsize en Estilo.
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import (
    QPixmap, QPainter, QColor, QFont, QFontMetrics,
    QDragEnterEvent, QDropEvent, QDesktopServices,
)
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QFrame, QComboBox, QCheckBox,
    QLineEdit, QScrollArea, QSpinBox, QGridLayout, QListWidget, QListWidgetItem,
)

from core.folio_format import FolioConfig, render, validate_pattern, preview_examples
from core.foleador_engine import FolioJob, FolioStyle, FoleadorEngine, FolioJobResult, _text_width
from core.output_paths import make_run_dir
from core.output_naming import unique_output_path_for_source
from shell.context import ShellContext
from shell.tippy import TippyButton
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.slider import SliderWithValue
from ui.common.tool_scaffold import PipelineWindow
from ui.common.send_to_tool import SendToToolButton
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.documents_step import DocumentsCard
from ui.common.process_step import ProcessStep
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.icons import set_button_icon
from ui.pdf_preview import PdfPreviewView, pil_to_qpixmap

TIPPY_FORMATO = """\
**Variables disponibles:**
- `{n}` — número de folio (sin formato)
- `{n:05}` — folio relleno a la izquierda, ancho mínimo 5
- `{total}` — total de páginas del lote o del documento
- `{doc}` — nombre del archivo sin extensión

**Ejemplos:**
- `{n:05}` → 00001 ... 00100 ... 10000
- `{n:02}` → 01 ... 99, 100, 101
- `FOLIO-{n:04}` → FOLIO-0001
- `{doc}-{n:03}` → contrato-001
- `{n:05}/{total:05}` → 00001/00123

**Nota sobre el relleno:**
Con `{n:05}`, el folio 100 es "00100" (5 chars).
El número crece hacia la derecha, nunca se trunca.
"""


class FoleadorWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs, config, style) -> None:
        super().__init__()
        self.jobs = jobs
        self.config = config
        self.style = style
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            engine = FoleadorEngine()
            results = engine.run_batch(
                self.jobs, self.config, self.style,
                progress=lambda c, t, m: (
                    self.progress.emit(c, t, m) if not self._cancel else None
                ),
                should_cancel=lambda: self._cancel,
            )
            if self._cancel:
                self.error.emit("Operación cancelada.")
            else:
                self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class FoleadorWindow(PipelineWindow):

    # Formato → Estilo → Posición: cada paso ya conoce lo anterior
    SECTIONS = [
        ("01", "Documentos", "Carga y ordena los PDFs"),
        ("02", "Formato",    "Máscara y numeración"),
        ("03", "Estilo",     "Tipografía y colores"),
        ("04", "Posición",   "Ubica el número de folio"),
        ("05", "Procesar",   "Ejecuta el foliado"),
        ("06", "Resultados", "Revisa el resultado"),
    ]
    BRAND = "Foleador"
    TAGLINE = "Numeración secuencial precisa"
    ACCENT_COLOR = "#3BD37C"

    FONT_OPTIONS = [
        ("Helvetica", "helv"),
        ("Times Roman", "tiro"),
        ("Courier", "cour"),
    ]

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[FolioJobResult] = []
        self._worker_thread: Optional[QThread] = None
        self._worker = None
        self._text_qcolor = QColor(0, 0, 0)
        self._bg_qcolor: Optional[QColor] = None

        # ── Estado de posición persistente entre navegaciones ──────────
        self._pos_saved_placement: Optional[tuple] = None
        self._pos_ref_path: Optional[str] = None
        self._pos_updating_pixmap: bool = False
        # True mientras el usuario arrastra — diferir syncs costosos al release
        self._pos_dragging: bool = False

        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------ #
    # Build — orden: Documentos → Formato → Estilo → Posición → Procesar → Resultados
    # ------------------------------------------------------------------ #

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())  # idx 0
        self.stack.addWidget(self._build_format_section())     # idx 1
        self.stack.addWidget(self._build_style_section())      # idx 2
        self.stack.addWidget(self._build_position_section())   # idx 3
        self.stack.addWidget(self._build_process_section())    # idx 4
        self.stack.addWidget(self._build_results_section())    # idx 5

    # ------------------------------------------------------------------ #
    # Paso 01: Documentos (via DocumentsCard compartida)
    # ------------------------------------------------------------------ #

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documentos",
            "Arrastra los items para cambiar el orden: el folio es continuo "
            "según esta secuencia.",
        ))

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=True,
            show_thumbnails=True,
            thumb_size=(64, 82),
        )
        self._docs_card.files_changed.connect(self._on_docs_changed)
        outer.addWidget(self._docs_card, 1)

        nav = QHBoxLayout()
        nav.addStretch()
        nxt = QPushButton("Continuar")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        set_button_icon(nxt, "arrow-right")
        nxt.clicked.connect(lambda: self._switch_section(1))   # → Formato
        nav.addWidget(nxt)
        outer.addLayout(nav)
        return page

    # ------------------------------------------------------------------ #
    # Paso 02: Formato (ahora PRIMERO — define el texto antes que el estilo)
    # ------------------------------------------------------------------ #

    def _build_style_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Estilo del folio",
            "Configura la tipografía y colores. La Posición mostrará el "
            "placeholder con el formato y estilo ya definidos.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        c_font = make_card("Fuente")
        self._font_combo = QComboBox()
        for display, _ in self.FONT_OPTIONS:
            self._font_combo.addItem(display)
        self._font_combo.currentIndexChanged.connect(self._on_style_changed)
        card_layout(c_font).addWidget(self._font_combo)
        grid.addWidget(c_font, 0, 0)

        c_size = make_card("Tamaño", "Tamaño del texto en puntos (pt)")
        self._size_slider = SliderWithValue(6.0, 48.0, 10.0, step=0.5, suffix="pt")
        self._size_slider.valueChanged.connect(self._on_style_changed)
        card_layout(c_size).addWidget(self._size_slider)
        grid.addWidget(c_size, 0, 1)

        c_var = make_card("Variantes")
        vr = QHBoxLayout()
        self._bold_chk = QCheckBox("Negrita")
        self._bold_chk.toggled.connect(self._on_style_changed)
        self._italic_chk = QCheckBox("Cursiva")
        self._italic_chk.toggled.connect(self._on_style_changed)
        vr.addWidget(self._bold_chk)
        vr.addWidget(self._italic_chk)
        vr.addStretch()
        card_layout(c_var).addLayout(vr)
        grid.addWidget(c_var, 1, 0)

        c_color = make_card("Color del texto")
        clr = QHBoxLayout()
        self._color_btn = QPushButton("Seleccionar color")
        self._color_btn.setProperty("class", "Ghost")
        self._color_btn.clicked.connect(self._on_pick_text_color)
        self._color_patch = QLabel()
        self._color_patch.setFixedSize(28, 28)
        self._color_patch.setStyleSheet("background:#000000; border-radius:4px; border:1px solid #33333B;")
        clr.addWidget(self._color_patch)
        clr.addWidget(self._color_btn)
        clr.addStretch()
        card_layout(c_color).addLayout(clr)
        grid.addWidget(c_color, 1, 1)

        c_bg = make_card("Fondo del recuadro")
        bgr = QHBoxLayout()
        self._bg_combo = QComboBox()
        self._bg_combo.addItems(["Sin fondo", "Blanco", "Personalizado"])
        self._bg_combo.currentIndexChanged.connect(self._on_bg_mode_changed)
        self._bg_patch = QLabel()
        self._bg_patch.setFixedSize(28, 28)
        self._bg_patch.setStyleSheet("background:transparent; border-radius:4px; border:1px dashed #33333B;")
        self._bg_custom_btn = QPushButton("Color")
        self._bg_custom_btn.setProperty("class", "Ghost")
        self._bg_custom_btn.setVisible(False)
        self._bg_custom_btn.clicked.connect(self._on_pick_bg_color)
        bgr.addWidget(self._bg_patch)
        bgr.addWidget(self._bg_combo, 1)
        bgr.addWidget(self._bg_custom_btn)
        card_layout(c_bg).addLayout(bgr)
        grid.addWidget(c_bg, 2, 0, 1, 2)

        outer.addLayout(grid)

        preview_card = make_card("Vista previa del estilo")
        self._style_preview_lbl = QLabel("00001")
        self._style_preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._style_preview_lbl.setMinimumHeight(60)
        self._style_preview_lbl.setStyleSheet(
            "background:#16161A; border-radius:6px; color:#ECEDEE; font-size:22px; font-weight:bold;"
        )
        card_layout(preview_card).addWidget(self._style_preview_lbl)
        outer.addWidget(preview_card)
        outer.addStretch(1)

        nav = QHBoxLayout()
        back = QPushButton("Formato")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(1))  # → Formato
        nav.addWidget(back)
        nav.addStretch()
        nxt = QPushButton("Continuar")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        set_button_icon(nxt, "arrow-right")
        nxt.clicked.connect(lambda: self._switch_section(3))   # → Posición
        nav.addWidget(nxt)
        outer.addLayout(nav)
        return page

    # ------------------------------------------------------------------ #
    # Paso 04: Posición (usa texto de Formato + estilo de Estilo)
    # ------------------------------------------------------------------ #

    def _build_position_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Posición del folio",
            "Arrastra el recuadro sobre la página. El placeholder ya muestra "
            "el estilo que configuraste en el paso anterior.",
        ))

        body = QHBoxLayout()
        body.setSpacing(20)

        left_col = QVBoxLayout()
        left_col.setSpacing(16)

        ref_card = make_card("Documento de referencia",
                             "Los demás documentos usarán la misma posición relativa.")
        rl = card_layout(ref_card)
        self._ref_list = QListWidget()
        self._ref_list.setMinimumHeight(120)
        self._ref_list.setMaximumHeight(160)
        self._ref_list.itemSelectionChanged.connect(self._on_ref_doc_changed)
        rl.addWidget(self._ref_list)
        left_col.addWidget(ref_card)

        zoom_card = make_card("Navegación y zoom")
        zl = card_layout(zoom_card)
        page_nav = QHBoxLayout()
        self._prev_pg = QPushButton()
        self._prev_pg.setProperty("class", "IconBtn")
        set_button_icon(self._prev_pg, "chevron-left", size=15, icon_only=True)
        self._prev_pg.clicked.connect(lambda: self._pos_preview.set_page(self._pos_preview.current_page()-1))
        self._next_pg = QPushButton()
        self._next_pg.setProperty("class", "IconBtn")
        set_button_icon(self._next_pg, "chevron-right", size=15, icon_only=True)
        self._next_pg.clicked.connect(lambda: self._pos_preview.set_page(self._pos_preview.current_page()+1))
        self._pg_lbl = QLabel("— / —")
        self._pg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pg_lbl.setStyleSheet("color: #9094A0;")
        page_nav.addWidget(self._prev_pg)
        page_nav.addWidget(self._pg_lbl, 1)
        page_nav.addWidget(self._next_pg)
        zl.addLayout(page_nav)

        zoom_row = QHBoxLayout()
        for label, fn, icon_name in [
            ("", lambda: self._pos_preview.zoom_out(), "minus"),
            ("", lambda: self._pos_preview.zoom_in(), "plus"),
            ("Ajustar", lambda: self._pos_preview.fit_to_view(), "maximize"),
        ]:
            btn = QPushButton(label)
            btn.setProperty("class", "IconBtn")
            set_button_icon(btn, icon_name, size=14, icon_only=not label)
            btn.clicked.connect(fn)
            zoom_row.addWidget(btn)
        zl.addLayout(zoom_row)
        left_col.addWidget(zoom_card)

        pos_card = make_card("Posición actual")
        self._pos_info = QLabel("—")
        self._pos_info.setProperty("class", "Mono")
        self._pos_info.setWordWrap(True)
        card_layout(pos_card).addWidget(self._pos_info)
        left_col.addWidget(pos_card)
        left_col.addStretch()

        left_w = QWidget()
        left_w.setLayout(left_col)
        left_scroll = QScrollArea()
        left_scroll.setObjectName("LeftPanelScroll")
        left_scroll.setWidget(left_w)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(320)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        body.addWidget(left_scroll)

        canvas_frame = QFrame()
        canvas_frame.setObjectName("PreviewCanvas")
        cf = QVBoxLayout(canvas_frame)
        cf.setContentsMargins(8, 8, 8, 8)
        self._pos_preview = PdfPreviewView()
        self._pos_preview.setObjectName("PdfPreview")
        self._pos_preview.placementChanged.connect(self._on_pos_placement_changed)
        self._pos_preview.pageChanged.connect(
            lambda c, t: self._pg_lbl.setText(f"{c+1} / {t}" if t > 0 else "— / —")
        )
        # Diferir el sync costoso de fontsize al momento en que el usuario
        # suelta el ratón — evita lag durante el arrastre.
        self._pos_preview.drag_started.connect(self._on_drag_started)
        self._pos_preview.drag_finished.connect(self._on_drag_finished)
        cf.addWidget(self._pos_preview)
        body.addWidget(canvas_frame, 1)

        outer.addLayout(body, 1)

        nav = QHBoxLayout()
        back = QPushButton("Estilo")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))  # → Estilo
        nav.addWidget(back)
        nav.addStretch()
        nxt = QPushButton("Continuar")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        set_button_icon(nxt, "arrow-right")
        nxt.clicked.connect(lambda: self._switch_section(4))   # → Procesar
        nav.addWidget(nxt)
        outer.addLayout(nav)
        return page

    # ------------------------------------------------------------------ #
    # Paso 02: Formato — con scroll para evitar cortes de texto
    # ------------------------------------------------------------------ #

    def _build_format_section(self) -> QWidget:
        # Envolver en scroll para que nada se corte
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        inner = QVBoxLayout(content)
        inner.setContentsMargins(36, 32, 36, 32)
        inner.setSpacing(20)

        inner.addLayout(make_page_header(
            "Formato de folio",
            "Define la máscara, número inicial y ámbito de la numeración.",
        ))

        # Máscara
        c_mask = make_card("Máscara de folio")
        ml = card_layout(c_mask)
        mask_row = QHBoxLayout()
        self._pattern_edit = QLineEdit("{n:05}")
        self._pattern_edit.setPlaceholderText("ej: {n:05}  o  FOLIO-{n:04}")
        self._pattern_edit.textChanged.connect(self._on_format_changed)
        tippy = TippyButton("Sintaxis de máscara", TIPPY_FORMATO)
        mask_row.addWidget(self._pattern_edit, 1)
        mask_row.addWidget(tippy)
        ml.addLayout(mask_row)
        self._mask_error_lbl = QLabel("")
        self._mask_error_lbl.setStyleSheet("color: #E5484D; font-size: 11px;")
        self._mask_error_lbl.setWordWrap(True)
        ml.addWidget(self._mask_error_lbl)
        inner.addWidget(c_mask)

        # Grid con configuración
        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        c_start = make_card("Número inicial", "Primer folio del lote")
        self._start_spin = QSpinBox()
        self._start_spin.setRange(0, 9_999_999)
        self._start_spin.setValue(1)
        self._start_spin.valueChanged.connect(self._on_format_changed)
        card_layout(c_start).addWidget(self._start_spin)
        grid.addWidget(c_start, 0, 0)

        c_step = make_card("Paso", "Incremento entre folios (normalmente 1)")
        self._step_spin = QSpinBox()
        self._step_spin.setRange(1, 1000)
        self._step_spin.setValue(1)
        self._step_spin.valueChanged.connect(self._on_format_changed)
        card_layout(c_step).addWidget(self._step_spin)
        grid.addWidget(c_step, 0, 1)

        # Ámbito en fila completa
        c_scope = make_card("Ámbito de la numeración")
        self._scope_combo = QComboBox()
        self._scope_combo.addItem("Continuo — todos los documentos comparten la secuencia")
        self._scope_combo.addItem("Por documento — reinicia en cada archivo")
        self._scope_combo.currentIndexChanged.connect(self._on_format_changed)
        card_layout(c_scope).addWidget(self._scope_combo)
        grid.addWidget(c_scope, 1, 0, 1, 2)

        # Opciones
        c_opts = make_card("Opciones adicionales")
        self._skip_first_chk = QCheckBox("Omitir primera página (portada sin folio)")
        self._skip_first_chk.toggled.connect(self._on_format_changed)
        card_layout(c_opts).addWidget(self._skip_first_chk)
        grid.addWidget(c_opts, 2, 0, 1, 2)

        inner.addLayout(grid)

        # Preview de ejemplos
        preview_card = make_card("Vista previa de la numeración")
        self._fmt_preview_lbl = QLabel()
        self._fmt_preview_lbl.setProperty("class", "Mono")
        self._fmt_preview_lbl.setWordWrap(True)
        card_layout(preview_card).addWidget(self._fmt_preview_lbl)
        inner.addWidget(preview_card)
        inner.addStretch(1)

        nav = QHBoxLayout()
        back = QPushButton("Documentos")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(0))  # → Documentos
        nav.addWidget(back)
        nav.addStretch()
        nxt = QPushButton("Continuar")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        set_button_icon(nxt, "arrow-right")
        nxt.clicked.connect(lambda: self._switch_section(2))   # → Estilo
        nav.addWidget(nxt)
        inner.addLayout(nav)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        self._update_format_preview()
        return page

    # ------------------------------------------------------------------ #
    # Paso 05: Procesar (via ProcessStep compartido)
    # ------------------------------------------------------------------ #

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header("Procesar", "Verifica el resumen y ejecuta el foliado masivo."))

        self._proc_step = ProcessStep(
            run_label="Foliar documentos",
            show_output_dir=False,
        )
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Posición")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(3))  # → Posición
        nav.addWidget(back)
        outer.addLayout(nav)
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

        outer.addLayout(make_page_header("Resultados", "Revisa los documentos foliados."))

        self._results_viewer = GenericPdfViewer("Documentos foliados")
        self._results_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._results_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(4))
        nav.addWidget(back)
        nav.addStretch()
        self._send_btn = SendToToolButton(self.ctx, "foleador")
        nav.addWidget(self._send_btn)
        restart_btn = QPushButton("Nueva sesión")
        restart_btn.setProperty("class", "Primary")
        restart_btn.setMinimumWidth(180)
        set_button_icon(restart_btn, "refresh-cw")
        restart_btn.clicked.connect(self._reset_session)
        nav.addWidget(restart_btn)
        outer.addLayout(nav)
        return page

    # ------------------------------------------------------------------ #
    # Hooks de navegación — ÍNDICES ACTUALIZADOS
    # ------------------------------------------------------------------ #

    def _on_section_activated(self, idx: int) -> None:
        if idx == 1:    # Formato
            self._update_format_preview()
        elif idx == 2:  # Estilo
            self._update_style_preview()
        elif idx == 3:  # Posición
            self._refresh_position_step()
        elif idx == 4:  # Procesar
            self._refresh_summary()

    # ------------------------------------------------------------------ #
    # API PipelineWindow
    # ------------------------------------------------------------------ #

    def set_inputs(self, paths: List[str]) -> None:
        self._add_file_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._add_file_paths(paths)
        self._switch_section(0)

    def _add_file_paths(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)

    def _get_ordered_paths(self) -> List[str]:
        return self._docs_card.paths()

    def _on_docs_changed(self, paths: List[str]) -> None:
        current_paths = set(paths)
        if not paths or (self._pos_ref_path and self._pos_ref_path not in current_paths):
            self._clear_position_reference()
        if self.stack.currentIndex() == 3:  # Posición
            self._refresh_position_step()

    # ------------------------------------------------------------------ #
    # Posición — preview con estilo actual
    # ------------------------------------------------------------------ #

    def _clear_position_reference(self) -> None:
        self._pos_saved_placement = None
        self._pos_ref_path = None
        if hasattr(self, "_ref_list"):
            self._ref_list.clear()
        if hasattr(self, "_pos_preview"):
            self._pos_preview.clear_page()
        if hasattr(self, "_pos_info"):
            self._pos_info.setText("Sin posición definida")
        if hasattr(self, "_pg_lbl"):
            self._pg_lbl.setText("— / —")

    def _refresh_position_step(self) -> None:
        """Actualiza la lista de referencia y carga el PDF sólo si cambió.
        Siempre restaura el placement guardado (posición + tamaño del usuario).
        """
        paths = self._get_ordered_paths()

        # ── Reconstruir lista sin disparar _on_ref_doc_changed ──────────
        self._ref_list.blockSignals(True)
        self._ref_list.clear()
        for p in paths:
            it = QListWidgetItem(Path(p).name)
            it.setData(Qt.ItemDataRole.UserRole, p)
            self._ref_list.addItem(it)

        # Intentar mantener el mismo doc de referencia si sigue en la lista
        target_row = 0
        if self._pos_ref_path:
            for i in range(self._ref_list.count()):
                if self._ref_list.item(i).data(Qt.ItemDataRole.UserRole) == self._pos_ref_path:
                    target_row = i
                    break

        self._ref_list.setCurrentRow(target_row)
        self._ref_list.blockSignals(False)

        # ── Cargar PDF si cambió el documento seleccionado ──────────────
        current_item = self._ref_list.currentItem()
        if current_item is None:
            self._clear_position_reference()
            return
        selected_path = current_item.data(Qt.ItemDataRole.UserRole)

        if selected_path != self._pos_ref_path:
            # Documento nuevo: limpiar placement guardado
            self._pos_saved_placement = None
            self._pos_ref_path = selected_path
            self._pos_preview.load_pdf(selected_path)

        self._update_placeholder()

    def _on_ref_doc_changed(self) -> None:
        """Llamado cuando el usuario cambia el documento de referencia manualmente."""
        item = self._ref_list.currentItem()
        if item is None:
            return
        p = item.data(Qt.ItemDataRole.UserRole)
        if p == self._pos_ref_path:
            return  # misma selección, no recargar
        # Cambio real de documento: resetear placement guardado
        self._pos_saved_placement = None
        self._pos_ref_path = p
        self._pos_preview.load_pdf(p)
        self._update_placeholder()

    def _on_drag_started(self) -> None:
        self._pos_dragging = True

    def _on_drag_finished(self) -> None:
        """Al soltar el ratón se ejecuta el sync completo (info + fontsize)."""
        self._pos_dragging = False
        if self._pos_preview.has_signature():
            self._pos_saved_placement = self._pos_preview.placement_of("_single")
        self._update_pos_info()
        self._sync_fontsize_from_position()

    def _on_pos_placement_changed(self) -> None:
        """Guarda el placement en tiempo real; el sync de fontsize se difiere al release."""
        if self._pos_updating_pixmap:
            return  # cambio programático, ignorar
        if self._pos_preview.has_signature():
            self._pos_saved_placement = self._pos_preview.placement_of("_single")
        self._update_pos_info()
        # Durante el drag activo no recalculamos el fontsize en cada evento —
        # eso se hace en _on_drag_finished para no introducir lag.
        if not self._pos_dragging:
            self._sync_fontsize_from_position()

    def _sync_fontsize_from_position(self) -> None:
        """Calcula el fontsize a partir del ancho actual del placeholder y
        actualiza el slider de Estilo.  Cierra el ciclo reactivo:
        Posición (tamaño) → Estilo (fontsize).

        En la página de referencia, scale=1.0 siempre, así que el fontsize
        nominal ES el fontsize actual — no se necesita corrección de escala.
        """
        if not hasattr(self, "_size_slider") or not self._pos_preview.has_signature():
            return
        w_pt, _ = self._pos_preview.signature_size_pdf()
        if w_pt <= 0:
            return

        cfg = self._read_config()
        sample = render(cfg.pattern, cfg.start, "documento")
        style = self._read_style()

        # Fontsize que hace que el texto ocupe el 92 % del ancho del placeholder.
        # text_width es proporcional a fontsize → fs = target_width / width_per_pt
        tw_unit = _text_width(sample, fontname=style.fontname, fontsize=1.0)
        if tw_unit <= 0:
            return

        fs_nominal = (w_pt * 0.92) / tw_unit
        # Clampear al rango del slider y redondear al paso de 0.5
        fs_nominal = max(6.0, min(48.0, round(fs_nominal * 2) / 2))

        if abs(fs_nominal - self._size_slider.value()) < 0.3:
            return  # cambio insignificante: evitar refresh inútil

        self._size_slider.blockSignals(True)
        self._size_slider.setValue(fs_nominal)
        self._size_slider.blockSignals(False)
        self._update_style_preview()

    def _update_placeholder(self) -> None:
        """Regenera el pixmap del placeholder con el estilo actual.

        1. Crea el pixmap con el texto y estilo actuales.
        2. Si hay un placement guardado (posición + tamaño) lo restaura.
        3. Si es la primera carga (sin placement previo), inicializa el
           tamaño a partir del fontsize actual para que el placeholder
           sea proporcional al texto desde el principio.
        """
        if self._pos_preview.page_count() == 0:
            return

        sample_n = getattr(self, "_start_spin", None)
        n = sample_n.value() if sample_n else 1
        pattern = getattr(self, "_pattern_edit", None)
        pat = pattern.text() if pattern else "{n:05}"
        sample = render(pat, n, "documento")

        fs = self._size_slider.value() if hasattr(self, "_size_slider") else 10.0
        pix = self._make_folio_pixmap(sample, fontsize=int(fs),
                                       text_color=self._text_qcolor,
                                       bg_color=self._bg_qcolor)

        # Bloquear guardado durante el reemplazo de pixmap
        self._pos_updating_pixmap = True
        try:
            self._pos_preview.set_signature(pix)
        finally:
            self._pos_updating_pixmap = False

        if self._pos_saved_placement is not None:
            # Restaurar tamaño y posición previos
            cx_n, cy_n, w_pt, h_pt, angle = self._pos_saved_placement
            self._pos_preview.restore_signature_placement(cx_n, cy_n, w_pt, h_pt, angle)
        else:
            # Primera vez: inicializar con tamaño proporcional al fontsize
            style = self._read_style()
            tw = _text_width(sample, fontname=style.fontname, fontsize=fs)
            init_w_pt = max(20.0, tw / 0.92)
            init_h_pt = fs * 2.0
            # Leer posición que asignó add_sig por defecto
            p = self._pos_preview.placement_of("_single")
            if p is not None:
                cx_n, cy_n = p[0], p[1]
                angle = p[4]
                self._pos_saved_placement = (cx_n, cy_n, init_w_pt, init_h_pt, angle)
                self._pos_preview.restore_signature_placement(cx_n, cy_n, init_w_pt, init_h_pt, angle)

        self._update_pos_info()

    def _update_pos_info(self) -> None:
        if not self._pos_preview.has_signature():
            self._pos_info.setText("Sin posición definida")
            return
        cx, cy = self._pos_preview.signature_center_pdf()
        w, h = self._pos_preview.signature_size_pdf()
        pw, ph = self._pos_preview.page_size_pt()
        self._pos_info.setText(
            f"Centro     {cx:6.1f}, {cy:6.1f} pt\n"
            f"Tamaño     {w:5.1f} × {h:5.1f} pt\n"
            f"Página     {pw:.0f} × {ph:.0f} pt"
        )

    @staticmethod
    def _make_folio_pixmap(text, fontsize=10, text_color=None, bg_color=None):
        if text_color is None:
            text_color = QColor(20, 20, 20)
        font = QFont("Segoe UI", fontsize, QFont.Weight.Bold)
        fm = QFontMetrics(font)
        tr = fm.tightBoundingRect(text)
        # Padding mínimo: el placeholder debe ser casi tan pequeño como el
        # texto real en el PDF, para que la posición visual sea fiel.
        pad_x, pad_y = 4, 3
        w = max(tr.width() + 2 * pad_x, 1)
        h = max(tr.height() + 2 * pad_y, 1)
        pix = QPixmap(w, h)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if bg_color:
            p.fillRect(pix.rect(), bg_color)
        p.setFont(font)
        p.setPen(text_color)
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, text)
        p.end()
        return pix

    # ------------------------------------------------------------------ #
    # Estilo
    # ------------------------------------------------------------------ #

    def _on_style_changed(self, *_) -> None:
        self._update_style_preview()
        # Reactivo: fontsize cambió → redimensionar el placeholder en Posición
        if self._pos_preview.page_count() > 0:
            self._sync_placeholder_size_from_style()
            self._update_placeholder()

    def _sync_placeholder_size_from_style(self) -> None:
        """Actualiza el tamaño del placeholder al cambiar fontsize o fuente.

        Calcula el ancho exacto que necesita el texto a la nueva tipografía y
        guarda esas dimensiones en _pos_saved_placement para que
        _update_placeholder las restaure en el visor.
        """
        if not self._pos_preview.has_signature():
            return
        cfg = self._read_config()
        sample = render(cfg.pattern, cfg.start, "documento")
        style = self._read_style()
        fs = style.fontsize

        tw = _text_width(sample, fontname=style.fontname, fontsize=fs)
        if tw <= 0:
            return

        # Caja justa para el texto: ancho = text_w / 0.92, alto = 2× fontsize
        new_w_pt = tw / 0.92
        new_h_pt = fs * 2.0

        if self._pos_saved_placement is not None:
            cx_n, cy_n, _, _, angle = self._pos_saved_placement
        else:
            # Primera vez: posición por defecto (zona inferior derecha)
            cx_n, cy_n, angle = 0.82, 0.88, 0.0

        self._pos_saved_placement = (cx_n, cy_n, new_w_pt, new_h_pt, angle)

    def _on_pick_text_color(self) -> None:
        from PyQt6.QtWidgets import QColorDialog
        color = QColorDialog.getColor(self._text_qcolor, self, "Color del texto")
        if color.isValid():
            self._text_qcolor = color
            self._color_patch.setStyleSheet(
                f"background:{color.name()}; border-radius:4px; border:1px solid #33333B;"
            )
            self._update_style_preview()

    def _on_bg_mode_changed(self, idx: int) -> None:
        if idx == 0:
            self._bg_qcolor = None
            self._bg_patch.setStyleSheet(
                "background:transparent; border-radius:4px; border:1px dashed #33333B;"
            )
            self._bg_custom_btn.setVisible(False)
        elif idx == 1:
            self._bg_qcolor = QColor(255, 255, 255)
            self._bg_patch.setStyleSheet(
                "background:#FFFFFF; border-radius:4px; border:1px solid #33333B;"
            )
            self._bg_custom_btn.setVisible(False)
        else:
            self._bg_custom_btn.setVisible(True)
        self._update_style_preview()

    def _on_pick_bg_color(self) -> None:
        from PyQt6.QtWidgets import QColorDialog
        init = self._bg_qcolor or QColor(255, 255, 255)
        color = QColorDialog.getColor(init, self, "Color de fondo")
        if color.isValid():
            self._bg_qcolor = color
            self._bg_patch.setStyleSheet(
                f"background:{color.name()}; border-radius:4px; border:1px solid #33333B;"
            )
            self._update_style_preview()

    def _update_style_preview(self) -> None:
        sample_text = render(
            getattr(self, "_pattern_edit", None) and self._pattern_edit.text() or "{n:05}",
            getattr(self, "_start_spin", None) and self._start_spin.value() or 1,
            "documento",
        )
        fs = int(self._size_slider.value()) if hasattr(self, "_size_slider") else 10
        pix = self._make_folio_pixmap(sample_text, fontsize=fs,
                                       text_color=self._text_qcolor,
                                       bg_color=self._bg_qcolor)
        scaled = pix.scaledToHeight(56, Qt.TransformationMode.SmoothTransformation)
        self._style_preview_lbl.setPixmap(scaled)
        self._style_preview_lbl.setText("")

    def _read_style(self) -> FolioStyle:
        idx = self._font_combo.currentIndex() if hasattr(self, "_font_combo") else 0
        _, fontbase = self.FONT_OPTIONS[idx]
        c = self._text_qcolor
        bg = self._bg_qcolor
        return FolioStyle(
            fontbase=fontbase,
            fontsize=self._size_slider.value() if hasattr(self, "_size_slider") else 10.0,
            bold=self._bold_chk.isChecked() if hasattr(self, "_bold_chk") else False,
            italic=self._italic_chk.isChecked() if hasattr(self, "_italic_chk") else False,
            color=(c.redF(), c.greenF(), c.blueF()),
            bg_color=(bg.redF(), bg.greenF(), bg.blueF()) if bg else None,
        )

    # ------------------------------------------------------------------ #
    # Formato
    # ------------------------------------------------------------------ #

    def _on_format_changed(self, *_) -> None:
        if not hasattr(self, "_pattern_edit"):
            return
        errors = validate_pattern(self._pattern_edit.text())
        self._mask_error_lbl.setText(errors[0] if errors else "")
        self._update_format_preview()
        # Reactivo: el texto del folio cambia → actualizar Estilo y Posición
        self._update_style_preview()
        if self._pos_preview.page_count() > 0:
            self._update_placeholder()

    def _update_format_preview(self) -> None:
        if not hasattr(self, "_pattern_edit"):
            return
        cfg = self._read_config()
        self._fmt_preview_lbl.setText(preview_examples(cfg, doc_name="documento"))

    def _read_config(self) -> FolioConfig:
        scope = "per_doc" if (hasattr(self, "_scope_combo") and self._scope_combo.currentIndex() == 1) else "continuous"
        return FolioConfig(
            pattern=self._pattern_edit.text() if hasattr(self, "_pattern_edit") else "{n:05}",
            start=self._start_spin.value() if hasattr(self, "_start_spin") else 1,
            step=self._step_spin.value() if hasattr(self, "_step_spin") else 1,
            scope=scope,
            skip_first_page=self._skip_first_chk.isChecked() if hasattr(self, "_skip_first_chk") else False,
        )

    # ------------------------------------------------------------------ #
    # Procesar
    # ------------------------------------------------------------------ #

    def _refresh_summary(self) -> None:
        paths = self._get_ordered_paths()
        cfg = self._read_config()
        scope_txt = "Continuo" if cfg.scope == "continuous" else "Por documento"
        rows = [
            f"<b>Documentos:</b> &nbsp; {len(paths)}",
            f"<b>Patrón:</b> &nbsp; <code>{cfg.pattern}</code>",
            f"<b>Inicio:</b> &nbsp; {cfg.start}  &nbsp;·&nbsp; <b>Paso:</b> &nbsp; {cfg.step}  &nbsp;·&nbsp; <b>Ámbito:</b> &nbsp; {scope_txt}",
        ]
        html = "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        self._proc_step.set_summary_html(html)

    def _validate_ready(self) -> Optional[str]:
        if self._docs_card.is_empty():
            return "Agrega al menos un documento."
        if not self._pos_preview.has_signature():
            return "Define la posición del folio en el Paso 04."
        errors = validate_pattern(self._pattern_edit.text())
        if errors:
            return f"Patrón inválido: {errors[0]}"
        return None

    def _build_jobs(self) -> List[FolioJob]:
        out_dir = make_run_dir("Foleador")
        cx_n, cy_n = self._pos_preview.signature_center_normalized()
        w_pt, h_pt = self._pos_preview.signature_size_pdf()
        ref_pw, ref_ph = self._pos_preview.page_size_pt()

        # Normalizar el tamaño del placeholder a fracción de página.
        # Esto garantiza que el folio escale proporcionalmente en páginas
        # de distinto tamaño (A4, Legal, scaneadas a alta resolución, etc.)
        ref_pw = ref_pw if ref_pw > 0 else 595.0
        ref_ph = ref_ph if ref_ph > 0 else 842.0
        w_norm = w_pt / ref_pw
        h_norm = h_pt / ref_ph

        jobs = []
        reserved: set[str] = set()
        add_suffix = add_tool_suffix_enabled()
        for p in self._get_ordered_paths():
            in_path = Path(p)
            out_path = unique_output_path_for_source(
                out_dir,
                in_path,
                extension=".pdf",
                tool_suffix="foliado",
                add_tool_suffix=add_suffix,
                reserved=reserved,
                fallback="documento",
            )
            jobs.append(FolioJob(
                pdf_path=str(in_path),
                output_path=str(out_path),
                x_norm=cx_n, y_norm=cy_n,
                width_norm=w_norm, height_norm=h_norm,
                ref_page_height_pt=ref_ph,
                ref_page_width_pt=ref_pw,
            ))
        return jobs

    def _on_run(self) -> None:
        err = self._validate_ready()
        if err:
            show_warning(self, "Falta información", err)
            return
        if self._worker_thread:
            return
        self._results_viewer.clear_results()
        self._send_btn.set_output_paths([])
        jobs = self._build_jobs()
        config = self._read_config()
        style = self._read_style()
        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Iniciando…")
        self._worker_thread = QThread(self)
        self._worker = FoleadorWorker(jobs, config, style)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._proc_step.set_progress(self._proc_step._prog_bar.value(), "Cancelando…")

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
        self.ctx.tray.add_items(output_paths, "Foleador")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)
        show_success(
            self, "Hecho",
            f"Se foliaron {ok} documento{'s' if ok!=1 else ''}.\n"
            + (f"Con error: {fail}" if fail else ""),
        )
        self._results_viewer.set_results(results)
        self._switch_section(5)

    def _on_worker_error(self, msg: str) -> None:
        show_error(self, "Error", msg)
        self._proc_step.set_running(False)
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
            self._worker_thread.deleteLater()
            self._worker_thread = None
            self._worker = None

    def _open_in_explorer(self, path: str) -> None:
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _reset_session(self) -> None:
        self._results_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []
        self._docs_card.clear()
        self._proc_step.reset()
        self._clear_position_reference()
        self._switch_section(0)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        self.handle_drop(paths)
