"""SendToToolButton — botón "Enviar a otra herramienta" reutilizable.

Aparece en el paso Resultados de cada herramienta.
Se oculta automáticamente si no hay otras herramientas habilitadas.
"""
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING, List

from PyQt6.QtWidgets import QPushButton, QMenu

from ui.common.icons import set_button_icon

if TYPE_CHECKING:
    from shell.context import ShellContext


class SendToToolButton(QPushButton):

    def __init__(self, ctx: "ShellContext", current_tool_id: str, parent=None) -> None:
        super().__init__("Enviar a otra herramienta", parent)
        self._ctx = ctx
        self._current_id = current_tool_id
        self._output_paths: List[str] = []
        self.setProperty("class", "Ghost")
        set_button_icon(self, "file-output", size=14)
        self.setToolTip("Abre los resultados actuales en otra herramienta compatible.")
        self.clicked.connect(self._show_menu)
        self._refresh_visibility()

    # ------------------------------------------------------------------ #

    def set_output_paths(self, paths: List[str]) -> None:
        self._output_paths = [p for p in paths if p]
        self._refresh_visibility()

    # ------------------------------------------------------------------ #

    def _other_tools(self):
        from shell.tool_registry import TOOLS
        output_exts = {
            Path(path).suffix.lower()
            for path in self._output_paths
            if Path(path).suffix
        }
        return [
            t for t in TOOLS
            if (
                t.enabled
                and t.id != self._current_id
                and output_exts.intersection(getattr(t, "input_extensions", (".pdf",)))
            )
        ]

    def _refresh_visibility(self) -> None:
        self.setVisible(bool(self._output_paths) and bool(self._other_tools()))

    def _show_menu(self) -> None:
        others = self._other_tools()
        if not others:
            return
        menu = QMenu(self)
        for tool in others:
            action = menu.addAction(tool.title)
            paths = list(self._output_paths)
            action.triggered.connect(
                lambda _, tid=tool.id, pp=paths: self._ctx.open_tool(tid, pp)
            )
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
