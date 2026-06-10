"""Geometría: round-trip display↔inserción en las 4 rotaciones, anclas y unidades."""
import fitz
import pytest

from core.editor.geometry import PageGeometry, insertion_rect, mm_to_pt, pt_to_mm

R_DISPLAY = fitz.Rect(100, 150, 300, 250)

# Esperados calculados a mano para A4 (595x842) — espacio sin rotar:
#   /Rotate=90:  disp(X,Y) → unrot(Y, 842-X)
#   /Rotate=180: disp(X,Y) → unrot(595-X, 842-Y)
#   /Rotate=270: disp(X,Y) → unrot(595-Y, X)
_EXPECTED_INSERTION = {
    0:   (100.0, 150.0, 300.0, 250.0),
    90:  (150.0, 542.0, 250.0, 742.0),
    180: (295.0, 592.0, 495.0, 692.0),
    270: (345.0, 100.0, 445.0, 300.0),
}


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_insertion_rect_derotates(make_pdf, rotation):
    """Contrato empírico PyMuPDF 1.27 (demostrado por píxeles en la prueba
    reina): TODAS las APIs de inserción operan en espacio sin rotar →
    derotación, con valores esperados calculados a mano."""
    path = make_pdf(rotations=[rotation])
    with fitz.open(path) as doc:
        geo = PageGeometry.from_page(0, doc[0])
        got = insertion_rect(R_DISPLAY, geo)
        assert tuple(got) == pytest.approx(_EXPECTED_INSERTION[rotation], abs=1e-6)


def test_page_geometry_captures_display_dims(make_pdf):
    path = make_pdf(rotations=[90])
    with fitz.open(path) as doc:
        geo = PageGeometry.from_page(0, doc[0])
        assert round(geo.width_pt) == 842 and round(geo.height_pt) == 595
        assert geo.rotation == 90


def test_units():
    assert mm_to_pt(25.4) == pytest.approx(72.0)
    assert pt_to_mm(72.0) == pytest.approx(25.4)
