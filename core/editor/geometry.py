"""Coordinate helpers for PDFlex Studio.

The editor model uses display coordinates: PDF points after applying page
rotation, with the origin at the visible top-left corner and Y growing down.
Exporting now writes display-sized overlay pages, so no backend-specific
derotation matrix is needed for drawing.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.pdf_backend import PageInfo, Rect

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0


def mm_to_pt(mm: float) -> float:
    return mm * PT_PER_INCH / MM_PER_INCH


def pt_to_mm(pt: float) -> float:
    return pt * MM_PER_INCH / PT_PER_INCH


Matrix6 = tuple[float, float, float, float, float, float]
IDENTITY_MATRIX: Matrix6 = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class PageGeometry:
    """Immutable display geometry for one PDF page."""

    index: int
    width_pt: float
    height_pt: float
    rotation: int
    derotation_matrix: Matrix6 = IDENTITY_MATRIX
    rotation_matrix: Matrix6 = IDENTITY_MATRIX

    @classmethod
    def from_page_info(cls, info: PageInfo) -> "PageGeometry":
        return cls(
            index=info.index,
            width_pt=info.width_pt,
            height_pt=info.height_pt,
            rotation=info.rotation % 360,
        )


def display_rect(rect: object) -> Rect:
    """Return a backend-neutral display rectangle."""
    return Rect(
        float(getattr(rect, "x0")),
        float(getattr(rect, "y0")),
        float(getattr(rect, "x1")),
        float(getattr(rect, "y1")),
    )


def insertion_rect(rect: object, _geo: PageGeometry) -> Rect:
    """Compatibility alias for old callers; overlays draw in display space."""
    return display_rect(rect)
