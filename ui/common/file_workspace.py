"""FileWorkspace — bandeja global + card de entrada especializado."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shell.transfer import ToolTransfer
from core.media_conversion import IMAGE_EXTENSIONS, IMAGE_IMPORT_EXTENSIONS
from ui.common.icons import icon, set_button_icon
from ui.common.result_ui import configure_file_list
from ui.styles import COLORS

if TYPE_CHECKING:
    from shell.context import ShellContext


class FileWorkspace(QFrame):
    """Wrapper reusable para entradas no PDF como imagenes o Word."""

    files_changed = pyqtSignal(list)

    def __init__(
        self,
        ctx: "ShellContext",
        work_card: QWidget,
        accepted_exts: Iterable[str],
        *,
        tray_title: str = "Bandeja",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._work_card = work_card
        self._accepted_exts = {ext.lower() for ext in accepted_exts}
        self._compatible_exts = set(self._accepted_exts)
        if self._accepted_exts and self._accepted_exts.issubset(IMAGE_EXTENSIONS):
            self._compatible_exts = set(IMAGE_IMPORT_EXTENSIONS)
        self._tray_title = tray_title
        set_context = getattr(self._work_card, "set_conversion_context", None)
        if callable(set_context):
            set_context(ctx)
        self._build()
        files_changed = getattr(self._work_card, "files_changed", None)
        if files_changed is not None:
            files_changed.connect(self.files_changed.emit)
        self._ctx.tray.changed.connect(self._refresh_tray)
        self._refresh_tray()

    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        root.addWidget(self._build_tray_panel())
        root.addWidget(self._work_card, 1)

        self.list_widget = getattr(self._work_card, "list_widget", None)

    def _build_tray_panel(self) -> QFrame:
        panel = QFrame()
        panel.setProperty("class", "Card")
        panel.setFixedWidth(320)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(self._tray_title)
        title.setProperty("class", "CardTitle")
        self._tray_count_lbl = QLabel("0 archivos")
        self._tray_count_lbl.setProperty("class", "CardHint")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._tray_count_lbl)
        layout.addLayout(header)

        self._tray_list = QListWidget()
        configure_file_list(self._tray_list)
        self._tray_list.setMinimumHeight(280)
        self._tray_list.setIconSize(QSize(18, 18))
        self._tray_list.setSpacing(3)
        self._tray_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._tray_list.itemSelectionChanged.connect(self._update_tray_actions)
        self._tray_list.itemDoubleClicked.connect(lambda *_: self._add_selected_to_work())
        layout.addWidget(self._tray_list, 1)

        primary_row = QHBoxLayout()
        primary_row.setSpacing(6)
        self._add_selected_btn = QPushButton("Agregar")
        self._add_selected_btn.setProperty("class", "Primary")
        self._add_selected_btn.setFixedHeight(30)
        set_button_icon(self._add_selected_btn, "plus", size=14)
        self._add_selected_btn.clicked.connect(self._add_selected_to_work)
        primary_row.addWidget(self._add_selected_btn, 1)

        self._replace_work_btn = QPushButton("Cambiar")
        self._replace_work_btn.setProperty("class", "Ghost")
        self._replace_work_btn.setFixedHeight(30)
        self._replace_work_btn.setToolTip("Reemplazar el lote de trabajo con la selección")
        set_button_icon(self._replace_work_btn, "refresh-cw", size=14)
        self._replace_work_btn.clicked.connect(self._replace_work_with_selected)
        primary_row.addWidget(self._replace_work_btn, 1)
        layout.addLayout(primary_row)

        secondary_row = QHBoxLayout()
        secondary_row.setSpacing(6)
        self._remove_tray_btn = QPushButton("Quitar")
        self._remove_tray_btn.setProperty("class", "Ghost")
        self._remove_tray_btn.setFixedHeight(28)
        set_button_icon(self._remove_tray_btn, "x", color=COLORS["danger"], size=14)
        self._remove_tray_btn.clicked.connect(self._remove_selected_from_tray)
        secondary_row.addWidget(self._remove_tray_btn, 1)

        self._clear_tray_btn = QPushButton("Vaciar")
        self._clear_tray_btn.setProperty("class", "Ghost")
        self._clear_tray_btn.setFixedHeight(28)
        set_button_icon(self._clear_tray_btn, "eraser", size=14)
        self._clear_tray_btn.clicked.connect(self._ctx.tray.clear)
        secondary_row.addWidget(self._clear_tray_btn, 1)
        layout.addLayout(secondary_row)
        return panel

    def paths(self) -> List[str]:
        paths = getattr(self._work_card, "paths", None)
        return list(paths()) if callable(paths) else []

    def add_paths(self, raw_paths: List[str]) -> None:
        add_paths = getattr(self._work_card, "add_paths", None)
        if callable(add_paths):
            add_paths(self._accepted_paths(raw_paths))

    def set_paths(self, paths: List[str], source: str = "transfer") -> None:
        self.clear()
        self.add_paths(paths)
        self._ctx.tray.mark_in_work(paths)

    def set_transfer(self, transfer: ToolTransfer) -> None:
        if transfer.mode == "replace":
            self.set_paths(transfer.paths, source="transfer")
        else:
            self.add_paths(transfer.paths)
            self._ctx.tray.mark_in_work(transfer.paths)

    def clear(self) -> None:
        clear = getattr(self._work_card, "clear", None)
        if callable(clear):
            clear()

    def count(self) -> int:
        count = getattr(self._work_card, "count", None)
        return int(count()) if callable(count) else len(self.paths())

    def is_empty(self) -> bool:
        is_empty = getattr(self._work_card, "is_empty", None)
        return bool(is_empty()) if callable(is_empty) else self.count() == 0

    def remove_selected(self) -> None:
        remove_selected = getattr(self._work_card, "remove_selected", None)
        if callable(remove_selected):
            remove_selected()

    def _accepted_paths(self, paths: List[str]) -> List[str]:
        return [
            path for path in paths
            if Path(path).suffix.lower() in self._compatible_exts
        ]

    def _selected_tray_paths(self) -> List[str]:
        rows = sorted({self._tray_list.row(i) for i in self._tray_list.selectedItems()})
        paths: List[str] = []
        for row in rows:
            item = self._tray_list.item(row)
            if item:
                path = item.data(Qt.ItemDataRole.UserRole)
                if path:
                    paths.append(path)
        return paths

    def _add_selected_to_work(self) -> None:
        paths = self._selected_tray_paths()
        if not paths:
            return
        self.add_paths(paths)
        self._ctx.tray.mark_in_work(paths)

    def _replace_work_with_selected(self) -> None:
        paths = self._selected_tray_paths()
        if not paths:
            return
        self.set_paths(paths, source="tray")

    def _remove_selected_from_tray(self) -> None:
        for path in self._selected_tray_paths():
            self._ctx.tray.remove(path)

    def _refresh_tray(self) -> None:
        selected = set(self._selected_tray_paths()) if hasattr(self, "_tray_list") else set()
        self._tray_list.clear()

        items = [
            item for item in self._ctx.tray.items
            if Path(item.path).suffix.lower() in self._compatible_exts
        ]
        for tray_item in items:
            list_item = QListWidgetItem(self._tray_text(tray_item))
            list_item.setData(Qt.ItemDataRole.UserRole, tray_item.path)
            list_item.setToolTip(tray_item.path)
            list_item.setIcon(icon("file-text", self._status_color(tray_item.status), 15))
            list_item.setSizeHint(QSize(220, 46))
            self._tray_list.addItem(list_item)
            list_item.setSelected(tray_item.path in selected)

        n = len(items)
        self._tray_count_lbl.setText(f"{n} archivo" + ("s" if n != 1 else ""))
        self._update_tray_actions()

    def _tray_text(self, tray_item) -> str:
        source = tray_item.source_tool_title or tray_item.source_tool
        return f"{tray_item.label}\n{source} · {self._status_label(tray_item.status)}"

    def _status_label(self, status: str) -> str:
        labels = {
            "available": "Disponible",
            "in_work": "En trabajo",
            "sent": "Enviado",
            "missing": "Faltante",
        }
        return labels.get(status, status or "Disponible")

    def _status_color(self, status: str) -> str:
        colors = {
            "available": COLORS["text_muted"],
            "in_work": COLORS["accent"],
            "sent": COLORS["success"],
            "missing": COLORS["danger"],
        }
        return colors.get(status, COLORS["text_muted"])

    def _update_tray_actions(self) -> None:
        selected = bool(self._tray_list.selectedItems())
        has_items = self._tray_list.count() > 0
        self._add_selected_btn.setEnabled(selected)
        self._replace_work_btn.setEnabled(selected)
        self._remove_tray_btn.setEnabled(selected)
        self._clear_tray_btn.setEnabled(has_items)
