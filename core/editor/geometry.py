"""Espacios de coordenadas de PDFlex Studio.

Espacio canónico del modelo: "display" — puntos PDF tras aplicar /Rotate,
origen sup-izq, Y hacia abajo (lo que reportan fitz.Page.rect y get_text()).

Las funciones insert_*() de PyMuPDF interpretan rectángulos en el sistema NO
rotado de la página. Este módulo centraliza esa conversión: NADIE más en el
código multiplica por derotation_matrix (lección del bug de membrete_engine).
"""
from __future__ import annotations
from dataclasses import dataclass

import fitz

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0


def mm_to_pt(mm: float) -> float:
    return mm * PT_PER_INCH / MM_PER_INCH


def pt_to_mm(pt: float) -> float:
    return pt * MM_PER_INCH / PT_PER_INCH


Matrix6 = tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class PageGeometry:
    """Geometría inmutable de una página, capturada UNA vez desde fitz.

    Se captura al abrir el documento; el resto del motor trabaja con estos
    valores puros sin tocar fitz (regla de hilos del spec §5.3).
    """
    index: int
    width_pt: float          # dimensiones DISPLAY (rotation-aware)
    height_pt: float
    rotation: int            # 0 | 90 | 180 | 270
    derotation_matrix: Matrix6
    rotation_matrix: Matrix6

    @classmethod
    def from_page(cls, index: int, page: fitz.Page) -> "PageGeometry":
        return cls(
            index=index,
            width_pt=page.rect.width,
            height_pt=page.rect.height,
            rotation=page.rotation % 360,
            derotation_matrix=tuple(page.derotation_matrix),
            rotation_matrix=tuple(page.rotation_matrix),
        )


# ---------------------------------------------------------------------------
# Chokepoint de inserción — VERDAD EMPÍRICA FINAL (sondas 1-3 del 2026-06-09,
# PyMuPDF 1.27.2.3, demostrada POR PÍXELES RENDERIZADOS en
# tests/editor/test_export_roundtrip.py — única corte que no miente):
#
#   * insert_textbox / Shape.draw_* / insert_image interpretan TODOS el rect
#     en espacio SIN ROTAR → derotar SIEMPRE (esta función).
#   * Texto e imagen además orientan su contenido según la página sin rotar:
#     rotate=geo.rotation lo endereza en pantalla (las primitivas lo aplican).
#   * Las APIs de extracción (get_text/get_drawings/get_image_info) reportan
#     en espacio SIN ROTAR en 1.27: NO sirven para verificar posición display
#     (parecen "eco" del input). Verificar posición = renderizar y medir.
#
# Si una versión futura de PyMuPDF cambia el contrato, la prueba reina falla
# y el fix vive en ESTA función, en ningún otro lado.
# ---------------------------------------------------------------------------

def insertion_rect(rect: fitz.Rect, geo: PageGeometry) -> fitz.Rect:
    """Display → coords de inserción (espacio sin rotar) para insert_*/draw_*."""
    out = fitz.Rect(rect) * fitz.Matrix(*geo.derotation_matrix)
    out.normalize()
    return out
