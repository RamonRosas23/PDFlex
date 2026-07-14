"""LauncherWidget - catalogo de herramientas de PDFlex."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.update_config import APP_VERSION
from shell.tippy import TippyButton
from shell.tool_registry import TOOLS, ToolDescriptor
from shell.tool_usage import ToolUsageStore, rank_tool_ids
from ui.styles import COLORS


ICON_SIZE = 40
CARD_H = 100
GRID_SPACING = 12
CARD_MIN_W = 248
QUICK_LIMIT = 6


@dataclass(frozen=True)
class ToolSection:
    id: str
    title: str
    subtitle: str
    tool_ids: tuple[str, ...]


EDITORIAL_ORDER: tuple[str, ...] = (
    "firmador",
    "foleador",
    "separador",
    "unir",
    "membretado",
    "organizador",
    "compresor",
    "marca_agua",
    "subrayador",
    "quitar_logos",
    "redactor",
    "protector",
    "formularios",
    "comparador",
    "reparador",
    "word_a_pdf",
    "pdf_to_word",
    "pdf_to_imgs",
    "scan_simulator",
    "imgs_a_pdf",
    "extraer_imagenes",
    "quitar_fondo",
    "ocr",
    "clasificador",
)


BASE_SECTIONS: tuple[ToolSection, ...] = (
    ToolSection(
        id="esenciales",
        title="Esenciales",
        subtitle="Firma, folios, separación, unión y membretes",
        tool_ids=("firmador", "foleador", "separador", "unir", "membretado", "organizador"),
    ),
    ToolSection(
        id="preparar",
        title="Preparar y proteger",
        subtitle="Optimiza, sella, subraya, limpia, redacta, protege, valida y repara",
        tool_ids=("compresor", "marca_agua", "subrayador", "quitar_logos", "redactor", "protector", "formularios", "comparador", "reparador"),
    ),
    ToolSection(
        id="conversion",
        title="Conversión e imagen",
        subtitle="Word, imágenes, OCR, extracción y clasificación",
        tool_ids=("word_a_pdf", "pdf_to_word", "pdf_to_imgs", "scan_simulator", "imgs_a_pdf", "extraer_imagenes", "quitar_fondo", "ocr", "clasificador"),
    ),
)


def catalog_sections(tools: Iterable[ToolDescriptor] = TOOLS) -> list[ToolSection]:
    """Devuelve secciones visibles y agrega automaticamente herramientas nuevas."""
    tool_ids = [tool.id for tool in tools]
    existing = set(tool_ids)
    sections: list[ToolSection] = []
    assigned: set[str] = set()

    for section in BASE_SECTIONS:
        ids = tuple(tool_id for tool_id in section.tool_ids if tool_id in existing)
        if ids:
            sections.append(ToolSection(section.id, section.title, section.subtitle, ids))
            assigned.update(ids)

    extras = tuple(tool_id for tool_id in tool_ids if tool_id not in assigned)
    if extras:
        sections.append(ToolSection("otras", "Otras herramientas", "Nuevas incorporaciones", extras))

    return sections


def _make_tool_icon(letter: str, color: str, size: int = ICON_SIZE) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    base = QColor(color)
    cx = size / 2
    grad = QRadialGradient(cx, cx, cx)
    grad.setColorAt(0.0, QColor(base.red(), base.green(), base.blue(), 70))
    grad.setColorAt(0.62, QColor(base.red(), base.green(), base.blue(), 34))
    grad.setColorAt(1.0, QColor(base.red(), base.green(), base.blue(), 12))
    painter.setBrush(QBrush(grad))

    pen = QPen(QColor(color))
    pen.setWidthF(1.2)
    painter.setPen(pen)
    painter.drawEllipse(2, 2, size - 4, size - 4)

    font = QFont("Segoe UI Variable", int(size * 0.34), QFont.Weight.Bold)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, letter)
    painter.end()
    return pix


def _hex_components(hex_color: str) -> str:
    """'#5E6AD2' → '94, 106, 210' para usar en rgba()."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r}, {g}, {b}"


class ToolCard(QFrame):
    """Tarjeta compacta de herramienta."""

    def __init__(
        self,
        tool: ToolDescriptor,
        on_click: Callable[[], None],
        *,
        badge: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._tool = tool
        self._on_click = on_click if tool.enabled else None
        self._badge = badge

        self.setObjectName("LauncherCard")
        self.setFixedHeight(CARD_H)
        self.setMinimumWidth(CARD_MIN_W)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor if tool.enabled else Qt.CursorShape.ArrowCursor)
        self._apply_style(False)
        self._build_content()

    def _build_content(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 12, 12)
        layout.setSpacing(12)

        from ui.common.icons import make_tool_icon_card, icon_pixmap
        icon_lbl = QLabel()
        icon_lbl.setPixmap(make_tool_icon_card(self._tool.id, self._tool.accent_color, size=ICON_SIZE))
        icon_lbl.setFixedSize(ICON_SIZE, ICON_SIZE)
        icon_lbl.setStyleSheet("background: transparent;")
        layout.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        text_col.setContentsMargins(0, 0, 0, 0)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title = QLabel(self._tool.title)
        title.setObjectName("ToolCardTitle")
        title.setStyleSheet(
            f"color: {self._tool.accent_color}; "
            "background: transparent; border: none;"
        )
        title.setWordWrap(False)
        title_row.addWidget(title, 1)

        if self._badge:
            badge = QLabel(self._badge)
            badge.setObjectName("LauncherMiniBadge")
            badge.setStyleSheet(
                "QLabel#LauncherMiniBadge {"
                "color: #DCE2F2;"
                f"background: {COLORS['surface_2']};"
                f"border: 1px solid {COLORS['border_strong']};"
                "border-radius: 5px;"
                "padding: 1px 6px;"
                "font-size: 10px;"
                "font-weight: 800;"
                "letter-spacing: 0px;"
                "}"
            )
            title_row.addWidget(badge)

        text_col.addLayout(title_row)

        if not self._tool.enabled:
            coming = QLabel("Próximamente")
            coming.setObjectName("ComingSoonBadge")
            text_col.addWidget(coming)
        else:
            tagline = QLabel(self._tool.tagline)
            tagline.setObjectName("ToolCardTagline")
            tagline.setWordWrap(True)
            tagline.setMaximumHeight(40)
            tagline.setStyleSheet("background: transparent; border: none;")
            text_col.addWidget(tagline)

        layout.addLayout(text_col, 1)

        # Flecha visible solo en hover
        self._arrow_lbl = QLabel()
        self._arrow_lbl.setPixmap(icon_pixmap("arrow-right", self._tool.accent_color, 14))
        self._arrow_lbl.setFixedSize(16, 16)
        self._arrow_lbl.setVisible(False)
        self._arrow_lbl.setStyleSheet("background: transparent;")
        layout.addWidget(self._arrow_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        info_btn = TippyButton(self._tool.title, self._tool.description_md, self.window())
        layout.addWidget(info_btn, 0, Qt.AlignmentFlag.AlignTop)

    def _apply_style(self, hover: bool) -> None:
        if hover and self._tool.enabled:
            comp = _hex_components(self._tool.accent_color)
            self.setStyleSheet(
                f"QFrame#LauncherCard {{"
                f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
                f" stop:0 rgba({comp}, 0.08), stop:0.42 rgba({comp}, 0.04),"
                f" stop:1 {COLORS['surface']});"
                f"border: 1px solid rgba({comp}, 0.42);"
                f"border-radius: 8px;"
                f"}}"
            )
        else:
            self.setStyleSheet(
                "QFrame#LauncherCard {"
                f"background: {COLORS['surface']};"
                f"border: 1px solid {COLORS['border']};"
                "border-radius: 8px;"
                "}"
            )

    def enterEvent(self, event) -> None:
        self._apply_style(True)
        if hasattr(self, "_arrow_lbl"):
            self._arrow_lbl.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._apply_style(False)
        if hasattr(self, "_arrow_lbl"):
            self._arrow_lbl.setVisible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._on_click and event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mousePressEvent(event)


class LauncherWidget(QWidget):
    """Catalogo compacto, filtrable y ordenado por uso."""

    ready = Signal()  # emitida cuando todas las tarjetas están renderizadas

    def __init__(
        self,
        open_tool_fn: Callable[[str], None],
        *,
        usage_store: ToolUsageStore | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._open_tool_fn = open_tool_fn
        self._usage_store = usage_store or ToolUsageStore()
        self._tool_map = {tool.id: tool for tool in TOOLS}
        self._sections = catalog_sections(TOOLS)
        self._active_section = "all"
        self._current_cols = 0
        self._filter_buttons: dict[str, QPushButton] = {}
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("LauncherContent")
        content.setStyleSheet(f"QWidget#LauncherContent {{ background: {COLORS['bg']}; }}")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(36, 24, 36, 24)
        self._content_layout.setSpacing(16)

        self._build_header()

        self._sections_host = QWidget()
        self._sections_host.setStyleSheet("background: transparent;")
        self._sections_layout = QVBoxLayout(self._sections_host)
        self._sections_layout.setContentsMargins(0, 0, 0, 0)
        self._sections_layout.setSpacing(20)
        self._content_layout.addWidget(self._sections_host, 1)

        self._content_layout.addWidget(_make_footer())
        self._scroll.setWidget(content)
        root.addWidget(self._scroll)

        QTimer.singleShot(0, self._render_tools)

    def _build_header(self) -> None:
        command = QFrame()
        command.setObjectName("LauncherCommandBar")
        command_layout = QVBoxLayout(command)
        command_layout.setContentsMargins(0, 0, 0, 0)
        command_layout.setSpacing(10)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)

        title = QLabel("Herramientas")
        title.setObjectName("LauncherTitle")
        title.setStyleSheet("font-size: 24px; font-weight: 800; letter-spacing: 0px;")
        title_row.addWidget(title)

        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("LauncherCountBadge")
        title_row.addWidget(self._status_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        top.addLayout(title_row, 1)

        self._search = QLineEdit()
        self._search.setObjectName("LauncherSearch")
        self._search.setPlaceholderText("Buscar herramienta, acción o formato")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedHeight(34)
        self._search.setMinimumWidth(380)
        self._search.setMaximumWidth(560)
        self._search.setStyleSheet(
            "QLineEdit#LauncherSearch {"
            f"background: {COLORS['surface_2']};"
            f"border: 1px solid {COLORS['border_strong']};"
            "border-radius: 8px;"
            "padding: 0 13px 0 9px;"
            f"color: {COLORS['text']};"
            "font-weight: 600;"
            "}"
            f"QLineEdit#LauncherSearch:focus {{ border-color: {COLORS['accent']}; }}"
        )
        from ui.common.icons import icon
        self._search.addAction(
            icon("search", COLORS["text_dim"], 14),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self._search.textChanged.connect(self._render_tools)
        command_layout.addLayout(top)

        filter_bar = QFrame()
        filter_bar.setObjectName("LauncherFilterBar")
        filters = QHBoxLayout()
        filters.setContentsMargins(5, 5, 5, 5)
        filters.setSpacing(4)
        filter_bar.setLayout(filters)
        filter_defs = [("all", "Todo")] + [(section.id, section.title) for section in self._sections]
        for section_id, label in filter_defs:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.clicked.connect(lambda checked=False, sid=section_id: self._set_active_section(sid))
            self._filter_buttons[section_id] = btn
            filters.addWidget(btn)

        lower = QHBoxLayout()
        lower.setContentsMargins(0, 0, 0, 0)
        lower.setSpacing(10)
        lower.addWidget(filter_bar, 0, Qt.AlignmentFlag.AlignLeft)
        lower.addStretch(1)
        lower.addWidget(self._search, 0, Qt.AlignmentFlag.AlignRight)
        command_layout.addLayout(lower)

        self._content_layout.addWidget(command)
        self._apply_filter_styles()

    def _set_active_section(self, section_id: str) -> None:
        self._active_section = section_id
        self._apply_filter_styles()
        self._render_tools()

    def _apply_filter_styles(self) -> None:
        for section_id, btn in self._filter_buttons.items():
            active = section_id == self._active_section
            btn.setChecked(active)
            if active:
                btn.setStyleSheet(
                    "QPushButton {"
                    f"background: {COLORS['surface_3']};"
                    f"color: {COLORS['text']};"
                    f"border: 1px solid {COLORS['border_strong']};"
                    "border-radius: 7px;"
                    "padding: 0 12px;"
                    "font-size: 12px;"
                    "font-weight: 800;"
                    "letter-spacing: 0px;"
                    "}"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton {"
                    "background: transparent;"
                    f"color: {COLORS['text_muted']};"
                    "border: 1px solid transparent;"
                    "border-radius: 7px;"
                    "padding: 0 12px;"
                    "font-size: 12px;"
                    "font-weight: 700;"
                    "}"
                    "QPushButton:hover {"
                    f"color: {COLORS['text']};"
                    f"background: {COLORS['surface_3']};"
                    f"border-color: {COLORS['border']};"
                    "}"
                )

    def refresh_usage(self) -> None:
        self._render_tools()

    def _render_tools(self) -> None:
        if not hasattr(self, "_sections_layout"):
            return
        if getattr(self, "_rendering", False):
            return
        self._rendering = True
        try:
            _clear_layout(self._sections_layout)

            query = self._search.text().strip().casefold() if hasattr(self, "_search") else ""
            columns = self._preferred_columns()
            shown_count = 0

            if query:
                tools = [tool for tool in self._ordered_tools() if _matches_query(tool, query)]
                shown_count = len(tools)
                self._add_section("Resultados", f"{shown_count} coincidencia{'s' if shown_count != 1 else ''}", tools, columns)
            else:
                if self._active_section == "all":
                    quick_tools, label = self._quick_tools()
                    quick_ids = {tool.id for tool in quick_tools}
                    self._add_section(label, "Orden inteligente local", quick_tools, columns, quick=True)
                    for section in self._sections:
                        tools = self._tools_for_section(section, exclude_ids=quick_ids)
                        shown_count += len(tools)
                        self._add_section(section.title, section.subtitle, tools, columns)
                else:
                    section = next((s for s in self._sections if s.id == self._active_section), None)
                    tools = self._tools_for_section(section) if section else []
                    shown_count = len(tools)
                    self._add_section(section.title if section else "Herramientas", section.subtitle if section else "", tools, columns)

            if shown_count == 0:
                empty = QLabel("No se encontraron herramientas con esa búsqueda.")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                empty.setMinimumHeight(220)
                empty.setStyleSheet(
                    f"color: {COLORS['text_dim']}; font-size: 13px; background: transparent;"
                )
                self._sections_layout.addWidget(empty)

            self._sections_layout.addStretch(1)
            total = sum(1 for tool in TOOLS if tool.enabled)
            if query:
                self._status_lbl.setText(f"{shown_count} de {total}")
            elif self._active_section == "all":
                self._status_lbl.setText(f"{total} disponibles")
            else:
                self._status_lbl.setText(f"{shown_count} en sección")
            self._current_cols = columns
        finally:
            self._rendering = False
            self.ready.emit()

    def _add_section(
        self,
        title: str,
        subtitle: str,
        tools: list[ToolDescriptor],
        columns: int,
        *,
        quick: bool = False,
    ) -> None:
        if not tools:
            return
        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        layout.addWidget(_make_section_header(title, subtitle, len(tools)))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(GRID_SPACING)
        for col in range(columns):
            grid.setColumnStretch(col, 1)

        for index, tool in enumerate(tools):
            badge = str(index + 1) if quick else ""
            card = ToolCard(tool, lambda tid=tool.id: self._open_tool_fn(tid), badge=badge)
            grid.addWidget(card, index // columns, index % columns)

        layout.addLayout(grid)
        self._sections_layout.addWidget(wrapper)

    def _quick_tools(self) -> tuple[list[ToolDescriptor], str]:
        available_ids = [tool.id for tool in TOOLS if tool.enabled]
        usage = self._usage_store.snapshot(available_ids)
        ranked_ids = rank_tool_ids(
            available_ids,
            usage,
            EDITORIAL_ORDER,
            limit=QUICK_LIMIT,
        )
        label = "Más usadas" if self._usage_store.has_usage(available_ids) else "Accesos rápidos"
        return [self._tool_map[tool_id] for tool_id in ranked_ids if tool_id in self._tool_map], label

    def _tools_for_section(
        self,
        section: ToolSection | None,
        *,
        exclude_ids: set[str] | None = None,
    ) -> list[ToolDescriptor]:
        if section is None:
            return []
        excluded = exclude_ids or set()
        return [
            self._tool_map[tool_id]
            for tool_id in _section_tool_ids(section, excluded)
            if tool_id in self._tool_map
        ]

    def _ordered_tools(self) -> list[ToolDescriptor]:
        by_id = self._tool_map
        ids = [tool_id for tool_id in EDITORIAL_ORDER if tool_id in by_id]
        ids.extend(tool.id for tool in TOOLS if tool.id not in ids)
        return [by_id[tool_id] for tool_id in ids]

    def _preferred_columns(self) -> int:
        viewport_width = self._scroll.viewport().width() if hasattr(self, "_scroll") else 0
        width = max(self.width(), viewport_width)
        content_width = max(520, width - 72)
        if content_width >= 1680:
            return 5
        if content_width >= 1180:
            return 4
        if content_width >= 820:
            return 3
        return 2

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_sections_layout"):
            columns = self._preferred_columns()
            if columns != self._current_cols:
                self._render_tools()


def _make_section_header(title: str, subtitle: str, count: int) -> QWidget:
    header = QWidget()
    header.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    title_lbl = QLabel(title)
    title_lbl.setStyleSheet(
        f"color: {COLORS['text']}; font-size: 15px; font-weight: 800; "
        "letter-spacing: 0px; background: transparent;"
    )
    layout.addWidget(title_lbl)

    count_lbl = QLabel(str(count))
    count_lbl.setStyleSheet(
        f"color: {COLORS['text_muted']};"
        f"background: {COLORS['surface_2']};"
        f"border: 1px solid {COLORS['border']};"
        "border-radius: 6px;"
        "padding: 1px 7px;"
        "font-size: 11px;"
        "font-weight: 700;"
    )
    layout.addWidget(count_lbl)

    if subtitle:
        sub = QLabel(subtitle)
        sub.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px; background: transparent;")
        layout.addWidget(sub)

    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"background: {COLORS['border_strong']}; border: none; max-height: 1px;")
    layout.addWidget(line, 1)
    return header


def _section_tool_ids(section: ToolSection, excluded_ids: set[str] | None = None) -> tuple[str, ...]:
    excluded = excluded_ids or set()
    return tuple(tool_id for tool_id in section.tool_ids if tool_id not in excluded)


def _make_footer() -> QWidget:
    footer = QWidget()
    layout = QHBoxLayout(footer)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    n_tools = sum(1 for tool in TOOLS if tool.enabled)
    label = QLabel(f"GRUPO OCMX  ·  {n_tools} herramientas disponibles")
    label.setStyleSheet(f"color: {COLORS['text_faint']}; font-size: 11px; background: transparent;")
    layout.addWidget(label)
    layout.addStretch(1)

    version = QLabel(f"v{APP_VERSION}")
    version.setStyleSheet(f"color: {COLORS['text_faint']}; font-size: 11px; background: transparent;")
    layout.addWidget(version)
    return footer


def _matches_query(tool: ToolDescriptor, query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        (
            tool.id,
            tool.title,
            tool.tagline,
            tool.description_md,
            " ".join(tool.input_extensions),
        )
    ).casefold()
    return all(part in haystack for part in query.split())


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        child_layout = item.layout()
        widget = item.widget()
        if child_layout is not None:
            _clear_layout(child_layout)
        if widget is not None:
            widget.deleteLater()
