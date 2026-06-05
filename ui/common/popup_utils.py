"""Utilidad para posicionar popups/popovers dentro de la pantalla.

El problema habitual: un botón en la esquina derecha/inferior genera un popup
que se desborda fuera de la pantalla.  smart_popup_pos() calcula la posición
óptima alineando el borde derecho del popup con el del anchor y ajustando si
es necesario para que quede siempre dentro del área disponible.
"""
from __future__ import annotations
from PyQt6.QtCore import QPoint, QSize
from PyQt6.QtWidgets import QApplication, QWidget


def smart_popup_pos(
    anchor: QWidget,
    popup_w: int = 360,
    popup_h: int = 450,
    prefer: str = "below-right",  # "below-right" | "below-left"
) -> QPoint:
    """Devuelve la posición global óptima para un popup relativo a anchor.

    Estrategia por defecto (below-right):
      - Alinea el borde DERECHO del popup con el borde derecho del anchor.
      - Si sigue desbordando por la izquierda, ajusta a la izquierda.
      - Si desborda por abajo, muestra el popup ENCIMA del anchor.
    """
    screen = (
        QApplication.screenAt(anchor.mapToGlobal(anchor.rect().center()))
        or QApplication.primaryScreen()
    )
    avail = screen.availableGeometry() if screen else None

    # Esquina inferior derecha e izquierda del anchor
    anchor_br = anchor.mapToGlobal(anchor.rect().bottomRight())
    anchor_bl = anchor.mapToGlobal(anchor.rect().bottomLeft())
    anchor_tl = anchor.mapToGlobal(anchor.rect().topLeft())

    if prefer == "below-right":
        # Alinear borde derecho del popup con borde derecho del anchor
        x = anchor_br.x() - popup_w
        y = anchor_br.y()
    else:
        x = anchor_bl.x()
        y = anchor_bl.y()

    if avail:
        # Desbordamiento por la derecha
        if x + popup_w > avail.right():
            x = avail.right() - popup_w - 4
        # Desbordamiento por la izquierda
        if x < avail.left():
            x = avail.left() + 4
        # Desbordamiento por abajo → mostrar encima
        if y + popup_h > avail.bottom():
            y = anchor_tl.y() - popup_h
        # Desbordamiento por arriba
        if y < avail.top():
            y = avail.top() + 4

    return QPoint(int(x), int(y))
