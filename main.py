"""
PDFlex — Suite de herramientas PDF.

Punto de entrada de la aplicación.
"""
from __future__ import annotations
import sys

# Suprimir los warnings de MuPDF en consola (PDFs con xref rotos imprimen spam).
# Los errores reales se manejan vía excepciones Python, no vía stderr de MuPDF.
try:
    import fitz
    fitz.TOOLS.mupdf_display_errors(False)
except Exception:
    pass

from PyQt6.QtWidgets import QApplication

from shell.shell_window import ShellWindow
from ui.styles import DARK_THEME


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PDFlex")
    app.setOrganizationName("GRUPO OCMX")
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_THEME)

    font = app.font()
    font.setPointSize(10)
    app.setFont(font)

    win = ShellWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
