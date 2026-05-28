"""
Firmador Masivo de Documentos.

Punto de entrada de la aplicación.
"""
from __future__ import annotations
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

from ui.main_window import MainWindow
from ui.styles import DARK_THEME


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Firmador Masivo")
    app.setOrganizationName("GRUPO OCMX")
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_THEME)

    # Fuente por defecto un poco más limpia
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
