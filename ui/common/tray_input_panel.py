"""TrayInputPanel — selector de bandeja para flujos de trabajo especializados."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ui.common.icons import icon, set_button_icon
from ui.common.result_ui import configure_file_list
from ui.styles import COLORS

if TYPE_CHECKING:
    from shell.context import ShellContext


class TrayInputPanel(QFrame):
    """Muestra archivos compatibles de la bandeja y emite la selección elegida."""

    add_requested = pyqtSignal(list)
    replace_requested = pyqtSignal(list)

    def __init__(
        self,
        ctx: "ShellContext",
        accepted_exts: Iterable[str],
        *,
        title: str = "Bandeja",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._accepted_exts = {ext.lower() for ext in accepted_exts}
        self.setProperty("class", "Card")
        self.setFixedWidth(320)
        self._build(title)
        self._ctx.tray.changed.connect(self._refresh)
        self._refresh()

    def _build(self, title: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title_lbl = QLabel(title)
        title_lbl.setProperty("class", "CardTitle")
        self._count_lbl = QLabel("0 archivos")
        self._count_lbl.setProperty("class", "CardHint")
        header.addWidget(title_lbl)
        header.addStretch()
        header.addWidget(self._count_lbl)
        layout.addLayout(header)

        self.list_widget = QListWidget()
        configure_file_list(self.list_widget)
        self.list_widget.setMinimumHeight(280)
        self.list_widget.setIconSize(QSize(18, 18))
        self.list_widget.setSpacing(3)
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self._update_actions)
        self.list_widget.itemDoubleClicked.connect(lambda *_: self._emit_add())
        layout.addWidget(self.list_widget, 1)

        primary_row = QHBoxLayout()
        primary_row.setSpacing(6)
        self._add_btn = QPushButton("Agregar")
        self._add_btn.setProperty("class", "Primary")
        self._add_btn.setFixedHeight(30)
        set_button_icon(self._add_btn, "plus", size=14)
        self._add_btn.clicked.connect(self._emit_add)
        primary_row.addWidget(self._add_btn, 1)

        self._replace_btn = QPushButton("Cambiar")
        self._replace_btn.setProperty("class", "Ghost")
        self._replace_btn.setFixedHeight(30)
        self._replace_btn.setToolTip("Reemplazar el lote de trabajo con la selección")
        set_button_icon(self._replace_btn, "refresh-cw", size=14)
        self._replace_btn.clicked.connect(self._emit_replace)
        primary_row.addWidget(self._replace_btn, 1)
        layout.addLayout(primary_row)

        secondary_row = QHBoxLayout()
        secondary_row.setSpacing(6)
        self._remove_btn = QPushButton("Quitar")
        self._remove_btn.setProperty("class", "Ghost")
        self._remove_btn.setFixedHeight(28)
        set_button_icon(self._remove_btn, "x", color=COLORS["danger"], size=14)
        self._remove_btn.clicked.connect(self._remove_selected)
        secondary_row.addWidget(self._remove_btn, 1)

        self._clear_btn = QPushButton("Vaciar")
        self._clear_btn.setProperty("class", "Ghost")
        self._clear_btn.setFixedHeight(28)
        set_button_icon(self._clear_btn, "eraser", size=14)
        self._clear_btn.clicked.connect(self._ctx.tray.clear)
        secondary_row.addWidget(self._clear_btn, 1)
        layout.addLayout(secondary_row)

    def selected_paths(self) -> List[str]:
        paths: List[str] = []
        for item in self.list_widget.selectedItems():
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                paths.append(path)
        return paths

    def _emit_add(self) -> None:
        paths = self.selected_paths()
        if not paths:
            return
        self.add_requested.emit(paths)
        self._ctx.tray.mark_in_work(paths)

    def _emit_replace(self) -> None:
        paths = self.selected_paths()
        if not paths:
            return
        self.replace_requested.emit(paths)
        self._ctx.tray.mark_in_work(paths)

    def _remove_selected(self) -> None:
        for path in self.selected_paths():
            self._ctx.tray.remove(path)

    def _refresh(self) -> None:
        selected = set(self.selected_paths()) if hasattr(self, "list_widget") else set()
        self.list_widget.clear()
        items = [
            item for item in self._ctx.tray.items
            if Path(item.path).suffix.lower() in self._accepted_exts
        ]
        for tray_item in items:
            item = QListWidgetItem(self._item_text(tray_item))
            item.setData(Qt.ItemDataRole.UserRole, tray_item.path)
            item.setToolTip(tray_item.path)
            item.setIcon(icon("file-text", self._status_color(tray_item.status), 15))
            item.setSizeHint(QSize(220, 46))
            self.list_widget.addItem(item)
            item.setSelected(tray_item.path in selected)

        count = len(items)
        self._count_lbl.setText(f"{count} archivo" + ("s" if count != 1 else ""))
        self._update_actions()

    def _item_text(self, tray_item) -> str:
        source = tray_item.source_tool_title or tray_item.source_tool
        return f"{tray_item.label}\n{source} · {self._status_label(tray_item.status)}"

    def _update_actions(self) -> None:
        selected = bool(self.list_widget.selectedItems())
        has_items = self.list_widget.count() > 0
        self._add_btn.setEnabled(selected)
        self._replace_btn.setEnabled(selected)
        self._remove_btn.setEnabled(selected)
        self._clear_btn.setEnabled(has_items)

    @staticmethod
    def _status_label(status: str) -> str:
        return {
            "available": "Disponible",
            "in_work": "En trabajo",
            "sent": "Enviado",
            "missing": "Faltante",
        }.get(status, status or "Disponible")

    @staticmethod
    def _status_color(status: str) -> str:
        return {
            "available": COLORS["text_muted"],
            "in_work": COLORS["accent"],
            "sent": COLORS["success"],
            "missing": COLORS["danger"],
        }.get(status, COLORS["text_muted"])
