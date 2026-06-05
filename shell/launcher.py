"""LauncherWidget — pantalla de inicio de la suite PDFlex."""
from __future__ import annotations
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QPixmap, QPainter, QColor, QFont, QRadialGradient, QBrush, QPen,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFrame, QLabel, QScrollArea, QSizePolicy,
)

from core.update_config import APP_VERSION
from shell.tool_registry import TOOLS, ToolDescriptor
from shell.tippy import TippyButton


# ──────────────────────────────────────────────
# Constantes de diseño
# ──────────────────────────────────────────────
ICON_SIZE    = 60
GRID_COLS    = 3
GRID_SPACING = 14
CARD_H       = 120

CATEGORIES = [
    ("Documentos PDF", ["firmador", "foleador", "separador", "membretado", "unir"]),
    ("Conversión e imagen", ["word_a_pdf", "pdf_to_imgs", "imgs_a_pdf", "quitar_fondo", "ocr"]),
]


# ──────────────────────────────────────────────
# Icono circular con gradiente radial
# ──────────────────────────────────────────────

def _make_tool_icon(letter: str, color: str, size: int = ICON_SIZE) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    base = QColor(color)
    cx = size / 2

    grad = QRadialGradient(cx, cx, cx)
    grad.setColorAt(0.0,  QColor(base.red(), base.green(), base.blue(), 72))
    grad.setColorAt(0.55, QColor(base.red(), base.green(), base.blue(), 44))
    grad.setColorAt(1.0,  QColor(base.red(), base.green(), base.blue(), 16))
    painter.setBrush(QBrush(grad))

    pen = QPen(QColor(color))
    pen.setWidthF(1.5)
    painter.setPen(pen)
    painter.drawEllipse(2, 2, size - 4, size - 4)

    font = QFont("Segoe UI Variable", int(size * 0.33), QFont.Weight.Bold)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, letter)

    painter.end()
    return pix


# ──────────────────────────────────────────────
# Tarjeta de herramienta
# ──────────────────────────────────────────────

class ToolCard(QFrame):
    """Tarjeta individual adaptativa con hover de acento."""

    def __init__(
        self,
        tool: ToolDescriptor,
        on_click: Callable[[], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._tool = tool
        self._on_click = on_click if tool.enabled else None

        self.setObjectName("LauncherCard")
        self.setFixedHeight(CARD_H)
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if tool.enabled
            else Qt.CursorShape.ArrowCursor
        )
        self._apply_style(hover=False)
        self._build_content()

    # ── Layout ─────────────────────────────────

    def _build_content(self) -> None:
        h = QHBoxLayout(self)
        h.setContentsMargins(20, 14, 16, 14)
        h.setSpacing(16)

        # Icono circular
        icon_lbl = QLabel()
        icon_lbl.setPixmap(
            _make_tool_icon(self._tool.icon_letter, self._tool.accent_color, ICON_SIZE)
        )
        icon_lbl.setFixedSize(ICON_SIZE, ICON_SIZE)
        icon_lbl.setStyleSheet("background: transparent;")
        h.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        # Columna de texto: título arriba, tagline abajo
        text = QVBoxLayout()
        text.setSpacing(5)
        text.setContentsMargins(0, 0, 0, 0)

        title_lbl = QLabel(self._tool.title)
        title_lbl.setStyleSheet(
            f"color: {self._tool.accent_color}; font-size: 15px; font-weight: 700;"
            "letter-spacing: -0.2px; background: transparent; border: none;"
        )
        text.addWidget(title_lbl)

        if not self._tool.enabled:
            badge = QLabel("Próximamente")
            badge.setObjectName("ComingSoonBadge")
            text.addWidget(badge)
        else:
            tagline = QLabel(self._tool.tagline)
            tagline.setStyleSheet(
                "color: #9094A0; font-size: 12px; background: transparent; border: none;"
            )
            tagline.setWordWrap(True)
            text.addWidget(tagline)

        h.addLayout(text, 1)

        # Botón de info (esquina superior derecha)
        info_btn = TippyButton(self._tool.title, self._tool.description_md, self.window())
        h.addWidget(info_btn, 0, Qt.AlignmentFlag.AlignTop)

    # ── Estilo ─────────────────────────────────

    def _apply_style(self, hover: bool) -> None:
        accent = self._tool.accent_color
        if hover and self._tool.enabled:
            self.setStyleSheet(f"""
                QFrame#LauncherCard {{
                    background: #15151B;
                    border: 1px solid {accent};
                    border-radius: 10px;
                }}
            """)
        else:
            self.setStyleSheet("""
                QFrame#LauncherCard {
                    background: #111114;
                    border: 1px solid #26262C;
                    border-radius: 10px;
                }
            """)

    # ── Eventos ────────────────────────────────

    def enterEvent(self, event) -> None:
        if self._tool.enabled:
            self._apply_style(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._apply_style(hover=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._on_click and event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mousePressEvent(event)


# ──────────────────────────────────────────────
# Encabezado de categoría
# ──────────────────────────────────────────────

def _make_category_header(label: str) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(12)

    lbl = QLabel(label.upper())
    lbl.setStyleSheet(
        "color: #6B6F7A; font-size: 10px; font-weight: 700;"
        "letter-spacing: 1.4px; background: transparent;"
    )
    h.addWidget(lbl)

    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("background: #26262C; border: none; max-height: 1px;")
    h.addWidget(line, 1)

    return w


# ──────────────────────────────────────────────
# Widget principal del launcher
# ──────────────────────────────────────────────

class LauncherWidget(QWidget):
    """Pantalla de inicio con cuadrícula adaptativa de herramientas."""

    def __init__(self, open_tool_fn: Callable[[str], None], parent=None) -> None:
        super().__init__(parent)
        self._build(open_tool_fn)

    def _build(self, open_tool_fn: Callable[[str], None]) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(52, 52, 52, 52)
        v.setSpacing(40)

        tool_map = {t.id: t for t in TOOLS}

        for cat_label, tool_ids in CATEGORIES:
            cat_tools = [tool_map[tid] for tid in tool_ids if tid in tool_map]
            if not cat_tools:
                continue

            section = QVBoxLayout()
            section.setSpacing(14)
            section.setContentsMargins(0, 0, 0, 0)

            section.addWidget(_make_category_header(cat_label))

            grid = QGridLayout()
            grid.setSpacing(GRID_SPACING)
            grid.setAlignment(Qt.AlignmentFlag.AlignTop)
            for col in range(GRID_COLS):
                grid.setColumnStretch(col, 1)

            for idx, tool in enumerate(cat_tools):
                card = ToolCard(
                    tool,
                    on_click=lambda tid=tool.id: open_tool_fn(tid),
                )
                grid.addWidget(card, idx // GRID_COLS, idx % GRID_COLS)

            section.addLayout(grid)
            v.addLayout(section)

        v.addStretch()
        v.addWidget(_make_footer())

        scroll.setWidget(content)
        root.addWidget(scroll)


# ──────────────────────────────────────────────
# Footer
# ──────────────────────────────────────────────

def _make_footer() -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(0)

    n_tools = sum(1 for t in TOOLS if t.enabled)
    lbl = QLabel(f"GRUPO OCMX  ·  {n_tools} herramientas disponibles")
    lbl.setStyleSheet("color: #3D3D45; font-size: 11px; background: transparent;")
    h.addWidget(lbl)
    h.addStretch()

    ver = QLabel(f"v{APP_VERSION}")
    ver.setStyleSheet("color: #3D3D45; font-size: 11px; background: transparent;")
    h.addWidget(ver)

    return w
