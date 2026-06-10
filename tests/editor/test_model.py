"""Modelo de elementos: defaults, serialización round-trip y resolución de anclas."""
import pytest

from core.editor.geometry import PageGeometry
from core.editor.model.placement import Anchor, Frame, Placement, resolve_frame
from core.editor.model.elements import TextElement, ImageElement, element_from_dict


def _a4():
    return PageGeometry(index=0, width_pt=595.0, height_pt=842.0, rotation=0,
                        derotation_matrix=(1, 0, 0, 1, 0, 0),
                        rotation_matrix=(1, 0, 0, 1, 0, 0))


def _oficio():
    return PageGeometry(index=1, width_pt=612.0, height_pt=1008.0, rotation=0,
                        derotation_matrix=(1, 0, 0, 1, 0, 0),
                        rotation_matrix=(1, 0, 0, 1, 0, 0))


def test_absolute_placement_is_identity():
    f = Frame(x=100, y=200, w=150, h=40)
    p = Placement(mode="absolute")
    assert resolve_frame(f, p, _a4()) == f


def test_anchor_bottom_right_adapts_to_page_size():
    f = Frame(x=0, y=0, w=100, h=30)
    p = Placement(mode="anchor", anchor=Anchor.BOTTOM_RIGHT, dx_pt=-20, dy_pt=-15)
    fa = resolve_frame(f, p, _a4())
    fo = resolve_frame(f, p, _oficio())
    # El frame queda pegado a la esquina inf-der menos el offset, en AMBAS páginas
    assert fa.x == pytest.approx(595 - 100 - 20) and fa.y == pytest.approx(842 - 30 - 15)
    assert fo.x == pytest.approx(612 - 100 - 20) and fo.y == pytest.approx(1008 - 30 - 15)


def test_anchor_center_centers_frame():
    f = Frame(x=0, y=0, w=200, h=100)
    p = Placement(mode="anchor", anchor=Anchor.CENTER)
    fa = resolve_frame(f, p, _a4())
    assert fa.x == pytest.approx((595 - 200) / 2)
    assert fa.y == pytest.approx((842 - 100) / 2)


def test_normalized_placement_scales_like_foleador():
    # Centro al 50%,25% de la página y tamaño 30%x5% de la página destino
    f = Frame(x=0, y=0, w=0, h=0)
    p = Placement(mode="normalized", cx_norm=0.5, cy_norm=0.25,
                  w_norm=0.3, h_norm=0.05, ref_page_w_pt=595, ref_page_h_pt=842)
    fo = resolve_frame(f, p, _oficio())
    assert fo.w == pytest.approx(612 * 0.3)
    assert fo.h == pytest.approx(1008 * 0.05)
    assert fo.x + fo.w / 2 == pytest.approx(612 * 0.5)
    assert fo.y + fo.h / 2 == pytest.approx(1008 * 0.25)


def test_text_element_serialization_roundtrip():
    el = TextElement(text="CONFIDENCIAL", font_size=24.0, color=(0.9, 0.1, 0.1),
                     frame=Frame(x=10, y=20, w=300, h=50), opacity=0.5,
                     align="center", rotation_deg=30.0, layer_id="marcas")
    data = el.to_dict()
    back = element_from_dict(data)
    assert isinstance(back, TextElement)
    assert back == el


def test_image_element_serialization_roundtrip():
    el = ImageElement(asset_id="ab12" * 16, frame=Frame(x=5, y=6, w=80, h=80),
                      crop=(0.1, 0.1, 0.9, 0.9), keep_aspect=False, flip_h=True)
    assert element_from_dict(el.to_dict()) == el


def test_elements_get_unique_ids():
    a, b = TextElement(text="a"), TextElement(text="b")
    assert a.id and b.id and a.id != b.id


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="kind"):
        element_from_dict({"kind": "hologram", "schema": 1})
