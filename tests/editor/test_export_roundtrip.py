"""PRUEBA REINA (gate de Fase 0): lo insertado queda EXACTAMENTE donde se pidió,
en las 4 rotaciones, verificado POR PÍXELES releyendo el PDF generado.

Nota crítica (sondas 2026-06-09, PyMuPDF 1.27): las APIs de extracción
(get_text / get_drawings / get_image_info) reportan en espacio SIN ROTAR —
la única verificación válida de posición display es renderizar y medir píxeles.
"""
import fitz
import numpy as np
import pytest

from core.editor.geometry import PageGeometry
from core.editor.export.primitives import (
    stamp_image, stamp_image_rotated, stamp_rect, stamp_text,
)

TARGET = fitz.Rect(120.0, 180.0, 320.0, 260.0)  # display space
ROTATIONS = [0, 90, 180, 270]
_SCALE = 2  # render del verificador: 2x → resolución de 0.5 pt


def _roundtrip(make_pdf, rotation, stamp_fn):
    src = make_pdf(rotations=[rotation])
    out = src.with_name(f"out_{rotation}.pdf")
    with fitz.open(src) as doc:
        geo = PageGeometry.from_page(0, doc[0])
        stamp_fn(doc[0], geo)
        doc.save(str(out))
    return out


def _visual_bbox_pt(page, *, red_corner: bool = False):
    """Bbox (pt display) de los píxeles no-blancos; opcionalmente en qué
    cuadrante del bbox quedó el promedio de los píxeles rojos. Vía numpy."""
    pix = page.get_pixmap(matrix=fitz.Matrix(_SCALE, _SCALE), alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    nonwhite = (arr < 250).any(axis=2)
    ys, xs = np.nonzero(nonwhite)
    assert xs.size, "no se encontró contenido renderizado en la página"
    bbox = fitz.Rect(xs.min() / _SCALE, ys.min() / _SCALE,
                     (xs.max() + 1) / _SCALE, (ys.max() + 1) / _SCALE)
    if not red_corner:
        return bbox, None
    red = (arr[:, :, 0] > 180) & (arr[:, :, 2] < 80)
    rys, rxs = np.nonzero(red)
    assert rxs.size, "no se encontraron píxeles rojos (sonda de orientación)"
    rx, ry = rxs.mean() / _SCALE, rys.mean() / _SCALE
    cx, cy = (bbox.x0 + bbox.x1) / 2, (bbox.y0 + bbox.y1) / 2
    corner = ("izq" if rx < cx else "der", "sup" if ry < cy else "inf")
    return bbox, corner


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_rect_lands_exactly_where_placed(make_pdf, rotation):
    out = _roundtrip(make_pdf, rotation,
                     lambda page, geo: stamp_rect(page, geo, TARGET, fill=(1, 0, 0)))
    with fitz.open(out) as doc:
        got, _ = _visual_bbox_pt(doc[0])
        for g, w in zip(tuple(got), tuple(TARGET)):
            assert g == pytest.approx(w, abs=0.5), f"/Rotate={rotation}: {got} vs {TARGET}"


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_text_lands_inside_box_and_reads_horizontal(make_pdf, rotation):
    out = _roundtrip(make_pdf, rotation,
                     lambda page, geo: stamp_text(page, geo, TARGET, "PDFlex Studio",
                                                  fontsize=14))
    with fitz.open(out) as doc:
        # Contenido correcto (la extracción de TEXTO es independiente del espacio)
        assert "PDFlex Studio" in doc[0].get_text()
        # Posición y horizontalidad: SOLO por píxeles
        got, _ = _visual_bbox_pt(doc[0])
        outer = fitz.Rect(TARGET) + (-1.5, -1.5, 1.5, 1.5)
        assert outer.contains(got), \
            f"/Rotate={rotation}: píxeles {got} fuera de {TARGET}"
        w, h = got.width, got.height
        assert w / h > 2.0, \
            f"/Rotate={rotation}: bbox {w:.0f}x{h:.0f} no es horizontal — texto girado"


SQUARE = fitz.Rect(150.0, 200.0, 230.0, 280.0)  # cuadrado: la sonda no se deforma


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_image_lands_exactly_and_upright(make_pdf, probe_png, rotation):
    """Posición ≤0.5 pt Y orientación (cuadrante rojo arriba-izquierda) por píxeles."""
    out = _roundtrip(make_pdf, rotation,
                     lambda page, geo: stamp_image(page, geo, SQUARE, probe_png))
    with fitz.open(out) as doc:
        got, corner = _visual_bbox_pt(doc[0], red_corner=True)
        for g, w in zip(tuple(got), tuple(SQUARE)):
            assert g == pytest.approx(w, abs=0.5), f"/Rotate={rotation}: {got} vs {SQUARE}"
        assert corner == ("izq", "sup"), \
            f"/Rotate={rotation}: rojo en {corner}, imagen rotada por error"


# ── Rotación libre de elementos (convención de producto: positivo = horario) ──


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_image_rotated_90cw_directional(make_pdf, probe_png, rotation):
    """90° horario: el cuadrante rojo pasa de sup-izq a sup-der; el bbox de un
    cuadrado no cambia. Pin del SIGNO de la rotación, en páginas rotadas y no."""
    out = _roundtrip(make_pdf, rotation,
                     lambda page, geo: stamp_image_rotated(page, geo, SQUARE,
                                                           probe_png, angle_deg=90.0))
    with fitz.open(out) as doc:
        got, corner = _visual_bbox_pt(doc[0], red_corner=True)
        for g, w in zip(tuple(got), tuple(SQUARE)):
            assert g == pytest.approx(w, abs=0.75), f"/Rotate={rotation}: {got} vs {SQUARE}"
        assert corner == ("der", "sup"), \
            f"/Rotate={rotation}: rojo en {corner} — signo de rotación incorrecto"


@pytest.mark.parametrize("rotation", [0, 180])
def test_image_rotated_45_grows_centered(make_pdf, probe_png, rotation):
    """45°: el bbox crece a lado·√2 y el CENTRO no se mueve (gira sobre sí misma)."""
    out = _roundtrip(make_pdf, rotation,
                     lambda page, geo: stamp_image_rotated(page, geo, SQUARE,
                                                           probe_png, angle_deg=45.0))
    side = SQUARE.width
    diag = side * 2 ** 0.5
    with fitz.open(out) as doc:
        got, _ = _visual_bbox_pt(doc[0])
        assert got.width == pytest.approx(diag, abs=1.5)
        assert got.height == pytest.approx(diag, abs=1.5)
        assert (got.x0 + got.x1) / 2 == pytest.approx((SQUARE.x0 + SQUARE.x1) / 2, abs=1.0)
        assert (got.y0 + got.y1) / 2 == pytest.approx((SQUARE.y0 + SQUARE.y1) / 2, abs=1.0)


@pytest.mark.parametrize("rotation", [0, 90])
def test_text_rotated_45_centered_and_diagonal(make_pdf, rotation):
    """Cuadro de texto AJUSTADO al contenido, a 45°: el bbox deja de ser
    horizontal (aspecto ~1) y gira alrededor del centro del frame (semántica
    de producto = Qt: el contenido se maqueta sup-izq dentro del frame y el
    FRAME es lo que gira). Por píxeles; el contenido sigue extraíble."""
    text = "IIIIIIIIIIIIIIII"
    tw = fitz.get_text_length(text, fontname="helv", fontsize=14)
    # insert_textbox exige alto ≥ ~fontsize*1.68 (sondeado: 23.5 pt para 14 pt)
    box = fitz.Rect(120.0, 180.0, 120.0 + tw + 1.0, 180.0 + 26.0)

    def _stamp(page, geo):
        leftover = stamp_text(page, geo, box, text, fontsize=14, angle_deg=45.0)
        assert leftover >= 0, f"insert_textbox omitió el texto (déficit {leftover:.2f})"

    out = _roundtrip(make_pdf, rotation, _stamp)
    with fitz.open(out) as doc:
        assert text in doc[0].get_text()
        got, _ = _visual_bbox_pt(doc[0])
        aspect = got.width / got.height
        assert 0.6 < aspect < 1.6, \
            f"/Rotate={rotation}: aspecto {aspect:.2f} — el texto no quedó a 45°"
        # Contenido ~llena el frame → el centroide se queda en el centro del frame
        assert (got.x0 + got.x1) / 2 == pytest.approx((box.x0 + box.x1) / 2, abs=3.0)
        assert (got.y0 + got.y1) / 2 == pytest.approx((box.y0 + box.y1) / 2, abs=3.0)
