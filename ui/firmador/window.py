"""FirmadorWindow — pipeline de firma masiva de PDFs.

v3 — Reescritura completa:
  - Modelo de datos estable: _SigEntry con uid único (uuid) en vez de índice entero.
  - Múltiples firmas aplicadas en una sola pasada (sin archivos temporales).
  - PdfPreviewView multi-sig: todas las firmas visibles simultáneamente.
  - set_page() conserva los items de firma (no limpia el canvas).
  - Barra de estado compacta: nav páginas | zoom | info de firma activa.
  - Posición por documento: combo "Misma para todos / Por documento".

Pipeline:
    01 Documentos  →  02 Firma y posición  →  03 Variación
    →  04 Procesar  →  05 Resultados
"""
from __future__ import annotations
import uuid as _uuid_mod
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import fitz
from PIL import Image
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread, QObject, QUrl
from PyQt6.QtGui import (
    QPixmap, QIcon, QDragEnterEvent, QDropEvent, QDesktopServices,
    QColor, QPainter, QImage,
)
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFileDialog, QFrame,
    QSpinBox, QCheckBox, QProgressBar, QMessageBox,
    QGridLayout, QComboBox,
)

from core.signature_engine import SignatureEngine, SignJob, SigPlacement, JobResult
from core.variation import VariationConfig
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.slider import SliderWithValue
from ui.common.tool_scaffold import PipelineWindow
from ui.common.send_to_tool import SendToToolButton
from ui.common.documents_step import DocumentsCard
from ui.common.process_step import ProcessStep
from ui.pdf_preview import PdfPreviewView, pil_to_qpixmap
from ui.results_viewer import ResultsViewer


# ── Paleta de colores para firmas ────────────────────────────────────── #
SIG_COLORS: List[QColor] = [
    QColor(94, 106, 210),   # indigo
    QColor(56, 178, 172),   # teal
    QColor(236, 135, 72),   # orange
    QColor(168, 85, 247),   # violet
    QColor(239, 68, 68),    # red
    QColor(34, 197, 94),    # green
    QColor(234, 179, 8),    # yellow
    QColor(236, 72, 153),   # pink
]


@dataclass
class _SigEntry:
    uid: str
    path: str
    label: str
    pixmap: object   # QPixmap
    color: object    # QColor


# ====================================================================== #
#  Worker de firma — sin archivos temporales, N firmas por pasada
# ====================================================================== #

class SignWorker(QObject):
    progress = pyqtSignal(int, int, str)
    doc_started = pyqtSignal(str)
    doc_finished = pyqtSignal(object)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[SignJob], variation: VariationConfig) -> None:
        super().__init__()
        self.jobs = jobs
        self.variation = variation
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        engine = SignatureEngine(self.variation)
        results: List[JobResult] = []
        total = len(self.jobs)

        for i, job in enumerate(self.jobs):
            if self._cancel:
                break
            self.doc_started.emit(job.pdf_path)

            def _p(cur, tot, msg, _i=i, _n=total):
                done = _i * 100 + int(cur / max(1, tot) * 100)
                self.progress.emit(done, _n * 100, msg)

            try:
                result = engine.run_job(job, progress=_p)
            except Exception as e:
                result = JobResult(job=job, output_path="", success=False, error=str(e))

            results.append(result)
            self.doc_finished.emit(result)

        self.finished.emit(results)


# ====================================================================== #
#  Utilidad: ícono compuesto (franja de color + miniatura)
# ====================================================================== #

def _make_sig_icon(pixmap: QPixmap, color: QColor, w: int = 90, h: int = 54) -> QPixmap:
    """Crea un ícono con franja de color a la izquierda y miniatura de la firma."""
    result = QPixmap(w, h)
    result.fill(QColor("#1A1A20"))
    painter = QPainter(result)
    # Franja de color
    painter.fillRect(0, 0, 5, h, color)
    # Miniatura centrada en el espacio restante
    thumb = pixmap.scaled(
        w - 10, h - 6,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    tx = 9 + (w - 10 - thumb.width()) // 2
    ty = (h - thumb.height()) // 2
    painter.drawPixmap(tx, ty, thumb)
    painter.end()
    return result


# ====================================================================== #
#  Ventana principal
# ====================================================================== #

class FirmadorWindow(PipelineWindow):

    SECTIONS = [
        ("01", "Documentos",       "Carga los PDFs"),
        ("02", "Firma y posición", "Coloca las firmas"),
        ("03", "Variación",        "Configura la variación"),
        ("04", "Procesar",         "Ejecuta el firmado"),
        ("05", "Resultados",       "Revisa el resultado"),
    ]
    BRAND = "Firmador"
    TAGLINE = "Firma masiva con variación natural"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)

        # ── Datos de firmas ────────────────────────────────────────────
        self._sigs: List[_SigEntry] = []
        self._active_uid: Optional[str] = None
        self._placements: Dict[str, Dict[Optional[str], Tuple[float,float,float,float,float]]] = {}
        self._sig_disabled: Dict[str, Set[str]] = {}
        self._doc_page_sizes: Dict[str, Tuple[float, float]] = {}
        self._updating_sig_list: bool = False

        # ── Datos de documentos ────────────────────────────────────────
        self._active_doc_idx: int = -1
        self.per_doc_mode: bool = False
        self.last_results: List[JobResult] = []
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[SignWorker] = None

        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #

    # ── Propiedad de compatibilidad: toda la lógica interna usa pdf_paths ──
    @property
    def pdf_paths(self) -> List[str]:
        return self._docs_card.paths()

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_preview_section())
        self.stack.addWidget(self._build_variation_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    # ================================================================== #
    # Paso 01: Documentos
    # ================================================================== #

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documentos",
            "Arrastra archivos PDF (o Word) o usa el botón para seleccionarlos.",
        ))

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=True,
            show_thumbnails=True,
            thumb_size=(68, 88),
        )
        self._docs_card.files_changed.connect(self._on_docs_changed)
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

    def _on_docs_changed(self, paths: List[str]) -> None:
        """Sincroniza estado cuando DocumentsCard cambia la lista."""
        if self._active_doc_idx >= len(paths):
            self._active_doc_idx = len(paths) - 1
        self._update_doc_nav()

    # ================================================================== #
    # Paso 02: Firma y posición
    # ================================================================== #

    def _build_preview_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 28, 36, 28)
        outer.setSpacing(12)

        outer.addLayout(make_page_header(
            "Firma y posición",
            "Agrega firmas PNG y arrástralas sobre la página. "
            "Haz click en una firma para seleccionarla y ajustar su posición.",
        ))

        # ── Área principal ─────────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(16)

        # ── Panel izquierdo (340 px fijo) ──────────────────────────────
        left_col = QVBoxLayout()
        left_col.setSpacing(12)
        left_col.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Card: firmas
        sig_card = make_card("Firmas")
        sl = card_layout(sig_card)
        sl.setSpacing(10)

        sig_actions = QHBoxLayout()
        sig_actions.setSpacing(8)
        add_sig_btn = QPushButton("+ Agregar PNG")
        add_sig_btn.setProperty("class", "Primary")
        add_sig_btn.clicked.connect(self._on_add_sig)
        rm_sig_btn = QPushButton("− Quitar")
        rm_sig_btn.setProperty("class", "Ghost")
        rm_sig_btn.clicked.connect(self._on_remove_sig)
        sig_actions.addWidget(add_sig_btn)
        sig_actions.addWidget(rm_sig_btn)
        sig_actions.addStretch()
        sl.addLayout(sig_actions)

        self.sigs_list = QListWidget()
        self.sigs_list.setIconSize(QSize(90, 54))
        self.sigs_list.setSpacing(2)
        self.sigs_list.setMaximumHeight(196)
        self.sigs_list.setMinimumHeight(72)
        self.sigs_list.currentRowChanged.connect(self._on_sig_list_row_changed)
        self.sigs_list.itemChanged.connect(self._on_sig_item_check_changed)
        sl.addWidget(self.sigs_list)

        self._sig_hint = QLabel(
            "Sin firmas — agrega al menos una imagen PNG.\n"
            "☑ = activa para el documento actual"
        )
        self._sig_hint.setProperty("class", "CardHint")
        self._sig_hint.setWordWrap(True)
        sl.addWidget(self._sig_hint)

        left_col.addWidget(sig_card)

        # Card: documento activo
        doc_card = make_card("Documento activo")
        dl = card_layout(doc_card)
        dl.setSpacing(10)

        # Fila de navegación entre documentos
        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        self._prev_doc_btn = QPushButton("◀")
        self._prev_doc_btn.setProperty("class", "IconBtn")
        self._prev_doc_btn.setFixedSize(28, 28)
        self._prev_doc_btn.clicked.connect(
            lambda: self._go_to_doc(self._active_doc_idx - 1)
        )
        self._doc_name_lbl = QLabel("Sin documento")
        self._doc_name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._doc_name_lbl.setStyleSheet("color:#ECEDEE; font-size:12px;")
        self._doc_counter_lbl = QLabel("—")
        self._doc_counter_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._doc_counter_lbl.setStyleSheet(
            "color:#9094A0; font-size:11px; min-width:44px;"
        )
        self._next_doc_btn = QPushButton("▶")
        self._next_doc_btn.setProperty("class", "IconBtn")
        self._next_doc_btn.setFixedSize(28, 28)
        self._next_doc_btn.clicked.connect(
            lambda: self._go_to_doc(self._active_doc_idx + 1)
        )
        nav_row.addWidget(self._prev_doc_btn)
        nav_row.addWidget(self._doc_name_lbl, 1)
        nav_row.addWidget(self._doc_counter_lbl)
        nav_row.addWidget(self._next_doc_btn)
        dl.addLayout(nav_row)

        # Modo de posición
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_lbl = QLabel("Posición:")
        mode_lbl.setStyleSheet("color:#9094A0; font-size:12px;")
        self._pos_mode_combo = QComboBox()
        self._pos_mode_combo.addItems(["Misma para todos", "Por documento"])
        self._pos_mode_combo.currentIndexChanged.connect(
            lambda i: self._set_per_doc_mode(i == 1)
        )
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self._pos_mode_combo, 1)
        dl.addLayout(mode_row)

        # Eliminar
        del_btn = QPushButton("Eliminar del lote")
        del_btn.setProperty("class", "Danger")
        del_btn.clicked.connect(self._on_delete_doc)
        dl.addWidget(del_btn)

        left_col.addWidget(doc_card)
        left_col.addStretch()

        # Contenedor fijo para el panel izquierdo
        left_widget = QWidget()
        left_widget.setFixedWidth(340)
        left_widget.setLayout(left_col)
        body.addWidget(left_widget)

        # ── Canvas + barra de estado ───────────────────────────────────
        canvas_wrap = QWidget()
        canvas_wrap.setObjectName("CanvasWrap")
        cw_layout = QVBoxLayout(canvas_wrap)
        cw_layout.setContentsMargins(0, 0, 0, 0)
        cw_layout.setSpacing(0)

        # Preview (creamos ANTES del status bar para que las lambdas funcionen)
        self.preview = PdfPreviewView()
        self.preview.setObjectName("PdfPreview")
        self.preview.sig_placement_changed.connect(self._on_placement_changed)
        self.preview.item_activated.connect(self._on_item_activated)
        self.preview.pageChanged.connect(self._on_page_changed)
        cw_layout.addWidget(self.preview, 1)

        # Barra de estado (42 px fijos)
        status_bar = self._build_status_bar()
        cw_layout.addWidget(status_bar)

        body.addWidget(canvas_wrap, 1)
        outer.addLayout(body, 1)

        # ── Botones de navegación del wizard ──────────────────────────
        nav_btns = QHBoxLayout()
        back_btn = QPushButton("←  Documentos")
        back_btn.setProperty("class", "Ghost")
        back_btn.clicked.connect(lambda: self._switch_section(0))
        nav_btns.addWidget(back_btn)
        nav_btns.addStretch()
        nxt_btn = QPushButton("Continuar  →")
        nxt_btn.setProperty("class", "Primary")
        nxt_btn.setMinimumWidth(160)
        nxt_btn.clicked.connect(lambda: self._switch_section(2))
        nav_btns.addWidget(nxt_btn)
        outer.addLayout(nav_btns)

        return page

    def _build_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("SigStatusBar")
        bar.setFixedHeight(42)
        bar.setStyleSheet(
            "QFrame#SigStatusBar {"
            "  background-color: #16161A;"
            "  border-top: 1px solid #26262C;"
            "}"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(6)

        # Navegación páginas
        self._sb_prev_pg = QPushButton("◀")
        self._sb_prev_pg.setProperty("class", "IconBtn")
        self._sb_prev_pg.setFixedSize(26, 26)
        self._sb_prev_pg.clicked.connect(
            lambda: self.preview.set_page(self.preview.current_page() - 1)
        )
        self._sb_page_lbl = QLabel("— / —")
        self._sb_page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sb_page_lbl.setStyleSheet(
            "color: #9094A0; font-size: 12px; min-width: 44px;"
        )
        self._sb_next_pg = QPushButton("▶")
        self._sb_next_pg.setProperty("class", "IconBtn")
        self._sb_next_pg.setFixedSize(26, 26)
        self._sb_next_pg.clicked.connect(
            lambda: self.preview.set_page(self.preview.current_page() + 1)
        )
        layout.addWidget(self._sb_prev_pg)
        layout.addWidget(self._sb_page_lbl)
        layout.addWidget(self._sb_next_pg)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet("color: #26262C;")
        layout.addWidget(sep1)

        # Zoom
        for icon, fn in [
            ("−", self.preview.zoom_out),
            ("+", self.preview.zoom_in),
            ("⊡", self.preview.fit_to_view),
        ]:
            btn = QPushButton(icon)
            btn.setProperty("class", "IconBtn")
            btn.setFixedSize(26, 26)
            btn.clicked.connect(fn)
            layout.addWidget(btn)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("color: #26262C;")
        layout.addWidget(sep2)

        # Info de firma activa
        self._sb_sig_info = QLabel("Sin firma seleccionada")
        self._sb_sig_info.setStyleSheet("color: #9094A0; font-size: 12px;")
        self._sb_sig_info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._sb_sig_info, 1)

        return bar

    # ================================================================== #
    # Paso 03: Variación
    # ================================================================== #

    def _build_variation_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Variación natural",
            "Cada firma variará dentro de estos rangos para que ninguna sea idéntica.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        c1 = make_card("Ángulo", "Inclinación aleatoria por página (±°)")
        self.s_angle = SliderWithValue(0.0, 10.0, 2.5, step=0.1, suffix="°")
        card_layout(c1).addWidget(self.s_angle)
        grid.addWidget(c1, 0, 0)

        c2 = make_card("Escala", "Variación de tamaño (±%)")
        self.s_scale = SliderWithValue(0.0, 20.0, 4.0, step=0.5, suffix="%")
        card_layout(c2).addWidget(self.s_scale)
        grid.addWidget(c2, 0, 1)

        c3 = make_card("Desplazamiento horizontal", "Movimiento aleatorio en X (±pt)")
        self.s_dx = SliderWithValue(0.0, 30.0, 4.0, step=0.5, suffix="pt")
        card_layout(c3).addWidget(self.s_dx)
        grid.addWidget(c3, 1, 0)

        c4 = make_card("Desplazamiento vertical", "Movimiento aleatorio en Y (±pt)")
        self.s_dy = SliderWithValue(0.0, 30.0, 4.0, step=0.5, suffix="pt")
        card_layout(c4).addWidget(self.s_dy)
        grid.addWidget(c4, 1, 1)

        c5 = make_card(
            "Opacidad mínima",
            "1.00 = sin variación. Valores menores generan ligera pérdida de tinta.",
        )
        self.s_op = SliderWithValue(0.5, 1.0, 0.92, step=0.01, decimals=2)
        card_layout(c5).addWidget(self.s_op)
        grid.addWidget(c5, 2, 0)

        c6 = make_card(
            "Imperfecciones de trazo",
            "Variaciones sutiles de contraste / brillo / blur.",
        )
        self.s_pressure = QCheckBox("Activar")
        self.s_pressure.setChecked(True)
        card_layout(c6).addWidget(self.s_pressure)
        grid.addWidget(c6, 2, 1)

        c7 = make_card("Semilla aleatoria", "Misma semilla = mismo resultado.")
        seed_row = QHBoxLayout()
        self.s_seed = QSpinBox()
        self.s_seed.setRange(0, 999_999_999)
        self.s_seed.setValue(42)
        self.s_seed.setMaximumWidth(180)
        seed_random = QPushButton("Aleatoria")
        seed_random.setProperty("class", "Ghost")
        seed_random.clicked.connect(
            lambda: self.s_seed.setValue(random.randint(1, 999_999_999))
        )
        seed_row.addWidget(self.s_seed)
        seed_row.addWidget(seed_random)
        seed_row.addStretch()
        card_layout(c7).addLayout(seed_row)
        grid.addWidget(c7, 3, 0, 1, 2)

        outer.addLayout(grid)
        outer.addStretch(1)

        nav = QHBoxLayout()
        back = QPushButton("←  Firma")
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

    # ================================================================== #
    # Paso 04: Procesar
    # ================================================================== #

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Define la carpeta de salida y ejecuta el firmado masivo.",
        ))

        self._proc_step = ProcessStep(
            run_label="Firmar documentos",
            settings_key="firmador/output_dir",
            default_output=str(Path.home() / "PDFlex" / "Firmador"),
        )
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("←  Variación")
        back.setProperty("class", "Ghost")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        outer.addLayout(nav)
        return page

    # ================================================================== #
    # Paso 05: Resultados
    # ================================================================== #

    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultados",
            "Revisa página por página cómo quedó cada documento firmado.",
        ))

        self.results_viewer = ResultsViewer()
        self.results_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self.results_viewer, 1)

        nav = QHBoxLayout()
        back_proc = QPushButton("←  Procesar")
        back_proc.setProperty("class", "Ghost")
        back_proc.clicked.connect(lambda: self._switch_section(3))
        nav.addWidget(back_proc)
        nav.addStretch()
        self._send_btn = SendToToolButton(self.ctx, "firmador")
        nav.addWidget(self._send_btn)
        restart_btn = QPushButton("↺  Nueva sesión")
        restart_btn.setProperty("class", "Primary")
        restart_btn.setMinimumWidth(180)
        restart_btn.clicked.connect(self._reset_session)
        nav.addWidget(restart_btn)
        outer.addLayout(nav)
        return page

    # ================================================================== #
    # Hooks de PipelineWindow
    # ================================================================== #

    def _on_section_activated(self, idx: int) -> None:
        if idx == 1:
            # Auto-cargar el primer doc si aún no hay ninguno cargado
            if self.pdf_paths and self._active_doc_idx < 0:
                self._go_to_doc(0)
            else:
                self._update_doc_nav()
                self._update_sig_list_checks()
                self._update_status_bar()
        elif idx == 3:
            self._refresh_summary()

    def set_inputs(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    # ================================================================== #
    # Paso 02: Firmas — lógica
    # ================================================================== #

    def _on_add_sig(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar firma PNG", "",
            "Imágenes (*.png *.jpg *.jpeg *.webp)",
        )
        if not path:
            return
        try:
            img = Image.open(path).convert("RGBA")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"No se pudo abrir la imagen: {e}")
            return

        uid = _uuid_mod.uuid4().hex[:8]
        color = SIG_COLORS[len(self._sigs) % len(SIG_COLORS)]
        label = f"Firma {len(self._sigs) + 1}"
        pixmap = pil_to_qpixmap(img)
        entry = _SigEntry(uid=uid, path=path, label=label, pixmap=pixmap, color=color)
        self._sigs.append(entry)
        self._sig_disabled[uid] = set()   # activa para todos los docs por defecto

        # Ítem en la lista con franja de color y checkbox
        list_item = QListWidgetItem(label)
        list_item.setIcon(QIcon(_make_sig_icon(pixmap, color)))
        list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        list_item.setCheckState(Qt.CheckState.Checked)
        self.sigs_list.blockSignals(True)
        self.sigs_list.addItem(list_item)
        self.sigs_list.blockSignals(False)

        self._sig_hint.setVisible(False)

        # Agregar al canvas si hay un doc activo
        if self._active_doc_idx >= 0:
            self.preview.add_sig(uid, pixmap, color)
            # Guardar la posición default normalizada como global
            self._capture_placement(uid, None)
            self.preview.set_active_uid(uid)

        self._active_uid = uid
        self.sigs_list.setCurrentRow(len(self._sigs) - 1)
        self._update_status_bar()

    def _on_remove_sig(self) -> None:
        row = self.sigs_list.currentRow()
        if row < 0 or row >= len(self._sigs):
            return

        entry = self._sigs[row]
        uid = entry.uid

        # Quitar del canvas
        if self._active_doc_idx >= 0:
            self.preview.remove_sig(uid)

        # Quitar de datos
        self._placements.pop(uid, None)
        self._sig_disabled.pop(uid, None)
        self._sigs.pop(row)

        # Quitar de la lista
        self.sigs_list.blockSignals(True)
        self.sigs_list.takeItem(row)
        self.sigs_list.blockSignals(False)

        # Re-etiquetar
        for i, e in enumerate(self._sigs):
            e.label = f"Firma {i + 1}"
            self.sigs_list.item(i).setText(f"Firma {i + 1}")

        # Actualizar activo
        if self._active_uid == uid:
            if self._sigs:
                new_row = min(row, len(self._sigs) - 1)
                new_uid = self._sigs[new_row].uid
                self._active_uid = new_uid
                if self._active_doc_idx >= 0:
                    self.preview.set_active_uid(new_uid)
                self.sigs_list.setCurrentRow(new_row)
            else:
                self._active_uid = None

        if not self._sigs:
            self._sig_hint.setVisible(True)

        self._update_status_bar()

    def _on_sig_list_row_changed(self, row: int) -> None:
        """El usuario seleccionó otra firma en la lista."""
        if row < 0 or row >= len(self._sigs):
            return
        uid = self._sigs[row].uid
        self._active_uid = uid
        if self._active_doc_idx >= 0:
            self.preview.set_active_uid(uid)
        self._update_status_bar()

    # ================================================================== #
    # Paso 02: Navegación entre documentos
    # ================================================================== #

    def _go_to_doc(self, new_idx: int) -> None:
        """Cambia el documento activo, guardando placements del anterior."""
        if new_idx < 0 or new_idx >= len(self.pdf_paths):
            return
        if new_idx == self._active_doc_idx:
            return

        # Guardar placements actuales normalizados (w_frac, h_frac)
        if self._active_doc_idx >= 0:
            old_path = self.pdf_paths[self._active_doc_idx]
            for e in self._sigs:
                if not self._sig_is_active(e.uid, old_path):
                    continue
                self._capture_placement(e.uid, None)
                if self.per_doc_mode:
                    self._capture_placement(e.uid, old_path)

        self._active_doc_idx = new_idx
        new_path = self.pdf_paths[new_idx]

        # Cargar el nuevo PDF (load_pdf limpia el canvas)
        self.preview.load_pdf(new_path)

        # Cachear tamaño de página
        pw, ph = self.preview.page_size_pt()
        if pw > 0:
            self._doc_page_sizes[new_path] = (pw, ph)

        # Re-agregar las firmas activas para este documento
        for e in self._sigs:
            if not self._sig_is_active(e.uid, new_path):
                continue
            self.preview.add_sig(e.uid, e.pixmap, e.color)
            saved = self._get_placement(e.uid, new_path)
            if saved:
                # Restaurar con las dimensiones del nuevo PDF
                self._restore_placement_to_canvas(e.uid, saved, new_path)
            else:
                # Primera vez: capturar la posición proporcional default
                self._capture_placement(e.uid, None)

        # Restaurar firma activa
        if self._active_uid and any(
            e.uid == self._active_uid and self._sig_is_active(e.uid, new_path)
            for e in self._sigs
        ):
            self.preview.set_active_uid(self._active_uid)
        elif self._sigs:
            # Buscar la primera firma activa para este doc
            first_active = next(
                (e.uid for e in self._sigs if self._sig_is_active(e.uid, new_path)),
                None,
            )
            self._active_uid = first_active
            if first_active:
                self.preview.set_active_uid(first_active)

        self._update_doc_nav()
        self._update_sig_list_checks()
        self._update_status_bar()

    def _on_delete_doc(self) -> None:
        idx = self._active_doc_idx
        paths = self.pdf_paths
        if idx < 0 or idx >= len(paths):
            return

        doc_path = paths[idx]

        # Limpiar placements y caches per-doc
        for uid in self._placements:
            self._placements[uid].pop(doc_path, None)
        for uid in self._sig_disabled:
            self._sig_disabled[uid].discard(doc_path)
        self._doc_page_sizes.pop(doc_path, None)

        # Quitar de la tarjeta (actualiza la lista internamente)
        self._docs_card.remove_at(idx)

        if not self.pdf_paths:
            self._active_doc_idx = -1
            self.preview.clear_all_sigs()
            self._update_doc_nav()
            self._update_sig_list_checks()
            self._update_status_bar()
        else:
            self._active_doc_idx = -1
            self._go_to_doc(min(idx, len(self.pdf_paths) - 1))

    def _update_doc_nav(self) -> None:
        n = len(self.pdf_paths)
        idx = self._active_doc_idx

        if n == 0 or idx < 0:
            self._doc_name_lbl.setText("Sin documento")
            self._doc_counter_lbl.setText("—")
            self._prev_doc_btn.setEnabled(False)
            self._next_doc_btn.setEnabled(False)
            return

        name = Path(self.pdf_paths[idx]).name
        if len(name) > 24:
            name = name[:21] + "…"
        self._doc_name_lbl.setText(name)
        self._doc_counter_lbl.setText(f"{idx + 1} / {n}")
        self._prev_doc_btn.setEnabled(idx > 0)
        self._next_doc_btn.setEnabled(idx < n - 1)

    # ================================================================== #
    # Paso 02: Señales del preview
    # ================================================================== #

    def _on_placement_changed(self, uid: str) -> None:
        """Guarda la nueva posición cuando el usuario mueve/redimensiona una firma."""
        self._capture_placement(uid, None)
        if self.per_doc_mode and self._active_doc_idx >= 0:
            doc_path = self.pdf_paths[self._active_doc_idx]
            self._capture_placement(uid, doc_path)
        self._update_status_bar()

    # ================================================================== #
    # Helpers de placement normalizado
    # ================================================================== #

    def _capture_placement(self, uid: str, key: Optional[str]) -> None:
        """Lee la posición del item del canvas y la guarda como fracciones del PDF."""
        p = self.preview.placement_of(uid)
        if not p:
            return
        cx_n, cy_n, w_pt, h_pt, angle = p
        pw, ph = self.preview.page_size_pt()
        w_frac = w_pt / pw if pw > 0 else 0.22
        h_frac = h_pt / ph if ph > 0 else 0.10
        if uid not in self._placements:
            self._placements[uid] = {}
        self._placements[uid][key] = (cx_n, cy_n, w_frac, h_frac, angle)

    def _restore_placement_to_canvas(
        self,
        uid: str,
        saved: Tuple[float, float, float, float, float],
        doc_path: Optional[str],
    ) -> None:
        """Restaura un placement almacenado como fracciones al canvas en pts."""
        cx_n, cy_n, w_frac, h_frac, angle = saved

        # Tamaño del nuevo PDF: preferir caché, luego preview
        if doc_path and doc_path in self._doc_page_sizes:
            pw, ph = self._doc_page_sizes[doc_path]
        else:
            pw, ph = self.preview.page_size_pt()

        if pw <= 0 or ph <= 0:
            return

        w_pt = w_frac * pw
        h_pt = h_frac * ph
        self.preview.restore_placement(uid, cx_n, cy_n, w_pt, h_pt, angle)

    # ================================================================== #
    # Helper activo/desactivo por documento
    # ================================================================== #

    def _sig_is_active(self, uid: str, doc_path: str) -> bool:
        """True si la firma está activa (visible) para el documento dado."""
        return doc_path not in self._sig_disabled.get(uid, set())

    # ================================================================== #
    # Checkbox de firmas por documento
    # ================================================================== #

    def _update_sig_list_checks(self) -> None:
        """Actualiza los checkboxes de la lista según el documento activo."""
        self._updating_sig_list = True
        doc_path = (
            self.pdf_paths[self._active_doc_idx]
            if self._active_doc_idx >= 0 else None
        )
        for i, e in enumerate(self._sigs):
            item = self.sigs_list.item(i)
            if item is None:
                continue
            active = doc_path is None or self._sig_is_active(e.uid, doc_path)
            item.setCheckState(
                Qt.CheckState.Checked if active else Qt.CheckState.Unchecked
            )
        self._updating_sig_list = False

    def _on_sig_item_check_changed(self, item: QListWidgetItem) -> None:
        """El usuario marcó/desmarcó una firma → activar/desactivar para el doc actual."""
        if self._updating_sig_list:
            return
        if self._active_doc_idx < 0:
            return
        row = self.sigs_list.row(item)
        if row < 0 or row >= len(self._sigs):
            return

        uid = self._sigs[row].uid
        doc_path = self.pdf_paths[self._active_doc_idx]
        checked = item.checkState() == Qt.CheckState.Checked

        if checked:
            # Activar: quitar del set de desactivadas
            self._sig_disabled.setdefault(uid, set()).discard(doc_path)
            # Agregar al canvas con su posición guardada
            entry = self._sigs[row]
            self.preview.add_sig(uid, entry.pixmap, entry.color)
            saved = self._get_placement(uid, doc_path)
            if saved:
                self._restore_placement_to_canvas(uid, saved, doc_path)
            else:
                self._capture_placement(uid, None)
            self.preview.set_active_uid(uid)
            self._active_uid = uid
            # Actualizar selección en la lista
            self.sigs_list.blockSignals(True)
            self.sigs_list.setCurrentRow(row)
            self.sigs_list.blockSignals(False)
        else:
            # Desactivar: agregar al set
            self._sig_disabled.setdefault(uid, set()).add(doc_path)
            # Guardar posición antes de quitar del canvas
            self._capture_placement(uid, doc_path)
            self.preview.remove_sig(uid)
            # Si era la firma activa, pasar a la siguiente activa
            if self._active_uid == uid:
                next_uid = next(
                    (e.uid for e in self._sigs
                     if e.uid != uid and self._sig_is_active(e.uid, doc_path)),
                    None,
                )
                self._active_uid = next_uid
                if next_uid:
                    self.preview.set_active_uid(next_uid)
        self._update_status_bar()

    def _on_item_activated(self, uid: str) -> None:
        """Sincroniza la selección en la lista cuando el usuario clica una firma."""
        if self._active_uid == uid:
            return
        self._active_uid = uid
        for i, e in enumerate(self._sigs):
            if e.uid == uid:
                self.sigs_list.blockSignals(True)
                self.sigs_list.setCurrentRow(i)
                self.sigs_list.blockSignals(False)
                break
        self._update_status_bar()

    def _on_page_changed(self, cur: int, total: int) -> None:
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        n = self.preview.page_count()
        cur = self.preview.current_page()
        self._sb_page_lbl.setText(f"{cur + 1} / {n}" if n > 0 else "— / —")
        self._sb_prev_pg.setEnabled(cur > 0)
        self._sb_next_pg.setEnabled(n > 1 and cur < n - 1)

        if not self._active_uid:
            self._sb_sig_info.setText("Sin firma seleccionada")
            return
        p = self.preview.placement_of(self._active_uid)
        entry = next((e for e in self._sigs if e.uid == self._active_uid), None)
        if not p or not entry:
            self._sb_sig_info.setText("Sin firma colocada")
            return
        cx_n, cy_n, w_pt, h_pt, angle = p
        r = entry.color.red()
        g = entry.color.green()
        b = entry.color.blue()
        self._sb_sig_info.setText(
            f"<span style='color:rgb({r},{g},{b}); font-size:14px;'>●</span>"
            f"&nbsp;&nbsp;<b>{entry.label}</b>"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;"
            f"x&nbsp;{cx_n*100:.0f}%&nbsp;&nbsp;y&nbsp;{cy_n*100:.0f}%"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;"
            f"{w_pt:.0f}&thinsp;×&thinsp;{h_pt:.0f}&nbsp;pt"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;{angle:+.1f}°"
        )

    # ================================================================== #
    # Paso 02: Modo posición
    # ================================================================== #

    def _set_per_doc_mode(self, per_doc: bool) -> None:
        self.per_doc_mode = per_doc

    def _get_placement(
        self, uid: str, doc_path: Optional[str]
    ) -> Optional[Tuple[float, float, float, float, float]]:
        per = self._placements.get(uid, {})
        if self.per_doc_mode and doc_path and doc_path in per:
            return per[doc_path]
        return per.get(None)

    # ================================================================== #
    # Word → PDF
    # ================================================================== #

    def _handle_word_files(self, paths: List[str]) -> None:
        if not self.ctx.word_converter.is_available():
            QMessageBox.information(
                self, "Microsoft Office requerido",
                "Para convertir archivos Word a PDF se necesita Microsoft Office.\n"
                "Los archivos .doc/.docx han sido omitidos.",
            )
            return
        from PyQt6.QtWidgets import QProgressDialog
        self._conv_dlg = QProgressDialog(
            "Convirtiendo archivos Word a PDF…", None, 0, len(paths), self
        )
        self._conv_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self._conv_dlg.setMinimumDuration(0)
        self._conv_dlg.show()
        worker = WordConvertWorker(self.ctx.word_converter, paths, self._word_tmp)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(
            lambda c, t, m: self._conv_dlg.setValue(c) if self._conv_dlg else None
        )
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.finished.connect(self._on_word_convert_done)
        worker.error.connect(self._on_word_convert_error)
        self._conv_thread = thread
        thread.start()

    def _on_word_convert_done(self, paths: List[str]) -> None:
        if self._conv_dlg:
            self._conv_dlg.close()
            self._conv_dlg = None
        self._conv_thread = None
        self._docs_card.add_paths(paths)

    def _on_word_convert_error(self, msg: str) -> None:
        if self._conv_dlg:
            self._conv_dlg.close()
            self._conv_dlg = None
        self._conv_thread = None
        QMessageBox.warning(self, "Error en conversión Word", msg)

    # ================================================================== #
    # Paso 04: Procesar — lógica
    # ================================================================== #

    def _refresh_summary(self) -> None:
        n = len(self.pdf_paths)
        n_sigs = len(self._sigs)
        mode_txt = "Por documento" if self.per_doc_mode else "Misma para todos"

        # Contar firmas activas por doc
        per_doc_info = ""
        if self._sigs and n > 0:
            counts = []
            for p in self.pdf_paths:
                active_n = sum(
                    1 for e in self._sigs if self._sig_is_active(e.uid, p)
                )
                counts.append(active_n)
            unique = set(counts)
            if len(unique) == 1:
                per_doc_info = f" ({counts[0]} por documento)"
            else:
                per_doc_info = f" (varía: {min(counts)}–{max(counts)} por doc)"

        rows = [
            f"<b>Documentos:</b>&nbsp;&nbsp;{n}",
            f"<b>Firmas configuradas:</b>&nbsp;&nbsp;{n_sigs}{per_doc_info}",
            f"<b>Modo de posición:</b>&nbsp;&nbsp;{mode_txt}",
            f"<b>Variación:</b>&nbsp;&nbsp;"
            f"±{self.s_angle.value():.1f}°&nbsp;&nbsp;·&nbsp;&nbsp;"
            f"±{self.s_scale.value():.1f}%",
        ]
        html = "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        self._proc_step.set_summary_html(html)

    def _validate_ready(self) -> Optional[str]:
        if not self.pdf_paths:
            return "Agrega al menos un PDF."
        if not self._sigs:
            return "Agrega al menos una imagen de firma (Paso 02)."

        missing = [
            e.label for e in self._sigs
            if None not in self._placements.get(e.uid, {})
        ]
        if missing:
            return (
                f"Las siguientes firmas no tienen posición definida:\n"
                f"{', '.join(missing)}\n\n"
                f"Ve al Paso 02 y coloca cada firma sobre el documento."
            )

        docs_sin_firma = [
            Path(p).name for p in self.pdf_paths
            if not any(self._sig_is_active(e.uid, p) for e in self._sigs)
        ]
        if docs_sin_firma and len(docs_sin_firma) == len(self.pdf_paths):
            return (
                "Todos los documentos tienen todas las firmas desactivadas.\n"
                "Activa al menos una firma por documento (☑ en el Paso 02)."
            )

        if not self._proc_step.output_dir():
            return "Define una carpeta de salida."
        return None

    def _build_jobs(self) -> List[SignJob]:
        out_dir = Path(self._proc_step.output_dir())
        out_dir.mkdir(parents=True, exist_ok=True)
        jobs: List[SignJob] = []

        for pdf_path in self.pdf_paths:
            stem = Path(pdf_path).stem
            final_out = str(out_dir / f"{stem}_firmado.pdf")

            # Tamaño de página del PDF para desnormalizar fracciones
            if pdf_path in self._doc_page_sizes:
                page_w_pt, page_h_pt = self._doc_page_sizes[pdf_path]
            else:
                try:
                    _doc = fitz.open(pdf_path)
                    _page = _doc[0]
                    page_w_pt, page_h_pt = _page.rect.width, _page.rect.height
                    _doc.close()
                except Exception:
                    page_w_pt, page_h_pt = 595.0, 842.0

            sig_placements: List[SigPlacement] = []
            for e in self._sigs:
                # Skip si desactivada para este documento
                if not self._sig_is_active(e.uid, pdf_path):
                    continue
                saved = self._get_placement(e.uid, pdf_path)
                if not saved:
                    continue
                cx_n, cy_n, w_frac, h_frac, angle = saved
                sig_placements.append(SigPlacement(
                    signature_path=e.path,
                    base_x_norm=cx_n,
                    base_y_norm=cy_n,
                    base_width_pt=w_frac * page_w_pt,
                    base_height_pt=h_frac * page_h_pt,
                    base_angle=angle,
                ))

            if sig_placements:
                jobs.append(SignJob(
                    pdf_path=pdf_path,
                    output_path=final_out,
                    signatures=sig_placements,
                ))

        return jobs

    def _build_variation_config(self) -> VariationConfig:
        return VariationConfig(
            angle_deg=self.s_angle.value(),
            scale_pct=self.s_scale.value(),
            offset_x=self.s_dx.value(),
            offset_y=self.s_dy.value(),
            opacity_min=self.s_op.value(),
            opacity_max=1.0,
            enable_pressure_jitter=self.s_pressure.isChecked(),
            seed=int(self.s_seed.value()),
        )

    def _on_run(self) -> None:
        err = self._validate_ready()
        if err:
            QMessageBox.warning(self, "Falta información", err)
            return
        if self._worker_thread:
            return

        self.results_viewer.clear_results()
        jobs = self._build_jobs()
        if not jobs:
            QMessageBox.warning(
                self, "Sin trabajos",
                "Ningún documento tiene firma con posición definida.",
            )
            return

        variation = self._build_variation_config()
        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Iniciando…")

        self._worker_thread = QThread(self)
        self._worker = SignWorker(jobs, variation)
        self._worker.moveToThread(self._worker_thread)

        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.doc_started.connect(
            lambda p: self._proc_step.set_progress(
                self._proc_step._prog_bar.value(), f"Procesando: {Path(p).name}"
            )
        )
        self._worker.finished.connect(self._on_all_finished)
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

    def _on_all_finished(self, results: list) -> None:
        self.last_results = list(results)
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Completado")
        self._worker_thread = None
        self._worker = None

        output_paths = [r.output_path for r in self.last_results if r.success and r.output_path]
        self.ctx.tray.add_items(output_paths, "Firmador")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        ok = sum(1 for r in self.last_results if r.success)
        fail = len(self.last_results) - ok
        QMessageBox.information(
            self, "Hecho",
            f"Se procesaron {len(self.last_results)} documentos.\n\n"
            f"Exitosos: {ok}" + (f"\nCon error: {fail}" if fail else ""),
        )
        self.results_viewer.set_results(self.last_results)
        self._switch_section(4)

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
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    # ================================================================== #
    # Reset
    # ================================================================== #

    def _reset_session(self) -> None:
        self.results_viewer.clear_results()
        self.last_results = []
        self._docs_card.clear()
        self._sigs.clear()
        self.sigs_list.clear()
        self._placements.clear()
        self._sig_disabled.clear()
        self._doc_page_sizes.clear()
        self._active_uid = None
        self._active_doc_idx = -1
        self._sig_hint.setVisible(True)
        self._update_doc_nav()
        self._update_sig_list_checks()
        self._update_status_bar()
        self.preview.clear_all_sigs()
        self._proc_step.reset()
        self._switch_section(0)

    # ================================================================== #
    # Drag & drop
    # ================================================================== #

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        self._docs_card.add_paths(paths)
        self._switch_section(0)
