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
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QMenu, QMessageBox,
)

from shell.context import ShellContext
from shell.transfer import ToolTransfer
from ui.styles import COLORS
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
from core.update_config import (
    UPDATE_STARTUP_DELAY_MS,
    UPDATE_STARTUP_RETRY_DELAYS_MS,
)


class ShellWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDFlex — Suite de herramientas PDF")
        from ui.common.icons import app_qicon
        self.setWindowIcon(app_qicon())
        self.setMinimumSize(1320, 820)
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
        self._active_tool_id: Optional[str] = None

        self._update_check_thread = None   # referencia para evitar GC prematuro
        self._update_check_worker = None
        self._manual_update_check = False
        self._startup_update_check_attempt = 0
        self._startup_update_check_done = False

        self._build_ui()

        # Comprobación de actualización diferida (no bloquea el arranque)
        self._schedule_startup_update_check(UPDATE_STARTUP_DELAY_MS)

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
        w.setStyleSheet(f"background: {COLORS['bg']};")
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel("Abriendo herramienta…")
        lbl.setStyleSheet(
            "color: #4A4D5E; font-size: 13px; letter-spacing: 0.2px; background: transparent;"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        return w

    # ------------------------------------------------------------------ #
    # Navegación
    # ------------------------------------------------------------------ #

    def _open_tool(
        self,
        tool_id: str,
        inputs: Optional[List[str] | ToolTransfer] = None,
    ) -> None:
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
        inputs: Optional[List[str] | ToolTransfer],
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
        inputs: Optional[List[str] | ToolTransfer],
    ) -> None:
        """Muestra el widget de herramienta ya instanciado."""
        widget = self._tool_widgets[tool_id]
        if inputs:
            self._deliver_tool_inputs(widget, inputs)
        self._main_stack.setCurrentWidget(widget)
        self._set_topbar_tool(tool)

    def _deliver_tool_inputs(
        self,
        widget: QWidget,
        inputs: List[str] | ToolTransfer,
    ) -> None:
        """Entrega entradas legacy o transferencias enriquecidas a una herramienta."""
        if isinstance(inputs, ToolTransfer):
            self._apply_transfer_tray_policy(inputs)
            if not inputs.paths:
                return
            set_transfer = getattr(widget, "set_transfer", None)
            if callable(set_transfer):
                set_transfer(inputs)
                return
            if inputs.mode == "replace":
                self._clear_widget_inputs(widget)
            set_inputs = getattr(widget, "set_inputs", None)
            if callable(set_inputs):
                set_inputs(list(inputs.paths))
            return

        set_inputs = getattr(widget, "set_inputs", None)
        if callable(set_inputs):
            set_inputs(list(inputs))

    def _clear_widget_inputs(self, widget: QWidget) -> bool:
        """Limpia inputs conocidos antes de una transferencia `replace`."""
        clear_inputs = getattr(widget, "clear_inputs", None)
        if callable(clear_inputs):
            clear_inputs()
            return True

        for attr in ("_docs_card", "_img_card", "_word_card"):
            card = getattr(widget, attr, None)
            clear = getattr(card, "clear", None)
            if callable(clear):
                clear()
                return True
        return False

    def _apply_transfer_tray_policy(self, transfer: ToolTransfer) -> None:
        """Aplica la politica de bandeja asociada a una transferencia."""
        if transfer.tray_policy == "keep":
            self._tray.mark_sent(transfer.paths)
            return

        if transfer.tray_policy == "replace_with_sent":
            source_title = (
                transfer.source_tool_title
                or transfer.source_tool_id
                or "Transferencia"
            )
            self._tray.replace_with(
                transfer.paths,
                source_title,
                kind=transfer.kind,
                source_tool_id=transfer.source_tool_id,
                source_tool_title=transfer.source_tool_title or source_title,
                batch_id=transfer.batch_id,
                parent_ids=transfer.parent_ids,
                status="sent",
            )
            return

        if transfer.tray_policy == "clear":
            self._tray.clear()

    def _set_topbar_tool(self, tool: object) -> None:
        """Actualiza topbar con nombre y color de la herramienta activa."""
        self._active_tool_id = tool.id
        self._tool_name_lbl.setText(tool.title)
        self._tool_name_lbl.setStyleSheet(f"color: {tool.accent_color};")
        self._tool_name_lbl.setVisible(True)
        self._home_btn.setVisible(True)

    def _go_home(self) -> None:
        self._launcher.refresh_usage()
        self._main_stack.setCurrentIndex(0)
        self._active_tool_id = None
        self._tool_name_lbl.setStyleSheet("")
        self._tool_name_lbl.setVisible(False)
        self._home_btn.setVisible(False)

    # ------------------------------------------------------------------ #
    # Bandeja
    # ------------------------------------------------------------------ #

    def _on_tray_changed(self) -> None:
        n = self._tray.count()
        self._tray_btn.setText(f"Bandeja ({n})")
        self._tray_btn.setToolTip(self._tray_tooltip())
        self._tray_btn.setProperty("has_items", "true" if n > 0 else "false")
        self._tray_btn.style().unpolish(self._tray_btn)
        self._tray_btn.style().polish(self._tray_btn)

    def _toggle_tray(self) -> None:
        if self._tray_popup and self._tray_popup.isVisible():
            self._tray_popup.close()
            self._tray_popup = None
            return
        active_tool = get_tool(self._active_tool_id) if self._active_tool_id else None
        active_title = active_tool.title if active_tool else ""
        active_extensions = active_tool.input_extensions if active_tool else ()
        self._tray_popup = TrayPopup(
            self._tray,
            self,
            active_tool_title=active_title,
            active_extensions=active_extensions,
        )
        self._tray_popup.use_in_active_tool_requested.connect(self._use_selected_tray_items)
        from ui.common.popup_utils import smart_popup_pos
        pos = smart_popup_pos(self._tray_btn, popup_w=420, popup_h=560, prefer="below-right")
        self._tray_popup.move(pos)
        self._tray_popup.show()
        self._tray_popup.raise_()

    def _tray_tooltip(self) -> str:
        counts = self._tray.source_counts()
        if not counts:
            return "Bandeja vacía"
        lines = [f"Bandeja: {self._tray.count()} archivo" + ("s" if self._tray.count() != 1 else "")]
        lines.extend(f"{source}: {count}" for source, count in counts.items())
        return "\n".join(lines)

    def _use_selected_tray_items(self, paths: List[str]) -> None:
        if not self._active_tool_id:
            return
        tool = get_tool(self._active_tool_id)
        widget = self._tool_widgets.get(self._active_tool_id)
        if tool is None or widget is None:
            return
        compatible = [
            path for path in paths
            if Path(path).suffix.lower() in tool.input_extensions
        ]
        if not compatible:
            return
        self._deliver_tool_inputs(widget, compatible)
        self._tray.mark_in_work(compatible)
        if self._tray_popup:
            self._tray_popup.close()
            self._tray_popup = None

    # ------------------------------------------------------------------ #
    # Auto-update
    # ------------------------------------------------------------------ #

    def _schedule_startup_update_check(self, delay_ms: int) -> None:
        """Agenda un intento automático de actualización al arrancar."""
        if self._startup_update_check_done:
            return
        from core.updater import log_update_event
        log_update_event(
            "Scheduling startup update check "
            f"attempt={self._startup_update_check_attempt + 1} delay_ms={delay_ms}"
        )
        QTimer.singleShot(delay_ms, self._run_startup_update_check)

    def _run_startup_update_check(self) -> None:
        """Ejecuta/reintenta el análisis automático de actualización."""
        if self._startup_update_check_done:
            return
        if (
            self._update_check_thread is not None
            and self._update_check_thread.isRunning()
        ):
            self._schedule_startup_update_check(10_000)
            return
        self._startup_update_check_attempt += 1
        self._start_update_check(manual=False, startup=True)

    def _start_update_check(self, manual: bool = False, startup: bool = False) -> bool:
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
            return False

        self._manual_update_check = manual
        self._update_check_worker = UpdateCheckWorker()
        self._update_check_thread = UpdateCheckThread(
            self._update_check_worker, self
        )
        self._update_check_worker.update_available.connect(
            lambda info, startup=startup: self._on_update_found(info, startup)
        )
        self._update_check_worker.up_to_date.connect(
            lambda version, manual=manual, startup=startup: (
                self._on_update_up_to_date(version, manual, startup)
            )
        )
        self._update_check_worker.check_error.connect(
            lambda message, manual=manual, startup=startup: (
                self._on_update_check_error(message, manual, startup)
            )
        )
        self._update_check_thread.finished.connect(self._update_check_thread.deleteLater)
        self._update_check_thread.finished.connect(self._on_update_check_finished)
        self._update_check_thread.start()
        return True

    def _on_update_found(self, info: object, startup: bool = False) -> None:
        """Muestra el diálogo de actualización cuando hay una versión nueva."""
        self._startup_update_check_done = True
        from core.updater import log_update_event
        from ui.updater_dialog import UpdaterDialog
        log_update_event("Update available signal received; showing update dialog.")
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        UpdaterDialog.show_update(info, self)  # type: ignore[arg-type]

    def _on_update_up_to_date(
        self,
        version: str,
        manual: bool = False,
        startup: bool = False,
    ) -> None:
        self._startup_update_check_done = True
        if manual:
            QMessageBox.information(
                self,
                "Actualizaciones",
                f"PDFlex ya está actualizado.\n\nVersión instalada: {version}",
            )

    def _on_update_check_error(
        self,
        message: str,
        manual: bool = False,
        startup: bool = False,
    ) -> None:
        if startup:
            from core.updater import log_update_event
            retry_idx = self._startup_update_check_attempt - 1
            if retry_idx < len(UPDATE_STARTUP_RETRY_DELAYS_MS):
                delay_ms = UPDATE_STARTUP_RETRY_DELAYS_MS[retry_idx]
                log_update_event(
                    "Startup update check failed; retry scheduled "
                    f"attempt={self._startup_update_check_attempt} "
                    f"next_delay_ms={delay_ms} error={message}"
                )
                self._schedule_startup_update_check(delay_ms)
            else:
                self._startup_update_check_done = True
                log_update_event(
                    "Startup update check failed; no retries left "
                    f"attempt={self._startup_update_check_attempt} error={message}"
                )
        if manual:
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
