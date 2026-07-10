"""SendToToolButton — panel de envío a otra herramienta con motor de prioridad.

UI: un botón Ghost que al pulsarse muestra un panel flotante con chips por
herramienta, dividido en sección "Sugeridas" (basadas en el flujo de trabajo
típico de la herramienta actual) y "Otras herramientas".
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from shell.transfer import ToolTransfer
from ui.common.icons import icon, set_button_icon
from ui.styles import COLORS

if TYPE_CHECKING:
    from shell.context import ShellContext


# ── Motor de prioridad ────────────────────────────────────────────────────────
# Para cada herramienta origen, lista ordenada de destinos más probables.
# Las herramientas que no aparezcan se muestran en la sección "Otras".
PRIORITY_MAP: dict[str, list[str]] = {
    "compresor":        ["firmador", "protector", "unir", "membretado"],
    "firmador":         ["compresor", "protector", "redactor", "unir"],
    "organizador":      ["firmador", "compresor", "separador", "protector"],
    "marca_agua":       ["firmador", "compresor", "protector", "redactor"],
    "redactor":         ["firmador", "compresor", "protector", "unir"],
    "protector":        ["firmador", "compresor", "redactor", "unir"],
    "unir":             ["firmador", "compresor", "separador", "protector"],
    "separador":        ["compresor", "firmador", "unir", "protector"],
    "membretado":       ["firmador", "compresor", "protector", "redactor"],
    "foleador":         ["firmador", "compresor", "protector", "unir"],
    "formularios":      ["firmador", "compresor", "protector", "redactor"],
    "reparador":        ["compresor", "firmador", "organizador", "protector"],
    "comparador":       ["compresor", "firmador", "protector"],
    "clasificador":     ["compresor", "firmador", "protector", "organizador"],
    "pdf_to_imgs":      ["quitar_fondo", "imgs_a_pdf"],
    "pdf_to_word":      ["word_a_pdf", "compresor", "firmador"],
    "word_a_pdf":       ["compresor", "firmador", "protector", "unir"],
    "ocr":              ["compresor", "firmador", "protector"],
    "imgs_a_pdf":       ["compresor", "firmador", "protector", "unir"],
    "extraer_imagenes": ["quitar_fondo", "imgs_a_pdf"],
    "quitar_fondo":     ["imgs_a_pdf", "firmador"],
}

_MAX_SUGGESTED = 4
_CHIPS_PER_ROW = 4
_CHIP_W = 112
_CHIP_H = 76


# ── ToolChip ──────────────────────────────────────────────────────────────────

class _ToolChip(QFrame):
    """Card clickable que representa una herramienta destino."""

    def __init__(self, tool, callback, parent=None) -> None:
        super().__init__(parent)
        self._tool = tool
        self._callback = callback
        self._hovered = False
        self.setFixedSize(_CHIP_W, _CHIP_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        ico_lbl = QLabel()
        ico_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico_lbl.setPixmap(
            icon(tool.icon_name or "file-text", tool.accent_color, 22).pixmap(22, 22)
        )
        ico_lbl.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(ico_lbl)

        name_lbl = QLabel(tool.title)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 10px; font-weight: 600; "
            "background: transparent; border: none;"
        )
        layout.addWidget(name_lbl)

    def _apply_style(self) -> None:
        bg = "#21212B" if self._hovered else COLORS["surface_3"]
        self.setStyleSheet(
            f"QFrame {{ background: {bg}; "
            f"border: 1px solid {COLORS['border']}; "
            f"border-top: 3px solid {self._tool.accent_color}; "
            "border-radius: 8px; }"
        )

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._apply_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._callback()
        super().mousePressEvent(event)


# ── Panel flotante ────────────────────────────────────────────────────────────

class SendToToolPanel(QWidget):
    """Panel popup con chips agrupados por prioridad."""

    def __init__(
        self,
        ctx: "ShellContext",
        current_id: str,
        output_paths: List[str],
        parent=None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
        )
        self._ctx = ctx
        self._current_id = current_id
        self._output_paths = output_paths
        self._mode_buttons: dict[str, QPushButton] = {}
        self._tray_buttons: dict[str, QPushButton] = {}
        self._option_groups: list[QButtonGroup] = []
        self.setStyleSheet(
            f"background: {COLORS['surface_2']}; "
            f"border: 1px solid {COLORS['border_strong']};"
        )
        self._build()

    def _compatible_tools(self) -> list:
        from shell.tool_registry import TOOLS
        exts = {Path(p).suffix.lower() for p in self._output_paths if Path(p).suffix}
        return [
            t for t in TOOLS
            if t.enabled
            and t.id != self._current_id
            and exts.intersection(getattr(t, "input_extensions", (".pdf",)))
        ]

    def _build(self) -> None:
        all_tools = self._compatible_tools()
        priority_ids = PRIORITY_MAP.get(self._current_id, [])

        priority_tools: list = []
        priority_set: set[str] = set()
        for tid in priority_ids:
            t = next((x for x in all_tools if x.id == tid), None)
            if t and t.id not in priority_set:
                priority_tools.append(t)
                priority_set.add(t.id)

        other_tools = [t for t in all_tools if t.id not in priority_set]

        main = QVBoxLayout(self)
        main.setContentsMargins(16, 14, 16, 16)
        main.setSpacing(10)

        self._add_transfer_options(main)

        if not all_tools:
            lbl = QLabel("No hay herramientas compatibles")
            lbl.setStyleSheet(
                f"color: {COLORS['text_muted']}; font-size: 11px; border: none;"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            main.addWidget(lbl)
            return

        if priority_tools:
            self._add_section(main, "SUGERIDAS", priority_tools[:_MAX_SUGGESTED])

        if priority_tools and other_tools:
            sep = QFrame()
            sep.setFixedHeight(1)
            sep.setStyleSheet(
                f"background: {COLORS['border']}; border: none; border-radius: 0;"
            )
            main.addWidget(sep)

        if other_tools:
            heading = "TODAS LAS HERRAMIENTAS" if not priority_tools else "OTRAS HERRAMIENTAS"
            self._add_section(main, heading, other_tools)

    def _add_transfer_options(self, layout: QVBoxLayout) -> None:
        count = len(self._output_paths)
        count_lbl = QLabel(f"{count} archivo" + ("s" if count != 1 else ""))
        count_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; "
            "background: transparent; border: none;"
        )
        layout.addWidget(count_lbl)

        self._add_option_row(
            layout,
            "DESTINO",
            [
                ("replace", "Reemplazar"),
                ("append", "Agregar"),
            ],
            self._mode_buttons,
            default="replace",
        )
        self._add_option_row(
            layout,
            "BANDEJA",
            [
                ("keep", "Mantener"),
                ("replace_with_sent", "Solo enviados"),
                ("clear", "Limpiar"),
            ],
            self._tray_buttons,
            default="keep",
        )

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(
            f"background: {COLORS['border']}; border: none; border-radius: 0;"
        )
        layout.addWidget(sep)

    def _add_option_row(
        self,
        layout: QVBoxLayout,
        title: str,
        options: list[tuple[str, str]],
        target: dict[str, QPushButton],
        *,
        default: str,
    ) -> None:
        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 9px; font-weight: 700; "
            "letter-spacing: 1.0px; background: transparent; border: none;"
        )
        layout.addWidget(lbl)

        group = QButtonGroup(self)
        group.setExclusive(True)
        self._option_groups.append(group)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(0, 0, 0, 0)

        for value, text in options:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton {"
                f"background: {COLORS['surface_3']};"
                f"color: {COLORS['text_muted']};"
                f"border: 1px solid {COLORS['border']};"
                "border-radius: 6px;"
                "padding: 0 10px;"
                "font-size: 11px;"
                "font-weight: 600;"
                "}"
                "QPushButton:checked {"
                f"background: {COLORS['accent']};"
                f"color: {COLORS['bg']};"
                f"border-color: {COLORS['accent']};"
                "}"
                "QPushButton:hover {"
                f"border-color: {COLORS['border_strong']};"
                "}"
            )
            btn.setChecked(value == default)
            target[value] = btn
            group.addButton(btn)
            row.addWidget(btn)

        row.addStretch()
        layout.addLayout(row)

    def _selected_mode(self) -> str:
        return self._selected_value(self._mode_buttons, "replace")

    def _selected_tray_policy(self) -> str:
        return self._selected_value(self._tray_buttons, "keep")

    def _selected_value(self, buttons: dict[str, QPushButton], default: str) -> str:
        for value, button in buttons.items():
            if button.isChecked():
                return value
        return default

    def _current_tool_title(self) -> str:
        from shell.tool_registry import get_tool
        tool = get_tool(self._current_id)
        return getattr(tool, "title", None) or self._current_id

    def _add_section(self, layout: QVBoxLayout, title: str, tools: list) -> None:
        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 9px; font-weight: 700; "
            "letter-spacing: 1.0px; background: transparent; border: none;"
        )
        layout.addWidget(lbl)

        row_layout: QHBoxLayout | None = None
        for i, tool in enumerate(tools):
            if i % _CHIPS_PER_ROW == 0:
                row_layout = QHBoxLayout()
                row_layout.setSpacing(8)
                row_layout.setContentsMargins(0, 0, 0, 0)
                layout.addLayout(row_layout)
            chip = _ToolChip(tool, lambda t=tool: self._send_to(t), self)
            row_layout.addWidget(chip)

        if row_layout is not None and len(tools) % _CHIPS_PER_ROW != 0:
            row_layout.addStretch()

    def _send_to(self, tool) -> None:
        self.close()
        transfer = ToolTransfer(
            paths=list(self._output_paths),
            source_tool_id=self._current_id,
            source_tool_title=self._current_tool_title(),
            mode=self._selected_mode(),
            tray_policy=self._selected_tray_policy(),
            kind="output",
        )
        self._ctx.open_tool(tool.id, transfer)


# ── Botón de entrada ──────────────────────────────────────────────────────────

class SendToToolButton(QPushButton):
    """Botón Ghost que abre el panel de selección de herramienta destino."""

    def __init__(
        self,
        ctx: "ShellContext",
        current_tool_id: str,
        parent=None,
    ) -> None:
        super().__init__("Enviar a herramienta", parent)
        self._ctx = ctx
        self._current_id = current_tool_id
        self._output_paths: List[str] = []
        self._panel: SendToToolPanel | None = None
        self.setProperty("class", "Ghost")
        set_button_icon(self, "file-output", size=14)
        self.setToolTip("Abre los resultados en otra herramienta compatible.")
        self.clicked.connect(self._show_panel)
        self._refresh_visibility()

    def set_output_paths(self, paths: List[str]) -> None:
        self._output_paths = [p for p in paths if p]
        self._refresh_visibility()

    def _compatible_count(self) -> int:
        from shell.tool_registry import TOOLS
        exts = {Path(p).suffix.lower() for p in self._output_paths if Path(p).suffix}
        return sum(
            1 for t in TOOLS
            if t.enabled
            and t.id != self._current_id
            and exts.intersection(getattr(t, "input_extensions", (".pdf",)))
        )

    def _refresh_visibility(self) -> None:
        self.setVisible(bool(self._output_paths) and self._compatible_count() > 0)

    def _show_panel(self) -> None:
        if self._panel is not None:
            try:
                self._panel.close()
            except RuntimeError:
                pass
            self._panel = None

        panel = SendToToolPanel(
            self._ctx, self._current_id, self._output_paths
        )
        panel.adjustSize()
        sz = panel.sizeHint()

        screen = QApplication.primaryScreen().availableGeometry()
        btn_bl = self.mapToGlobal(self.rect().bottomLeft())
        btn_tl = self.mapToGlobal(self.rect().topLeft())

        pos_y = btn_bl.y() + 4
        if pos_y + sz.height() > screen.bottom() - 8:
            pos_y = btn_tl.y() - sz.height() - 4

        pos_x = btn_bl.x()
        if pos_x + sz.width() > screen.right() - 8:
            pos_x = screen.right() - sz.width() - 8
        pos_x = max(screen.left() + 8, pos_x)

        panel.move(pos_x, pos_y)
        panel.show()
        self._panel = panel
