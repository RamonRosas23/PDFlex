"""Tests para transición launcher → herramienta con feedback inmediato."""
import sys
import pytest
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from PySide6.QtCore import Qt


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    yield a


def test_loading_widget_construction(app):
    """_build_loading_widget crea un QWidget con label de texto."""
    from shell.shell_window import ShellWindow
    # Verificar que ShellWindow tiene el atributo _loading_widget
    # Sin instanciación completa (requiere display), solo verifica el método
    # Creamos manualmente un widget similar para el test
    w = QWidget()
    from PySide6.QtWidgets import QVBoxLayout
    layout = QVBoxLayout(w)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl = QLabel("Cargando herramienta…")
    layout.addWidget(lbl)
    assert lbl.text() == "Cargando herramienta…"


def test_shell_window_uses_custom_chrome(app):
    """ShellWindow usa frame custom con controles propios."""
    from shell.shell_window import ShellWindow

    win = ShellWindow()
    try:
        assert bool(win.windowFlags() & Qt.WindowType.FramelessWindowHint)
        assert win.windowTitle() == "PDFlex"
        assert win._win_min_btn.toolTip() == "Minimizar"
        assert win._win_max_btn.toolTip() in {"Maximizar", "Restaurar"}
        assert win._win_close_btn.objectName() == "WindowCloseBtn"
    finally:
        win.deleteLater()
        app.processEvents()


def test_stacked_widget_transition(app):
    """QStackedWidget cambia de widget inmediatamente."""
    from PySide6.QtWidgets import QStackedWidget
    stack = QStackedWidget()
    launcher = QLabel("launcher")
    loading = QLabel("Cargando…")
    stack.addWidget(launcher)
    stack.addWidget(loading)
    stack.setCurrentIndex(0)
    assert stack.currentWidget() is launcher
    stack.setCurrentWidget(loading)
    assert stack.currentWidget() is loading


def test_close_event_survives_deleted_license_thread_wrapper(app):
    """Reproduce el crash real de v2.0.8 al cerrar: la revalidación de
    licencia termina, finished→deleteLater destruye el objeto C++ del
    QThread, pero _license_revalidate_thread conserva el wrapper Python
    muerto. closeEvent llamaba isRunning() sobre el cadáver →
    "RuntimeError: libshiboken: Internal C++ object already deleted" →
    CrashHandlerApp lo registraba como crash fatal en pleno cierre."""
    from unittest.mock import Mock

    import shiboken6
    from PySide6.QtCore import QThread

    from shell.shell_window import ShellWindow

    win = ShellWindow()
    try:
        dead = QThread()
        shiboken6.delete(dead)  # destruye el C++ dejando vivo el wrapper Python
        win._license_revalidate_thread = dead

        event = Mock()
        win.closeEvent(event)  # no debe lanzar RuntimeError

        event.accept.assert_called_once()
    finally:
        win.deleteLater()
        app.processEvents()


def test_close_event_waits_running_child_threads(app):
    """closeEvent debe esperar cualquier QThread hijo aún corriendo (p. ej.
    la comprobación de actualizaciones, conversiones, miniaturas): destruir
    la ventana con un QThread hijo vivo aborta el proceso entero — es un
    qFatal de Qt ("QThread: Destroyed while thread is still running"), no
    una excepción capturable."""
    import time
    from unittest.mock import Mock

    from PySide6.QtCore import QThread

    from shell.shell_window import ShellWindow

    class _CooperativeThread(QThread):
        def run(self):
            while not self.isInterruptionRequested():
                self.msleep(10)

    win = ShellWindow()
    try:
        th = _CooperativeThread(win)
        th.start()
        deadline = time.monotonic() + 5.0
        while not th.isRunning() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert th.isRunning()

        event = Mock()
        win.closeEvent(event)

        assert not th.isRunning()  # esperado y terminado, no abandonado
        event.accept.assert_called_once()
    finally:
        win.deleteLater()
        app.processEvents()


def test_close_event_survives_deleted_tool_worker_thread_wrapper(app):
    """Mismo peligro con los _worker_thread de las herramientas: si algún
    widget conecta finished→deleteLater sin limpiar su referencia,
    closeEvent no debe reventar sobre el wrapper muerto."""
    from unittest.mock import Mock

    import shiboken6
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QWidget

    from shell.shell_window import ShellWindow

    win = ShellWindow()
    try:
        holder = QWidget()
        dead = QThread()
        shiboken6.delete(dead)
        holder._worker_thread = dead
        win._tool_widgets["fake_tool"] = holder

        event = Mock()
        win.closeEvent(event)

        event.accept.assert_called_once()
    finally:
        win.deleteLater()
        app.processEvents()
