"""
Ventana principal del Firmador Masivo - Rediseño profesional.

Mejoras principales:
  - Sidebar con pasos numerados (01, 02, 03...) y mejor tipografía.
  - Headers de página consistentes.
  - Cards con espaciado refinado y jerarquía visual clara.
  - Controles de zoom expuestos en el preview.
  - Drop zone visual cuando no hay PDFs.
  - Validaciones con feedback inline.
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional

from PIL import Image
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread, QObject, QUrl
from PyQt6.QtGui import (
    QPixmap, QDragEnterEvent, QDropEvent, QDesktopServices, QColor, QFont,
)
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QStackedWidget, QFrame,
    QSpinBox, QDoubleSpinBox, QCheckBox, QSlider, QProgressBar,
    QGridLayout, QLineEdit, QSizePolicy, QGraphicsDropShadowEffect, QScrollArea,
)

from core.signature_engine import SignatureEngine, SignJob, SigPlacement, JobResult
from core.update_config import APP_VERSION
from core.variation import VariationConfig
from core.output_naming import unique_output_path_for_source
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.file_dialogs import (
    get_existing_directory,
    get_open_file_name,
    get_open_file_names,
)
from ui.common.icons import set_button_icon
from .pdf_preview import PdfPreviewView, pil_to_qpixmap
from .results_viewer import ResultsViewer


# ====================================================================== #
#  Worker en thread separado
# ====================================================================== #

class SignWorker(QObject):
    progress = pyqtSignal(int, int, str)
    doc_started = pyqtSignal(str)
    doc_finished = pyqtSignal(object)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[SignJob],
                 variation: VariationConfig):
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
#  Helpers de UI
# ====================================================================== #

def make_card(title: Optional[str] = None, hint: Optional[str] = None) -> QFrame:
    card = QFrame()
    card.setProperty("class", "Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(10)
    if title:
        lbl = QLabel(title)
        lbl.setProperty("class", "CardTitle")
        layout.addWidget(lbl)
    if hint:
        h = QLabel(hint)
        h.setProperty("class", "CardHint")
        h.setWordWrap(True)
        layout.addWidget(h)
    return card


def card_layout(card: QFrame) -> QVBoxLayout:
    return card.layout()


def make_page_header(title: str, subtitle: str) -> QVBoxLayout:
    v = QVBoxLayout()
    v.setSpacing(4)
    v.setContentsMargins(0, 0, 0, 0)
    t = QLabel(title)
    t.setObjectName("PageTitle")
    v.addWidget(t)
    s = QLabel(subtitle)
    s.setObjectName("PageSubtitle")
    s.setWordWrap(True)
    v.addWidget(s)
    return v


def make_divider() -> QFrame:
    f = QFrame()
    f.setProperty("class", "Divider")
    f.setFixedHeight(1)
    return f


class SliderWithValue(QWidget):
    """Slider + spinbox alineados horizontalmente, con altura consistente."""
    valueChanged = pyqtSignal(float)

    def __init__(self, minimum: float, maximum: float, value: float,
                 step: float = 0.1, suffix: str = "", decimals: int = 1):
        super().__init__()
        self._min = minimum
        self._max = maximum
        self._step = step

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(int(round(minimum / step)))
        self.slider.setMaximum(int(round(maximum / step)))
        self.slider.setValue(int(round(value / step)))
        self.slider.valueChanged.connect(self._on_slider)
        self.slider.setMinimumHeight(28)

        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setValue(value)
        if suffix:
            self.spin.setSuffix(f" {suffix}")
        self.spin.setFixedWidth(100)
        self.spin.valueChanged.connect(self._on_spin)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight)

        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)

    def _on_slider(self, v: int):
        val = v * self._step
        self.spin.blockSignals(True)
        self.spin.setValue(val)
        self.spin.blockSignals(False)
        self.valueChanged.emit(val)

    def _on_spin(self, v: float):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(v / self._step)))
        self.slider.blockSignals(False)
        self.valueChanged.emit(v)

    def value(self) -> float:
        return self.spin.value()


# ====================================================================== #
#  Ventana principal
# ====================================================================== #

class MainWindow(QMainWindow):

    SECTIONS = [
        ("01", "Documentos",         "Carga los PDFs"),
        ("02", "Firma y posición",   "Coloca la firma"),
        ("03", "Variación",          "Configura la variación"),
        ("04", "Procesar",           "Ejecuta el firmado"),
        ("05", "Resultados",         "Revisa el resultado"),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Firmador Masivo de Documentos")
        self.setMinimumSize(1320, 820)
        self.showMaximized()
        self.setAcceptDrops(True)

        # Estado
        self.pdf_paths: List[str] = []
        self.signature_path: Optional[str] = None
        self.signature_pixmap: Optional[QPixmap] = None
        self.output_folder: str = str(Path.home() / "Documentos firmados")
        self.last_results: List[JobResult] = []
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[SignWorker] = None

        self._build_ui()
        self._switch_section(0)

    # ================================================================== #
    # UI
    # ================================================================== #
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ===== Sidebar =====
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(260)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(0)

        brand = QLabel("Firmador")
        brand.setObjectName("SidebarBrand")
        sb.addWidget(brand)

        tagline = QLabel("Firma masiva con variación natural")
        tagline.setObjectName("SidebarTagline")
        sb.addWidget(tagline)

        section_lbl = QLabel("PASOS")
        section_lbl.setObjectName("SidebarSection")
        sb.addWidget(section_lbl)

        self.section_buttons: List[QPushButton] = []
        for i, (num, name, _) in enumerate(self.SECTIONS):
            btn = QPushButton(f"  {num}    {name}")
            btn.setProperty("class", "SidebarBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, idx=i: self._switch_section(idx))
            sb.addWidget(btn)
            self.section_buttons.append(btn)

        sb.addStretch(1)

        footer = QLabel(f"GRUPO OCMX · v{APP_VERSION}")
        footer.setObjectName("SidebarFooter")
        sb.addWidget(footer)

        root.addWidget(sidebar)

        # ===== Stack =====
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background-color: #0A0A0B;")
        root.addWidget(self.stack, 1)

        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_preview_section())
        self.stack.addWidget(self._build_variation_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    # ------------------ Sección 1: Documentos ------------------
    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documentos",
            "Arrastra archivos PDF al área inferior o usa el botón para seleccionarlos."
        ))

        # Card principal
        card = make_card()
        cl = card_layout(card)
        cl.setSpacing(14)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        add_btn = QPushButton("Agregar PDFs")
        add_btn.setProperty("class", "Primary")
        add_btn.clicked.connect(self._on_add_pdfs)
        clear_btn = QPushButton("Vaciar")
        clear_btn.setProperty("class", "Ghost")
        clear_btn.clicked.connect(self._on_clear_pdfs)
        actions.addWidget(add_btn)
        actions.addWidget(clear_btn)
        actions.addStretch()
        self.docs_count_label = QLabel("0 documentos")
        self.docs_count_label.setProperty("class", "CardHint")
        actions.addWidget(self.docs_count_label)
        cl.addLayout(actions)

        # Stack: drop zone vacía / lista con items
        self.pdf_list = QListWidget()
        self.pdf_list.setMinimumHeight(340)
        cl.addWidget(self.pdf_list, 1)

        outer.addWidget(card, 1)

        # Nav
        nav = QHBoxLayout()
        nav.addStretch()
        nxt = QPushButton("Continuar")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        set_button_icon(nxt, "arrow-right")
        nxt.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(nxt)
        outer.addLayout(nav)

        return page

    # ------------------ Sección 2: Firma & Preview ------------------
    def _build_preview_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Firma y posición",
            "Carga la imagen de firma (PNG transparente) y arrástrala sobre la página de referencia."
        ))

        body = QHBoxLayout()
        body.setSpacing(20)

        # ===== Columna izquierda =====
        left_col = QVBoxLayout()
        left_col.setSpacing(16)

        # Card: cargar firma
        sig_card = make_card("Imagen de firma")
        sl = card_layout(sig_card)
        self.sig_btn = QPushButton("Seleccionar PNG")
        self.sig_btn.setProperty("class", "Primary")
        self.sig_btn.clicked.connect(self._on_load_signature)
        sl.addWidget(self.sig_btn)

        self.sig_preview = QLabel("Sin firma cargada")
        self.sig_preview.setFixedHeight(110)
        self.sig_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sig_preview.setStyleSheet(
            "background: #16161A; border: 1px dashed #33333B; "
            "border-radius: 8px; color: #6B6F7A;"
        )
        sl.addWidget(self.sig_preview)
        left_col.addWidget(sig_card)

        # Card: documento de referencia
        ref_card = make_card("Documento de referencia",
                             "Posicionarás la firma sobre este; los demás documentos usarán "
                             "la misma posición relativa.")
        rl = card_layout(ref_card)
        self.doc_selector = QListWidget()
        self.doc_selector.setMinimumHeight(120)
        self.doc_selector.setMaximumHeight(160)
        self.doc_selector.itemSelectionChanged.connect(self._on_doc_selector_changed)
        rl.addWidget(self.doc_selector)
        left_col.addWidget(ref_card)

        # Card: navegación + zoom
        nav_card = make_card("Navegación")
        nvl = card_layout(nav_card)

        page_nav = QHBoxLayout()
        page_nav.setSpacing(6)
        self.prev_page_btn = QPushButton()
        self.prev_page_btn.setProperty("class", "IconBtn")
        set_button_icon(self.prev_page_btn, "chevron-left", size=15, icon_only=True)
        self.prev_page_btn.clicked.connect(
            lambda: self.preview.set_page(self.preview.current_page() - 1)
        )
        self.next_page_btn = QPushButton()
        self.next_page_btn.setProperty("class", "IconBtn")
        set_button_icon(self.next_page_btn, "chevron-right", size=15, icon_only=True)
        self.next_page_btn.clicked.connect(
            lambda: self.preview.set_page(self.preview.current_page() + 1)
        )
        self.page_label = QLabel("— / —")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setStyleSheet("color: #9094A0;")
        page_nav.addWidget(self.prev_page_btn)
        page_nav.addWidget(self.page_label, 1)
        page_nav.addWidget(self.next_page_btn)
        nvl.addLayout(page_nav)

        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(6)
        z_out = QPushButton()
        z_out.setProperty("class", "IconBtn")
        set_button_icon(z_out, "minus", size=14, icon_only=True)
        z_out.clicked.connect(lambda: self.preview.zoom_out())
        z_in = QPushButton()
        z_in.setProperty("class", "IconBtn")
        set_button_icon(z_in, "plus", size=14, icon_only=True)
        z_in.clicked.connect(lambda: self.preview.zoom_in())
        z_fit = QPushButton("Ajustar")
        z_fit.setProperty("class", "IconBtn")
        set_button_icon(z_fit, "maximize", size=14)
        z_fit.clicked.connect(lambda: self.preview.fit_to_view())
        zoom_row.addWidget(z_out)
        zoom_row.addWidget(z_in)
        zoom_row.addWidget(z_fit, 1)
        nvl.addLayout(zoom_row)
        left_col.addWidget(nav_card)

        # Card: info de colocación
        info_card = make_card("Colocación actual")
        il = card_layout(info_card)
        self.placement_info = QLabel("—")
        self.placement_info.setProperty("class", "Mono")
        self.placement_info.setWordWrap(True)
        il.addWidget(self.placement_info)
        left_col.addWidget(info_card)

        left_widget = QWidget()
        left_widget.setLayout(left_col)

        left_scroll = QScrollArea()
        left_scroll.setObjectName("LeftPanelScroll")
        left_scroll.setWidget(left_widget)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(320)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        body.addWidget(left_scroll)

        # ===== Canvas =====
        canvas_frame = QFrame()
        canvas_frame.setObjectName("PreviewCanvas")
        cf = QVBoxLayout(canvas_frame)
        cf.setContentsMargins(8, 8, 8, 8)
        self.preview = PdfPreviewView()
        self.preview.setObjectName("PdfPreview")
        self.preview.placementChanged.connect(self._update_placement_info)
        self.preview.pageChanged.connect(self._on_preview_page_changed)
        cf.addWidget(self.preview)
        body.addWidget(canvas_frame, 1)

        outer.addLayout(body, 1)

        nav = QHBoxLayout()
        back = QPushButton("Documentos")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(0))
        nav.addWidget(back)
        nav.addStretch()
        nxt = QPushButton("Continuar")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        set_button_icon(nxt, "arrow-right")
        nxt.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(nxt)
        outer.addLayout(nav)

        return page

    # ------------------ Sección 3: Variación ------------------
    def _build_variation_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Variación natural",
            "Cada firma variará dentro de estos rangos para que ninguna sea idéntica. "
            "Los valores son ± respecto a la base."
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Ángulo
        c1 = make_card("Ángulo", "Inclinación aleatoria por página (±°)")
        self.s_angle = SliderWithValue(0.0, 10.0, 2.5, step=0.1, suffix="°")
        card_layout(c1).addWidget(self.s_angle)
        grid.addWidget(c1, 0, 0)

        # Escala
        c2 = make_card("Escala", "Variación de tamaño (±%)")
        self.s_scale = SliderWithValue(0.0, 20.0, 4.0, step=0.5, suffix="%")
        card_layout(c2).addWidget(self.s_scale)
        grid.addWidget(c2, 0, 1)

        # Offset X
        c3 = make_card("Desplazamiento horizontal", "Movimiento aleatorio en X (±pt)")
        self.s_dx = SliderWithValue(0.0, 30.0, 4.0, step=0.5, suffix="pt")
        card_layout(c3).addWidget(self.s_dx)
        grid.addWidget(c3, 1, 0)

        # Offset Y
        c4 = make_card("Desplazamiento vertical", "Movimiento aleatorio en Y (±pt)")
        self.s_dy = SliderWithValue(0.0, 30.0, 4.0, step=0.5, suffix="pt")
        card_layout(c4).addWidget(self.s_dy)
        grid.addWidget(c4, 1, 1)

        # Opacidad
        c5 = make_card(
            "Opacidad mínima",
            "1.00 = sin variación. Valores menores generan ligera pérdida de tinta."
        )
        self.s_op = SliderWithValue(0.5, 1.0, 0.92, step=0.01, decimals=2)
        card_layout(c5).addWidget(self.s_op)
        grid.addWidget(c5, 2, 0)

        # Pressure
        c6 = make_card(
            "Imperfecciones de trazo",
            "Variaciones sutiles de contraste/brillo/blur que simulan la presión del bolígrafo."
        )
        self.s_pressure = QCheckBox("Activar")
        self.s_pressure.setChecked(True)
        card_layout(c6).addWidget(self.s_pressure)
        grid.addWidget(c6, 2, 1)

        # Seed
        c7 = make_card(
            "Semilla aleatoria",
            "Misma semilla = mismo resultado. Cambiarla genera un patrón distinto."
        )
        seed_row = QHBoxLayout()
        self.s_seed = QSpinBox()
        self.s_seed.setRange(0, 999_999_999)
        self.s_seed.setValue(42)
        self.s_seed.setMaximumWidth(180)
        seed_random = QPushButton("Aleatoria")
        seed_random.setProperty("class", "Ghost")
        seed_random.clicked.connect(self._on_random_seed)
        seed_row.addWidget(self.s_seed)
        seed_row.addWidget(seed_random)
        seed_row.addStretch()
        card_layout(c7).addLayout(seed_row)
        grid.addWidget(c7, 3, 0, 1, 2)

        outer.addLayout(grid)
        outer.addStretch(1)

        nav = QHBoxLayout()
        back = QPushButton("Firma")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(back)
        nav.addStretch()
        nxt = QPushButton("Continuar")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        set_button_icon(nxt, "arrow-right")
        nxt.clicked.connect(lambda: self._switch_section(3))
        nav.addWidget(nxt)
        outer.addLayout(nav)

        return page

    # ------------------ Sección 4: Procesar ------------------
    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Define la carpeta de salida y ejecuta el firmado masivo."
        ))

        # Out folder
        out_card = make_card("Carpeta de salida")
        ol = card_layout(out_card)
        h = QHBoxLayout()
        h.setSpacing(8)
        self.out_edit = QLineEdit(self.output_folder)
        browse = QPushButton("Examinar")
        browse.setProperty("class", "Ghost")
        browse.clicked.connect(self._on_browse_output)
        h.addWidget(self.out_edit, 1)
        h.addWidget(browse)
        ol.addLayout(h)
        outer.addWidget(out_card)

        # Summary
        sum_card = make_card("Resumen del trabajo")
        sl = card_layout(sum_card)
        self.summary_label = QLabel("—")
        self.summary_label.setStyleSheet(
            "color: #ECEDEE; line-height: 1.7; font-size: 13px;"
        )
        self.summary_label.setWordWrap(True)
        sl.addWidget(self.summary_label)
        outer.addWidget(sum_card)

        # Progress
        prog_card = make_card("Progreso")
        pl = card_layout(prog_card)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        pl.addWidget(self.progress)
        self.progress_label = QLabel("Listo para iniciar")
        self.progress_label.setProperty("class", "CardHint")
        pl.addWidget(self.progress_label)
        outer.addWidget(prog_card)

        outer.addStretch(1)

        nav = QHBoxLayout()
        back = QPushButton("Variación")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        nav.addStretch()

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setProperty("class", "Danger")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        nav.addWidget(self.cancel_btn)

        self.run_btn = QPushButton("Firmar documentos")
        self.run_btn.setProperty("class", "Primary")
        self.run_btn.setMinimumWidth(200)
        self.run_btn.clicked.connect(self._on_run)
        nav.addWidget(self.run_btn)
        outer.addLayout(nav)

        return page

    # ------------------ Sección 5: Resultados ------------------
    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultados",
            "Revisa página por página cómo quedó cada documento firmado."
        ))

        self.results_viewer = ResultsViewer()
        self.results_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self.results_viewer, 1)

        nav = QHBoxLayout()
        back_proc = QPushButton("Procesar")
        back_proc.setProperty("class", "Ghost")
        set_button_icon(back_proc, "arrow-left")
        back_proc.clicked.connect(lambda: self._switch_section(3))
        nav.addWidget(back_proc)
        nav.addStretch()
        restart_btn = QPushButton("Nueva sesión")
        restart_btn.setProperty("class", "Primary")
        restart_btn.setMinimumWidth(180)
        set_button_icon(restart_btn, "refresh-cw")
        restart_btn.setToolTip("Reinicia desde el paso 1 con documentos y firma limpios")
        restart_btn.clicked.connect(self._reset_session)
        nav.addWidget(restart_btn)
        outer.addLayout(nav)

        return page

    # ================================================================== #
    # Navegación
    # ================================================================== #
    def _switch_section(self, idx: int) -> None:
        for i, btn in enumerate(self.section_buttons):
            btn.setProperty("active", "true" if i == idx else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()
        self.stack.setCurrentIndex(idx)
        if idx == 3:
            self._refresh_summary()

    # ================================================================== #
    # Documentos
    # ================================================================== #
    def _on_add_pdfs(self) -> None:
        files, _ = get_open_file_names(
            self, "Seleccionar PDFs", "", "PDF (*.pdf)"
        )
        if files:
            self._add_pdf_paths(files)

    def _add_pdf_paths(self, paths: List[str]) -> None:
        for p in paths:
            if p.lower().endswith(".pdf") and p not in self.pdf_paths:
                self.pdf_paths.append(p)
                self.pdf_list.addItem(QListWidgetItem(Path(p).name))
        self._refresh_doc_count()
        self._refresh_doc_selector()

    def _on_clear_pdfs(self) -> None:
        self.pdf_paths.clear()
        self.pdf_list.clear()
        self.doc_selector.clear()
        self._refresh_doc_count()

    def _refresh_doc_count(self) -> None:
        n = len(self.pdf_paths)
        self.docs_count_label.setText(f"{n} documento" + ("s" if n != 1 else ""))

    def _refresh_doc_selector(self) -> None:
        self.doc_selector.clear()
        for p in self.pdf_paths:
            self.doc_selector.addItem(QListWidgetItem(Path(p).name))
        if self.pdf_paths:
            self.doc_selector.setCurrentRow(0)

    def _on_doc_selector_changed(self) -> None:
        row = self.doc_selector.currentRow()
        if 0 <= row < len(self.pdf_paths):
            self.preview.load_pdf(self.pdf_paths[row])
            self._update_page_label()
            if self.signature_pixmap is not None and not self.preview.has_signature():
                self.preview.set_signature(self.signature_pixmap)
            self._update_placement_info()

    # ================================================================== #
    # Firma
    # ================================================================== #
    def _on_load_signature(self) -> None:
        path, _ = get_open_file_name(
            self, "Cargar firma", "", "Imágenes (*.png *.jpg *.jpeg *.webp)"
        )
        if not path:
            return
        try:
            img = Image.open(path).convert("RGBA")
        except Exception as e:
            show_warning(self, "Error", f"No se pudo abrir la imagen: {e}")
            return
        self.signature_path = path
        self.signature_pixmap = pil_to_qpixmap(img)

        thumb = self.signature_pixmap.scaledToHeight(
            100, Qt.TransformationMode.SmoothTransformation
        )
        self.sig_preview.setPixmap(thumb)
        self.sig_preview.setText("")

        if self.preview.page_count() > 0:
            self.preview.set_signature(self.signature_pixmap)
            self._update_placement_info()

    # ================================================================== #
    # Preview
    # ================================================================== #
    def _on_preview_page_changed(self, cur: int, total: int) -> None:
        self.page_label.setText(f"{cur + 1} / {total}" if total > 0 else "— / —")

    def _update_page_label(self) -> None:
        if self.preview.page_count() == 0:
            self.page_label.setText("— / —")
        else:
            self.page_label.setText(
                f"{self.preview.current_page() + 1} / {self.preview.page_count()}"
            )

    def _update_placement_info(self) -> None:
        self._update_page_label()
        if not self.preview.has_signature():
            self.placement_info.setText("Sin firma colocada")
            return
        cx, cy = self.preview.signature_center_pdf()
        w, h = self.preview.signature_size_pdf()
        ang = self.preview.signature_angle()
        pw, ph = self.preview.page_size_pt()
        self.placement_info.setText(
            f"Centro     {cx:6.1f}, {cy:6.1f} pt\n"
            f"Tamaño     {w:5.1f} × {h:5.1f} pt\n"
            f"Ángulo     {ang:+5.1f}°\n"
            f"Página     {pw:.0f} × {ph:.0f} pt"
        )

    # ================================================================== #
    # Variación
    # ================================================================== #
    def _on_random_seed(self) -> None:
        import random
        self.s_seed.setValue(random.randint(1, 999_999_999))

    # ================================================================== #
    # Procesar
    # ================================================================== #
    def _on_browse_output(self) -> None:
        folder = get_existing_directory(
            self, "Carpeta de salida", self.out_edit.text()
        )
        if folder:
            self.out_edit.setText(folder)

    def _refresh_summary(self) -> None:
        n = len(self.pdf_paths)
        sig = "Sí" if self.signature_path else "No"
        placed = (self.preview.has_signature() and self.preview.page_count() > 0)
        placed_txt = "Sí" if placed else "No"
        cx_n, cy_n = self.preview.signature_center_normalized() if placed else (0, 0)

        rows = [
            f"<b>Documentos:</b> &nbsp; {n}",
            f"<b>Firma cargada:</b> &nbsp; {sig}",
        ]
        if placed:
            rows.append(
                f"<b>Posición definida:</b> &nbsp; Sí "
                f"<span style='color:#9094A0'>· centro ({cx_n:.2f}, {cy_n:.2f})</span>"
            )
        else:
            rows.append(f"<b>Posición definida:</b> &nbsp; {placed_txt}")
        rows.append(
            f"<b>Variación:</b> &nbsp; "
            f"±{self.s_angle.value():.1f}° &nbsp;·&nbsp; "
            f"±{self.s_scale.value():.1f}% &nbsp;·&nbsp; "
            f"±({self.s_dx.value():.1f}, {self.s_dy.value():.1f}) pt"
        )
        rows.append(f"<b>Semilla:</b> &nbsp; {int(self.s_seed.value())}")

        html = "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.summary_label.setText(html)

    def _validate_ready(self) -> Optional[str]:
        if not self.pdf_paths:
            return "Agrega al menos un PDF."
        if not self.signature_path:
            return "Carga la imagen de la firma."
        if not self.preview.has_signature() or self.preview.page_count() == 0:
            return "Coloca la firma sobre la página de referencia."
        if not self.out_edit.text().strip():
            return "Define una carpeta de salida."
        return None

    def _build_jobs(self) -> List[SignJob]:
        out_dir = Path(self.out_edit.text().strip())
        out_dir.mkdir(parents=True, exist_ok=True)

        cx_n, cy_n = self.preview.signature_center_normalized()
        w_pt, h_pt = self.preview.signature_size_pdf()
        angle = self.preview.signature_angle()

        jobs: List[SignJob] = []
        reserved: set[str] = set()
        add_suffix = add_tool_suffix_enabled()
        for p in self.pdf_paths:
            in_path = Path(p)
            out_path = unique_output_path_for_source(
                out_dir,
                in_path,
                extension=".pdf",
                tool_suffix="firmado",
                add_tool_suffix=add_suffix,
                reserved=reserved,
                fallback="documento",
            )
            jobs.append(SignJob(
                pdf_path=str(in_path),
                output_path=str(out_path),
                signatures=[
                    SigPlacement(
                        signature_path=self.signature_path,
                        base_x_norm=cx_n,
                        base_y_norm=cy_n,
                        base_width_pt=w_pt,
                        base_height_pt=h_pt,
                        base_angle=angle,
                    )
                ],
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
            show_warning(self, "Falta información", err)
            return
        if self._worker_thread is not None:
            return

        # Cierra cualquier PDF abierto en el visor para liberar el handle de archivo
        # antes de intentar sobreescribirlo.
        self.results_viewer.clear_results()

        jobs = self._build_jobs()
        variation = self._build_variation_config()

        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setValue(0)
        self.progress_label.setText("Iniciando…")

        self._worker_thread = QThread(self)
        self._worker = SignWorker(jobs, variation)
        self._worker.moveToThread(self._worker_thread)

        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.doc_started.connect(self._on_doc_started)
        self._worker.doc_finished.connect(self._on_doc_finished)
        self._worker.finished.connect(self._on_all_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._worker_thread.quit)

        self._worker_thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self.progress_label.setText("Cancelando…")

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        pct = int(current / max(1, total) * 100)
        self.progress.setValue(pct)
        self.progress_label.setText(msg)

    def _on_doc_started(self, path: str) -> None:
        self.progress_label.setText(f"Procesando: {Path(path).name}")

    def _on_doc_finished(self, result: JobResult) -> None:
        pass

    def _on_all_finished(self, results: list) -> None:
        self.last_results = list(results)
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setValue(100)
        self.progress_label.setText("Completado")
        if self._worker_thread:
            self._worker_thread.wait(1000)
            self._worker_thread = None
            self._worker = None

        ok = sum(1 for r in self.last_results if r.success)
        fail = len(self.last_results) - ok
        show_success(
            self, "Hecho",
            f"Se procesaron {len(self.last_results)} documentos.\n\n"
            f"Exitosos: {ok}\n"
            + (f"Con error: {fail}" if fail else "")
        )
        self.results_viewer.set_results(self.last_results)
        self._switch_section(4)

    def _on_worker_error(self, msg: str) -> None:
        show_error(self, "Error", msg)
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(1000)
            self._worker_thread = None
            self._worker = None

    def _open_in_explorer(self, path: str) -> None:
        folder = str(Path(path).parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _reset_session(self) -> None:
        """Reinicia toda la sesión: limpia documentos, firma y estado, vuelve al paso 1."""
        # Libera handles de archivos en el visor
        self.results_viewer.clear_results()
        self.last_results = []

        # Limpia documentos
        self.pdf_paths.clear()
        self.pdf_list.clear()
        self.doc_selector.clear()
        self._refresh_doc_count()

        # Limpia firma
        self.signature_path = None
        self.signature_pixmap = None
        self.sig_preview.clear()
        self.sig_preview.setText("Sin firma cargada")
        self.preview.clear_signature()

        # Resetea progreso
        self.progress.setValue(0)
        self.progress_label.setText("Listo para iniciar")
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

        # Vuelve al paso 1
        self._switch_section(0)

    # ================================================================== #
    # Drag & drop
    # ================================================================== #
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        pdfs = [p for p in paths if p.lower().endswith(".pdf")]
        if pdfs:
            self._add_pdf_paths(pdfs)
            self._switch_section(0)
