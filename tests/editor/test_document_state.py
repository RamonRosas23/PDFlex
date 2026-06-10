"""EditorDocument: resolución por página de elementos + reglas, orden z, capas."""
import pytest

from core.editor.geometry import PageGeometry
from core.editor.model.document_state import EditorDocument
from core.editor.model.elements import TextElement
from core.editor.model.layers import Layer
from core.editor.model.page_target import PageTarget
from core.editor.model.placement import Anchor, Frame, Placement
from core.editor.model.rules import PageRule


def _geo(i, w=595.0, h=842.0):
    return PageGeometry(index=i, width_pt=w, height_pt=h, rotation=0,
                        derotation_matrix=(1, 0, 0, 1, 0, 0),
                        rotation_matrix=(1, 0, 0, 1, 0, 0))


def _doc(n_pages=4) -> EditorDocument:
    return EditorDocument(source_path="x.pdf", source_sha256="0" * 64,
                          page_geometries=[_geo(i) for i in range(n_pages)])


def test_concrete_element_only_on_its_page():
    doc = _doc()
    el = TextElement(text="hola", frame=Frame(10, 10, 100, 20))
    doc.add_element(page=2, element=el)
    assert [r.element.id for r in doc.resolved_elements(2)] == [el.id]
    assert doc.resolved_elements(1) == []


def test_rule_materializes_on_target_pages_with_resolved_frame():
    doc = _doc(4)  # páginas 1..4
    rule = PageRule(
        element=TextElement(text="Pág. {pagina} de {total}", variables_enabled=True,
                            frame=Frame(0, 0, 120, 18),
                            placement=Placement(mode="anchor",
                                                anchor=Anchor.BOTTOM_CENTER, dy_pt=-10)),
        target=PageTarget(mode="odd"),
    )
    doc.add_rule(rule)
    r1 = doc.resolved_elements(1)
    assert len(r1) == 1 and r1[0].from_rule_id == rule.id
    assert r1[0].is_ghost
    assert r1[0].text == "Pág. 1 de 4"                    # variable sustituida
    assert r1[0].frame.y == pytest.approx(842 - 18 - 10)  # ancla resuelta
    assert doc.resolved_elements(2) == []                 # página par: nada


def test_z_order_layer_then_element():
    doc = _doc(1)
    doc.layers.add(Layer(id="fondo", name="Fondo", z=0))
    doc.layers.add(Layer(id="frente", name="Frente", z=10))
    a = TextElement(text="a", layer_id="frente", z=1)
    b = TextElement(text="b", layer_id="fondo", z=99)   # z alto en capa baja
    c = TextElement(text="c", layer_id="frente", z=0)
    for el in (a, b, c):
        doc.add_element(page=1, element=el)
    order = [r.text for r in doc.resolved_elements(1)]
    assert order == ["b", "c", "a"]                     # capa manda; luego z


def test_hidden_layer_and_hidden_element_excluded():
    doc = _doc(1)
    doc.layers.add(Layer(id="oculta", name="Oculta", z=5, visible=False))
    doc.add_element(1, TextElement(text="invisible-capa", layer_id="oculta"))
    doc.add_element(1, TextElement(text="invisible-flag", hidden=True))
    doc.add_element(1, TextElement(text="visible"))
    assert [r.text for r in doc.resolved_elements(1)] == ["visible"]


def test_layer_opacity_multiplies_element_opacity():
    doc = _doc(1)
    doc.layers.add(Layer(id="suave", name="Suave", z=1, opacity=0.5))
    doc.add_element(1, TextElement(text="x", layer_id="suave", opacity=0.6))
    assert doc.resolved_elements(1)[0].effective_opacity == pytest.approx(0.3)


def test_default_layer_always_exists_and_is_protected():
    doc = _doc(1)
    assert doc.layers.get("general") is not None
    with pytest.raises(ValueError, match="protegida"):
        doc.layers.remove("general")


def test_remove_element_and_rule():
    doc = _doc(1)
    el = TextElement(text="x")
    doc.add_element(1, el)
    assert doc.remove_element(1, el.id) is el
    assert doc.remove_element(1, "no-existe") is None
    rule = PageRule(element=TextElement(text="r"), target=PageTarget())
    doc.add_rule(rule)
    assert doc.remove_rule(rule.id) is rule
    assert doc.remove_rule("no-existe") is None
    assert doc.resolved_elements(1) == []
