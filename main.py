"""
PDFlex — Suite de herramientas PDF.

Punto de entrada de la aplicación.
"""
from __future__ import annotations
import sys
from pathlib import Path


def _asset_path(relative: str) -> Path:
    """Devuelve la ruta correcta en desarrollo, PyInstaller y Nuitka standalone."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / relative
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / relative
    return Path(__file__).resolve().parent / relative


def _run_internal_worker_if_requested() -> int | None:
    """Despacha procesos auxiliares antes de cargar la interfaz grafica."""
    marker = "--pdflex-ocr-worker"
    if marker not in sys.argv:
        return None
    from core.ocr_process import main as ocr_worker_main
    marker_index = sys.argv.index(marker)
    return ocr_worker_main(sys.argv[marker_index + 1:])


# Suprimir warnings de MuPDF (PDFs con xref rotos imprimen spam al stderr).
try:
    import fitz
    fitz.TOOLS.mupdf_display_errors(False)
except Exception:
    pass


def main() -> int:
    from shell.shell_window import ShellWindow
    from ui.styles import DARK_THEME
    from core.crash_handler import CrashHandlerApp, install_crash_handlers

    # Windows: AppUserModelID para ícono correcto en barra de tareas
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "GRUPOOCMX.PDFlex.1"
        )
    except Exception:
        pass

    # ── Usar CrashHandlerApp en lugar de QApplication ─────────────────────
    app = CrashHandlerApp(sys.argv)
    app.setApplicationName("PDFlex")
    app.setOrganizationName("GRUPO OCMX")
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_THEME)

    # Instalar todos los hooks globales de excepción
    install_crash_handlers()

    from ui.common.icons import app_qicon
    app.setWindowIcon(app_qicon())

    font = app.font()
    font.setPointSize(10)
    app.setFont(font)

    win = ShellWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()
    worker_exit_code = _run_internal_worker_if_requested()

    # El worker OCR es un proceso auxiliar — no necesita crash handler Qt
    if worker_exit_code is not None:
        sys.exit(worker_exit_code)

    # Para el proceso principal instalamos el hook ANTES de crear Qt,
    # así capturamos también errores en la fase de importación/inicialización.
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        # Captura de último recurso: main() falló antes de que Qt existiera
        from core.crash_handler import handle_crash
        handle_crash(*sys.exc_info(), fatal=True)
