"""FoleadorWindow — pipeline de foliado masivo de PDFs.

Pipeline (orden corregido):
    01 Documentos  →  02 Estilo  →  03 Posición  →  04 Formato
    →  05 Procesar  →  06 Resultados

El Estilo va ANTES que la Posición para que el placeholder en el preview
ya refleje la tipografía y colores configurados por el usuario.
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
    QFrame, QComboBox, QCheckBox, QMessageBox,
    QLineEdit, QScrollArea, QSpinBox, QGridLayout,
)

from core.folio_format import FolioConfig, render, validate_pattern, preview_examples
from core.foleador_engine import FolioJob, FolioStyle, FoleadorEngine, FolioJobResult
from shell.context import ShellContext
from shell.tippy import TippyButton
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.slider import SliderWithValue
from ui.common.tool_scaffold import PipelineWindow
from ui.common.send_to_tool import SendToToolButton
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.documents_step import DocumentsCard
from ui.common.process_step import ProcessStep
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
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class FoleadorWindow(PipelineWindow):

    # ORDEN CORREGIDO: Estilo (02) ANTES de Posición (03)
    SECTIONS = [
        ("01", "Documentos", "Carga y ordena los PDFs"),
        ("02", "Estilo",     "Tipografía y colores"),
        ("03", "Posición",   "Ubica el número de folio"),
        ("04", "Formato",    "Máscara y numeración"),
        ("05", "Procesar",   "Ejecuta el foliado"),
        ("06", "Resultados", "Revisa el resultado"),
    ]
    BRAND = "Foleador"
    TAGLINE = "Numeración secuencial precisa"

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

        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------ #
    # Build — orden: Documentos → Estilo → Posición → Formato → Procesar → Resultados
    # ------------------------------------------------------------------ #

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())  # idx 0
        self.stack.addWidget(self._build_style_section())      # idx 1
        self.stack.addWidget(self._build_position_section())   # idx 2
        self.stack.addWidget(self._build_format_section())     # idx 3
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
        outer.addWidget(self._docs_card, 1)

        nav = QHBoxLayout()
        nav.addStretch()
        nxt = QPushButton("Continuar  →")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        nxt.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(nxt)
        outer.addLayout(nav)
        return page

    # ------------------------------------------------------------------ #
    # Paso 02: Estilo (ahora ANTES de Posición)
    # ------------------------------------------------------------------ #

    def _build_style_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Estilo del folio",
            "Configura la tipografía y colores. La Posición mostrará "
            "el placeholder con este estilo ya aplicado.",
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

        c_align = make_card("Alineación")
        self._align_combo = QComboBox()
        self._align_combo.addItems(["Izquierda", "Centro", "Derecha"])
        self._align_combo.setCurrentIndex(1)
        self._align_combo.currentIndexChanged.connect(self._on_style_changed)
        card_layout(c_align).addWidget(self._align_combo)
        grid.addWidget(c_align, 1, 1)

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
        grid.addWidget(c_color, 2, 0)

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
        grid.addWidget(c_bg, 2, 1)

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
        back = QPushButton("←  Documentos")
        back.setProperty("class", "Ghost")
        back.clicked.connect(lambda: self._switch_section(0))
        nav.addWidget(back)
        nav.addStretch()
        nxt = QPushButton("Continuar  →")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        nxt.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(nxt)
        outer.addLayout(nav)
        return page

    # ------------------------------------------------------------------ #
    # Paso 03: Posición (ahora DESPUÉS de Estilo)
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
        self._prev_pg = QPushButton("◀")
        self._prev_pg.setProperty("class", "IconBtn")
        self._prev_pg.clicked.connect(lambda: self._pos_preview.set_page(self._pos_preview.current_page()-1))
        self._next_pg = QPushButton("▶")
        self._next_pg.setProperty("class", "IconBtn")
        self._next_pg.clicked.connect(lambda: self._pos_preview.set_page(self._pos_preview.current_page()+1))
        self._pg_lbl = QLabel("— / —")
        self._pg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pg_lbl.setStyleSheet("color: #9094A0;")
        page_nav.addWidget(self._prev_pg)
        page_nav.addWidget(self._pg_lbl, 1)
        page_nav.addWidget(self._next_pg)
        zl.addLayout(page_nav)

        zoom_row = QHBoxLayout()
        for label, fn in [("−", lambda: self._pos_preview.zoom_out()),
                          ("+", lambda: self._pos_preview.zoom_in()),
                          ("Ajustar", lambda: self._pos_preview.fit_to_view())]:
            btn = QPushButton(label)
            btn.setProperty("class", "IconBtn")
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
        self._pos_preview.placementChanged.connect(self._update_pos_info)
        self._pos_preview.pageChanged.connect(
            lambda c, t: self._pg_lbl.setText(f"{c+1} / {t}" if t > 0 else "— / —")
        )
        cf.addWidget(self._pos_preview)
        body.addWidget(canvas_frame, 1)

        outer.addLayout(body, 1)

        nav = QHBoxLayout()
        back = QPushButton("←  Estilo")
        back.setProperty("class", "Ghost")
        back.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(back)
        nav.addStretch()
        nxt = QPushButton("Continuar  →")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        nxt.clicked.connect(lambda: self._switch_section(3))
        nav.addWidget(nxt)
        outer.addLayout(nav)
        return page

    # ------------------------------------------------------------------ #
    # Paso 04: Formato — con scroll para evitar cortes de texto
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
        back = QPushButton("←  Posición")
        back.setProperty("class", "Ghost")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        nav.addStretch()
        nxt = QPushButton("Continuar  →")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        nxt.clicked.connect(lambda: self._switch_section(4))
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
            settings_key="foleador/output_dir",
            default_output=str(Path.home() / "PDFlex" / "Foleador"),
        )
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("←  Formato")
        back.setProperty("class", "Ghost")
        back.clicked.connect(lambda: self._switch_section(3))
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
        back = QPushButton("←  Procesar")
        back.setProperty("class", "Ghost")
        back.clicked.connect(lambda: self._switch_section(4))
        nav.addWidget(back)
        nav.addStretch()
        self._send_btn = SendToToolButton(self.ctx, "foleador")
        nav.addWidget(self._send_btn)
        restart_btn = QPushButton("↺  Nueva sesión")
        restart_btn.setProperty("class", "Primary")
        restart_btn.setMinimumWidth(180)
        restart_btn.clicked.connect(self._reset_session)
        nav.addWidget(restart_btn)
        outer.addLayout(nav)
        return page

    # ------------------------------------------------------------------ #
    # Hooks de navegación — ÍNDICES ACTUALIZADOS
    # ------------------------------------------------------------------ #

    def _on_section_activated(self, idx: int) -> None:
        if idx == 1:   # Estilo
            self._update_style_preview()
        elif idx == 2:  # Posición — genera placeholder con estilo actual
            self._refresh_ref_list()
            self._update_placeholder()
        elif idx == 3:  # Formato
            self._update_format_preview()
        elif idx == 4:  # Procesar
            self._refresh_summary()

    # ------------------------------------------------------------------ #
    # API PipelineWindow
    # ------------------------------------------------------------------ #

    def set_inputs(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def _get_ordered_paths(self) -> List[str]:
        return self._docs_card.paths()

    # ------------------------------------------------------------------ #
    # Posición — preview con estilo actual
    # ------------------------------------------------------------------ #

    def _refresh_ref_list(self) -> None:
        self._ref_list.clear()
        for p in self._get_ordered_paths():
            item = QListWidgetItem(Path(p).name)
            item.setData(Qt.ItemDataRole.UserRole, p)
            self._ref_list.addItem(item)
        if self._ref_list.count() > 0:
            self._ref_list.setCurrentRow(0)

    def _on_ref_doc_changed(self) -> None:
        item = self._ref_list.currentItem()
        if item is None:
            return
        p = item.data(Qt.ItemDataRole.UserRole)
        self._pos_preview.load_pdf(p)
        self._update_placeholder()

    def _update_placeholder(self) -> None:
        """Genera el placeholder usando el ESTILO ACTUAL configurado en paso 02."""
        if self._pos_preview.page_count() == 0:
            return
        # Número de muestra
        sample_n = getattr(self, "_start_spin", None)
        n = sample_n.value() if sample_n else 1
        pattern = getattr(self, "_pattern_edit", None)
        pat = pattern.text() if pattern else "{n:05}"
        sample = render(pat, n, "documento")

        # Colores y tamaño del estilo actual
        text_color = self._text_qcolor
        bg_color = self._bg_qcolor
        fs = int(self._size_slider.value()) if hasattr(self, "_size_slider") else 10

        pix = self._make_folio_pixmap(sample, fontsize=fs,
                                       text_color=text_color, bg_color=bg_color)
        self._pos_preview.set_signature(pix)
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
        tr = fm.boundingRect(text)
        pad_x, pad_y = 14, 8
        w = max(tr.width() + 2 * pad_x, 80)
        h = tr.height() + 2 * pad_y
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
            text_align=self._align_combo.currentIndex() if hasattr(self, "_align_combo") else 1,
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
            return "Define la posición del folio en el Paso 03."
        if not self._proc_step.output_dir():
            return "Define una carpeta de salida."
        errors = validate_pattern(self._pattern_edit.text())
        if errors:
            return f"Patrón inválido: {errors[0]}"
        return None

    def _build_jobs(self) -> List[FolioJob]:
        out_dir = Path(self._proc_step.output_dir())
        out_dir.mkdir(parents=True, exist_ok=True)
        cx_n, cy_n = self._pos_preview.signature_center_normalized()
        w_pt, h_pt = self._pos_preview.signature_size_pdf()
        jobs = []
        for p in self._get_ordered_paths():
            in_path = Path(p)
            out_path = out_dir / f"{in_path.stem}_foliado.pdf"
            jobs.append(FolioJob(
                pdf_path=str(in_path),
                output_path=str(out_path),
                x_norm=cx_n, y_norm=cy_n,
                width_pt=w_pt, height_pt=h_pt,
            ))
        return jobs

    def _on_run(self) -> None:
        err = self._validate_ready()
        if err:
            QMessageBox.warning(self, "Falta información", err)
            return
        if self._worker_thread:
            return
        self._results_viewer.clear_results()
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
        QMessageBox.information(
            self, "Hecho",
            f"Se foliaron {ok} documento{'s' if ok!=1 else ''}.\n"
            + (f"Con error: {fail}" if fail else ""),
        )
        self._results_viewer.set_results(results)
        self._switch_section(5)

    def _on_worker_error(self, msg: str) -> None:
        QMessageBox.critical(self, "Error", msg)
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
        self.last_results = []
        self._docs_card.clear()
        self._proc_step.reset()
        self._switch_section(0)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        self._add_file_paths(paths)
        self._switch_section(0)
