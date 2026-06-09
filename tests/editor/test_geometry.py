"""Geometría: round-trip display↔inserción en las 4 rotaciones, anclas y unidades."""
import fitz
import pytest

from core.editor.geometry import PageGeometry, display_rect_to_insertion, mm_to_pt, pt_to_mm


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_display_to_insertion_roundtrip(make_pdf, rotation):
    """rect_display → inserción → (rotation_matrix) → rect_display: identidad ≤1e-3 pt."""
    path = make_pdf(rotations=[rotation])
    with fitz.open(path) as doc:
        page = doc[0]
        geo = PageGeometry.from_page(0, page)
        rect_display = fitz.Rect(100, 150, 300, 250)
        rect_ins = display_rect_to_insertion(rect_display, geo)
        # Volver al espacio display con la matriz de rotación capturada
        back = rect_ins * fitz.Matrix(*geo.rotation_matrix)
        back.normalize()
        for got, want in zip(tuple(back), tuple(rect_display)):
            assert got == pytest.approx(want, abs=1e-3)


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
