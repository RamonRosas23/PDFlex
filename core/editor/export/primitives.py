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
               align: int = fitz.TEXT_ALIGN_LEFT, angle_deg: float = 0.0) -> float:
    """Texto plano en caja display, horizontal EN PANTALLA en cualquier /Rotate.

    rotate=geo.rotation: el texto se orienta respecto a la página sin rotar;
    este parámetro lo endereza en display (gate por píxeles, las 4 rotaciones).
    angle_deg: rotación libre del elemento alrededor del centro de su caja
    (convención de producto: positivo = horario en pantalla, como Qt). El morph
    se aplica en espacio de inserción con pivote en el centro derotado; al ser
    rotación pura, la magnitud visual se conserva en páginas /Rotate≠0
    (verificado por píxeles en test_text_rotated_45_centered_and_diagonal).
    Retorna el sobrante de insert_textbox (<0 = no cupo).
    """
    rect = insertion_rect(rect_display, geo)
    morph = None
    if angle_deg:
        pivot = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
        morph = (pivot, fitz.Matrix(angle_deg))
    return page.insert_textbox(
        rect, text,
        fontsize=fontsize, fontname=fontname, color=color,
        fill_opacity=opacity, align=align,
        rotate=geo.rotation, morph=morph,
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


def stamp_image_rotated(page: fitz.Page, geo: PageGeometry, rect_display: fitz.Rect,
                        image_bytes: bytes, *, angle_deg: float) -> None:
    """Imagen con ángulo libre alrededor del centro de su frame.

    Decisión registrada (Task 5): NO se usa show_pdf_page/XObject — el membrete
    ya documentó que ignora /Rotate y su semántica fit-inside no coincide con un
    canvas donde el frame gira con la imagen. En su lugar: pre-rotación PIL
    (expand=True, bicúbica, lienzo RGBA transparente) y stamp_image (ya probado
    en las 4 rotaciones) sobre el bbox crecido centrado en el mismo punto.
    Paridad exacta con QGraphicsItem.setRotation (positivo = horario).
    """
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    # PIL rota antihorario con ángulo positivo (espacio y-abajo) → negar para horario
    rotated = img.rotate(-angle_deg, resample=Image.Resampling.BICUBIC, expand=True)
    out = io.BytesIO()
    rotated.save(out, format="PNG")

    # El frame crece al bbox de la rotación, conservando el centro y la escala pt/px
    scale_x = rect_display.width / img.width
    scale_y = rect_display.height / img.height
    new_w = rotated.width * scale_x
    new_h = rotated.height * scale_y
    cx = (rect_display.x0 + rect_display.x1) / 2
    cy = (rect_display.y0 + rect_display.y1) / 2
    grown = fitz.Rect(cx - new_w / 2, cy - new_h / 2, cx + new_w / 2, cy + new_h / 2)
    stamp_image(page, geo, grown, out.getvalue())
