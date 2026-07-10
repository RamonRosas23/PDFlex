"""Detector automático de márgenes de hojas membretadas.

Analiza la primera página de un PDF membrete y estima cuánto espacio ocupan
el encabezado (logo, nombre de empresa) y el pie de página (dirección, teléfonos).

El resultado se usa como punto de partida en el paso de Márgenes del Membretado;
el usuario puede ajustar libremente con los sliders.

Algoritmo:
  1. Extraer texto, dibujos e imágenes de la página.
  2. Clasificar elementos en zona de encabezado (y_center < 40 % de la altura)
     y zona de pie (y_center > 60 % de la altura).
  3. El margen superior = y1 del elemento más bajo en la zona de encabezado + gracia.
  4. El margen inferior = (página_h − y0 del elemento más alto en la zona de pie) + gracia.
  5. Si no hay elementos en una zona, se usa el mínimo por defecto (18 pt).
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from core.pdf_backend import PdfRenderDocument


# ====================================================================== #
#  Modelo de márgenes
# ====================================================================== #

@dataclass
class MembreteMargins:
    """Márgenes de seguridad para el membretado (en puntos PDF)."""
    top_pt: float = 72.0     # ≈ 1 pulgada — espacio del encabezado
    bottom_pt: float = 54.0  # ≈ 0.75 pulgada — espacio del pie
    left_pt: float = 18.0    # margen izquierdo
    right_pt: float = 18.0   # margen derecho


# ====================================================================== #
#  Detección
# ====================================================================== #

_HEADER_ZONE = 0.40   # elementos cuyo centro está por encima de este % son encabezado
_FOOTER_ZONE = 0.60   # elementos cuyo centro está por debajo de este % son pie
_GRACE_PT = 8.0       # padding extra sobre el borde detectado
_DEFAULT_PT = 18.0    # margen mínimo si no se detecta nada
_MAX_RATIO = 0.45     # el margen no puede superar el 45 % de la altura de la página


def detect_margins(pdf_path: str) -> MembreteMargins:
    """Detecta los márgenes del membrete a partir de su primera página.

    Retorna valores por defecto conservadores si el análisis falla.
    """
    try:
        return _analyse(pdf_path)
    except Exception:
        return MembreteMargins()


def _analyse(pdf_path: str) -> MembreteMargins:
    with PdfRenderDocument(pdf_path) as document:
        if document.page_count <= 0:
            raise ValueError("El PDF no tiene páginas.")
        page = document.page_info(0)
        ph = page.height_pt

        header_y_max = 0.0    # y1 del elemento más bajo en la zona de encabezado
        footer_y_min = ph     # y0 del elemento más alto en la zona de pie

        threshold_top = ph * _HEADER_ZONE
        threshold_bot = ph * _FOOTER_ZONE

        def _process(y0: float, y1: float) -> None:
            nonlocal header_y_max, footer_y_min
            y_center = (y0 + y1) / 2
            if y_center < threshold_top:
                header_y_max = max(header_y_max, y1)
            elif y_center > threshold_bot:
                footer_y_min = min(footer_y_min, y0)

        for bounds in document.object_bounds(0, kinds=("text", "path", "image")):
            if bounds.width > 0 and bounds.height >= 0:
                _process(bounds.top, bounds.bottom)

        top = (header_y_max + _GRACE_PT) if header_y_max > 0 else _DEFAULT_PT
        bottom = ((ph - footer_y_min) + _GRACE_PT) if footer_y_min < ph else _DEFAULT_PT

        max_margin = ph * _MAX_RATIO
        return MembreteMargins(
            top_pt=round(max(_DEFAULT_PT, min(top, max_margin)), 1),
            bottom_pt=round(max(_DEFAULT_PT, min(bottom, max_margin)), 1),
            left_pt=_DEFAULT_PT,
            right_pt=_DEFAULT_PT,
        )
