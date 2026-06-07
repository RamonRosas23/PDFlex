"""AnimationHelper — animaciones reutilizables para PDFlex.

Todos los métodos son helpers estáticos. No mantienen estado.
Las animaciones respetan la preferencia de accesibilidad del sistema
cuando _reduced_motion = True (configurable desde Preferencias).
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import (
    QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup,
    QTimer,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QLabel, QWidget, QGraphicsDropShadowEffect

# Toggle global — Preferencias lo cambia cuando el usuario lo pide
_reduced_motion: bool = False


def set_reduced_motion(value: bool) -> None:
    """Activa/desactiva todas las animaciones globalmente."""
    global _reduced_motion
    _reduced_motion = value


def is_reduced_motion() -> bool:
    return _reduced_motion


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (94, 106, 210)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (94, 106, 210)


class AnimationHelper:
    """Helpers estáticos para animaciones PyQt6."""

    # ── Fade ────────────────────────────────────────────────────────────────

    @staticmethod
    def fade_in(
        widget: QWidget,
        duration: int = 200,
        start: bool = True,
    ) -> QPropertyAnimation:
        """Anima la opacidad del widget de 0.0 a 1.0."""
        widget.setWindowOpacity(0.0)
        anim = QPropertyAnimation(widget, b"windowOpacity", widget)
        anim.setDuration(0 if _reduced_motion else duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if start:
            anim.start()
        return anim

    @staticmethod
    def fade_out(
        widget: QWidget,
        duration: int = 140,
        on_finished: Optional[Callable[[], None]] = None,
    ) -> QPropertyAnimation:
        """Anima la opacidad de 1.0 a 0.0. Llama on_finished al terminar."""
        anim = QPropertyAnimation(widget, b"windowOpacity", widget)
        anim.setDuration(0 if _reduced_motion else duration)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        if on_finished:
            anim.finished.connect(on_finished)
        anim.start()
        return anim

    # ── Scale press (feedback táctil visual) ────────────────────────────────

    @staticmethod
    def scale_press(widget: QWidget, scale: float = 0.97, duration: int = 120) -> None:
        """Micro-animación de press: encoge y vuelve. Solo geometría interior."""
        if _reduced_motion:
            return
        orig = widget.geometry()
        dx = int(orig.width() * (1 - scale) / 2)
        dy = int(orig.height() * (1 - scale) / 2)
        pressed = orig.adjusted(dx, dy, -dx, -dy)

        a_down = QPropertyAnimation(widget, b"geometry", widget)
        a_down.setDuration(duration // 2)
        a_down.setStartValue(orig)
        a_down.setEndValue(pressed)
        a_down.setEasingCurve(QEasingCurve.Type.OutQuad)

        a_up = QPropertyAnimation(widget, b"geometry", widget)
        a_up.setDuration(duration // 2)
        a_up.setStartValue(pressed)
        a_up.setEndValue(orig)
        a_up.setEasingCurve(QEasingCurve.Type.OutBack)

        group = QSequentialAnimationGroup(widget)
        group.addAnimation(a_down)
        group.addAnimation(a_up)
        group.start()

    # ── Count-up para stat values ────────────────────────────────────────────

    @staticmethod
    def count_up(
        label: QLabel,
        target: int,
        duration: int = 400,
        suffix: str = "",
        prefix: str = "",
    ) -> None:
        """Anima un QLabel de 0 al valor target con easing OutQuart."""
        if _reduced_motion:
            label.setText(f"{prefix}{target}{suffix}")
            return

        steps = max(1, duration // 16)  # ~60fps
        step_ms = duration // steps
        current: list[int] = [0]

        def _tick():
            t = current[0] / steps
            eased = 1 - (1 - t) ** 4  # OutQuart
            val = int(eased * target)
            label.setText(f"{prefix}{val}{suffix}")
            current[0] += 1
            if current[0] > steps:
                label.setText(f"{prefix}{target}{suffix}")
                return
            QTimer.singleShot(step_ms, _tick)

        QTimer.singleShot(0, _tick)

    # ── Stagger list items ───────────────────────────────────────────────────

    @staticmethod
    def stagger_in(
        widgets: list[QWidget],
        delay_ms: int = 25,
        duration: int = 180,
    ) -> None:
        """Fade-in escalonado de una lista de widgets."""
        if _reduced_motion:
            for w in widgets:
                w.setWindowOpacity(1.0)
            return

        for i, w in enumerate(widgets):
            w.setWindowOpacity(0.0)
            QTimer.singleShot(
                i * delay_ms,
                lambda widget=w: AnimationHelper.fade_in(widget, duration),
            )

    # ── Glow en botones Primary ──────────────────────────────────────────────

    @staticmethod
    def apply_glow(widget: QWidget, accent: str, blur: int = 18, alpha: int = 80) -> None:
        """Aplica QGraphicsDropShadowEffect de acento a un widget."""
        r, g, b = _hex_to_rgb(accent)
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(blur)
        effect.setColor(QColor(r, g, b, alpha))
        effect.setOffset(0, 2)
        widget.setGraphicsEffect(effect)

    @staticmethod
    def apply_glow_to_primary_buttons(root: QWidget, accent: str) -> None:
        """Aplica glow a todos los QPushButton[class='Primary'] bajo root."""
        from PyQt6.QtWidgets import QPushButton
        for btn in root.findChildren(QPushButton):
            if btn.property("class") == "Primary":
                AnimationHelper.apply_glow(btn, accent, blur=18, alpha=75)

    # ── Progress bar shimmer ─────────────────────────────────────────────────

    @staticmethod
    def start_shimmer(progress_bar: QWidget, accent: str) -> QTimer:
        """Inicia un shimmer animado sobre un QProgressBar.

        Retorna el QTimer para poder detenerlo con timer.stop().
        El shimmer actualiza el QSS del chunk en cada tick — no requiere
        paintEvent custom.
        """
        step: list[int] = [0]
        r, g, b = _hex_to_rgb(accent)

        def _update():
            offset = (step[0] % 100) / 100.0
            stop1 = max(0.0, offset - 0.15)
            stop2 = offset
            stop3 = min(1.0, offset + 0.15)
            shimmer_style = (
                f"QProgressBar::chunk {{"
                f"background: qlineargradient(x1:{stop1:.3f}, y1:0, x2:{stop3:.3f}, y2:0,"
                f" stop:{stop1:.2f} rgba({r},{g},{b},200),"
                f" stop:{stop2:.2f} rgba({r},{g},{b},255),"
                f" stop:{stop3:.2f} rgba({r},{g},{b},200));"
                f"border-radius: 4px;}}"
            )
            progress_bar.setStyleSheet(shimmer_style)
            step[0] += 3

        timer = QTimer(progress_bar)
        timer.setInterval(50)
        timer.timeout.connect(_update)
        timer.start()
        return timer
