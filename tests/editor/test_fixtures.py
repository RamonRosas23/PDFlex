"""Sanidad de los fixtures: los PDFs generados tienen la rotación y tamaños esperados."""
import fitz
import pytest


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_pdf_has_rotation(make_pdf, rotation):
    path = make_pdf(rotations=[rotation])
    with fitz.open(path) as doc:
        page = doc[0]
        assert page.rotation == rotation
        # A4: 595x842. Con /Rotate 90/270 el rect display transpone dimensiones.
        if rotation in (90, 270):
            assert round(page.rect.width) == 842 and round(page.rect.height) == 595
        else:
            assert round(page.rect.width) == 595 and round(page.rect.height) == 842


def test_mixed_sizes_pdf(make_pdf):
    path = make_pdf(sizes=[(595, 842), (612, 1008), (420, 595)])  # A4, oficio, A5
    with fitz.open(path) as doc:
        assert doc.page_count == 3
        assert round(doc[1].rect.width) == 612 and round(doc[1].rect.height) == 1008
