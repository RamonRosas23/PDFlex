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
from typing import List

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QScrollArea,
)

from ui.common.icons import set_button_icon


# ====================================================================== #
#  Modelo
# ====================================================================== #

@dataclass
class TrayItem:
    path: str
    source_tool: str
    label: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if not self.label:
            self.label = Path(self.path).name


class PdfTray(QObject):
    """Modelo observable de la bandeja de PDFs."""

    changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: List[TrayItem] = []

    @property
    def items(self) -> List[TrayItem]:
        return list(self._items)

    def count(self) -> int:
        return len(self._items)

    def add_items(self, paths: List[str], source_tool: str) -> None:
        existing = {i.path for i in self._items}
        added = False
        for p in paths:
            if p and p not in existing and Path(p).exists():
                self._items.append(TrayItem(path=p, source_tool=source_tool))
                existing.add(p)
                added = True
        if added:
            self.changed.emit()

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


# ====================================================================== #
#  Popup de la bandeja
# ====================================================================== #

class TrayPopup(QFrame):
    """Popup flotante mostrado bajo el botón de la bandeja en la topbar."""

    send_to_tool_requested = pyqtSignal(str)   # path solicitado para abrir en tool

    def __init__(self, tray: PdfTray, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self._tray = tray
        self.setObjectName("TrayPopup")
        self.setMinimumWidth(340)
        self.setMaximumHeight(420)
        self._build()
        tray.changed.connect(self._refresh)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("Bandeja de PDFs")
        title.setObjectName("TrayTitle")
        clear_btn = QPushButton("Vaciar")
        clear_btn.setProperty("class", "Ghost")
        clear_btn.setFixedHeight(26)
        set_button_icon(clear_btn, "eraser", size=14)
        clear_btn.clicked.connect(self._tray.clear)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(clear_btn)
        layout.addLayout(header)

        # Scroll con items
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setSpacing(4)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._container)
        layout.addWidget(scroll, 1)

        self._refresh()

    def _refresh(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        items = self._tray.items
        if not items:
            empty = QLabel("La bandeja está vacía")
            empty.setProperty("class", "CardHint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_layout.addWidget(empty)
            return

        for ti in items:
            row = QFrame()
            row.setProperty("class", "TrayItemRow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 6, 10, 6)
            rl.setSpacing(8)

            info = QVBoxLayout()
            info.setSpacing(1)
            lbl = QLabel(ti.label)
            lbl.setToolTip(ti.path)
            source = QLabel(f"de {ti.source_tool}")
            source.setProperty("class", "CardHint")
            info.addWidget(lbl)
            info.addWidget(source)
            rl.addLayout(info, 1)

            remove_btn = QPushButton()
            remove_btn.setProperty("class", "IconBtn")
            remove_btn.setFixedSize(24, 24)
            set_button_icon(remove_btn, "x", size=14, icon_only=True)
            remove_btn.setToolTip("Quitar de la bandeja")
            remove_btn.clicked.connect(lambda _, p=ti.path: self._tray.remove(p))
            rl.addWidget(remove_btn)

            self._list_layout.addWidget(row)

        self._list_layout.addStretch()
