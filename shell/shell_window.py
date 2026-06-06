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

from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QMenu, QMessageBox,
)

from shell.context import ShellContext
from shell.tray import PdfTray, TrayPopup
from shell.word_to_pdf import WordToPdfConverter
from shell.launcher import LauncherWidget
from shell.tool_usage import ToolUsageStore
from shell.tool_registry import TOOLS, get_tool
from ui.common.output_settings import (
    add_tool_suffix_enabled,
    set_add_tool_suffix_enabled,
)
from ui.common.icons import set_button_icon
from core.update_config import UPDATE_STARTUP_DELAY_MS


class ShellWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDFlex — Suite de herramientas PDF")
        from ui.common.icons import app_qicon
        self.setWindowIcon(app_qicon())
        self.setMinimumSize(1320, 820)
        self.showMaximized()
        self.setAcceptDrops(True)

        # Infraestructura compartida
        self._tray = PdfTray(self)
        self._word_converter = WordToPdfConverter()
        self._tool_usage = ToolUsageStore()
        self._ctx = ShellContext(
            tray=self._tray,
            word_converter=self._word_converter,
            open_tool=self._open_tool,
        )

        self._tool_widgets: Dict[str, QWidget] = {}   # lazy instances
        self._pending_tool_id: Optional[str] = None  # guard para re-entry en apertura

        self._update_check_thread = None   # referencia para evitar GC prematuro
        self._update_check_worker = None
        self._manual_update_check = False

        self._build_ui()

        # Comprobación de actualización diferida (no bloquea el arranque)
        QTimer.singleShot(UPDATE_STARTUP_DELAY_MS, self._start_update_check)

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
        self._launcher = LauncherWidget(self._open_tool, usage_store=self._tool_usage)
        self._main_stack.addWidget(self._launcher)   # idx 0

        # Widget de loading para transición suave
        self._loading_widget = self._build_loading_widget()
        self._main_stack.addWidget(self._loading_widget)

        root.addWidget(self._main_stack, 1)

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("ShellTopbar")
        bar.setFixedHeight(48)

        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 0, 20, 0)
        h.setSpacing(12)

        # Logo: ícono + texto
        from ui.common.icons import app_pixmap
        logo_icon = QLabel()
        logo_icon.setPixmap(app_pixmap(24))
        logo_icon.setFixedSize(24, 24)
        logo_icon.setStyleSheet("background: transparent;")
        h.addWidget(logo_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        logo = QLabel("PDFlex")
        logo.setObjectName("TopbarLogo")
        h.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)

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

        # Botón Inicio
        self._home_btn = QPushButton("Inicio")
        self._home_btn.setProperty("class", "Ghost")
        self._home_btn.setFixedHeight(32)
        set_button_icon(self._home_btn, "arrow-left", size=15)
        self._home_btn.setVisible(False)
        self._home_btn.clicked.connect(self._go_home)
        h.addWidget(self._home_btn)

        self._options_btn = QPushButton("Opciones")
        self._options_btn.setProperty("class", "Ghost")
        self._options_btn.setFixedHeight(32)
        set_button_icon(self._options_btn, "settings", size=15)
        options_menu = QMenu(self._options_btn)
        self._suffix_action = QAction(
            "Agregar sufijo de herramienta al nombre de salida",
            self._options_btn,
        )
        self._suffix_action.setCheckable(True)
        self._suffix_action.setChecked(add_tool_suffix_enabled())
        self._suffix_action.toggled.connect(set_add_tool_suffix_enabled)
        options_menu.addAction(self._suffix_action)
        options_menu.addSeparator()
        self._check_updates_action = QAction(
            "Buscar actualizaciones",
            self._options_btn,
        )
        self._check_updates_action.triggered.connect(
            lambda: self._start_update_check(manual=True)
        )
        options_menu.addAction(self._check_updates_action)
        self._options_btn.setMenu(options_menu)
        h.addWidget(self._options_btn)

        # Botón bandeja
        self._tray_btn = QPushButton("Bandeja (0)")
        self._tray_btn.setObjectName("TrayBtn")
        self._tray_btn.setFixedHeight(32)
        set_button_icon(self._tray_btn, "folder", size=15)
        self._tray_btn.clicked.connect(self._toggle_tray)
        h.addWidget(self._tray_btn)

        self._tray.changed.connect(self._on_tray_changed)
        self._tray_popup: Optional[TrayPopup] = None

        return bar

    def _build_loading_widget(self) -> QWidget:
        """Widget placeholder mostrado mientras se construye una herramienta."""
        w = QWidget()
        w.setStyleSheet("background: #0D0D12;")
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel("Cargando herramienta…")
        lbl.setStyleSheet(
            "color: #555568; font-size: 14px; background: transparent;"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        return w

    # ------------------------------------------------------------------ #
    # Navegación
    # ------------------------------------------------------------------ #

    def _open_tool(self, tool_id: str, inputs: Optional[List[str]] = None) -> None:
        tool = get_tool(tool_id)
        if tool is None or not tool.enabled:
            return

        self._tool_usage.record_open(tool_id)

        if tool_id not in self._tool_widgets:
            # Mostrar loading inmediatamente (feedback visual antes del freeze)
            self._main_stack.setCurrentWidget(self._loading_widget)
            self._set_topbar_tool(tool)
            # Diferir construcción 1 frame para que Qt renderice el loading primero
            self._pending_tool_id = tool_id
            QTimer.singleShot(
                0,
                lambda tid=tool_id, t=tool, i=inputs: self._finish_open_tool(tid, t, i),
            )
            return

        self._show_tool_widget(tool_id, tool, inputs)

    def _finish_open_tool(
        self,
        tool_id: str,
        tool: object,
        inputs: Optional[List[str]],
    ) -> None:
        """Construye e instancia la herramienta (ejecutado tras 1 frame de diferimiento)."""
        if self._pending_tool_id != tool_id:
            return  # otra herramienta fue solicitada mientras este timer estaba pendiente
        self._pending_tool_id = None
        try:
            widget = tool.window_factory(self._ctx)
        except Exception as exc:
            from ui.common.dialogs import show_error
            show_error(self, "Error al abrir herramienta", str(exc))
            self._go_home()
            return
        self._tool_widgets[tool_id] = widget
        self._main_stack.addWidget(widget)
        self._show_tool_widget(tool_id, tool, inputs)

    def _show_tool_widget(
        self,
        tool_id: str,
        tool: object,
        inputs: Optional[List[str]],
    ) -> None:
        """Muestra el widget de herramienta ya instanciado."""
        widget = self._tool_widgets[tool_id]
        if inputs:
            widget.set_inputs(inputs)
        self._main_stack.setCurrentWidget(widget)
        self._set_topbar_tool(tool)

    def _set_topbar_tool(self, tool: object) -> None:
        """Actualiza topbar con nombre y color de la herramienta activa."""
        self._tool_name_lbl.setText(tool.title)
        self._tool_name_lbl.setStyleSheet(f"color: {tool.accent_color};")
        self._tool_name_lbl.setVisible(True)
        self._home_btn.setVisible(True)

    def _go_home(self) -> None:
        self._launcher.refresh_usage()
        self._main_stack.setCurrentIndex(0)
        self._tool_name_lbl.setStyleSheet("")
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
    # Auto-update
    # ------------------------------------------------------------------ #

    def _start_update_check(self, manual: bool = False) -> None:
        """Lanza la comprobación de actualizaciones en segundo plano."""
        from core.updater import UpdateCheckWorker, UpdateCheckThread

        if (
            self._update_check_thread is not None
            and self._update_check_thread.isRunning()
        ):
            if manual:
                QMessageBox.information(
                    self,
                    "Actualizaciones",
                    "Ya hay una comprobación de actualizaciones en curso.",
                )
            return

        self._manual_update_check = manual
        self._update_check_worker = UpdateCheckWorker()
        self._update_check_thread = UpdateCheckThread(
            self._update_check_worker, self
        )
        self._update_check_worker.update_available.connect(self._on_update_found)
        self._update_check_worker.up_to_date.connect(self._on_update_up_to_date)
        self._update_check_worker.check_error.connect(self._on_update_check_error)
        self._update_check_thread.finished.connect(self._update_check_thread.deleteLater)
        self._update_check_thread.finished.connect(self._on_update_check_finished)
        self._update_check_thread.start()

    def _on_update_found(self, info: object) -> None:
        """Muestra el diálogo de actualización cuando hay una versión nueva."""
        from ui.updater_dialog import UpdaterDialog
        UpdaterDialog.show_update(info, self)  # type: ignore[arg-type]

    def _on_update_up_to_date(self, version: str) -> None:
        if self._manual_update_check:
            QMessageBox.information(
                self,
                "Actualizaciones",
                f"PDFlex ya está actualizado.\n\nVersión instalada: {version}",
            )

    def _on_update_check_error(self, message: str) -> None:
        if self._manual_update_check:
            from core.updater import update_log_path
            QMessageBox.warning(
                self,
                "Actualizaciones",
                "No se pudo comprobar si hay actualizaciones.\n\n"
                f"{message}\n\nLog: {update_log_path()}",
            )

    def _on_update_check_finished(self) -> None:
        self._manual_update_check = False
        self._update_check_worker = None
        self._update_check_thread = None

    # ------------------------------------------------------------------ #
    # Cierre limpio
    # ------------------------------------------------------------------ #

    def closeEvent(self, event) -> None:
        """Cancela workers activos y espera terminación antes de cerrar."""
        threads_to_wait = []

        for widget in self._tool_widgets.values():
            # Herramientas con shutdown explícito (OCR, etc.)
            shutdown = getattr(widget, "_shutdown_worker", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    pass

            # Patrón legado: _worker + _worker_thread separados
            worker = getattr(widget, "_worker", None)
            if worker and callable(getattr(worker, "cancel", None)):
                try:
                    worker.cancel()
                except Exception:
                    pass

            thread = getattr(widget, "_worker_thread", None)
            if thread is not None and hasattr(thread, "isRunning") and thread.isRunning():
                threads_to_wait.append(thread)

        # Esperar terminación de todos los threads (máximo 3s por thread)
        for t in threads_to_wait:
            if hasattr(t, "wait"):
                t.wait(3000)

        event.accept()

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
