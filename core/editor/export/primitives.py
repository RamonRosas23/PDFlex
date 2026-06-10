"""Primitivas de inserción rotación-seguras. ÚNICO lugar que llama insert_*/draw_*.

Reglas:
  - Reciben rects en espacio DISPLAY y PageGeometry; el mapeo a coordenadas de
    inserción pasa SIEMPRE por geometry.display_rect_to_insertion (chokepoint).
  - Sonda empírica PyMuPDF 1.27 (2026-06-09): insert_textbox/draw_* operan en
    espacio display; rotate=0 deja el texto horizontal EN PANTALLA en cualquier
    /Rotate de página. El parámetro rotate gira el texto en espacio display
    (múltiplos de 90 del usuario); el ángulo libre va por morph.
"""
from __future__ import annotations

import fitz

from core.editor.geometry import PageGeometry, display_rect_to_insertion

RGB = tuple[float, float, float]


def stamp_rect(page: fitz.Page, geo: PageGeometry, rect_display: fitz.Rect,
               *, fill: RGB, opacity: float = 1.0) -> None:
    """Rectángulo relleno (base de whiteout/formas; y vara de medir del gate)."""
    rect = display_rect_to_insertion(rect_display, geo)
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(fill=fill, fill_opacity=opacity, color=None)
    shape.commit(overlay=True)


def stamp_text(page: fitz.Page, geo: PageGeometry, rect_display: fitz.Rect,
               text: str, *, fontsize: float = 12.0, fontname: str = "helv",
               color: RGB = (0, 0, 0), opacity: float = 1.0,
               align: int = fitz.TEXT_ALIGN_LEFT) -> float:
    """Texto plano en caja. Retorna el sobrante de insert_textbox (<0 = no cupo)."""
    rect = display_rect_to_insertion(rect_display, geo)
    return page.insert_textbox(
        rect, text,
        fontsize=fontsize, fontname=fontname, color=color,
        fill_opacity=opacity, align=align,
        rotate=0,
    )
