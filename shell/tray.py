"""PdfTray — bandeja global de PDFs activos en sesión.

La bandeja vive en ShellWindow y es accesible desde cualquier herramienta
a través de ShellContext.  Los outputs de una herramienta se publican aquí
automáticamente; cualquier herramienta puede leer los items para cargarlos
como input propio.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QPushButton, QCheckBox, QLabel, QScrollArea, QSizePolicy,
)

from ui.common.icons import set_button_icon
from ui.common.result_ui import ElidedLabel
from ui.styles import COLORS


# ====================================================================== #
#  Modelo
# ====================================================================== #

@dataclass
class TrayItem:
    path: str
    source_tool: str
    label: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=lambda: uuid4().hex)
    kind: str = "output"
    source_tool_id: str = ""
    source_tool_title: str = ""
    batch_id: str = ""
    parent_ids: List[str] = field(default_factory=list)
    status: str = "available"
    last_used_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if not self.label:
            self.label = Path(self.path).name
        if not self.source_tool_title:
            self.source_tool_title = self.source_tool
        if not self.source_tool_id:
            self.source_tool_id = self.source_tool
        if not self.batch_id:
            self.batch_id = uuid4().hex

    def touch(self) -> None:
        self.last_used_at = datetime.now()


class PdfTray(QObject):
    """Modelo observable de la bandeja de PDFs."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: List[TrayItem] = []

    @property
    def items(self) -> List[TrayItem]:
        return list(self._items)

    def count(self) -> int:
        return len(self._items)

    def add_items(
        self,
        paths: List[str],
        source_tool: str,
        *,
        kind: str = "output",
        source_tool_id: str = "",
        source_tool_title: str = "",
        batch_id: Optional[str] = None,
        parent_ids: Optional[List[str]] = None,
        status: str = "available",
    ) -> None:
        existing = {i.path for i in self._items}
        added = False
        batch = batch_id or uuid4().hex
        for p in paths:
            if p and p not in existing and Path(p).exists():
                self._items.append(
                    TrayItem(
                        path=p,
                        source_tool=source_tool,
                        kind=kind,
                        source_tool_id=source_tool_id or source_tool,
                        source_tool_title=source_tool_title or source_tool,
                        batch_id=batch,
                        parent_ids=list(parent_ids or []),
                        status=status,
                    )
                )
                existing.add(p)
                added = True
        if added:
            self.changed.emit()

    def replace_with(
        self,
        paths: List[str],
        source_tool: str,
        *,
        kind: str = "output",
        source_tool_id: str = "",
        source_tool_title: str = "",
        batch_id: Optional[str] = None,
        parent_ids: Optional[List[str]] = None,
        status: str = "available",
    ) -> None:
        """Reemplaza la bandeja completa por los paths validos recibidos."""
        old_paths = self.paths()
        self._items.clear()
        existing: set[str] = set()
        batch = batch_id or uuid4().hex
        for p in paths:
            if not p or p in existing or not Path(p).exists():
                continue
            self._items.append(
                TrayItem(
                    path=p,
                    source_tool=source_tool,
                    kind=kind,
                    source_tool_id=source_tool_id or source_tool,
                    source_tool_title=source_tool_title or source_tool,
                    batch_id=batch,
                    parent_ids=list(parent_ids or []),
                    status=status,
                )
            )
            existing.add(p)
        if old_paths != self.paths():
            self.changed.emit()

    def mark_in_work(self, paths: List[str]) -> None:
        self._set_status(paths, "in_work")

    def mark_sent(self, paths: List[str]) -> None:
        self._set_status(paths, "sent")

    def refresh_missing(self) -> None:
        changed = False
        for item in self._items:
            if not Path(item.path).exists() and item.status != "missing":
                item.status = "missing"
                item.touch()
                changed = True
        if changed:
            self.changed.emit()

    def items_by_group(self) -> Dict[str, List[TrayItem]]:
        groups: Dict[str, List[TrayItem]] = {}
        for item in self._items:
            groups.setdefault(item.batch_id, []).append(item)
        return groups

    def source_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self._items:
            source = item.source_tool_title or item.source_tool
            counts[source] = counts.get(source, 0) + 1
        return counts

    def clear_results(self) -> None:
        self._remove_matching(lambda item: item.kind in {"output", "converted"})

    def clear_originals(self) -> None:
        self._remove_matching(lambda item: item.kind in {"original", "manual"})

    def remove_missing(self) -> None:
        self._remove_matching(
            lambda item: item.status == "missing" or not Path(item.path).exists()
        )

    def remove(self, path: str) -> None:
        before = len(self._items)
        self._items = [i for i in self._items if i.path != path]
        if len(self._items) != before:
            self.changed.emit()

    def clear(self) -> None:
        if self._items:
            self._items.clear()
            self.changed.emit()

    def paths(self) -> List[str]:
        return [i.path for i in self._items]

    def _set_status(self, paths: List[str], status: str) -> None:
        path_set = set(paths)
        changed = False
        for item in self._items:
            if item.path in path_set and item.status != status:
                item.status = status
                item.touch()
                changed = True
        if changed:
            self.changed.emit()

    def _remove_matching(self, predicate) -> None:
        before = len(self._items)
        self._items = [item for item in self._items if not predicate(item)]
        if len(self._items) != before:
            self.changed.emit()


# ====================================================================== #
#  Popup de la bandeja
# ====================================================================== #

class TrayPopup(QFrame):
    """Popup flotante mostrado bajo el botón de la bandeja en la topbar."""

    use_in_active_tool_requested = Signal(list)

    def __init__(
        self,
        tray: PdfTray,
        parent=None,
        *,
        active_tool_title: str = "",
        active_extensions: tuple[str, ...] = (),
    ) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self._tray = tray
        self._active_tool_title = active_tool_title
        self._active_extensions = {ext.lower() for ext in active_extensions}
        self._selected_paths: set[str] = set()
        self._item_checks: Dict[str, QCheckBox] = {}
        self.setObjectName("TrayPopup")
        self.setFixedWidth(420)
        self.setMaximumHeight(560)
        self._build()
        tray.changed.connect(self._refresh)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("Bandeja")
        title.setObjectName("TrayTitle")
        self._count_lbl = QLabel("0 archivos")
        self._count_lbl.setProperty("class", "CardHint")
        clear_btn = QPushButton("Vaciar")
        clear_btn.setProperty("class", "Ghost")
        clear_btn.setFixedHeight(26)
        set_button_icon(clear_btn, "eraser", size=14)
        clear_btn.clicked.connect(self._tray.clear)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._count_lbl)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._clear_results_btn = self._make_mass_action(
            "Resultados", "Quitar resultados y conversiones de la bandeja", self._tray.clear_results,
        )
        self._clear_originals_btn = self._make_mass_action(
            "Originales", "Quitar archivos originales o agregados manualmente", self._tray.clear_originals,
        )
        self._remove_missing_btn = self._make_mass_action(
            "Faltantes", "Quitar archivos que ya no existen", self._tray.remove_missing,
        )
        actions.addWidget(self._clear_results_btn)
        actions.addWidget(self._clear_originals_btn)
        actions.addWidget(self._remove_missing_btn)
        layout.addLayout(actions)

        # Scroll con items
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea {"
            f"background: {COLORS['surface']};"
            "border: none;"
            "}"
        )

        self._container = QWidget()
        self._container.setStyleSheet(f"background: {COLORS['surface']};")
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setSpacing(4)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._container)
        layout.addWidget(scroll, 1)

        self._use_active_btn = QPushButton()
        self._use_active_btn.setProperty("class", "Primary")
        self._use_active_btn.setFixedHeight(32)
        set_button_icon(self._use_active_btn, "arrow-right", size=15)
        self._use_active_btn.clicked.connect(self._emit_use_in_active_tool)
        self._use_active_btn.setVisible(bool(self._active_extensions))
        layout.addWidget(self._use_active_btn)

        self._refresh()

    def _make_mass_action(self, text: str, tooltip: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("class", "Ghost")
        button.setFixedHeight(26)
        button.setToolTip(tooltip)
        button.clicked.connect(slot)
        return button

    def _refresh(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        items = self._tray.items
        self._selected_paths.intersection_update(item.path for item in items)
        self._item_checks.clear()
        self._count_lbl.setText(f"{len(items)} archivo" + ("s" if len(items) != 1 else ""))
        self._update_mass_actions(items)
        if not items:
            empty = QLabel("La bandeja está vacía")
            empty.setProperty("class", "CardHint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_layout.addWidget(empty)
            self._update_use_active_action(items)
            return

        for group in self._tray.items_by_group().values():
            self._list_layout.addWidget(self._build_group_header(group))
            for tray_item in group:
                self._list_layout.addWidget(self._build_item_row(tray_item))

        self._list_layout.addStretch()
        self._update_use_active_action(items)

    def _build_group_header(self, group: List[TrayItem]) -> ElidedLabel:
        first = group[0]
        source = first.source_tool_title or first.source_tool
        kind = self._kind_label(first.kind)
        label = ElidedLabel(
            f"{source} · {kind} · {len(group)} archivo" + ("s" if len(group) != 1 else "")
        )
        label.setProperty("class", "TrayGroupTitle")
        label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 11px; font-weight: 600;"
            "padding: 6px 2px 1px; background: transparent;"
        )
        return label

    def _build_item_row(self, tray_item: TrayItem) -> QFrame:
        row = QFrame()
        row.setProperty("class", "TrayItemRow")
        row.setMinimumWidth(0)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        if self._active_extensions:
            check = QCheckBox()
            check.setToolTip("Seleccionar para usar en la herramienta actual")
            compatible = self._is_compatible(tray_item)
            check.setEnabled(compatible)
            check.setChecked(tray_item.path in self._selected_paths)
            if not compatible:
                check.setToolTip("No es compatible con la herramienta actual")
            check.toggled.connect(
                lambda checked, path=tray_item.path: self._set_selected(path, checked)
            )
            self._item_checks[tray_item.path] = check
            layout.addWidget(check)

        info_host = QWidget()
        info_host.setMinimumWidth(0)
        info_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        info = QVBoxLayout(info_host)
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(1)
        label = ElidedLabel(tray_item.label)
        label.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; background: transparent;")
        label.setToolTip(tray_item.path)
        source = ElidedLabel(
            f"{self._status_label(tray_item.status)} · {self._kind_label(tray_item.kind)}"
        )
        source.setProperty("class", "CardHint")
        source.setStyleSheet(
            f"color: {self._status_color(tray_item.status)}; font-size: 12px; background: transparent;"
        )
        info.addWidget(label)
        info.addWidget(source)
        layout.addWidget(info_host, 1)

        remove_btn = QPushButton()
        remove_btn.setProperty("class", "IconBtn")
        remove_btn.setFixedSize(30, 30)
        set_button_icon(remove_btn, "x", size=14, icon_only=True)
        remove_btn.setToolTip("Quitar de la bandeja")
        remove_btn.clicked.connect(lambda _, path=tray_item.path: self._tray.remove(path))
        layout.addWidget(remove_btn)
        return row

    def _set_selected(self, path: str, selected: bool) -> None:
        if selected:
            self._selected_paths.add(path)
        else:
            self._selected_paths.discard(path)
        self._update_use_active_action(self._tray.items)

    def _update_mass_actions(self, items: List[TrayItem]) -> None:
        self._clear_results_btn.setEnabled(
            any(item.kind in {"output", "converted"} for item in items)
        )
        self._clear_originals_btn.setEnabled(
            any(item.kind in {"original", "manual"} for item in items)
        )
        self._remove_missing_btn.setEnabled(
            any(item.status == "missing" or not Path(item.path).exists() for item in items)
        )

    def _update_use_active_action(self, items: List[TrayItem]) -> None:
        if not self._active_extensions:
            return
        selected = [
            item.path for item in items
            if item.path in self._selected_paths and self._is_compatible(item)
        ]
        count = len(selected)
        title = self._active_tool_title or "herramienta actual"
        self._use_active_btn.setText(
            f"Usar {count} archivo" + ("s" if count != 1 else "") + f" en {title}"
        )
        self._use_active_btn.setEnabled(bool(selected))

    def _emit_use_in_active_tool(self) -> None:
        paths = [
            item.path for item in self._tray.items
            if item.path in self._selected_paths and self._is_compatible(item)
        ]
        if paths:
            self.use_in_active_tool_requested.emit(paths)

    def _is_compatible(self, item: TrayItem) -> bool:
        return Path(item.path).suffix.lower() in self._active_extensions

    @staticmethod
    def _kind_label(kind: str) -> str:
        return {
            "original": "Original",
            "output": "Resultado",
            "converted": "Convertido",
            "manual": "Manual",
        }.get(kind, kind or "Archivo")

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
