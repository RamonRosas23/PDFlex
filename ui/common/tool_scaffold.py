"""PipelineWindow — clase base para todas las herramientas de PDFlex.

Provee:
  - Sidebar con pasos numerados (01, 02 …)
  - QStackedWidget derecho para las páginas de contenido
  - _switch_section(idx) con highlight del paso activo
  - set_inputs(paths) y señal outputs_ready para inter-herramientas
"""
from __future__ import annotations
from typing import TYPE_CHECKING, List, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget,
)

if TYPE_CHECKING:
    from shell.context import ShellContext


class PipelineWindow(QWidget):
    """Widget base para el pipeline de cada herramienta."""

    outputs_ready = pyqtSignal(list)   # list[str] — paths de PDFs producidos

    # Subclases deben definir estas constantes
    SECTIONS: List[Tuple[str, str, str]] = []   # (num, nombre, hint)
    BRAND: str = ""
    TAGLINE: str = ""

    def __init__(self, ctx: "ShellContext", parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._build_scaffold()

    # ------------------------------------------------------------------ #
    # Construcción del caparazón (sidebar + stack)
    # ------------------------------------------------------------------ #

    def _build_scaffold(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background-color: #0A0A0B;")
        root.addWidget(self.stack, 1)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(260)

        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(0)

        brand = QLabel(self.BRAND)
        brand.setObjectName("SidebarBrand")
        sb.addWidget(brand)

        tagline = QLabel(self.TAGLINE)
        tagline.setObjectName("SidebarTagline")
        sb.addWidget(tagline)

        section_lbl = QLabel("PASOS")
        section_lbl.setObjectName("SidebarSection")
        sb.addWidget(section_lbl)

        self._section_buttons: List[QPushButton] = []
        for i, (num, name, hint) in enumerate(self.SECTIONS):
            btn = QPushButton(f"  {num}    {name}")
            btn.setProperty("class", "SidebarBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if hint:
                btn.setToolTip(hint)
            btn.clicked.connect(lambda _, idx=i: self._switch_section(idx))
            sb.addWidget(btn)
            self._section_buttons.append(btn)

        sb.addStretch(1)

        footer = QLabel("GRUPO OCMX · PDFlex v2.0")
        footer.setObjectName("SidebarFooter")
        sb.addWidget(footer)

        return sidebar

    # ------------------------------------------------------------------ #
    # Navegación
    # ------------------------------------------------------------------ #

    def _switch_section(self, idx: int) -> None:
        for i, btn in enumerate(self._section_buttons):
            btn.setProperty("active", "true" if i == idx else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()
        self.stack.setCurrentIndex(idx)
        self._on_section_activated(idx)

    def _on_section_activated(self, idx: int) -> None:
        """Hook para que subclases reaccionen al cambio de paso."""

    # ------------------------------------------------------------------ #
    # API inter-herramientas
    # ------------------------------------------------------------------ #

    def set_inputs(self, paths: List[str]) -> None:
        """Recibe PDFs desde otra herramienta o la bandeja. Override en subclase."""

    def handle_drop(self, paths: List[str]) -> None:
        """Forwarding de drag&drop desde ShellWindow. Override en subclase."""
