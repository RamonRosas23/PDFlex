"""DocumentWorkspace — bandeja global y trabajo de herramienta separados."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from shell.transfer import ToolTransfer
from ui.common.documents_step import DocumentsCard
from ui.common.icons import icon, set_button_icon
from ui.styles import COLORS

if TYPE_CHECKING:
    from shell.context import ShellContext


class DocumentWorkspace(QFrame):
    """Componente comun que separa bandeja global y lote de trabajo."""

    files_changed = pyqtSignal(list)

    def __init__(
        self,
        ctx: "ShellContext",
        *,
        single_file: bool = False,
        allow_reorder: bool = False,
        show_thumbnails: bool = True,
        thumb_size: tuple[int, int] = (64, 82),
        file_filter: str = (
            "PDF y Word (*.pdf *.doc *.docx);;"
            "PDF (*.pdf);;"
            "Word (*.doc *.docx)"
        ),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._accent = "#5E6AD2"
        self.setAcceptDrops(False)
        self._build(
            single_file=single_file,
            allow_reorder=allow_reorder,
            show_thumbnails=show_thumbnails,
            show_preview=True,
            thumb_size=thumb_size,
            file_filter=file_filter,
        )
        self._ctx.tray.changed.connect(self._refresh_tray)
        self._ctx.tray.changed.connect(self._hide_legacy_tray_button)
        self._refresh_tray()
        self._hide_legacy_tray_button()
        self._sync_preview_visibility()

    def _build(
        self,
        *,
        single_file: bool,
        allow_reorder: bool,
        show_thumbnails: bool,
        show_preview: bool,
        thumb_size: tuple[int, int],
        file_filter: str,
    ) -> None:
        root = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        self._root_layout = root

        tray_panel = self._build_tray_panel()
        self._tray_panel = tray_panel
        root.addWidget(tray_panel)

        self._work_card = DocumentsCard(
            self._ctx,
            single_file=single_file,
            allow_reorder=allow_reorder,
            show_thumbnails=show_thumbnails,
            show_preview=show_preview,
            thumb_size=thumb_size,
            file_filter=file_filter,
        )
        self._work_card.files_changed.connect(self.files_changed.emit)
        root.addWidget(self._work_card, 1)

        self.list_widget = self._work_card.list_widget
        self._remove_btn = self._work_card._remove_btn
        self._clear_btn = self._work_card._clear_btn
        self._sort_btn = self._work_card._sort_btn
        self._empty_w = self._work_card._empty_w
        self._count_lbl = self._work_card._count_lbl

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_preview_visibility()

    def _sync_preview_visibility(self) -> None:
        if not hasattr(self, "_work_card"):
            return
        visible_width = min(self.width(), self.window().width())
        compact = visible_width < 900
        direction = (
            QBoxLayout.Direction.TopToBottom
            if compact
            else QBoxLayout.Direction.LeftToRight
        )
        if self._root_layout.direction() != direction:
            self._root_layout.setDirection(direction)

        if compact:
            self._tray_panel.setMinimumWidth(0)
            self._tray_panel.setMaximumWidth(16777215)
            self._tray_panel.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
        else:
            self._tray_panel.setFixedWidth(320)

        self._work_card.set_preview_visible(visible_width >= 1450)

    def _build_tray_panel(self) -> QFrame:
        panel = QFrame()
        panel.setProperty("class", "Card")
        panel.setFixedWidth(320)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Bandeja")
        title.setProperty("class", "CardTitle")
        self._tray_count_lbl = QLabel("0 archivos")
        self._tray_count_lbl.setProperty("class", "CardHint")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._tray_count_lbl)
        layout.addLayout(header)

        self._tray_list = QListWidget()
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

        self._replace_work_btn = QPushButton("Reemplazar")
        self._replace_work_btn.setProperty("class", "Ghost")
        self._replace_work_btn.setFixedHeight(30)
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
        return self._work_card.paths()

    def add_paths(self, raw_paths: List[str]) -> None:
        self._work_card.add_paths(raw_paths)

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
        self._work_card.clear()

    def count(self) -> int:
        return self._work_card.count()

    def is_empty(self) -> bool:
        return self._work_card.is_empty()

    def remove_selected(self) -> None:
        self._work_card.remove_selected()

    def remove_at(self, idx: int) -> None:
        self._work_card.remove_at(idx)

    def remove_path(self, path: str) -> None:
        self._work_card.remove_path(path)

    def reorder_paths(self, ordered_paths: List[str]) -> None:
        self._work_card.reorder_paths(ordered_paths)

    def set_accent(self, accent: str) -> None:
        self._accent = accent or "#5E6AD2"
        self._work_card.set_accent(self._accent)

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

        items = self._ctx.tray.items
        for tray_item in items:
            list_item = QListWidgetItem(self._tray_text(tray_item))
            list_item.setData(Qt.ItemDataRole.UserRole, tray_item.path)
            list_item.setToolTip(tray_item.path)
            list_item.setIcon(icon("file-text", self._status_color(tray_item.status), 15))
            list_item.setSelected(tray_item.path in selected)
            self._tray_list.addItem(list_item)

        n = len(items)
        self._tray_count_lbl.setText(f"{n} archivo" + ("s" if n != 1 else ""))
        self._update_tray_actions()

    def _tray_text(self, tray_item) -> str:
        source = tray_item.source_tool_title or tray_item.source_tool
        status = self._status_label(tray_item.status)
        missing = "" if Path(tray_item.path).exists() else " · Faltante"
        return f"{tray_item.label}\n{source} · {status}{missing}"

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

    def _hide_legacy_tray_button(self) -> None:
        tray_btn = getattr(self._work_card, "_tray_btn", None)
        if tray_btn is not None:
            tray_btn.setVisible(False)
