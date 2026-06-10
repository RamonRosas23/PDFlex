"""Estilo de texto → parámetros de primitivas.

MVP: catálogo base-14 (helv/tiro/cour + variantes), EXACTAMENTE el mapa probado
de core/foleador_engine._FONT_VARIANTS — consistencia visual con el Foleador.
Fase 2 añade fuentes embebidas OFL + sistema (fontTools) sin tocar este contrato.
"""
from __future__ import annotations

import fitz

_FONT_VARIANTS: dict[tuple[str, bool, bool], str] = {
    ("helv", False, False): "helv", ("helv", True, False): "hebo",
    ("helv", False, True): "heit", ("helv", True, True): "hebi",
    ("tiro", False, False): "tiro", ("tiro", True, False): "tibo",
    ("tiro", False, True): "tiit", ("tiro", True, True): "tibi",
    ("cour", False, False): "cour", ("cour", True, False): "cobo",
    ("cour", False, True): "coit", ("cour", True, True): "cobi",
}

_ALIGN = {
    "left": fitz.TEXT_ALIGN_LEFT, "center": fitz.TEXT_ALIGN_CENTER,
    "right": fitz.TEXT_ALIGN_RIGHT, "justify": fitz.TEXT_ALIGN_JUSTIFY,
}


def resolve_font(family: str, *, bold: bool, italic: bool) -> str:
    base = family if (family, False, False) in _FONT_VARIANTS else "helv"
    return _FONT_VARIANTS[(base, bold, italic)]


def alignment_flag(align: str) -> int:
    return _ALIGN.get(align, fitz.TEXT_ALIGN_LEFT)
