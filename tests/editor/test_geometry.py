"""Geometria del editor: coordenadas display, anclas y unidades."""
import pytest

from core.editor.geometry import PageGeometry, insertion_rect, mm_to_pt, pt_to_mm
from core.pdf_backend import PdfRenderDocument, Rect

R_DISPLAY = Rect(100, 150, 300, 250)


def _coords(rect: Rect) -> tuple[float, float, float, float]:
    return (rect.x0, rect.y0, rect.x1, rect.y1)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_insertion_rect_keeps_display_coordinates(make_pdf, rotation):
    path = make_pdf(rotations=[rotation])
    with PdfRenderDocument(path) as document:
        geo = PageGeometry.from_page_info(document.page_info(0))
        got = insertion_rect(R_DISPLAY, geo)
        assert _coords(got) == pytest.approx(_coords(R_DISPLAY), abs=1e-6)


def test_page_geometry_captures_display_dims(make_pdf):
    path = make_pdf(rotations=[90])
    with PdfRenderDocument(path) as document:
        geo = PageGeometry.from_page_info(document.page_info(0))
        assert round(geo.width_pt) == 842 and round(geo.height_pt) == 595
        assert geo.rotation == 90


def test_units():
    assert mm_to_pt(25.4) == pytest.approx(72.0)
    assert pt_to_mm(72.0) == pytest.approx(25.4)
