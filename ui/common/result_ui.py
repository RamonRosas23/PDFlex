"""Small UI helpers for result viewers."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QListWidget, QSizePolicy


class ElidedLabel(QLabel):
    """Label that keeps the full text in a tooltip and elides visually."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__("", parent)
        self._full_text = ""
        self._elide_mode = Qt.TextElideMode.ElideMiddle
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        super().setText(text)
        self.setText(text)

    def setText(self, text: str) -> None:  # type: ignore[override]
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._refresh()

    def text(self) -> str:  # type: ignore[override]
        return self._full_text

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if not self._full_text:
            super().setText("")
            return
        width = max(24, self.width() - 4)
        metrics = self.fontMetrics()
        super().setText(metrics.elidedText(self._full_text, self._elide_mode, width))


def configure_result_list(widget: QListWidget) -> None:
    """Use predictable clipping behavior for result lists."""
    widget.setObjectName("ResultList")
    widget.setSpacing(2)
    widget.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
