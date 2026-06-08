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
    "rotate-ccw": '<path d="M3 12a9 9 0 1 0 9-9 9.8 9.8 0 0 0-6.7 2.7L3 8"/><path d="M3 3v5h5"/>',
    "rotate-cw": '<path d="M21 12a9 9 0 1 1-9-9 9.8 9.8 0 0 1 6.7 2.7L21 8"/><path d="M21 3v5h-5"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/><rect x="2" y="2" width="13" height="13" rx="2"/>',
    "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9"/><path d="m14.5 14.5 5.5 5.5"/><path d="M8.1 8.1 12 12"/>',
    "panel-top": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/>',
    "columns": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
    "more-horizontal": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    "arrow-up-down": '<path d="m21 16-4 4-4-4"/><path d="M17 20V4"/><path d="m3 8 4-4 4 4"/><path d="M7 4v16"/>',
    # ── Iconos de herramientas PDFlex ─────────────────────────────────────
    "tool-firmador": (
        '<path d="M12 19l7-7 3 3-7 7-3-3z"/>'
        '<path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z"/>'
        '<path d="M2 2l7.5 7.5"/>'
    ),
    "tool-foleador": (
        '<line x1="4" y1="9" x2="20" y2="9"/>'
        '<line x1="4" y1="15" x2="20" y2="15"/>'
        '<line x1="10" y1="3" x2="8" y2="21"/>'
        '<line x1="16" y1="3" x2="14" y2="21"/>'
    ),
    "tool-separador": (
        '<circle cx="6" cy="6" r="3"/>'
        '<circle cx="6" cy="18" r="3"/>'
        '<path d="M20 4 8.1 15.9"/>'
        '<path d="m14.5 14.5 5.5 5.5"/>'
        '<path d="M8.1 8.1 12 12"/>'
    ),
    "tool-unir": (
        '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/>'
        '<path d="m6.08 9.5-3.5 1.6a1 1 0 0 0 0 1.81l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9a1 1 0 0 0 0-1.83l-3.5-1.59"/>'
        '<path d="m6.08 14.5-3.5 1.6a1 1 0 0 0 0 1.81l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9a1 1 0 0 0 0-1.83l-3.5-1.59"/>'
    ),
    "tool-membretado": (
        '<rect width="18" height="7" x="3" y="3" rx="1"/>'
        '<rect width="9" height="7" x="3" y="14" rx="1"/>'
        '<rect width="5" height="7" x="16" y="14" rx="1"/>'
    ),
    "tool-organizador": (
        '<rect x="3" y="3" width="7" height="7" rx="1"/>'
        '<rect x="14" y="3" width="7" height="7" rx="1"/>'
        '<rect x="3" y="14" width="7" height="7" rx="1"/>'
        '<rect x="14" y="14" width="7" height="7" rx="1"/>'
    ),
    "tool-compresor": (
        '<polyline points="5 15 3 15 3 21 9 21 9 19"/>'
        '<polyline points="19 9 21 9 21 3 15 3 15 5"/>'
        '<line x1="3" y1="21" x2="9" y2="15"/>'
        '<line x1="21" y1="3" x2="15" y2="9"/>'
    ),
    "tool-marca-agua": (
        '<path d="M7 16.3c2.2 0 4-1.83 4-4.05 0-1.16-.57-2.26-1.71-3.19S7.29 6.75 7 5.3c-.29 1.45-1.14 2.84-2.29 3.76S3 11.1 3 12.25c0 2.22 1.8 4.05 4 4.05z"/>'
        '<path d="M12.56 6.6A10.97 10.97 0 0 0 14 3.02c.5 2.5 2 4.9 4 6.5s3 3.5 3 5.5a6.98 6.98 0 0 1-11.91 4.97"/>'
    ),
    "tool-redactor": (
        '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696a10.747 10.747 0 0 1-1.444 2.49"/>'
        '<path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/>'
        '<path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696a10.75 10.75 0 0 1 4.446-5.143"/>'
        '<path d="m2 2 20 20"/>'
    ),
    "tool-protector": (
        '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    "tool-formularios": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/>'
        '<path d="M14 2v6h6"/>'
        '<path d="M16 13H8"/>'
        '<path d="M16 17H8"/>'
        '<path d="M10 9H8"/>'
    ),
    "tool-comparador": (
        '<circle cx="18" cy="18" r="3"/>'
        '<circle cx="6" cy="6" r="3"/>'
        '<path d="M13 6h3a2 2 0 0 1 2 2v7"/>'
        '<path d="M11 18H8a2 2 0 0 1-2-2V9"/>'
        '<path d="m16 6-2-2 2-2"/>'
        '<path d="m8 18 2 2-2 2"/>'
    ),
    "tool-reparador": (
        '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>'
    ),
    "tool-word-a-pdf": (
        '<path d="M4 22h14a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v4"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<path d="M2 13v-1h6v1"/>'
        '<path d="M5 12v6"/>'
        '<path d="M3 18h4"/>'
    ),
    "tool-pdf-to-word": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/>'
        '<path d="M14 2v6h6"/>'
        '<path d="M9 13h1l1 4 1.5-3 1.5 3 1-4h1"/>'
    ),
    "tool-pdf-to-imgs": (
        '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/>'
        '<circle cx="9" cy="9" r="2"/>'
        '<path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>'
    ),
    "tool-imgs-a-pdf": (
        '<path d="M18 22H4a2 2 0 0 1-2-2V6"/>'
        '<path d="m22 13-1.296-1.296a2.41 2.41 0 0 0-3.408 0L11 18"/>'
        '<circle cx="12" cy="8" r="2"/>'
        '<rect width="16" height="16" x="6" y="2" rx="2"/>'
    ),
    "tool-extraer-imagenes": (
        '<path d="M10.3 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10l-3.1-3.1a2 2 0 0 0-2.814.014L6 21"/>'
        '<path d="m14 19.5 3 3v-6"/>'
        '<path d="m17 22.5 3-3"/>'
        '<circle cx="9" cy="9" r="2"/>'
    ),
    "tool-quitar-fondo": (
        '<path d="m7 21-4-4a2 2 0 0 1 0-2.8L14.2 3a2 2 0 0 1 2.8 0l4 4a2 2 0 0 1 0 2.8L9.8 21Z"/>'
        '<path d="M22 21H7"/>'
        '<path d="m5 12 7 7"/>'
    ),
    "tool-ocr": (
        '<path d="M3 7V5a2 2 0 0 1 2-2h2"/>'
        '<path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
        '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/>'
        '<path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
        '<line x1="7" y1="8" x2="17" y2="8"/>'
        '<line x1="7" y1="12" x2="17" y2="12"/>'
        '<line x1="7" y1="16" x2="13" y2="16"/>'
    ),
    "tool-clasificador": (
        '<path d="M9 5H2v7l6.29 6.29c.94.94 2.48.94 3.42 0l3.58-3.58c.94-.94.94-2.48 0-3.42L9 5Z"/>'
        '<path d="M6 9.01V9"/>'
        '<path d="m15 5 6.3 6.3a2.4 2.4 0 0 1 0 3.4L17 19"/>'
    ),
}


# Mapping herramienta_id → nombre del icono en _ICONS
TOOL_ICON_MAP: dict[str, str] = {
    "firmador":          "tool-firmador",
    "foleador":          "tool-foleador",
    "separador":         "tool-separador",
    "unir":              "tool-unir",
    "membretado":        "tool-membretado",
    "organizador":       "tool-organizador",
    "compresor":         "tool-compresor",
    "marca_agua":        "tool-marca-agua",
    "redactor":          "tool-redactor",
    "protector":         "tool-protector",
    "formularios":       "tool-formularios",
    "comparador":        "tool-comparador",
    "reparador":         "tool-reparador",
    "word_a_pdf":        "tool-word-a-pdf",
    "pdf_to_word":       "tool-pdf-to-word",
    "pdf_to_imgs":       "tool-pdf-to-imgs",
    "imgs_a_pdf":        "tool-imgs-a-pdf",
    "extraer_imagenes":  "tool-extraer-imagenes",
    "quitar_fondo":      "tool-quitar-fondo",
    "ocr":               "tool-ocr",
    "clasificador":      "tool-clasificador",
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


def make_tool_icon_card(
    tool_id: str,
    accent: str,
    size: int = 40,
) -> "QPixmap":
    """Renders a tool's SVG icon on a tinted rounded-square background.

    Replaces the letter+radial-gradient circle used by the old launcher.
    """
    from PyQt6.QtGui import QBrush, QColor, QPen  # QPixmap, QPainter, QSvgRenderer, etc. ya en módulo

    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    base = QColor(accent)
    r, g, b = base.red(), base.green(), base.blue()

    bg = QColor(r, g, b, 28)
    border_color = QColor(r, g, b, 60)
    painter.setBrush(QBrush(bg))
    painter.setPen(QPen(border_color, 1.0))
    radius = size * 0.28
    painter.drawRoundedRect(QRectF(1, 1, size - 2, size - 2), radius, radius)

    icon_name = TOOL_ICON_MAP.get(tool_id, "file-text")
    icon_sz = int(size * 0.58)
    offset = (size - icon_sz) // 2
    body = _ICONS.get(icon_name, _ICONS.get("file-text", ""))
    svg_bytes = QByteArray(
        _BASE_SVG.format(color=accent, body=body).encode("utf-8")
    )
    renderer = QSvgRenderer(svg_bytes)
    renderer.render(painter, QRectF(offset, offset, icon_sz, icon_sz))

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
