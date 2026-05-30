"""ShellWindow — ventana principal de la suite PDFlex.

Estructura:
    QMainWindow
      centralWidget
        QVBoxLayout
          Topbar (QFrame, 48px)  ← PDFlex + botón Inicio + bandeja
          QStackedWidget
            [0]  LauncherWidget
            [1…] PipelineWindow de cada herramienta (lazy)
"""
from __future__ import annotations
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget,
)

from shell.context import ShellContext
from shell.tray import PdfTray, TrayPopup
from shell.word_to_pdf import WordToPdfConverter
from shell.launcher import LauncherWidget
from shell.tool_registry import TOOLS, get_tool


class ShellWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDFlex — Suite de herramientas PDF")
        self.setMinimumSize(1320, 820)
        self.showMaximized()
        self.setAcceptDrops(True)

        # Infraestructura compartida
        self._tray = PdfTray(self)
        self._word_converter = WordToPdfConverter()
        self._ctx = ShellContext(
            tray=self._tray,
            word_converter=self._word_converter,
            open_tool=self._open_tool,
        )

        self._tool_widgets: Dict[str, QWidget] = {}   # lazy instances

        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        self._main_stack = QStackedWidget()
        self._launcher = LauncherWidget(self._open_tool)
        self._main_stack.addWidget(self._launcher)   # idx 0
        root.addWidget(self._main_stack, 1)

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("ShellTopbar")
        bar.setFixedHeight(48)

        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 0, 20, 0)
        h.setSpacing(12)

        # Logo
        logo = QLabel("PDFlex")
        logo.setObjectName("TopbarLogo")
        h.addWidget(logo)

        # Divisor
        sep = QFrame()
        sep.setObjectName("TopbarSep")
        sep.setFixedSize(1, 20)
        h.addWidget(sep)

        # Nombre de la herramienta activa
        self._tool_name_lbl = QLabel("")
        self._tool_name_lbl.setObjectName("TopbarToolName")
        self._tool_name_lbl.setVisible(False)
        h.addWidget(self._tool_name_lbl)

        h.addStretch(1)

        # Botón ← Inicio
        self._home_btn = QPushButton("← Inicio")
        self._home_btn.setProperty("class", "Ghost")
        self._home_btn.setFixedHeight(32)
        self._home_btn.setVisible(False)
        self._home_btn.clicked.connect(self._go_home)
        h.addWidget(self._home_btn)

        # Botón bandeja
        self._tray_btn = QPushButton("Bandeja (0)")
        self._tray_btn.setObjectName("TrayBtn")
        self._tray_btn.setFixedHeight(32)
        self._tray_btn.clicked.connect(self._toggle_tray)
        h.addWidget(self._tray_btn)

        self._tray.changed.connect(self._on_tray_changed)
        self._tray_popup: Optional[TrayPopup] = None

        return bar

    # ------------------------------------------------------------------ #
    # Navegación
    # ------------------------------------------------------------------ #

    def _open_tool(self, tool_id: str, inputs: Optional[List[str]] = None) -> None:
        tool = get_tool(tool_id)
        if tool is None or not tool.enabled:
            return

        if tool_id not in self._tool_widgets:
            widget = tool.window_factory(self._ctx)
            self._tool_widgets[tool_id] = widget
            self._main_stack.addWidget(widget)

        widget = self._tool_widgets[tool_id]

        if inputs:
            widget.set_inputs(inputs)

        self._main_stack.setCurrentWidget(widget)
        self._tool_name_lbl.setText(tool.title)
        self._tool_name_lbl.setVisible(True)
        self._home_btn.setVisible(True)

    def _go_home(self) -> None:
        self._main_stack.setCurrentIndex(0)
        self._tool_name_lbl.setVisible(False)
        self._home_btn.setVisible(False)

    # ------------------------------------------------------------------ #
    # Bandeja
    # ------------------------------------------------------------------ #

    def _on_tray_changed(self) -> None:
        n = self._tray.count()
        self._tray_btn.setText(f"Bandeja ({n})")
        self._tray_btn.setProperty("has_items", "true" if n > 0 else "false")
        self._tray_btn.style().unpolish(self._tray_btn)
        self._tray_btn.style().polish(self._tray_btn)

    def _toggle_tray(self) -> None:
        if self._tray_popup and self._tray_popup.isVisible():
            self._tray_popup.close()
            self._tray_popup = None
            return
        self._tray_popup = TrayPopup(self._tray, self)
        from ui.common.popup_utils import smart_popup_pos
        pos = smart_popup_pos(self._tray_btn, popup_w=360, popup_h=440, prefer="below-right")
        self._tray_popup.move(pos)
        self._tray_popup.show()
        self._tray_popup.raise_()

    # ------------------------------------------------------------------ #
    # Drag & drop — forwarding a la herramienta activa
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event) -> None:
        active = self._main_stack.currentWidget()
        if event.mimeData().hasUrls() and hasattr(active, "handle_drop"):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        active = self._main_stack.currentWidget()
        if hasattr(active, "handle_drop"):
            active.handle_drop(paths)
            event.acceptProposedAction()
