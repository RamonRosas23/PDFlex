"""Large page preview for the visual organizer."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import fitz
from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QImage, QKeyEvent, QPixmap, QWheelEvent
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from core.page_organizer_engine import PageRef
from ui.common.icons import app_qicon, set_button_icon
from ui.styles import COLORS


ZOOM_LEVELS = [0.35, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 2.50, 3.00, 4.00]
_FIT_ZOOM_IDX = 3
_CANVAS_MAX_PX = 2600


class OrganizerPagePreviewDialog(QDialog):
    """Immersive preview for the current ordered PageRef list."""

    page_action_requested = pyqtSignal(str, str)

    def __init__(
        self,
        parent: Optional[QWidget],
        refs: list[PageRef],
        current_index: int = 0,
        accent_color: str = "",
    ) -> None:
        super().__init__(parent)
        self._refs = list(refs)
        self._current_index = max(0, min(current_index, len(self._refs) - 1))
        self._current_doc: Optional[fitz.Document] = None
        self._current_doc_path: str = ""
        self._zoom_index = _FIT_ZOOM_IDX
        self._fit_mode = "page"
        self._accent = accent_color or COLORS["accent"]

        self._setup_window()
        self._build()
        self._render_current()

    def _setup_window(self) -> None:
        self.setWindowTitle("Vista de pagina")
        self.setModal(True)
        self.setWindowIcon(app_qicon())
        self.setMinimumSize(760, 560)

        screen = (
            QApplication.screenAt(self.mapToGlobal(QPoint(0, 0)))
            or QApplication.primaryScreen()
        )
        if screen:
            avail = screen.availableGeometry()
            self.resize(int(avail.width() * 0.88), int(avail.height() * 0.88))

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("OrganizerPreviewShell")
        shell.setStyleSheet(
            "QFrame#OrganizerPreviewShell {"
            f" background: {COLORS['surface']};"
            f" border: 1px solid {COLORS['border_strong']};"
            " border-radius: 10px;"
            "}"
        )
        outer.addWidget(shell, 1)

        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_toolbar())
        root.addWidget(self._make_separator())
        root.addWidget(self._build_canvas(), 1)

    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("OrganizerPreviewToolbar")
        bar.setFixedHeight(46)
        bar.setStyleSheet(
            "QFrame#OrganizerPreviewToolbar {"
            f" background: {COLORS['surface_2']};"
            " border-top-left-radius: 10px;"
            " border-top-right-radius: 10px;"
            "}"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 0, 10, 0)
        h.setSpacing(5)

        self._prev_btn = QPushButton()
        self._prev_btn.setProperty("class", "IconBtn")
        self._prev_btn.setFixedSize(30, 30)
        self._prev_btn.setToolTip("Hoja anterior")
        set_button_icon(self._prev_btn, "chevron-left", size=14, icon_only=True)
        self._prev_btn.clicked.connect(self._prev_page)
        h.addWidget(self._prev_btn)

        self._page_spin = QSpinBox()
        self._page_spin.setRange(1, max(1, len(self._refs)))
        self._page_spin.setFixedSize(58, 28)
        self._page_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._page_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_spin.setStyleSheet(
            f"QSpinBox {{ background: {COLORS['surface_3']}; color: {COLORS['text']};"
            f" border: 1px solid {COLORS['border_strong']}; border-radius: 5px;"
            " padding: 1px 4px; font-size: 12px; }}"
            f"QSpinBox:focus {{ border-color: {self._accent}; }}"
        )
        self._page_spin.editingFinished.connect(self._on_page_jump)
        h.addWidget(self._page_spin)

        self._total_lbl = QLabel(f"/ {len(self._refs)}")
        self._total_lbl.setMinimumWidth(42)
        self._total_lbl.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        h.addWidget(self._total_lbl)

        self._next_btn = QPushButton()
        self._next_btn.setProperty("class", "IconBtn")
        self._next_btn.setFixedSize(30, 30)
        self._next_btn.setToolTip("Hoja siguiente")
        set_button_icon(self._next_btn, "chevron-right", size=14, icon_only=True)
        self._next_btn.clicked.connect(self._next_page)
        h.addWidget(self._next_btn)

        h.addWidget(self._make_toolbar_separator())

        self._zoom_out_btn = QPushButton()
        self._zoom_out_btn.setProperty("class", "IconBtn")
        self._zoom_out_btn.setFixedSize(30, 30)
        self._zoom_out_btn.setToolTip("Reducir zoom")
        set_button_icon(self._zoom_out_btn, "minus", size=14, icon_only=True)
        self._zoom_out_btn.clicked.connect(self._zoom_out)
        h.addWidget(self._zoom_out_btn)

        self._zoom_lbl = QLabel("100%")
        self._zoom_lbl.setFixedWidth(48)
        self._zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_lbl.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        h.addWidget(self._zoom_lbl)

        self._zoom_in_btn = QPushButton()
        self._zoom_in_btn.setProperty("class", "IconBtn")
        self._zoom_in_btn.setFixedSize(30, 30)
        self._zoom_in_btn.setToolTip("Aumentar zoom")
        set_button_icon(self._zoom_in_btn, "plus", size=14, icon_only=True)
        self._zoom_in_btn.clicked.connect(self._zoom_in)
        h.addWidget(self._zoom_in_btn)

        self._fit_width_btn = QPushButton()
        self._fit_width_btn.setProperty("class", "IconBtn")
        self._fit_width_btn.setFixedSize(30, 30)
        self._fit_width_btn.setToolTip("Ajustar al ancho")
        set_button_icon(self._fit_width_btn, "maximize", size=14, icon_only=True)
        self._fit_width_btn.clicked.connect(self._fit_width)
        h.addWidget(self._fit_width_btn)

        self._fit_page_btn = QPushButton()
        self._fit_page_btn.setProperty("class", "IconBtn")
        self._fit_page_btn.setFixedSize(30, 30)
        self._fit_page_btn.setToolTip("Ajustar pagina completa")
        set_button_icon(self._fit_page_btn, "file-text", size=14, icon_only=True)
        self._fit_page_btn.clicked.connect(self._fit_page)
        h.addWidget(self._fit_page_btn)

        h.addWidget(self._make_toolbar_separator())

        self._rot_left_btn = self._make_action_btn(
            "rotate-ccw",
            "Rotar 90 grados a la izquierda (Shift+R)",
            "rotate_ccw",
        )
        h.addWidget(self._rot_left_btn)

        self._rot_right_btn = self._make_action_btn(
            "rotate-cw",
            "Rotar 90 grados a la derecha (R)",
            "rotate_cw",
        )
        h.addWidget(self._rot_right_btn)

        self._duplicate_btn = self._make_action_btn(
            "copy",
            "Duplicar hoja (Ctrl+D)",
            "duplicate",
        )
        h.addWidget(self._duplicate_btn)

        self._trim_btn = self._make_action_btn(
            "scissors",
            "Recortar fila a esta hoja (T)",
            "trim_lane",
        )
        h.addWidget(self._trim_btn)

        self._delete_btn = self._make_action_btn(
            "trash-2",
            "Eliminar hoja (Del)",
            "delete",
        )
        h.addWidget(self._delete_btn)

        h.addWidget(self._make_toolbar_separator())

        self._meta_lbl = QLabel("")
        self._meta_lbl.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        self._meta_lbl.setMinimumWidth(140)
        h.addWidget(self._meta_lbl, 1)

        close_btn = QPushButton()
        close_btn.setProperty("class", "IconBtn")
        close_btn.setFixedSize(32, 32)
        close_btn.setToolTip("Cerrar")
        set_button_icon(close_btn, "x", size=15, icon_only=True)
        close_btn.clicked.connect(self.reject)
        h.addWidget(close_btn)

        return bar

    def _build_canvas(self) -> QScrollArea:
        self._scroll = QScrollArea()
        self._scroll.setObjectName("OrganizerPreviewCanvas")
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setStyleSheet(
            f"QScrollArea#OrganizerPreviewCanvas {{ background: {COLORS['bg']}; border: none; }}"
        )

        self._canvas = QLabel()
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas.setStyleSheet("background: transparent;")
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._scroll.setWidget(self._canvas)
        return self._scroll

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {COLORS['border']}; border: none;")
        return sep

    def _make_toolbar_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFixedSize(1, 22)
        sep.setStyleSheet(f"background: {COLORS['border_strong']}; border: none;")
        return sep

    def _make_action_btn(self, icon_name: str, tooltip: str, action: str) -> QPushButton:
        btn = QPushButton()
        btn.setProperty("class", "IconBtn")
        btn.setFixedSize(30, 30)
        btn.setToolTip(tooltip)
        set_button_icon(btn, icon_name, size=14, icon_only=True)
        btn.clicked.connect(lambda _, a=action: self._emit_page_action(a))
        return btn

    def _current_ref(self) -> Optional[PageRef]:
        if not (0 <= self._current_index < len(self._refs)):
            return None
        return self._refs[self._current_index]

    def _ensure_doc(self, path: str) -> Optional[fitz.Document]:
        if self._current_doc is not None and self._current_doc_path == path:
            return self._current_doc
        self._close_doc()
        try:
            self._current_doc = fitz.open(path)
            self._current_doc_path = path
        except Exception as exc:
            self._show_error(f"No se pudo abrir: {exc}")
            return None
        return self._current_doc

    def _close_doc(self) -> None:
        if self._current_doc is not None:
            try:
                self._current_doc.close()
            except Exception:
                pass
        self._current_doc = None
        self._current_doc_path = ""

    def _display_size_for(self, page: fitz.Page, rotation_deg: int) -> tuple[float, float]:
        width = max(1.0, page.rect.width)
        height = max(1.0, page.rect.height)
        if rotation_deg % 180:
            return height, width
        return width, height

    def _compute_dpi(self, page: fitz.Page, rotation_deg: int) -> float:
        vp_w = max(220, self._scroll.viewport().width() - 28)
        vp_h = max(220, self._scroll.viewport().height() - 28)
        page_w, page_h = self._display_size_for(page, rotation_deg)
        dpi_w = vp_w / page_w * 72.0
        dpi_h = vp_h / page_h * 72.0
        base = dpi_w if self._fit_mode == "width" else min(dpi_w, dpi_h)
        max_dpi = min(360.0, _CANVAS_MAX_PX / max(page_w, page_h) * 72.0)
        return max(4.0, min(base * ZOOM_LEVELS[self._zoom_index], max_dpi))

    def _render_ref(self, ref: PageRef, dpi: float) -> QPixmap:
        doc = self._ensure_doc(ref.source_path)
        if doc is None:
            return QPixmap()
        if ref.page_index < 0 or ref.page_index >= doc.page_count:
            self._show_error("Pagina fuera de rango.")
            return QPixmap()

        page = doc[ref.page_index]
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        if ref.rotation_deg:
            matrix = matrix.prerotate(ref.rotation_deg)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        qimg = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        )
        return QPixmap.fromImage(qimg.copy())

    def _render_current(self) -> None:
        ref = self._current_ref()
        if ref is None:
            self._show_error("Sin paginas para previsualizar.")
            return
        doc = self._ensure_doc(ref.source_path)
        if doc is None:
            return
        if ref.page_index < 0 or ref.page_index >= doc.page_count:
            self._show_error("Pagina fuera de rango.")
            return

        page = doc[ref.page_index]
        dpi = self._compute_dpi(page, ref.rotation_deg)
        pix = self._render_ref(ref, dpi)
        if pix.isNull():
            return

        self._canvas.setStyleSheet("background: transparent;")
        self._canvas.clear()
        self._canvas.setPixmap(pix)
        self._canvas.setFixedSize(pix.size())
        self._sync_controls(ref)

    def _show_error(self, message: str) -> None:
        self._canvas.clear()
        self._canvas.setText(message)
        self._canvas.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 13px; background: transparent;"
        )
        self._canvas.setFixedSize(520, 150)
        self._sync_controls(self._current_ref())

    def _sync_controls(self, ref: Optional[PageRef]) -> None:
        total = len(self._refs)
        self._page_spin.blockSignals(True)
        self._page_spin.setRange(1, max(1, total))
        self._page_spin.setValue(self._current_index + 1 if total else 1)
        self._page_spin.blockSignals(False)
        self._page_spin.setEnabled(total > 1)
        self._total_lbl.setText(f"/ {total}" if total else "/ -")
        self._prev_btn.setEnabled(self._current_index > 0)
        self._next_btn.setEnabled(self._current_index < total - 1)
        self._zoom_out_btn.setEnabled(self._zoom_index > 0)
        self._zoom_in_btn.setEnabled(self._zoom_index < len(ZOOM_LEVELS) - 1)
        self._zoom_lbl.setText(f"{int(ZOOM_LEVELS[self._zoom_index] * 100)}%")
        for btn in (
            self._rot_left_btn,
            self._rot_right_btn,
            self._duplicate_btn,
            self._trim_btn,
            self._delete_btn,
        ):
            btn.setEnabled(ref is not None)
        if ref is None:
            self._meta_lbl.setText("")
            self._meta_lbl.setToolTip("")
            return
        name = Path(ref.source_path).name
        rot = f" · {ref.rotation_deg}°" if ref.rotation_deg % 360 else ""
        meta = f"{name} · pag {ref.page_index + 1}{rot}"
        self._meta_lbl.setText(self._meta_lbl.fontMetrics().elidedText(
            meta, Qt.TextElideMode.ElideMiddle, 520
        ))
        self._meta_lbl.setToolTip(meta)

    def _go_to_index(self, index: int) -> None:
        if not self._refs:
            return
        index = max(0, min(index, len(self._refs) - 1))
        if index == self._current_index:
            return
        self._current_index = index
        if self._fit_mode != "manual":
            self._zoom_index = _FIT_ZOOM_IDX
        self._render_current()

    def replace_refs(self, refs: list[PageRef], *, current_page_id: str = "") -> None:
        previous_index = self._current_index
        self._refs = list(refs)
        if not self._refs:
            self._current_index = 0
            self._render_current()
            return
        if current_page_id:
            for index, ref in enumerate(self._refs):
                if ref.page_id == current_page_id:
                    self._current_index = index
                    break
            else:
                self._current_index = min(previous_index, len(self._refs) - 1)
        else:
            self._current_index = min(previous_index, len(self._refs) - 1)
        self._render_current()

    def _emit_page_action(self, action: str) -> None:
        ref = self._current_ref()
        if ref is None:
            return
        self.page_action_requested.emit(action, ref.page_id)

    def _prev_page(self) -> None:
        self._go_to_index(self._current_index - 1)

    def _next_page(self) -> None:
        self._go_to_index(self._current_index + 1)

    def _on_page_jump(self) -> None:
        self._go_to_index(self._page_spin.value() - 1)

    def _zoom_out(self) -> None:
        self._fit_mode = "manual"
        if self._zoom_index > 0:
            self._zoom_index -= 1
            self._render_current()

    def _zoom_in(self) -> None:
        self._fit_mode = "manual"
        if self._zoom_index < len(ZOOM_LEVELS) - 1:
            self._zoom_index += 1
            self._render_current()

    def _fit_width(self) -> None:
        self._fit_mode = "width"
        self._zoom_index = _FIT_ZOOM_IDX
        self._render_current()

    def _fit_page(self) -> None:
        self._fit_mode = "page"
        self._zoom_index = _FIT_ZOOM_IDX
        self._render_current()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        mods = event.modifiers()
        ctrl = Qt.KeyboardModifier.ControlModifier
        if key == Qt.Key.Key_Escape:
            self.reject()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            self._prev_page()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_PageDown):
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
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._emit_page_action("delete")
        elif key == Qt.Key.Key_R:
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self._emit_page_action("rotate_ccw")
            else:
                self._emit_page_action("rotate_cw")
        elif key == Qt.Key.Key_D and (mods & ctrl):
            self._emit_page_action("duplicate")
        elif key == Qt.Key.Key_T:
            self._emit_page_action("trim_lane")
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self._zoom_in()
            else:
                self._zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_mode != "manual":
            self._render_current()

    def closeEvent(self, event) -> None:
        self._close_doc()
        super().closeEvent(event)
