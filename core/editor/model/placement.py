"""Frame (caja en pt display) y Placement (cómo se resuelve por página).

Tres modos (spec §12):
  absolute   — el frame es literal (elementos colocados a mano en UNA página)
  anchor     — 9 anclas + offset en pt (encabezados/pies/folios en reglas)
  normalized — centro y tamaño como fracción de la página destino
               (marcas de agua; patrón probado del foleador)
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Literal

from core.editor.geometry import PageGeometry


class Anchor(str, Enum):
    TOP_LEFT = "top-left"
    TOP_CENTER = "top-center"
    TOP_RIGHT = "top-right"
    MIDDLE_LEFT = "middle-left"
    CENTER = "center"
    MIDDLE_RIGHT = "middle-right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_CENTER = "bottom-center"
    BOTTOM_RIGHT = "bottom-right"


@dataclass(frozen=True)
class Frame:
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


# Fracciones horizontales/verticales por ancla
_ANCHOR_FRACTIONS: dict[Anchor, tuple[float, float]] = {
    Anchor.TOP_LEFT: (0.0, 0.0), Anchor.TOP_CENTER: (0.5, 0.0), Anchor.TOP_RIGHT: (1.0, 0.0),
    Anchor.MIDDLE_LEFT: (0.0, 0.5), Anchor.CENTER: (0.5, 0.5), Anchor.MIDDLE_RIGHT: (1.0, 0.5),
    Anchor.BOTTOM_LEFT: (0.0, 1.0), Anchor.BOTTOM_CENTER: (0.5, 1.0), Anchor.BOTTOM_RIGHT: (1.0, 1.0),
}


@dataclass(frozen=True)
class Placement:
    mode: Literal["absolute", "anchor", "normalized"] = "absolute"
    # anchor:
    anchor: Anchor = Anchor.TOP_LEFT
    dx_pt: float = 0.0
    dy_pt: float = 0.0
    # normalized:
    cx_norm: float = 0.5
    cy_norm: float = 0.5
    w_norm: float = 0.0
    h_norm: float = 0.0
    ref_page_w_pt: float = 595.0
    ref_page_h_pt: float = 842.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["anchor"] = self.anchor.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Placement":
        d = dict(d)
        d["anchor"] = Anchor(d.get("anchor", Anchor.TOP_LEFT.value))
        return cls(**d)


def resolve_frame(frame: Frame, placement: Placement, geo: PageGeometry) -> Frame:
    """Frame efectivo del elemento en UNA página concreta (display space)."""
    if placement.mode == "absolute":
        return frame

    if placement.mode == "normalized":
        w = geo.width_pt * placement.w_norm
        h = geo.height_pt * placement.h_norm
        cx = geo.width_pt * placement.cx_norm
        cy = geo.height_pt * placement.cy_norm
        return Frame(x=cx - w / 2, y=cy - h / 2, w=w, h=h)

    # anchor: el frame conserva su tamaño; la posición se calcula contra la página
    fx, fy = _ANCHOR_FRACTIONS[placement.anchor]
    x = (geo.width_pt - frame.w) * fx + placement.dx_pt
    y = (geo.height_pt - frame.h) * fy + placement.dy_pt
    return Frame(x=x, y=y, w=frame.w, h=frame.h)
