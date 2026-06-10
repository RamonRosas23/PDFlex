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


def display_rect_to_insertion(rect: fitz.Rect, geo: PageGeometry) -> fitz.Rect:
    """Convierte un rect en espacio display al espacio que esperan insert_*()/draw_*().

    HALLAZGO EMPÍRICO (sonda 2026-06-09, PyMuPDF 1.27.2.3): las APIs de
    inserción y dibujo de Page interpretan los rects EN ESPACIO DISPLAY
    (rotación ya aplicada) — la conversión es identidad. La receta antigua
    "rect * derotation_matrix + rotate=page.rotation" produce posiciones
    transpuestas en 1.27 (verificado por tests/editor/test_export_roundtrip.py).

    La función se conserva como punto único de control: si una versión futura
    de PyMuPDF cambia el contrato, la prueba reina falla y el fix vive AQUÍ.
    """
    out = fitz.Rect(rect)
    out.normalize()
    return out


def display_point_to_insertion(pt: fitz.Point, geo: PageGeometry) -> fitz.Point:
    return fitz.Point(pt)
