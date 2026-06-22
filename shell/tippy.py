"""TippyButton — botón informativo con popover de ayuda contextual.

Uso:
    btn = TippyButton("Formato de folio", "Usa {n:05} para ...\n\n**Ejemplos:**\n...")
    layout.addWidget(btn)
"""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextBrowser,
)

from ui.common.icons import set_button_icon
from ui.styles import COLORS


class TippyPopover(QFrame):
    """Ventana flotante con título + contenido de ayuda."""

    def __init__(self, title: str, body: str, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("TippyPopover")
        from ui.common.icons import app_qicon
        self.setWindowIcon(app_qicon())
        self.setMinimumWidth(340)
        self.setMaximumWidth(440)
        self.setMaximumHeight(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        # Header
        header_row = QHBoxLayout()
        title_lbl = QLabel(title)
        title_lbl.setObjectName("TippyTitle")
        title_lbl.setWordWrap(True)
        close_btn = QPushButton()
        close_btn.setProperty("class", "IconBtn")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            "QPushButton {"
            f"background: {COLORS['surface_2']};"
            f"border: 1px solid {COLORS['border']};"
            "border-radius: 6px;"
            "padding: 0;"
            "min-width: 28px;"
            "max-width: 28px;"
            "min-height: 28px;"
            "max-height: 28px;"
            "}"
            f"QPushButton:hover {{ border-color: {COLORS['border_strong']}; }}"
        )
        set_button_icon(close_btn, "x", size=14, icon_only=True)
        close_btn.clicked.connect(self.close)
        header_row.addWidget(title_lbl, 1)
        header_row.addWidget(close_btn)
        layout.addLayout(header_row)

        # Divisor
        div = QFrame()
        div.setProperty("class", "Divider")
        div.setFixedHeight(1)
        layout.addWidget(div)

        # Contenido
        browser = QTextBrowser()
        browser.setObjectName("TippyBody")
        browser.setOpenExternalLinks(False)
        browser.setReadOnly(True)
        browser.setFrameShape(QFrame.Shape.NoFrame)
        # Convierte texto simple a HTML básico preservando saltos de línea
        html = self._to_html(body)
        browser.setHtml(html)
        browser.setMinimumHeight(160)
        browser.setMaximumHeight(320)
        layout.addWidget(browser, 1)

    @staticmethod
    def _to_html(text: str) -> str:
        """Convierte texto con **negrita**, `código` y saltos de línea a HTML."""
        import re
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        lines = text.split("\n")
        html_lines = []
        for line in lines:
            if line.startswith("- "):
                html_lines.append(f"&nbsp;&nbsp;• {line[2:]}")
            else:
                html_lines.append(line if line else "<br>")
        return (
            "<style>"
            f"body {{ color: {COLORS['text']}; background: transparent; font-size: 12px; }}"
            f"code {{ background: {COLORS['surface_3']}; padding: 1px 4px; border-radius: 3px; }}"
            f"b {{ color: {COLORS['text']}; }}"
            "</style>"
            + "<br>".join(html_lines)
        )


class TippyButton(QPushButton):
    """Botón circular de ayuda que abre un TippyPopover al pulsarlo."""

    def __init__(self, title: str, body: str, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._body = body
        self._popup: TippyPopover | None = None
        self.setProperty("class", "TippyBtn")
        self.setFixedSize(24, 24)
        set_button_icon(self, "info", size=15, icon_only=True)
        self.setToolTip(title)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._toggle_popup)

    def _toggle_popup(self) -> None:
        if self._popup and self._popup.isVisible():
            self._popup.close()
            self._popup = None
            return
        self._popup = TippyPopover(self._title, self._body, self.window())
        from ui.common.popup_utils import smart_popup_pos
        self._popup.ensurePolished()
        hint = self._popup.sizeHint()
        size = QSize(
            min(440, max(340, hint.width())),
            min(420, max(220, hint.height())),
        )
        self._popup.resize(size)
        pos = smart_popup_pos(
            self,
            popup_w=self._popup.width(),
            popup_h=self._popup.height(),
            prefer="below-right",
        )
        self._popup.move(pos)
        self._popup.show()
        self._popup.raise_()
