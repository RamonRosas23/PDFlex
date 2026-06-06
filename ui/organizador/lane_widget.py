"""DocLane — one horizontal page strip per PDF document."""
from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import fitz
from PyQt6.QtCore import Qt, QEvent, QPoint, QSize, pyqtSignal
from PyQt6.QtGui import (
    QColor, QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent, QIcon,
    QKeyEvent, QPixmap,
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


def _placeholder_pixmap() -> QPixmap:
    pix = QPixmap(THUMB_W, THUMB_H)
    pix.fill(QColor("#26262C"))
    return pix


class _PageStrip(QListWidget):
    """Horizontal QListWidget with custom drag/drop for intra- and cross-lane operations."""

    cross_lane_drop_received = pyqtSignal(str, str, list, bool)  # src_id, dst_id, refs, ctrl
    pdf_file_dropped = pyqtSignal(str)                           # file path
    internal_reorder_done = pyqtSignal()

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
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.viewport().setAcceptDrops(True)
        self.model().rowsMoved.connect(lambda *_: self.internal_reorder_done.emit())

    def startDrag(self, supported_actions) -> None:
        selected_items = [
            self.item(i)
            for i in range(self.count())
            if self.item(i) and self.item(i).isSelected()
        ]
        selected_refs = [
            item.data(Qt.ItemDataRole.UserRole) for item in selected_items
        ]
        if not selected_refs:
            return
        mime = encode_drag(self._lane_id, selected_refs)
        drag = QDrag(self)
        drag.setMimeData(mime)
        # Mostrar miniatura de la primera página seleccionada como cursor de drag
        if selected_items:
            icon = selected_items[0].icon()
            if not icon.isNull():
                pix = icon.pixmap(QSize(THUMB_W // 2, THUMB_H // 2))
                drag.setPixmap(pix)
                drag.setHotSpot(QPoint(pix.width() // 2, pix.height() // 2))
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(MIME_TYPE) or event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_highlight(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        # El base QAbstractItemView rechaza MIME personalizados — debemos aceptar explícitamente
        if event.mimeData().hasFormat(MIME_TYPE) or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_highlight(False)
        decoded = decode_drag(event.mimeData())

        if decoded is not None:
            src_id, refs = decoded
            if src_id == self._lane_id:
                target_item = self.itemAt(event.position().toPoint())
                target_row = self.row(target_item) if target_item else self.count()
                self._reorder_to(refs, target_row)
            else:
                ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                self.cross_lane_drop_received.emit(src_id, self._lane_id, refs, ctrl)
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

    def _set_highlight(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                "QListWidget#DocLaneStrip {"
                "  border: 2px solid #14B8A6;"
                "  border-radius: 4px;"
                "  background: rgba(20,184,166,0.06);"
                "}"
            )
        else:
            self.setStyleSheet(
                "QListWidget#DocLaneStrip {"
                "  border: 1px solid #26262C;"
                "  border-radius: 4px;"
                "}"
            )

    def contextMenuEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        if item is None:
            return
        if item not in self.selectedItems():
            self.clearSelection()
            item.setSelected(True)
        # _list está dentro de _strip_wrap, que está dentro de DocLane
        p = self.parent()
        while p is not None:
            if hasattr(p, "_show_page_context_menu"):
                p._show_page_context_menu(event.globalPos())
                return
            p = p.parent()


class DocLane(QFrame):
    """Header + horizontal page strip for one document in the organizer."""

    pages_changed = pyqtSignal(str)                               # lane_id
    lane_delete_requested = pyqtSignal(str)                       # lane_id
    reorder_requested = pyqtSignal(str, int)                      # lane_id, direction
    cross_lane_drop_received = pyqtSignal(str, str, list, bool)   # src_id, dst_id, refs, ctrl

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
        worker.thumb_ready.connect(self._on_thumb_ready)
        self._build()

    @property
    def lane_id(self) -> str:
        return self._lane_id

    @property
    def display_name(self) -> str:
        return self._display_name

    def _build(self) -> None:
        self.setProperty("class", "Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = self._build_header()
        layout.addWidget(self._header)

        self._strip_wrap = QFrame()
        sw = QVBoxLayout(self._strip_wrap)
        sw.setContentsMargins(8, 6, 8, 8)
        sw.setSpacing(0)

        self._list = _PageStrip(self._lane_id)
        self._list.internal_reorder_done.connect(lambda: self.pages_changed.emit(self._lane_id))
        self._list.cross_lane_drop_received.connect(self.cross_lane_drop_received)
        self._list.pdf_file_dropped.connect(self.add_pages_from_pdf)
        self._list.installEventFilter(self)

        sw.addWidget(self._list)
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
            "QLineEdit { background: #26262C; border: 1px solid #5E6AD2; "
            "border-radius: 4px; color: #ECEDEE; font-size: 13px; padding: 2px 6px; }"
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

    def set_siblings_provider(
        self, fn: Callable[[], List[Tuple[str, str]]]
    ) -> None:
        self._siblings_provider = fn

    def add_pages_from_pdf(self, path: str) -> None:
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
        self._list.clear()
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    def remove_by_page_ids(self, page_ids: set) -> None:
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
        for item in self._list.selectedItems():
            ref = item.data(Qt.ItemDataRole.UserRole)
            updated = replace(ref, rotation_deg=(ref.rotation_deg + delta) % 360)
            item.setData(Qt.ItemDataRole.UserRole, updated)
            item.setText(self._label_for(updated))
            item.setToolTip(f"{Path(updated.source_path).name}\nPágina {updated.page_index + 1}"
                            + (f"\nRot {updated.rotation_deg}°" if updated.rotation_deg else ""))
            key = ThumbnailKey(updated.source_path, updated.page_index, updated.rotation_deg, THUMB_W)
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
        last_row = max(self._list.row(item) for item in selected)
        clones: List[PageRef] = []
        for item in selected:
            ref = item.data(Qt.ItemDataRole.UserRole)
            stem = Path(ref.source_path).stem
            new_ref = replace(ref, page_id=f"{stem}-{ref.page_index+1}-{uuid.uuid4().hex[:8]}")
            clones.append(new_ref)
        for offset, ref in enumerate(clones):
            new_item = self._make_item(ref)
            self._list.insertItem(last_row + 1 + offset, new_item)
            self._worker.request(
                self._lane_id, ref.page_id,
                ref.source_path, ref.page_index, ref.rotation_deg, THUMB_W,
            )
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._list and event.type() == QEvent.Type.KeyPress:
            if isinstance(event, QKeyEvent):
                key = event.key()
                mods = event.modifiers()
                if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    self._remove_selected()
                    return True
                if key == Qt.Key.Key_A and mods & Qt.KeyboardModifier.ControlModifier:
                    self._list.selectAll()
                    return True
                if key == Qt.Key.Key_D and mods & Qt.KeyboardModifier.ControlModifier:
                    self.duplicate_selected()
                    return True
                if key == Qt.Key.Key_R:
                    delta = -90 if mods & Qt.KeyboardModifier.ShiftModifier else 90
                    self.rotate_selected(delta)
                    return True
        return super().eventFilter(obj, event)

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

        rot_cw = menu.addAction("Rotar 90° →")
        rot_ccw = menu.addAction("Rotar 90° ←")
        menu.addSeparator()
        dup_act = menu.addAction("Duplicar")
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
        del_act = menu.addAction("Eliminar")

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen == rot_cw:
            self.rotate_selected(90)
        elif chosen == rot_ccw:
            self.rotate_selected(-90)
        elif chosen == dup_act:
            self.duplicate_selected()
        elif chosen == del_act:
            self._remove_selected()
        elif chosen.data() is not None:
            action_type, target_lane_id = chosen.data()
            ctrl_held = (action_type == "copy")
            self.cross_lane_drop_received.emit(
                self._lane_id, target_lane_id, selected, ctrl_held
            )
            if not ctrl_held:
                page_ids = {r.page_id for r in selected}
                self.remove_by_page_ids(page_ids)

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

    def _on_thumb_ready(self, lane_id: str, page_id: str, pixmap: object) -> None:
        if lane_id != self._lane_id:
            return
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole).page_id == page_id:
                item.setIcon(QIcon(pixmap))
                break

    def _remove_selected(self) -> None:
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
