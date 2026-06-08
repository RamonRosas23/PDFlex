"""PdfFullViewDialog — modal inmersivo de visualización PDF para PDFlex.

API:
    dlg = PdfFullViewDialog(parent, results=lista, current_index=0)
    dlg.exec()

`results` debe ser una lista de objetos con atributos:
    output_path: str   — ruta del PDF generado
    success: bool      — si el procesamiento fue exitoso
    error: str         — mensaje de error (si success=False)

Atributos opcionales que se respetan si están presentes:
    user_password / open_password — para PDFs protegidos
    job.open_password             — alternativa al anterior
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import fitz
from PIL import Image
from PyQt6.QtCore import (
    Qt, QSize, QPoint, QPropertyAnimation, QEasingCurve, QTimer,
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QImage, QKeyEvent, QWheelEvent, QPainter, QColor,
)
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from ui.common.icons import set_button_icon
from ui.common.result_ui import ElidedLabel
from ui.styles import COLORS

# ── Constantes ────────────────────────────────────────────────────────────────
ZOOM_LEVELS = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 2.50, 3.00, 4.00]
_FIT_ZOOM_IDX = 3        # índice de zoom=1.00 (base "fit")
_CANVAS_MAX_PX = 2400    # píxeles máximos en el lado largo del canvas
_THUMB_TARGET_PX = 140   # lado largo objetivo de miniaturas en px

_SIDEBAR_W = 120
_TOOLBAR_H = 46
_STRIP_H = 52


def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


# ─────────────────────────────────────────────────────────────────────────────
class PdfFullViewDialog(QDialog):
    """Modal inmersivo de visualización PDF con navegación entre documentos."""

    def __init__(
        self,
        parent: Optional[QWidget],
        results: list,
        current_index: int = 0,
        accent_color: str = "",
    ) -> None:
        super().__init__(parent)
        self._results = list(results)
        self._current_doc_idx = max(0, min(current_index, len(results) - 1))
        self._current_doc: Optional[fitz.Document] = None
        self._current_page: int = 0
        self._zoom_index: int = _FIT_ZOOM_IDX
        self._fit_mode: str = "width"
        self._accent = accent_color or COLORS["accent"]
        self._sidebar_visible: bool = True
        self._sidebar_anim: Optional[QPropertyAnimation] = None
        self._doc_chips: list[QFrame] = []
        self._drag_pos: Optional[QPoint] = None

        self._setup_window()
        self._build()
        QTimer.singleShot(0, lambda: self._load_doc(self._current_doc_idx))

    # ── Window setup ──────────────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        screen = (
            QApplication.screenAt(self.mapToGlobal(QPoint(0, 0)))
            or QApplication.primaryScreen()
        )
        if screen:
            avail = screen.availableGeometry()
            w = int(avail.width() * 0.92)
            h = int(avail.height() * 0.92)
            self.resize(w, h)
            self.move(
                avail.x() + (avail.width() - w) // 2,
                avail.y() + (avail.height() - h) // 2,
            )

        from ui.common.icons import app_qicon
        self.setWindowIcon(app_qicon())

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("FullViewShell")
        shell.setStyleSheet(
            "QFrame#FullViewShell {"
            f"  background-color: {COLORS['surface']};"
            f"  border: 1px solid {COLORS['border_strong']};"
            "  border-radius: 12px;"
            "}"
        )
        outer.addWidget(shell)

        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())
        root.addWidget(self._make_hsep())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar_container = self._build_sidebar()
        body.addWidget(self._sidebar_container)

        self._sidebar_sep = self._make_vsep()
        body.addWidget(self._sidebar_sep)

        body.addWidget(self._build_canvas(), 1)
        root.addLayout(body, 1)

        root.addWidget(self._make_hsep())
        root.addWidget(self._build_doc_strip())

    # ── Toolbar ───────────────────────────────────────────────────────────────

    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("FullViewToolbar")
        bar.setFixedHeight(_TOOLBAR_H)
        bar.setStyleSheet(
            "QFrame#FullViewToolbar {"
            f"  background-color: {COLORS['surface_2']};"
            "  border-top-left-radius: 12px;"
            "  border-top-right-radius: 12px;"
            "  border: none;"
            "}"
        )

        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 0, 10, 0)
        h.setSpacing(4)

        # G1: Toggle sidebar
        self._toggle_btn = QPushButton()
        self._toggle_btn.setProperty("class", "IconBtn")
        self._toggle_btn.setFixedSize(32, 32)
        self._toggle_btn.setToolTip("Mostrar/ocultar miniaturas (panel izquierdo)")
        set_button_icon(self._toggle_btn, "columns", size=15, icon_only=True)
        self._toggle_btn.clicked.connect(self._toggle_sidebar)
        h.addWidget(self._toggle_btn)

        h.addSpacing(2)
        h.addWidget(self._make_tsep())
        h.addSpacing(2)

        # G2: Navegación de documentos
        self._prev_doc_btn = QPushButton()
        self._prev_doc_btn.setProperty("class", "IconBtn")
        self._prev_doc_btn.setFixedSize(26, 26)
        self._prev_doc_btn.setToolTip("Documento anterior (←)")
        set_button_icon(self._prev_doc_btn, "chevron-left", size=13, icon_only=True)
        self._prev_doc_btn.clicked.connect(lambda: self._navigate_doc(-1))
        h.addWidget(self._prev_doc_btn)

        self._doc_nav_lbl = QLabel("Doc 1 / 1")
        self._doc_nav_lbl.setFixedWidth(76)
        self._doc_nav_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._doc_nav_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px;"
        )
        h.addWidget(self._doc_nav_lbl)

        self._next_doc_btn = QPushButton()
        self._next_doc_btn.setProperty("class", "IconBtn")
        self._next_doc_btn.setFixedSize(26, 26)
        self._next_doc_btn.setToolTip("Documento siguiente (→)")
        set_button_icon(self._next_doc_btn, "chevron-right", size=13, icon_only=True)
        self._next_doc_btn.clicked.connect(lambda: self._navigate_doc(1))
        h.addWidget(self._next_doc_btn)

        h.addSpacing(2)
        h.addWidget(self._make_tsep())
        h.addSpacing(2)

        # G3: Nombre del archivo (expanding)
        self._filename_lbl = ElidedLabel("—")
        self._filename_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px;"
        )
        h.addWidget(self._filename_lbl, 1)

        h.addSpacing(2)
        h.addWidget(self._make_tsep())
        h.addSpacing(2)

        # G4: Zoom
        self._zoom_out_btn = QPushButton()
        self._zoom_out_btn.setProperty("class", "IconBtn")
        self._zoom_out_btn.setFixedSize(28, 28)
        self._zoom_out_btn.setToolTip("Reducir zoom (Ctrl+−)")
        set_button_icon(self._zoom_out_btn, "minus", size=13, icon_only=True)
        self._zoom_out_btn.clicked.connect(self._zoom_out)
        h.addWidget(self._zoom_out_btn)

        self._zoom_lbl = QLabel("100%")
        self._zoom_lbl.setFixedWidth(46)
        self._zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px;"
        )
        h.addWidget(self._zoom_lbl)

        self._zoom_in_btn = QPushButton()
        self._zoom_in_btn.setProperty("class", "IconBtn")
        self._zoom_in_btn.setFixedSize(28, 28)
        self._zoom_in_btn.setToolTip("Aumentar zoom (Ctrl+=)")
        set_button_icon(self._zoom_in_btn, "plus", size=13, icon_only=True)
        self._zoom_in_btn.clicked.connect(self._zoom_in)
        h.addWidget(self._zoom_in_btn)

        self._fit_w_btn = QPushButton()
        self._fit_w_btn.setProperty("class", "IconBtn")
        self._fit_w_btn.setFixedSize(28, 28)
        self._fit_w_btn.setToolTip("Ajustar al ancho (Ctrl+0)")
        set_button_icon(self._fit_w_btn, "maximize", size=13, icon_only=True)
        self._fit_w_btn.clicked.connect(self._fit_width)
        h.addWidget(self._fit_w_btn)

        self._fit_p_btn = QPushButton()
        self._fit_p_btn.setProperty("class", "IconBtn")
        self._fit_p_btn.setFixedSize(28, 28)
        self._fit_p_btn.setToolTip("Ajustar página completa (Ctrl+Shift+0)")
        set_button_icon(self._fit_p_btn, "file-text", size=13, icon_only=True)
        self._fit_p_btn.clicked.connect(self._fit_page)
        h.addWidget(self._fit_p_btn)

        h.addSpacing(2)
        h.addWidget(self._make_tsep())
        h.addSpacing(2)

        # G5: Paginador
        _pag_lbl = QLabel("Pág.")
        _pag_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px;"
        )
        h.addWidget(_pag_lbl)

        self._page_spin = QSpinBox()
        self._page_spin.setRange(1, 1)
        self._page_spin.setEnabled(False)
        self._page_spin.setFixedWidth(54)
        self._page_spin.setFixedHeight(28)
        self._page_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._page_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_spin.setStyleSheet(
            f"QSpinBox {{ background: {COLORS['surface_3']}; color: {COLORS['text']}; "
            f"border: 1px solid {COLORS['border_strong']}; border-radius: 5px; "
            f"padding: 1px 4px; font-size: 12px; }}"
            f"QSpinBox:focus {{ border-color: {COLORS['border_focus']}; }}"
        )
        self._page_spin.editingFinished.connect(self._on_page_jump)
        h.addWidget(self._page_spin)

        self._page_total_lbl = QLabel("/ —")
        self._page_total_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px; min-width: 34px;"
        )
        h.addWidget(self._page_total_lbl)

        self._prev_page_btn = QPushButton()
        self._prev_page_btn.setProperty("class", "IconBtn")
        self._prev_page_btn.setFixedSize(26, 26)
        self._prev_page_btn.setToolTip("Página anterior (Re Pág)")
        set_button_icon(self._prev_page_btn, "chevron-left", size=13, icon_only=True)
        self._prev_page_btn.clicked.connect(self._prev_page)
        h.addWidget(self._prev_page_btn)

        self._next_page_btn = QPushButton()
        self._next_page_btn.setProperty("class", "IconBtn")
        self._next_page_btn.setFixedSize(26, 26)
        self._next_page_btn.setToolTip("Página siguiente (Av Pág)")
        set_button_icon(self._next_page_btn, "chevron-right", size=13, icon_only=True)
        self._next_page_btn.clicked.connect(self._next_page)
        h.addWidget(self._next_page_btn)

        h.addSpacing(2)
        h.addWidget(self._make_tsep())
        h.addSpacing(2)

        # G6: Cerrar
        close_btn = QPushButton()
        close_btn.setProperty("class", "IconBtn")
        close_btn.setFixedSize(32, 32)
        close_btn.setToolTip("Cerrar (Esc)")
        set_button_icon(close_btn, "x", size=15, icon_only=True)
        close_btn.clicked.connect(self.reject)
        h.addWidget(close_btn)

        return bar

    # ── Sidebar (page thumbnails) ─────────────────────────────────────────────

    def _build_sidebar(self) -> QFrame:
        container = QFrame()
        container.setObjectName("FullViewSidebar")
        container.setFixedWidth(_SIDEBAR_W)
        container.setStyleSheet(
            "QFrame#FullViewSidebar { border: none; background: transparent; }"
        )

        cv = QVBoxLayout(container)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        self._page_list = QListWidget()
        self._page_list.setObjectName("FullViewPageList")
        self._page_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._page_list.setIconSize(QSize(80, 103))
        self._page_list.setGridSize(QSize(100, 130))
        self._page_list.setFlow(QListWidget.Flow.TopToBottom)
        self._page_list.setWrapping(False)
        self._page_list.setResizeMode(QListWidget.ResizeMode.Fixed)
        self._page_list.setSpacing(4)
        self._page_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._page_list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._page_list.itemSelectionChanged.connect(self._on_thumb_selected)
        cv.addWidget(self._page_list, 1)

        return container

    # ── Canvas ────────────────────────────────────────────────────────────────

    def _build_canvas(self) -> QScrollArea:
        self._scroll = QScrollArea()
        self._scroll.setObjectName("FullViewCanvas")
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setStyleSheet(
            f"QScrollArea#FullViewCanvas {{ background: {COLORS['bg']}; border: none; }}"
            f"QScrollArea#FullViewCanvas > QWidget > QWidget {{ background: {COLORS['bg']}; }}"
        )

        self._canvas = QLabel()
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas.setStyleSheet("background: transparent;")
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._scroll.setWidget(self._canvas)

        return self._scroll

    # ── Doc strip (bottom) ────────────────────────────────────────────────────

    def _build_doc_strip(self) -> QScrollArea:
        self._strip_scroll = QScrollArea()
        self._strip_scroll.setObjectName("FullViewDocStrip")
        self._strip_scroll.setFixedHeight(_STRIP_H)
        self._strip_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._strip_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._strip_scroll.setWidgetResizable(True)
        self._strip_scroll.setStyleSheet(
            "QScrollArea#FullViewDocStrip {"
            f"  background: {COLORS['surface_2']};"
            "  border: none;"
            "  border-bottom-left-radius: 12px;"
            "  border-bottom-right-radius: 12px;"
            "}"
        )

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self._strip_inner = QHBoxLayout(container)
        self._strip_inner.setContentsMargins(10, 6, 10, 6)
        self._strip_inner.setSpacing(6)
        self._strip_inner.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self._doc_chips = []
        for i, result in enumerate(self._results):
            chip = self._make_chip(i, result)
            self._doc_chips.append(chip)
            self._strip_inner.addWidget(chip)
        self._strip_inner.addStretch()

        self._strip_scroll.setWidget(container)
        return self._strip_scroll

    def _make_chip(self, index: int, result) -> QFrame:
        success = getattr(result, "success", False)
        out = getattr(result, "output_path", "") or ""
        name = Path(out).name if out else "(error)"

        chip = QFrame()
        chip.setFixedHeight(36)
        chip.setMinimumWidth(90)
        chip.setMaximumWidth(190)

        if success:
            chip.setCursor(Qt.CursorShape.PointingHandCursor)

        cl = QHBoxLayout(chip)
        cl.setContentsMargins(8, 0, 10, 0)
        cl.setSpacing(6)

        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(
            f"background: {COLORS['success'] if success else COLORS['danger']};"
            "border-radius: 4px; border: none;"
        )
        cl.addWidget(dot)

        name_lbl = QLabel()
        name_lbl.setStyleSheet(
            f"color: {COLORS['text'] if success else COLORS['text_muted']};"
            "font-size: 11px; background: transparent; border: none;"
        )
        metrics = name_lbl.fontMetrics()
        name_lbl.setText(metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, 140))
        name_lbl.setToolTip(name)
        cl.addWidget(name_lbl)

        self._style_chip(chip, active=False, success=success)

        if success:
            chip.mousePressEvent = lambda _e, idx=index: self._load_doc(idx)

        return chip

    def _style_chip(self, chip: QFrame, *, active: bool, success: bool) -> None:
        if active:
            chip.setStyleSheet(
                "QFrame {"
                f"  background: {COLORS['surface_4']};"
                f"  border: 1.5px solid {self._accent};"
                "  border-radius: 8px;"
                "}"
            )
        elif not success:
            chip.setStyleSheet(
                "QFrame {"
                "  background: transparent;"
                f"  border: 1px solid {COLORS['border']};"
                "  border-radius: 8px;"
                "}"
            )
        else:
            chip.setStyleSheet(
                "QFrame {"
                f"  background: {COLORS['surface_3']};"
                f"  border: 1px solid {COLORS['border']};"
                "  border-radius: 8px;"
                "}"
                "QFrame:hover {"
                f"  background: {COLORS['surface_4']};"
                f"  border-color: {COLORS['border_strong']};"
                "}"
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_hsep(self) -> QFrame:
        f = QFrame()
        f.setFixedHeight(1)
        f.setStyleSheet(f"background: {COLORS['border']}; border: none;")
        return f

    def _make_vsep(self) -> QFrame:
        f = QFrame()
        f.setFixedWidth(1)
        f.setStyleSheet(f"background: {COLORS['border']}; border: none;")
        return f

    def _make_tsep(self) -> QFrame:
        """Separador vertical delgado para la toolbar."""
        f = QFrame()
        f.setFixedSize(1, 22)
        f.setStyleSheet(f"background: {COLORS['border_strong']}; border: none;")
        return f

    # ── Document loading ──────────────────────────────────────────────────────

    def _load_doc(self, index: int) -> None:
        if not (0 <= index < len(self._results)):
            return

        result = self._results[index]
        success = getattr(result, "success", False)
        out_path = getattr(result, "output_path", "") or ""

        # Actualizar chips
        for i, chip in enumerate(self._doc_chips):
            r = self._results[i]
            self._style_chip(chip, active=(i == index), success=getattr(r, "success", False))

        self._current_doc_idx = index
        n = len(self._results)
        self._doc_nav_lbl.setText(f"Doc {index + 1} / {n}")
        self._prev_doc_btn.setEnabled(index > 0)
        self._next_doc_btn.setEnabled(index < n - 1)

        self._scroll_chip_visible(index)
        self._close_doc()
        self._current_page = 0
        self._zoom_index = _FIT_ZOOM_IDX
        self._fit_mode = "width"

        self._filename_lbl.setText(Path(out_path).name if out_path else "—")

        if not success or not out_path:
            self._show_canvas_error(getattr(result, "error", "") or "Documento con error")
            return

        try:
            self._current_doc = fitz.open(out_path)
            if self._current_doc.needs_pass:
                pwd = (
                    getattr(result, "user_password", "")
                    or getattr(result, "open_password", "")
                    or getattr(getattr(result, "job", None), "open_password", "")
                )
                if not pwd or not self._current_doc.authenticate(pwd):
                    self._show_canvas_error("El PDF requiere contraseña para abrirse")
                    return
        except Exception as exc:
            self._show_canvas_error(f"No se pudo abrir: {exc}")
            return

        self._load_thumbnails()
        if self._current_doc.page_count > 0:
            self._page_list.blockSignals(True)
            self._page_list.setCurrentRow(0)
            self._page_list.blockSignals(False)
            self._render_page()
        self._sync_controls()

    def _show_canvas_error(self, msg: str) -> None:
        self._close_doc()
        self._page_list.blockSignals(True)
        self._page_list.clear()
        self._page_list.blockSignals(False)
        self._canvas.setPixmap(QPixmap())
        self._canvas.setText(msg)
        self._canvas.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 13px; background: transparent;"
        )
        self._canvas.setFixedSize(500, 140)
        self._sync_controls()

    def _load_thumbnails(self) -> None:
        if self._current_doc is None:
            return
        self._page_list.blockSignals(True)
        try:
            self._page_list.clear()
            for i in range(self._current_doc.page_count):
                dpi = self._thumb_dpi(i)
                pix = self._render_fitz(i, dpi)
                item = QListWidgetItem(QIcon(pix), str(i + 1))
                item.setToolTip(f"Página {i + 1}")
                self._page_list.addItem(item)
        finally:
            self._page_list.blockSignals(False)

    def _close_doc(self) -> None:
        if self._current_doc is not None:
            try:
                self._current_doc.close()
            except Exception:
                pass
            self._current_doc = None

    def _scroll_chip_visible(self, index: int) -> None:
        if 0 <= index < len(self._doc_chips):
            self._strip_scroll.ensureWidgetVisible(self._doc_chips[index])

    # ── Render ────────────────────────────────────────────────────────────────

    def _thumb_dpi(self, page_idx: int) -> float:
        if self._current_doc is None:
            return 12.0
        page = self._current_doc[page_idx]
        long_side = max(1.0, page.rect.width, page.rect.height)
        return max(3.0, min(_THUMB_TARGET_PX * 72.0 / long_side, 30.0))

    def _compute_dpi(self) -> float:
        if self._current_doc is None:
            return 96.0
        if not (0 <= self._current_page < self._current_doc.page_count):
            return 96.0
        page = self._current_doc[self._current_page]
        vp_w = max(200, self._scroll.viewport().width() - 24)
        vp_h = max(200, self._scroll.viewport().height() - 24)
        pw = max(1.0, page.rect.width)
        ph = max(1.0, page.rect.height)
        dpi_w = vp_w / pw * 72.0
        dpi_h = vp_h / ph * 72.0
        base = dpi_w if self._fit_mode == "width" else min(dpi_w, dpi_h)
        min_dpi = max(4.0, base * ZOOM_LEVELS[0])
        max_dpi = min(320.0, _CANVAS_MAX_PX / max(pw, ph) * 72.0)
        return max(min_dpi, min(base * ZOOM_LEVELS[self._zoom_index], max_dpi))

    def _render_fitz(self, page_idx: int, dpi: float) -> QPixmap:
        page = self._current_doc[page_idx]
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pm = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
        return _pil_to_qpixmap(img)

    def _render_page(self) -> None:
        if self._current_doc is None:
            return
        if not (0 <= self._current_page < self._current_doc.page_count):
            return
        dpi = self._compute_dpi()
        pix = self._render_fitz(self._current_page, dpi)
        self._canvas.setStyleSheet("background: transparent;")
        self._canvas.clear()
        self._canvas.setPixmap(pix)
        self._canvas.setFixedSize(pix.size())
        self._zoom_lbl.setText(f"{int(ZOOM_LEVELS[self._zoom_index] * 100)}%")
        self._sync_controls()

    # ── Controls sync ─────────────────────────────────────────────────────────

    def _sync_controls(self) -> None:
        n = self._current_doc.page_count if self._current_doc else 0
        pg = self._current_page

        self._page_spin.blockSignals(True)
        self._page_spin.setRange(1, max(1, n))
        self._page_spin.setValue(pg + 1 if n > 0 else 1)
        self._page_spin.blockSignals(False)
        self._page_spin.setEnabled(n > 1)
        self._page_total_lbl.setText(f"/ {n}" if n > 0 else "/ —")
        self._prev_page_btn.setEnabled(pg > 0)
        self._next_page_btn.setEnabled(n > 1 and pg < n - 1)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate_doc(self, delta: int) -> None:
        target = self._current_doc_idx + delta
        if 0 <= target < len(self._results):
            self._load_doc(target)

    def _prev_page(self) -> None:
        if self._current_doc and self._current_page > 0:
            self._current_page -= 1
            self._page_list.blockSignals(True)
            self._page_list.setCurrentRow(self._current_page)
            self._page_list.blockSignals(False)
            self._render_page()

    def _next_page(self) -> None:
        if self._current_doc and self._current_page < self._current_doc.page_count - 1:
            self._current_page += 1
            self._page_list.blockSignals(True)
            self._page_list.setCurrentRow(self._current_page)
            self._page_list.blockSignals(False)
            self._render_page()

    def _on_page_jump(self) -> None:
        if self._current_doc is None:
            return
        target = max(0, min(self._page_spin.value() - 1, self._current_doc.page_count - 1))
        if target != self._current_page:
            self._current_page = target
            self._page_list.blockSignals(True)
            self._page_list.setCurrentRow(target)
            self._page_list.blockSignals(False)
            self._render_page()

    def _on_thumb_selected(self) -> None:
        if self._current_doc is None:
            return
        row = self._page_list.currentRow()
        if not (0 <= row < self._current_doc.page_count):
            return
        if row == self._current_page:
            return
        self._current_page = row
        self._render_page()

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def _zoom_out(self) -> None:
        self._fit_mode = "manual"
        if self._zoom_index > 0:
            self._zoom_index -= 1
            self._render_page()

    def _zoom_in(self) -> None:
        self._fit_mode = "manual"
        if self._zoom_index < len(ZOOM_LEVELS) - 1:
            self._zoom_index += 1
            self._render_page()

    def _fit_width(self) -> None:
        self._fit_mode = "width"
        self._zoom_index = _FIT_ZOOM_IDX
        self._render_page()

    def _fit_page(self) -> None:
        self._fit_mode = "page"
        self._zoom_index = _FIT_ZOOM_IDX
        self._render_page()

    # ── Sidebar toggle ────────────────────────────────────────────────────────

    def _toggle_sidebar(self) -> None:
        self._sidebar_visible = not self._sidebar_visible
        target_w = _SIDEBAR_W if self._sidebar_visible else 0

        if self._sidebar_anim is not None:
            self._sidebar_anim.stop()

        anim = QPropertyAnimation(self._sidebar_container, b"maximumWidth")
        anim.setDuration(180)
        anim.setStartValue(self._sidebar_container.width())
        anim.setEndValue(target_w)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self._after_sidebar_toggle(target_w))
        self._sidebar_anim = anim
        if not self._sidebar_visible:   # just toggled to hidden
            self._sidebar_sep.setVisible(False)
        self._sidebar_container.setMinimumWidth(0)
        anim.start()

    def _after_sidebar_toggle(self, target_w: int) -> None:
        if target_w == 0:
            self._sidebar_container.setMaximumWidth(0)
            self._sidebar_container.setFixedWidth(0)
        else:
            self._sidebar_container.setMaximumWidth(_SIDEBAR_W)
            self._sidebar_container.setFixedWidth(_SIDEBAR_W)
            self._sidebar_sep.setVisible(True)   # show AFTER expand completes
        if self._current_doc and self._fit_mode != "manual":
            self._render_page()

    # ── Qt events ─────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 160))
        p.end()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        ctrl = Qt.KeyboardModifier.ControlModifier
        mods = event.modifiers()

        if key == Qt.Key.Key_Escape:
            self.reject()
        elif key == Qt.Key.Key_Left and not (mods & ctrl):
            self._navigate_doc(-1)
        elif key == Qt.Key.Key_Right and not (mods & ctrl):
            self._navigate_doc(1)
        elif key == Qt.Key.Key_PageUp:
            self._prev_page()
        elif key == Qt.Key.Key_PageDown:
            self._next_page()
        elif key == Qt.Key.Key_Minus and (mods & ctrl):
            self._zoom_out()
        elif key == Qt.Key.Key_Equal and (mods & ctrl):
            self._zoom_in()
        elif key == Qt.Key.Key_0 and (mods & ctrl):
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self._fit_page()
            else:
                self._fit_width()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self._zoom_in()
            else:
                self._zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._current_doc and self._fit_mode != "manual":
            self._render_page()

    def closeEvent(self, event) -> None:
        self._close_doc()
        super().closeEvent(event)

    # ── Draggable via toolbar ─────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            toolbar = self.findChild(QFrame, "FullViewToolbar")
            if toolbar and toolbar.underMouse():
                self._drag_pos = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._drag_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)
