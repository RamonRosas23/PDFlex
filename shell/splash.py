"""SplashScreen — pantalla de inicio animada para PDFlex.

Aparece en <5 ms antes de que ShellWindow se construya, eliminando la pantalla
blanca de arranque. Permanece visible (stays-on-top) mientras se renderizan las
tarjetas del launcher; se cierra automáticamente cuando LauncherWidget emite
la señal `ready`.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QLabel, QProgressBar, QVBoxLayout, QWidget,
)

from ui.common.icons import app_pixmap
from ui.styles import COLORS


class SplashScreen(QWidget):
    """Pantalla de marca sin bordes que bloquea la vista de la ventana vacía."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedSize(400, 268)

        self._step = 0
        self._timer = QTimer(self)
        self._timer.setInterval(420)
        self._timer.timeout.connect(self._tick)

        self._build()
        self._center_on_screen()

    # ------------------------------------------------------------------ #
    # Construcción
    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        self.setStyleSheet(
            f"background: {COLORS['bg']};"
            f"border: 1px solid {COLORS['border_strong']};"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(44, 40, 44, 36)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setPixmap(app_pixmap(56))
        logo.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(logo)

        layout.addSpacing(18)

        name = QLabel("PDFlex")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 22px; font-weight: 800; "
            "letter-spacing: -0.5px; background: transparent; border: none;"
        )
        layout.addWidget(name)

        layout.addSpacing(5)

        tagline = QLabel("Suite de herramientas PDF")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; "
            "background: transparent; border: none;"
        )
        layout.addWidget(tagline)

        layout.addStretch(1)

        self._status_lbl = QLabel("Iniciando")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px; letter-spacing: 0.4px; "
            "background: transparent; border: none;"
        )
        layout.addWidget(self._status_lbl)

        layout.addSpacing(8)

        self._pbar = QProgressBar()
        self._pbar.setRange(0, 0)
        self._pbar.setTextVisible(False)
        self._pbar.setFixedHeight(3)
        self._pbar.setStyleSheet(
            f"QProgressBar {{ background: {COLORS['surface_3']}; border: none; border-radius: 1px; }}"
            f"QProgressBar::chunk {{ background: {COLORS['accent']}; border-radius: 1px; }}"
        )
        layout.addWidget(self._pbar)

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.center().y() - self.height() // 2,
        )

    # ------------------------------------------------------------------ #
    # Control público
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Muestra el splash y arranca la animación de puntos."""
        self.show()
        self._timer.start()
        QApplication.processEvents()

    def finish(self, _main_window=None) -> None:
        """Detiene la animación y cierra el splash."""
        self._timer.stop()
        self.close()

    # ------------------------------------------------------------------ #
    # Animación interna
    # ------------------------------------------------------------------ #

    def _tick(self) -> None:
        self._step = (self._step + 1) % 4
        self._status_lbl.setText("Iniciando" + "." * self._step)
