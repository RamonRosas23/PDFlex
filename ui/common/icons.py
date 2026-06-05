"""Small inline SVG icon set for PyQt widgets.

Keeps UI iconography independent from system fonts and avoids embedding
decorative Unicode glyphs directly in labels/buttons.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QRectF, QByteArray
from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QLabel, QPushButton

# ── Ícono de la aplicación ────────────────────────────────────────────────────

def _app_assets_base() -> Path:
    """Raíz de assets compatible con desarrollo, PyInstaller y Nuitka."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def app_qicon() -> QIcon:
    """Devuelve el QIcon de la aplicación (assets/icon.ico)."""
    ico = _app_assets_base() / "assets" / "icon.ico"
    if ico.exists():
        return QIcon(str(ico))
    return QIcon()


def app_pixmap(size: int = 48) -> QPixmap:
    """Devuelve el ícono de la app como QPixmap escalado (assets/icon.png)."""
    png = _app_assets_base() / "assets" / "icon.png"
    if png.exists():
        pix = QPixmap(str(png))
        if not pix.isNull():
            return pix.scaled(
                size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
    # Fallback: ícono SVG genérico
    return icon_pixmap("file-text", "#5E6AD2", size)


DEFAULT_ICON_COLOR = "#ECEDEE"

_BASE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" """
_BASE_SVG += """viewBox="0 0 24 24" fill="none" stroke="{color}" """
_BASE_SVG += """stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>"""

_ICONS = {
    "arrow-left": '<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "check": '<path d="m20 6-11 11-5-5"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "warning": '<path d="m21 16-8.7-15a1 1 0 0 0-1.7 0L2 16a1 1 0 0 0 .9 1.5h18.2A1 1 0 0 0 21 16Z"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
    "refresh-cw": '<path d="M21 12a9 9 0 0 1-15.5 6.3"/><path d="M3 12A9 9 0 0 1 18.5 5.7"/><path d="M18 2v4h4"/><path d="M6 22v-4H2"/>',
    "folder-open": '<path d="M6 17 8 9h12a2 2 0 0 1 2 2l-2 6a2 2 0 0 1-2 1.5H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5l2 2h4a2 2 0 0 1 2 2v1"/>',
    "file-text": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>',
    "divide": '<path d="M5 12h14"/><path d="M12 6h.01"/><path d="M12 18h.01"/>',
    "list": '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>',
    "dot": '<circle cx="12" cy="12" r="3" fill="{color}" stroke="none"/>',
    "loader": '<path d="M21 12a9 9 0 0 1-9 9"/><path d="M12 3a9 9 0 0 1 9 9"/>',
    "maximize": '<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M16 3h3a2 2 0 0 1 2 2v3"/><path d="M21 16v3a2 2 0 0 1-2 2h-3"/><path d="M8 21H5a2 2 0 0 1-2-2v-3"/>',
    "folder": '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7l-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2Z"/>',
    "trash-2": '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>',
    "eraser": '<path d="m7 21-4-4a2 2 0 0 1 0-2.8L14.2 3a2 2 0 0 1 2.8 0l4 4a2 2 0 0 1 0 2.8L9.8 21Z"/><path d="M22 21H7"/><path d="m5 12 7 7"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
    "play": '<path d="m5 3 14 9-14 9Z"/>',
    "square": '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "external-link": '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "file-output": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h7"/><path d="M14 2v6h6"/><path d="M16 18h6"/><path d="m19 15 3 3-3 3"/>',
    "settings": '<path d="M12.2 2h-.4a2 2 0 0 0-2 1.7l-.1.8a8 8 0 0 0-1.8.8l-.7-.5a2 2 0 0 0-2.6.2l-.3.3a2 2 0 0 0-.2 2.6l.5.7a8 8 0 0 0-.8 1.8l-.8.1A2 2 0 0 0 1.3 12v.4a2 2 0 0 0 1.7 2l.8.1a8 8 0 0 0 .8 1.8l-.5.7a2 2 0 0 0 .2 2.6l.3.3a2 2 0 0 0 2.6.2l.7-.5a8 8 0 0 0 1.8.8l.1.8a2 2 0 0 0 2 1.7h.4a2 2 0 0 0 2-1.7l.1-.8a8 8 0 0 0 1.8-.8l.7.5a2 2 0 0 0 2.6-.2l.3-.3a2 2 0 0 0 .2-2.6l-.5-.7a8 8 0 0 0 .8-1.8l.8-.1a2 2 0 0 0 1.7-2V12a2 2 0 0 0-1.7-2l-.8-.1a8 8 0 0 0-.8-1.8l.5-.7a2 2 0 0 0-.2-2.6l-.3-.3a2 2 0 0 0-2.6-.2l-.7.5a8 8 0 0 0-1.8-.8l-.1-.8a2 2 0 0 0-2-1.7Z"/><circle cx="12" cy="12" r="3"/>',
}


def _svg(name: str, color: str) -> bytes:
    body = _ICONS[name].format(color=color)
    return _BASE_SVG.format(color=color, body=body).encode("utf-8")


@lru_cache(maxsize=512)
def icon_pixmap(
    name: str,
    color: str = DEFAULT_ICON_COLOR,
    size: int = 16,
    rotate_degrees: int = 0,
) -> QPixmap:
    """Render an SVG icon to a pixmap."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    renderer = QSvgRenderer(QByteArray(_svg(name, color)))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if rotate_degrees:
        painter.translate(size / 2, size / 2)
        painter.rotate(rotate_degrees)
        painter.translate(-size / 2, -size / 2)

    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pix


def icon(name: str, color: str = DEFAULT_ICON_COLOR, size: int = 16) -> QIcon:
    return QIcon(icon_pixmap(name, color, size))


def set_button_icon(
    button: QPushButton,
    name: str,
    *,
    color: str = DEFAULT_ICON_COLOR,
    size: int = 16,
    icon_only: bool = False,
) -> None:
    button.setIcon(icon(name, color, size))
    button.setIconSize(QSize(size, size))
    if icon_only:
        button.setText("")


def make_icon_label(
    name: str,
    *,
    color: str = DEFAULT_ICON_COLOR,
    size: int = 24,
    parent=None,
) -> QLabel:
    label = QLabel(parent)
    label.setPixmap(icon_pixmap(name, color, size))
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet("background: transparent;")
    return label
