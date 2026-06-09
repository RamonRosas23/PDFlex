"""DocLane — one horizontal page strip per PDF document."""
from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import fitz
from PyQt6.QtCore import Qt, QEvent, QPoint, QRect, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent,
    QFont, QIcon, QKeyEvent, QPainter, QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QPushButton, QVBoxLayout,
    QWidget,
)

from core.page_organizer_engine import PageRef
from ui.common.file_dialogs import get_open_file_names
from ui.common.icons import set_button_icon
from ui.organizador.page_mime import MIME_TYPE, decode_drag, encode_drag
from ui.organizador.thumb_cache import ThumbnailCache, ThumbnailKey, ThumbnailWorker

THUMB_W = 116
THUMB_H = 150
STRIP_HEIGHT = 206
PDF_FILTER = "PDF (*.pdf)"

LANE_COLORS: List[QColor] = [
    QColor(94, 106, 210),   # índigo
    QColor(56, 178, 172),   # teal
    QColor(236, 135, 72),   # naranja
    QColor(168, 85, 247),   # violeta
    QColor(239, 68, 68),    # rojo
    QColor(34, 197, 94),    # verde
    QColor(234, 179, 8),    # amarillo
    QColor(236, 72, 153),   # rosa
]

_COLOR_MOVE = "#14B8A6"
_COLOR_COPY = "#5E6AD2"

# ── Portapapeles global (compartido entre todas las lanes) ────────────────────
_CLIPBOARD: dict = {"refs": [], "is_cut": False}


def _placeholder_pixmap() -> QPixmap:
    pix = QPixmap(THUMB_W, THUMB_H)
    pix.fill(QColor("#26262C"))
    return pix


# ─────────────────────────────────────────────────────────────────────────────
# _PageStrip
# ─────────────────────────────────────────────────────────────────────────────

class _PageStrip(QListWidget):
    """QListWidget horizontal con drag/drop intra- y cross-lane mejorado."""

    # src_id, dst_id, refs, ctrl, target_row (-1 = al final)
    cross_lane_drop_received = pyqtSignal(str, str, list, bool, int)
    before_internal_reorder  = pyqtSignal()   # disparado ANTES de _reorder_to
    pdf_file_dropped          = pyqtSignal(str)
    internal_reorder_done     = pyqtSignal()

    def __init__(self, lane_id: str, parent=None) -> None:
        super().__init__(parent)
        self._lane_id = lane_id
        self.setObjectName("DocLaneStrip")
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(False)
        self.setIconSize(QSize(THUMB_W, THUMB_H))
        self.setGridSize(QSize(THUMB_W + 24, THUMB_H + 28))
        self.setSpacing(4)
        self.setFixedHeight(STRIP_HEIGHT)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)   # usamos el nuestro
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.viewport().setAcceptDrops(True)
        self.model().rowsMoved.connect(lambda *_: self.internal_reorder_done.emit())

        # ── Indicador de posición de drop (línea vertical de 3 px)
        self._drop_indicator = QFrame(self.viewport())
        self._drop_indicator.setFixedWidth(3)
        self._drop_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._drop_indicator.hide()

        # ── Badge MOVER / COPIAR
        self._mode_badge = QLabel(self.viewport())
        self._mode_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mode_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._mode_badge.hide()

        # ── Empty-state hint
        self._empty_hint = QLabel(self.viewport())
        self._empty_hint.setText("Arrastra páginas aquí\no usa  + Agregar  en el encabezado")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setStyleSheet(
            "color: #3A3E4A; font-size: 12px; background: transparent;"
        )
        self._empty_hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._empty_hint.show()
        self.viewport().installEventFilter(self)

    # ── Drag iniciado ────────────────────────────────────────────────────

    def startDrag(self, supported_actions) -> None:
        selected_items = [
            self.item(i)
            for i in range(self.count())
            if self.item(i) and self.item(i).isSelected()
        ]
        selected_refs = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items]
        if not selected_refs:
            return

        mime = encode_drag(self._lane_id, selected_refs)
        drag = QDrag(self)
        drag.setMimeData(mime)

        pix = self._make_drag_pixmap(selected_items)
        if pix:
            drag.setPixmap(pix)
            drag.setHotSpot(QPoint(pix.width() // 2, pix.height() // 2))

        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)

    def _make_drag_pixmap(self, items: list) -> Optional[QPixmap]:
        if not items:
            return None
        icon = items[0].icon()
        if icon.isNull():
            return None
        w, h = THUMB_W // 2, THUMB_H // 2
        base = icon.pixmap(QSize(w, h))
        result = QPixmap(w, h)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(0.88)
        painter.drawPixmap(0, 0, base)
        painter.setOpacity(1.0)
        if len(items) > 1:
            badge_w, badge_h = 34, 20
            bx, by = w - badge_w - 2, h - badge_h - 2
            painter.setBrush(QBrush(QColor(_COLOR_COPY)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRect(bx, by, badge_w, badge_h), 5, 5)
            font = QFont()
            font.setPixelSize(10)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("white"))
            painter.drawText(QRect(bx, by, badge_w, badge_h),
                             Qt.AlignmentFlag.AlignCenter,
                             f"+{len(items)}")
        painter.end()
        return result

    # ── Eventos de drag (como destino) ───────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(MIME_TYPE) or event.mimeData().hasUrls():
            event.acceptProposedAction()
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self._set_highlight(True, copy_mode=ctrl)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(MIME_TYPE) or event.mimeData().hasUrls():
            event.acceptProposedAction()
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self._update_drop_ui(event.position().toPoint(), ctrl)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_highlight(False)
        self._drop_indicator.hide()
        self._mode_badge.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_highlight(False)
        self._drop_indicator.hide()
        self._mode_badge.hide()

        decoded = decode_drag(event.mimeData())
        if decoded is not None:
            src_id, refs = decoded
            x, target_row = self._insertion_for_pos(event.position().toPoint())
            if src_id == self._lane_id:
                self.before_internal_reorder.emit()
                self._reorder_to(refs, target_row)
            else:
                ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                self.cross_lane_drop_received.emit(
                    src_id, self._lane_id, refs, ctrl, target_row
                )
            event.acceptProposedAction()
            return

        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path.lower().endswith(".pdf"):
                    self.pdf_file_dropped.emit(path)
            event.acceptProposedAction()
            return

        event.ignore()

    # ── Helpers visuales de drop ─────────────────────────────────────────

    def _update_drop_ui(self, pos: QPoint, copy_mode: bool) -> None:
        color = _COLOR_COPY if copy_mode else _COLOR_MOVE
        x, _ = self._insertion_for_pos(pos)
        h = self.viewport().height()

        self._drop_indicator.setStyleSheet(
            f"background: {color}; border-radius: 1px;"
        )
        self._drop_indicator.setGeometry(x - 1, 2, 3, h - 4)
        self._drop_indicator.show()
        self._drop_indicator.raise_()

        label = "COPIAR" if copy_mode else "MOVER"
        self._mode_badge.setText(label)
        self._mode_badge.setStyleSheet(f"""
            QLabel {{
                background: {color};
                color: white;
                font-size: 9px;
                font-weight: 700;
                border-radius: 4px;
                padding: 2px 7px;
                letter-spacing: 0.8px;
            }}
        """)
        self._mode_badge.adjustSize()
        bw = self._mode_badge.width()
        bh = self._mode_badge.height()
        bx = max(4, min(x - bw // 2, self.viewport().width() - bw - 4))
        self._mode_badge.move(bx, h - bh - 6)
        self._mode_badge.show()
        self._mode_badge.raise_()

        self._set_highlight(True, copy_mode=copy_mode)

    def _insertion_for_pos(self, pos: QPoint) -> Tuple[int, int]:
        """Devuelve (x_pixel_viewport, row_index) para indicador de drop."""
        n = self.count()
        if n == 0:
            return 8, 0
        for i in range(n):
            rect = self.visualItemRect(self.item(i))
            if not rect.isValid():
                continue
            if pos.x() <= rect.center().x():
                return max(2, rect.left() - 4), i
        last = self.visualItemRect(self.item(n - 1))
        return last.right() + 2, n

    def _set_highlight(self, active: bool, copy_mode: bool = False) -> None:
        # Siempre usamos border: 2px para no cambiar el tamaño del viewport
        if active:
            color = _COLOR_COPY if copy_mode else _COLOR_MOVE
            r, g, b = (94, 106, 210) if copy_mode else (20, 184, 166)
            self.setStyleSheet(
                f"QListWidget#DocLaneStrip {{"
                f"  border: 2px solid {color};"
                f"  border-radius: 4px;"
                f"  background: rgba({r},{g},{b},0.07);"
                f"}}"
            )
        else:
            self.setStyleSheet(
                "QListWidget#DocLaneStrip {"
                "  border: 2px solid #26262C;"   # misma anchura que activo
                "  border-radius: 4px;"
                "}"
            )

    def _reorder_to(self, refs: List[PageRef], target_row: int) -> None:
        page_ids = {r.page_id for r in refs}
        moving_rows = sorted(
            [i for i in range(self.count())
             if self.item(i) and self.item(i).data(Qt.ItemDataRole.UserRole).page_id in page_ids]
        )
        items = []
        adj = target_row
        for row in sorted(moving_rows, reverse=True):
            items.insert(0, self.takeItem(row))
            if row < adj:
                adj -= 1
        for offset, item in enumerate(items):
            self.insertItem(adj + offset, item)
        self.internal_reorder_done.emit()

    def update_empty_state(self, count: int) -> None:
        self._empty_hint.setVisible(count == 0)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.viewport() and event.type() == QEvent.Type.Resize:
            vr = self.viewport().rect()
            m = 12
            self._empty_hint.setGeometry(m, m, vr.width() - m * 2, vr.height() - m * 2)
        return super().eventFilter(obj, event)

    def contextMenuEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        if item is None:
            return
        if item not in self.selectedItems():
            self.clearSelection()
            item.setSelected(True)
        p = self.parent()
        while p is not None:
            if hasattr(p, "_show_page_context_menu"):
                p._show_page_context_menu(event.globalPos())
                return
            p = p.parent()


# ─────────────────────────────────────────────────────────────────────────────
# DocLane
# ─────────────────────────────────────────────────────────────────────────────

class DocLane(QFrame):
    """Header + horizontal page strip para un documento en el organizador."""

    pages_changed            = pyqtSignal(str)
    lane_delete_requested    = pyqtSignal(str)
    reorder_requested        = pyqtSignal(str, int)
    # src_id, dst_id, refs, ctrl, target_row
    cross_lane_drop_received = pyqtSignal(str, str, list, bool, int)

    def __init__(
        self,
        lane_id: str,
        display_name: str,
        color: QColor,
        cache: ThumbnailCache,
        worker: ThumbnailWorker,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._lane_id = lane_id
        self._display_name = display_name
        self._color = color
        self._cache = cache
        self._worker = worker
        self._collapsed = False
        self._siblings_provider: Callable[[], List[Tuple[str, str]]] = lambda: []
        self._before_mutation_cb: Optional[Callable[[], None]] = None
        worker.thumb_ready.connect(self._on_thumb_ready)
        self._build()

    @property
    def lane_id(self) -> str:
        return self._lane_id

    @property
    def display_name(self) -> str:
        return self._display_name

    def set_before_mutation_cb(self, cb: Callable[[], None]) -> None:
        self._before_mutation_cb = cb

    def teardown(self) -> None:
        """Desconecta la señal del worker antes de que Qt destruya este widget.

        Debe llamarse justo antes de deleteLater(). Sin esto, thumb_ready puede
        dispararse después de que el C++ _PageStrip sea destruido, causando
        RuntimeError: wrapped C/C++ object of type _PageStrip has been deleted.
        """
        try:
            self._worker.thumb_ready.disconnect(self._on_thumb_ready)
        except (RuntimeError, TypeError):
            pass  # ya desconectado o nunca conectado

    def _record_before_mutation(self) -> None:
        if self._before_mutation_cb:
            self._before_mutation_cb()

    # ── Build ─────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setProperty("class", "Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = self._build_header()
        layout.addWidget(self._header)

        self._strip_wrap = QFrame()
        sw = QVBoxLayout(self._strip_wrap)
        sw.setContentsMargins(8, 6, 8, 4)
        sw.setSpacing(2)

        self._list = _PageStrip(self._lane_id)
        self._list.internal_reorder_done.connect(
            lambda: self.pages_changed.emit(self._lane_id)
        )
        self._list.before_internal_reorder.connect(self._record_before_mutation)
        self._list.cross_lane_drop_received.connect(self.cross_lane_drop_received)
        self._list.pdf_file_dropped.connect(self.add_pages_from_pdf)
        self._list.installEventFilter(self)
        sw.addWidget(self._list)

        self._shortcut_lbl = QLabel(
            "Del  ·  R rotar  ·  Shift+R rotar ←  ·  "
            "Ctrl+D duplicar  ·  Ctrl+C copiar  ·  Ctrl+X cortar  ·  Ctrl+V pegar  ·  Ctrl+Z deshacer"
        )
        self._shortcut_lbl.setStyleSheet(
            "color: #3A3E4A; font-size: 10px; background: transparent; padding: 0 4px 2px 4px;"
        )
        sw.addWidget(self._shortcut_lbl)

        layout.addWidget(self._strip_wrap)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setFixedHeight(40)
        r, g, b = self._color.red(), self._color.green(), self._color.blue()
        header.setStyleSheet(
            "QFrame { background-color: #1A1A22; border-bottom: 1px solid #26262C; }"
        )
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 8, 0)
        h.setSpacing(0)

        accent = QFrame()
        accent.setFixedWidth(4)
        accent.setStyleSheet(f"background-color: rgb({r},{g},{b});")
        h.addWidget(accent)
        h.addSpacing(8)

        up_btn = QPushButton("↑")
        up_btn.setProperty("class", "IconBtn")
        up_btn.setFixedSize(22, 22)
        up_btn.setToolTip("Mover fila hacia arriba")
        up_btn.clicked.connect(lambda: self.reorder_requested.emit(self._lane_id, -1))
        h.addWidget(up_btn)

        down_btn = QPushButton("↓")
        down_btn.setProperty("class", "IconBtn")
        down_btn.setFixedSize(22, 22)
        down_btn.setToolTip("Mover fila hacia abajo")
        down_btn.clicked.connect(lambda: self.reorder_requested.emit(self._lane_id, +1))
        h.addWidget(down_btn)
        h.addSpacing(8)

        self._name_lbl = QLabel(self._display_name)
        self._name_lbl.setStyleSheet(
            "color: #ECEDEE; font-size: 13px; font-weight: 600; background: transparent;"
        )
        self._name_lbl.setToolTip("Doble clic para renombrar")
        self._name_lbl.mouseDoubleClickEvent = lambda _: self._start_name_edit()
        h.addWidget(self._name_lbl)

        self._name_edit = QLineEdit(self._display_name)
        self._name_edit.setStyleSheet(
            "QLineEdit { background: #26262C; border: 1px solid #5E6AD2;"
            " border-radius: 4px; color: #ECEDEE; font-size: 13px; padding: 2px 6px; }"
        )
        self._name_edit.setMaximumWidth(200)
        self._name_edit.setVisible(False)
        self._name_edit.returnPressed.connect(self._commit_name_edit)
        self._name_edit.editingFinished.connect(self._commit_name_edit)
        h.addWidget(self._name_edit)
        h.addSpacing(10)

        self._count_lbl = QLabel("0 págs")
        self._count_lbl.setStyleSheet(
            "color: #9094A0; font-size: 11px; background: transparent;"
        )
        self._count_lbl.setMinimumWidth(52)
        h.addWidget(self._count_lbl)
        h.addStretch()

        add_btn = QPushButton("+ Agregar")
        add_btn.setProperty("class", "Ghost")
        add_btn.setFixedHeight(26)
        add_btn.setToolTip("Agregar páginas de un PDF")
        add_btn.clicked.connect(self._on_add_pages)
        h.addWidget(add_btn)
        h.addSpacing(4)

        clear_btn = QPushButton()
        clear_btn.setProperty("class", "IconBtn")
        clear_btn.setFixedSize(26, 26)
        clear_btn.setToolTip("Vaciar esta fila")
        set_button_icon(clear_btn, "trash-2", size=13, icon_only=True)
        clear_btn.clicked.connect(self.clear)
        h.addWidget(clear_btn)

        del_btn = QPushButton()
        del_btn.setProperty("class", "IconBtn")
        del_btn.setFixedSize(26, 26)
        del_btn.setToolTip("Eliminar esta fila del organizador")
        set_button_icon(del_btn, "x", size=13, icon_only=True)
        del_btn.clicked.connect(lambda: self.lane_delete_requested.emit(self._lane_id))
        h.addWidget(del_btn)
        h.addSpacing(4)

        self._collapse_btn = QPushButton("▼")
        self._collapse_btn.setProperty("class", "IconBtn")
        self._collapse_btn.setFixedSize(26, 26)
        self._collapse_btn.setToolTip("Colapsar / expandir fila")
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        h.addWidget(self._collapse_btn)

        return header

    # ── API pública ───────────────────────────────────────────────────────

    def set_siblings_provider(self, fn: Callable[[], List[Tuple[str, str]]]) -> None:
        self._siblings_provider = fn

    def add_pages_from_pdf(self, path: str) -> None:
        self._record_before_mutation()
        try:
            doc = fitz.open(path)
            try:
                for idx in range(doc.page_count):
                    page_id = f"{Path(path).stem}-{idx+1}-{uuid.uuid4().hex[:8]}"
                    ref = PageRef(
                        source_path=path,
                        page_index=idx,
                        rotation_deg=0,
                        page_id=page_id,
                    )
                    item = self._make_item(ref)
                    self._list.addItem(item)
                    self._worker.request(
                        self._lane_id, ref.page_id,
                        ref.source_path, ref.page_index, ref.rotation_deg, THUMB_W,
                    )
            finally:
                doc.close()
        except Exception:
            pass
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    def add_page_ref(self, ref: PageRef, at_row: Optional[int] = None) -> None:
        """Agrega un ref. No dispara snapshot — el llamador es responsable."""
        item = self._make_item(ref)
        if at_row is not None and 0 <= at_row <= self._list.count():
            self._list.insertItem(at_row, item)
        else:
            self._list.addItem(item)
        self._worker.request(
            self._lane_id, ref.page_id,
            ref.source_path, ref.page_index, ref.rotation_deg, THUMB_W,
        )
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    def restore_refs(self, refs: List[PageRef]) -> None:
        """Restaura desde snapshot — no dispara mutation callback ni snapshot."""
        self._list.clear()
        for ref in refs:
            item = self._make_item(ref)
            self._list.addItem(item)
            self._worker.request(
                self._lane_id, ref.page_id,
                ref.source_path, ref.page_index, ref.rotation_deg, THUMB_W,
            )
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    def page_refs(self) -> List[PageRef]:
        return [
            self._list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._list.count())
        ]

    def selected_refs(self) -> List[PageRef]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._list.selectedItems()
        ]

    def count(self) -> int:
        return self._list.count()

    def clear(self) -> None:
        self._record_before_mutation()
        self._list.clear()
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    def remove_by_page_ids(self, page_ids: set, _record: bool = False) -> None:
        if _record:
            self._record_before_mutation()
        rows = sorted(
            [i for i in range(self._list.count())
             if self._list.item(i).data(Qt.ItemDataRole.UserRole).page_id in page_ids],
            reverse=True,
        )
        for row in rows:
            self._list.takeItem(row)
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    def rotate_selected(self, delta: int) -> None:
        self._record_before_mutation()
        for item in self._list.selectedItems():
            ref = item.data(Qt.ItemDataRole.UserRole)
            updated = replace(ref, rotation_deg=(ref.rotation_deg + delta) % 360)
            item.setData(Qt.ItemDataRole.UserRole, updated)
            item.setText(self._label_for(updated))
            item.setToolTip(
                f"{Path(updated.source_path).name}\nPágina {updated.page_index + 1}"
                + (f"\nRot {updated.rotation_deg}°" if updated.rotation_deg else "")
            )
            key = ThumbnailKey(
                updated.source_path, updated.page_index, updated.rotation_deg, THUMB_W
            )
            cached = self._cache.get(key)
            if cached:
                item.setIcon(QIcon(cached))
            else:
                item.setIcon(QIcon(_placeholder_pixmap()))
                self._worker.request(
                    self._lane_id, updated.page_id,
                    updated.source_path, updated.page_index, updated.rotation_deg, THUMB_W,
                )
        self.pages_changed.emit(self._lane_id)

    def duplicate_selected(self) -> None:
        selected = self._list.selectedItems()
        if not selected:
            return
        self._record_before_mutation()
        last_row = max(self._list.row(item) for item in selected)
        clones: List[PageRef] = []
        for item in selected:
            ref = item.data(Qt.ItemDataRole.UserRole)
            stem = Path(ref.source_path).stem
            new_ref = replace(ref, page_id=f"{stem}-{ref.page_index+1}-{uuid.uuid4().hex[:8]}")
            clones.append(new_ref)
        new_items = []
        for offset, ref in enumerate(clones):
            new_item = self._make_item(ref)
            self._list.insertItem(last_row + 1 + offset, new_item)
            self._worker.request(
                self._lane_id, ref.page_id,
                ref.source_path, ref.page_index, ref.rotation_deg, THUMB_W,
            )
            new_items.append(self._list.item(last_row + 1 + offset))
        self._update_count()
        self.pages_changed.emit(self._lane_id)
        self._flash_items(new_items, "paste")

    # ── Portapapeles ─────────────────────────────────────────────────────

    def _clipboard_copy(self) -> None:
        refs = self.selected_refs()
        if not refs:
            return
        _CLIPBOARD["refs"] = refs
        _CLIPBOARD["is_cut"] = False
        self._flash_items(self._list.selectedItems(), "copy")

    def _clipboard_cut(self) -> None:
        refs = self.selected_refs()
        if not refs:
            return
        _CLIPBOARD["refs"] = refs
        _CLIPBOARD["is_cut"] = True
        self._flash_items(self._list.selectedItems(), "cut")
        QTimer.singleShot(300, self._remove_selected)

    def _clipboard_paste(self) -> None:
        refs: List[PageRef] = _CLIPBOARD.get("refs", [])
        if not refs:
            return
        self._record_before_mutation()
        selected = self._list.selectedItems()
        insert_at = (
            max(self._list.row(item) for item in selected) + 1
            if selected else self._list.count()
        )
        pasted_items = []
        for i, ref in enumerate(refs):
            stem = Path(ref.source_path).stem
            new_ref = replace(
                ref,
                page_id=f"{stem}-p{ref.page_index+1}-{uuid.uuid4().hex[:8]}"
            )
            item = self._make_item(new_ref)
            self._list.insertItem(insert_at + i, item)
            self._worker.request(
                self._lane_id, new_ref.page_id,
                new_ref.source_path, new_ref.page_index, new_ref.rotation_deg, THUMB_W,
            )
            real = self._list.item(insert_at + i)
            if real:
                pasted_items.append(real)
        self._update_count()
        self.pages_changed.emit(self._lane_id)
        if pasted_items:
            self._flash_items(pasted_items, "paste")
            # Seleccionar items pegados
            self._list.clearSelection()
            for item in pasted_items:
                item.setSelected(True)

    def _flash_items(self, items: list, mode: str) -> None:
        """Flash de color para retroalimentación visual de operaciones."""
        palette = {
            "paste": QColor(94, 106, 210, 80),
            "copy":  QColor(20, 184, 166, 80),
            "cut":   QColor(239, 68, 68, 80),
        }
        color = palette.get(mode, QColor(255, 255, 255, 60))
        for item in items:
            item.setBackground(QBrush(color))

        def _clear():
            for item in items:
                try:
                    if item.listWidget():
                        item.setBackground(QBrush(Qt.GlobalColor.transparent))
                except RuntimeError:
                    pass

        QTimer.singleShot(550, _clear)

    # ── Teclas (event filter sobre _list) ─────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        if obj is self._list and event.type() == QEvent.Type.KeyPress:
            if isinstance(event, QKeyEvent):
                key  = event.key()
                mods = event.modifiers()
                ctrl  = bool(mods & Qt.KeyboardModifier.ControlModifier)
                shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

                if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and not ctrl:
                    self._remove_selected()
                    return True
                if key == Qt.Key.Key_A and ctrl:
                    self._list.selectAll()
                    return True
                if key == Qt.Key.Key_D and ctrl:
                    self.duplicate_selected()
                    return True
                if key == Qt.Key.Key_C and ctrl:
                    self._clipboard_copy()
                    return True
                if key == Qt.Key.Key_X and ctrl:
                    self._clipboard_cut()
                    return True
                if key == Qt.Key.Key_V and ctrl:
                    self._clipboard_paste()
                    return True
                if key == Qt.Key.Key_Z and ctrl:
                    self._trigger_undo()
                    return True
                if key == Qt.Key.Key_R and not ctrl:
                    self.rotate_selected(-90 if shift else 90)
                    return True
        return super().eventFilter(obj, event)

    def _trigger_undo(self) -> None:
        p = self.parent()
        while p is not None:
            if hasattr(p, "undo"):
                p.undo()
                return
            p = p.parent()

    # ── Context menu ──────────────────────────────────────────────────────

    def _show_page_context_menu(self, global_pos) -> None:
        selected = self.selected_refs()
        if not selected:
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#1E1E26; border:1px solid #32323C; border-radius:6px;"
            " padding:4px 0; color:#ECEDEE; font-size:12px; }"
            "QMenu::item { padding:6px 20px 6px 14px; border-radius:4px; margin:1px 4px; }"
            "QMenu::item:selected { background:#2E2E3A; }"
            "QMenu::item:disabled { color:#5A5A6A; }"
            "QMenu::separator { height:1px; background:#32323C; margin:3px 8px; }"
        )

        rot_cw  = menu.addAction("Rotar 90° →  (R)")
        rot_ccw = menu.addAction("Rotar 90° ←  (Shift+R)")
        menu.addSeparator()

        dup_act   = menu.addAction("Duplicar  (Ctrl+D)")
        copy_act  = menu.addAction("Copiar  (Ctrl+C)")
        cut_act   = menu.addAction("Cortar  (Ctrl+X)")
        has_cb    = bool(_CLIPBOARD.get("refs"))
        paste_act = menu.addAction("Pegar  (Ctrl+V)")
        paste_act.setEnabled(has_cb)

        menu.addSeparator()

        siblings = self._siblings_provider()
        if siblings:
            move_menu = menu.addMenu("Mover a…")
            copy_menu = menu.addMenu("Copiar a…")
            move_menu.setStyleSheet(menu.styleSheet())
            copy_menu.setStyleSheet(menu.styleSheet())
            for sib_id, sib_name in siblings:
                move_menu.addAction(sib_name).setData(("move", sib_id))
                copy_menu.addAction(sib_name).setData(("copy", sib_id))

        menu.addSeparator()
        del_act = menu.addAction("Eliminar  (Del)")

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen == rot_cw:
            self.rotate_selected(90)
        elif chosen == rot_ccw:
            self.rotate_selected(-90)
        elif chosen == dup_act:
            self.duplicate_selected()
        elif chosen == copy_act:
            self._clipboard_copy()
        elif chosen == cut_act:
            self._clipboard_cut()
        elif chosen == paste_act:
            self._clipboard_paste()
        elif chosen == del_act:
            self._remove_selected()
        elif chosen.data() is not None:
            action_type, target_lane_id = chosen.data()
            ctrl_held = (action_type == "copy")
            # LaneContainer maneja inserción Y eliminación vía _on_cross_lane_drop
            self.cross_lane_drop_received.emit(
                self._lane_id, target_lane_id, selected, ctrl_held, -1
            )

    # ── Helpers internos ─────────────────────────────────────────────────

    def _make_item(self, ref: PageRef) -> QListWidgetItem:
        item = QListWidgetItem(QIcon(_placeholder_pixmap()), self._label_for(ref))
        item.setData(Qt.ItemDataRole.UserRole, ref)
        item.setSizeHint(QSize(THUMB_W + 24, THUMB_H + 28))
        item.setToolTip(
            f"{Path(ref.source_path).name}\nPágina {ref.page_index + 1}"
            + (f"\nRot {ref.rotation_deg}°" if ref.rotation_deg else "")
        )
        return item

    @staticmethod
    def _label_for(ref: PageRef) -> str:
        rot = f" ↺{ref.rotation_deg}°" if ref.rotation_deg % 360 else ""
        return f"Pág {ref.page_index + 1}{rot}"

    def _on_thumb_ready(self, lane_id: str, page_id: str, qimage: object) -> None:
        if lane_id != self._lane_id:
            return
        # Convert QImage → QPixmap in GUI thread (QPixmap cannot be created in worker threads)
        try:
            pix = QPixmap.fromImage(qimage)
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole).page_id == page_id:
                    item.setIcon(QIcon(pix))
                    break
        except RuntimeError:
            # El C++ _PageStrip fue destruido antes de que llegara la miniatura.
            # Sucede cuando deleteLater() corre antes del teardown() (race condition
            # entre el hilo del worker y el event loop). Se ignora con seguridad.
            pass

    def _remove_selected(self) -> None:
        self._record_before_mutation()
        rows = sorted(
            {self._list.row(item) for item in self._list.selectedItems()},
            reverse=True,
        )
        for row in rows:
            self._list.takeItem(row)
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    def _update_count(self) -> None:
        n = self._list.count()
        self._count_lbl.setText(f"{n} pág" + ("s" if n != 1 else ""))
        self._list.update_empty_state(n)

    def _on_add_pages(self) -> None:
        files, _ = get_open_file_names(self.window(), "Agregar PDFs", "", PDF_FILTER)
        for path in files:
            self.add_pages_from_pdf(path)

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self._strip_wrap.setVisible(not self._collapsed)
        self._collapse_btn.setText("▶" if self._collapsed else "▼")

    def _start_name_edit(self) -> None:
        self._name_lbl.setVisible(False)
        self._name_edit.setText(self._display_name)
        self._name_edit.setVisible(True)
        self._name_edit.setFocus()
        self._name_edit.selectAll()

    def _commit_name_edit(self) -> None:
        if not self._name_edit.isVisible():
            return
        text = self._name_edit.text().strip() or self._display_name
        self._display_name = text
        self._name_lbl.setText(text)
        self._name_lbl.setVisible(True)
        self._name_edit.setVisible(False)
