"""Primitivas de inserción rotación-seguras. ÚNICO lugar que llama insert_*/draw_*.

Reglas (verdad empírica PyMuPDF 1.27, demostrada por píxeles — ver geometry.py):
  - Reciben rects en espacio DISPLAY y PageGeometry; el mapeo a coordenadas de
    inserción (espacio sin rotar) pasa SIEMPRE por geometry.insertion_rect.
  - Texto e imagen llevan rotate=geo.rotation para quedar derechos en pantalla.
  - La verificación de posición es SIEMPRE por píxeles renderizados
    (las APIs de extracción reportan en espacio sin rotar y no sirven de prueba).
"""
from __future__ import annotations

import fitz

from core.editor.geometry import PageGeometry, insertion_rect

RGB = tuple[float, float, float]


def stamp_rect(page: fitz.Page, geo: PageGeometry, rect_display: fitz.Rect,
               *, fill: RGB, opacity: float = 1.0) -> None:
    """Rectángulo relleno (base de whiteout/formas; y vara de medir del gate)."""
    rect = insertion_rect(rect_display, geo)
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(fill=fill, fill_opacity=opacity, color=None)
    shape.commit(overlay=True)


def stamp_text(page: fitz.Page, geo: PageGeometry, rect_display: fitz.Rect,
               text: str, *, fontsize: float = 12.0, fontname: str = "helv",
               color: RGB = (0, 0, 0), opacity: float = 1.0,
               align: int = fitz.TEXT_ALIGN_LEFT) -> float:
    """Texto plano en caja display, horizontal EN PANTALLA en cualquier /Rotate.

    rotate=geo.rotation: el texto se orienta respecto a la página sin rotar;
    este parámetro lo endereza en display (gate por píxeles, las 4 rotaciones).
    Retorna el sobrante de insert_textbox (<0 = no cupo).
    """
    rect = insertion_rect(rect_display, geo)
    return page.insert_textbox(
        rect, text,
        fontsize=fontsize, fontname=fontname, color=color,
        fill_opacity=opacity, align=align,
        rotate=geo.rotation,
    )


def stamp_image(page: fitz.Page, geo: PageGeometry, rect_display: fitz.Rect,
                image_bytes: bytes) -> None:
    """Imagen en caja display, derecha en pantalla en cualquier /Rotate.

    Sonda 3 (2026-06-09): rect derotado + rotate=geo.rotation produce posición
    exacta Y orientación correcta (rojo sup-izq) en 0/90/180/270.
    keep_proportion=False: el frame del elemento ya trae la proporción deseada;
    la política de aspecto vive en el modelo, no aquí.
    """
    rect = insertion_rect(rect_display, geo)
    page.insert_image(rect, stream=image_bytes, rotate=geo.rotation,
                      keep_proportion=False, overlay=True)
