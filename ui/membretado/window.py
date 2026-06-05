"""MembretadoWindow — pipeline de membretado masivo de PDFs.

Pipeline:
    01 Membrete  →  02 Documentos  →  03 Márgenes  →  04 Procesar  →  05 Resultados
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional

import fitz
from PIL import Image
from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal, QRectF
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QColor, QBrush,
    QDragEnterEvent, QDropEvent, QDesktopServices,
)
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QFrame, QProgressBar,
    QScrollArea,
)

from core.margin_detector import MembreteMargins, detect_margins
from core.membrete_engine import MembreteJob, MembreteEngine, MembreteJobResult
from core.output_paths import make_run_dir
from core.output_naming import unique_output_path_for_source
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.slider import SliderWithValue
from ui.common.tool_scaffold import PipelineWindow
from ui.common.send_to_tool import SendToToolButton
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.documents_step import DocumentsCard
from ui.common.process_step import ProcessStep
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.dialogs import show_error, show_info, show_success, show_warning
from ui.common.file_dialogs import get_open_file_name
from ui.common.icons import set_button_icon


# ====================================================================== #
#  Worker
# ====================================================================== #

class MembreteWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

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
        from PyQt6.QtWidgets import QSizePolicy
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

    SECTIONS = [
        ("01", "Membrete",   "Carga la hoja membretada"),
        ("02", "Documentos", "Carga los PDFs a membretar"),
        ("03", "Márgenes",   "Ajusta los márgenes de seguridad"),
        ("04", "Procesar",   "Ejecuta el membretado"),
        ("05", "Resultados", "Revisa los documentos membretados"),
    ]
    BRAND = "Membretado"
    TAGLINE = "Superpone PDFs sobre hojas membretadas"
    ACCENT_COLOR = "#B87FF5"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)

        self._lh_path: Optional[str] = None
        self._margins = MembreteMargins()
        self.last_results: List[MembreteJobResult] = []
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[MembreteWorker] = None

        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_membrete_section())
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_margins_section())
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
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Hoja membretada",
            "Carga el PDF que contiene tu membrete (encabezado/pie). "
            "Se usará siempre la primera página.",
        ))

        load_card = make_card("Seleccionar membrete")
        ll = card_layout(load_card)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        open_btn = QPushButton("Seleccionar PDF")
        open_btn.setProperty("class", "Primary")
        open_btn.clicked.connect(self._on_open_membrete)
        tray_btn = QPushButton("Cargar desde bandeja")
        tray_btn.setProperty("class", "Ghost")
        tray_btn.clicked.connect(self._on_membrete_from_tray)
        self.ctx.tray.changed.connect(
            lambda: tray_btn.setVisible(self.ctx.tray.count() > 0)
        )
        tray_btn.setVisible(self.ctx.tray.count() > 0)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(tray_btn)
        btn_row.addStretch()
        ll.addLayout(btn_row)
        outer.addWidget(load_card)

        info_card = make_card("Membrete cargado")
        il = card_layout(info_card)
        doc_body = QHBoxLayout()
        doc_body.setSpacing(20)

        self._lh_thumb = QLabel("Sin membrete")
        self._lh_thumb.setFixedSize(100, 130)
        self._lh_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lh_thumb.setStyleSheet(
            "background: #16161A; border: 1px dashed #33333B; "
            "border-radius: 6px; color: #6B6F7A; font-size: 11px;"
        )
        doc_body.addWidget(self._lh_thumb)

        info_col = QVBoxLayout()
        info_col.setSpacing(6)
        self._lh_name_lbl = QLabel("—")
        self._lh_name_lbl.setObjectName("CardTitle")
        self._lh_name_lbl.setWordWrap(True)
        self._lh_pages_lbl = QLabel("")
        self._lh_pages_lbl.setProperty("class", "CardHint")
        self._lh_margins_lbl = QLabel("")
        self._lh_margins_lbl.setProperty("class", "CardHint")
        info_col.addWidget(self._lh_name_lbl)
        info_col.addWidget(self._lh_pages_lbl)
        info_col.addWidget(self._lh_margins_lbl)
        info_col.addStretch()
        doc_body.addLayout(info_col, 1)

        il.addLayout(doc_body)
        outer.addWidget(info_card)
        outer.addStretch(1)

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
            "Carga los PDFs cuyas páginas se pegarán sobre el membrete.",
        ))

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=True,
            show_thumbnails=True,
            thumb_size=(64, 82),
        )
        outer.addWidget(self._docs_card, 1)

        nav = QHBoxLayout()
        back = QPushButton("Membrete")
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
            s = SliderWithValue(0.0, 250.0, default, step=1.0, suffix="pt", decimals=0)
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
        reset_btn = QPushButton("Restablecer detección automática")
        reset_btn.setProperty("class", "Ghost")
        set_button_icon(reset_btn, "refresh-cw")
        reset_btn.clicked.connect(self._on_reset_margins)
        ll.addWidget(reset_btn)
        ll.addStretch()

        # Conectar sliders al preview
        for s in (self._s_top, self._s_bottom, self._s_left, self._s_right):
            s.valueChanged.connect(self._on_margin_slider_changed)

        left_scroll = QScrollArea()
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

        nav = QHBoxLayout()
        back = QPushButton("Documentos")
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

    # ------------------------------------------------------------------ #
    # Paso 04: Procesar (via ProcessStep compartido)
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
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Márgenes")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        outer.addLayout(nav)

        return page

    # ------------------------------------------------------------------ #
    # Paso 05: Resultados
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

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(3))
        nav.addWidget(back)
        nav.addStretch()

        self._send_btn = SendToToolButton(self.ctx, "membretado")
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
    # Hooks de navegación
    # ------------------------------------------------------------------ #

    def _on_section_activated(self, idx: int) -> None:
        if idx == 2:
            self._sync_preview_pixmap()
        elif idx == 3:
            self._refresh_summary()

    # ------------------------------------------------------------------ #
    # API PipelineWindow
    # ------------------------------------------------------------------ #

    def set_inputs(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(1)

    def handle_drop(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)

    # ------------------------------------------------------------------ #
    # Membrete
    # ------------------------------------------------------------------ #

    def _on_open_membrete(self) -> None:
        path, _ = get_open_file_name(
            self, "Seleccionar membrete PDF", "",
            "PDF (*.pdf)",
        )
        if path:
            self._load_membrete(path)

    def _on_membrete_from_tray(self) -> None:
        paths = [p for p in self.ctx.tray.paths() if Path(p).suffix.lower() == ".pdf"]
        if paths:
            self._load_membrete(paths[0])
        else:
            show_info(
                self,
                "Sin PDFs compatibles",
                "La bandeja no contiene un PDF para usar como membrete.",
            )

    def _load_membrete(self, path: str) -> None:
        try:
            doc = fitz.open(path)
            page = doc[0]
            pw = page.rect.width
            ph = page.rect.height

            # Miniatura
            mat = fitz.Matrix(0.4, 0.4)
            pm = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples).convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
            thumb = QPixmap.fromImage(qimg.copy()).scaledToWidth(
                94, Qt.TransformationMode.SmoothTransformation
            )

            # Pixmap de mayor resolución para el preview de márgenes
            mat_prev = fitz.Matrix(1.5, 1.5)
            pm_prev = page.get_pixmap(matrix=mat_prev, alpha=False)
            img_prev = Image.frombytes("RGB", (pm_prev.width, pm_prev.height), pm_prev.samples).convert("RGBA")
            data_prev = img_prev.tobytes("raw", "RGBA")
            qimg_prev = QImage(data_prev, img_prev.width, img_prev.height, QImage.Format.Format_RGBA8888)
            self._lh_preview_pixmap = QPixmap.fromImage(qimg_prev.copy())
            self._lh_page_w_pt = pw
            self._lh_page_h_pt = ph

            doc.close()
        except Exception as e:
            show_warning(self, "Error al abrir membrete", str(e))
            return

        self._lh_path = path
        self._lh_thumb.setPixmap(thumb)
        self._lh_thumb.setStyleSheet(
            "background: #111114; border: 1px solid #26262C; border-radius: 6px;"
        )
        self._lh_name_lbl.setText(Path(path).name)
        self._lh_pages_lbl.setText(f"{self._lh_page_w_pt:.0f} × {self._lh_page_h_pt:.0f} pt")

        # Detección automática de márgenes
        self._margins = detect_margins(path)
        self._lh_margins_lbl.setText(
            f"Márgenes detectados: sup. {self._margins.top_pt:.0f} pt  "
            f"inf. {self._margins.bottom_pt:.0f} pt"
        )
        self._apply_margins_to_sliders(self._margins)

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
    # Márgenes
    # ------------------------------------------------------------------ #

    def _on_margin_slider_changed(self, *_) -> None:
        self._margin_preview.set_margins(
            self._s_top.value(),
            self._s_bottom.value(),
            self._s_left.value(),
            self._s_right.value(),
        )

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
            rows.append(f"<b>Membrete:</b> &nbsp; {Path(self._lh_path).name}")
        rows.append(f"<b>Documentos:</b> &nbsp; {n}")
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
            jobs.append(MembreteJob(pdf_path=str(in_path), output_path=str(out_path)))
        return jobs

    def _on_run(self) -> None:
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

        self._worker_thread = QThread(self)
        self._worker = MembreteWorker(jobs, self._lh_path, margins)
        self._worker.moveToThread(self._worker_thread)

        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._worker_thread.quit)
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
        self._switch_section(4)

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

    # ------------------------------------------------------------------ #
    # Reset
    # ------------------------------------------------------------------ #

    def _reset_session(self) -> None:
        self._results_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []
        self._lh_path = None
        self._lh_preview_pixmap = None
        self._lh_page_w_pt = 0.0
        self._lh_page_h_pt = 0.0
        self._margins = MembreteMargins()
        self._lh_thumb.clear()
        self._lh_thumb.setText("Sin membrete")
        self._lh_thumb.setStyleSheet(
            "background: #16161A; border: 1px dashed #33333B; "
            "border-radius: 6px; color: #6B6F7A; font-size: 11px;"
        )
        self._lh_name_lbl.setText("—")
        self._lh_pages_lbl.setText("")
        self._lh_margins_lbl.setText("")
        self._margin_preview.clear_letterhead()
        self._apply_margins_to_sliders(self._margins)
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
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        self._add_file_paths_smart(paths)

    def _add_file_paths_smart(self, paths: List[str]) -> None:
        if not paths:
            return

        current_idx = self.stack.currentIndex()
        pdfs = [p for p in paths if Path(p).suffix.lower() == ".pdf"]

        if current_idx == 0 and not self._lh_path and pdfs:
            self._load_membrete(pdfs[0])
            remaining = [p for p in paths if p != pdfs[0]]
            if remaining:
                self._docs_card.add_paths(remaining)
                self._switch_section(1)
            return

        self._docs_card.add_paths(paths)
        self._switch_section(1)
