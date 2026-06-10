"""PRUEBA REINA (gate de Fase 0): lo insertado queda EXACTAMENTE donde se pidió,
en las 4 rotaciones, verificado releyendo el PDF generado."""
import fitz
import pytest

from core.editor.geometry import PageGeometry
from core.editor.export.primitives import stamp_rect, stamp_text

TARGET = fitz.Rect(120.0, 180.0, 320.0, 260.0)  # display space
ROTATIONS = [0, 90, 180, 270]


def _roundtrip(make_pdf, rotation, stamp_fn):
    src = make_pdf(rotations=[rotation])
    out = src.with_name(f"out_{rotation}.pdf")
    with fitz.open(src) as doc:
        geo = PageGeometry.from_page(0, doc[0])
        stamp_fn(doc[0], geo)
        doc.save(str(out))
    return out


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_rect_lands_exactly_where_placed(make_pdf, rotation):
    out = _roundtrip(make_pdf, rotation,
                     lambda page, geo: stamp_rect(page, geo, TARGET,
                                                  fill=(1, 0, 0), opacity=0.5))
    with fitz.open(out) as doc:
        drawings = doc[0].get_drawings()
        assert len(drawings) == 1
        got = drawings[0]["rect"]  # get_drawings reporta en espacio display
        for g, w in zip(tuple(got), tuple(TARGET)):
            assert g == pytest.approx(w, abs=0.5), f"/Rotate={rotation}: {got} vs {TARGET}"


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_text_lands_inside_box_and_reads_horizontal(make_pdf, rotation):
    out = _roundtrip(make_pdf, rotation,
                     lambda page, geo: stamp_text(page, geo, TARGET, "PDFlex Studio",
                                                  fontsize=14))
    with fitz.open(out) as doc:
        d = doc[0].get_text("dict")
        spans = [s for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]]
        assert len(spans) >= 1
        span = spans[0]
        assert span["text"].strip() == "PDFlex Studio"
        # Contenido dentro de la caja pedida (+1.5 pt de holgura por métricas de fuente)
        box = fitz.Rect(span["bbox"])
        outer = fitz.Rect(TARGET) + (-1.5, -1.5, 1.5, 1.5)
        assert outer.contains(box), \
            f"/Rotate={rotation}: bbox {box} fuera de {TARGET}"
        # El texto se LEE horizontal en pantalla (dirección de escritura compensada)
        line = [l for b in d["blocks"] for l in b.get("lines", [])][0]
        assert line["dir"] == pytest.approx((1.0, 0.0), abs=1e-6), \
            f"/Rotate={rotation}: dir={line['dir']} — rotación no compensada"
