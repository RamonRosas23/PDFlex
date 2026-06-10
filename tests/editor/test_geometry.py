"""Geometría: round-trip display↔inserción en las 4 rotaciones, anclas y unidades."""
import fitz
import pytest

from core.editor.geometry import PageGeometry, display_rect_to_insertion, mm_to_pt, pt_to_mm


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_display_to_insertion_is_identity_on_pymupdf_127(make_pdf, rotation):
    """Contrato empírico PyMuPDF ≥1.27: las APIs de inserción operan en espacio
    display → la conversión es identidad EN TODA rotación. La garantía real de
    posición la da la prueba reina (test_export_roundtrip.py); este test fija
    el contrato del chokepoint."""
    path = make_pdf(rotations=[rotation])
    with fitz.open(path) as doc:
        geo = PageGeometry.from_page(0, doc[0])
        rect_display = fitz.Rect(100, 150, 300, 250)
        rect_ins = display_rect_to_insertion(rect_display, geo)
        assert tuple(rect_ins) == pytest.approx(tuple(rect_display), abs=1e-9)


def test_rotation_0_is_identity(make_pdf):
    path = make_pdf(rotations=[0])
    with fitz.open(path) as doc:
        geo = PageGeometry.from_page(0, doc[0])
        r = fitz.Rect(10, 20, 30, 40)
        assert tuple(display_rect_to_insertion(r, geo)) == pytest.approx(tuple(r))


def test_page_geometry_captures_display_dims(make_pdf):
    path = make_pdf(rotations=[90])
    with fitz.open(path) as doc:
        geo = PageGeometry.from_page(0, doc[0])
        assert round(geo.width_pt) == 842 and round(geo.height_pt) == 595
        assert geo.rotation == 90


def test_units():
    assert mm_to_pt(25.4) == pytest.approx(72.0)
    assert pt_to_mm(72.0) == pytest.approx(25.4)
