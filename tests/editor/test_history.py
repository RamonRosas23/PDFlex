"""HistoryStack puro: undo/redo, merge de arrastres, macros, tope de pasos."""
import pytest

from core.editor.geometry import PageGeometry
from core.editor.history.commands import (
    AddElement, MoveResize, RemoveElement, SetElementAttrs,
)
from core.editor.history.stack import HistoryStack
from core.editor.model.document_state import EditorDocument
from core.editor.model.elements import TextElement
from core.editor.model.placement import Frame


def _doc():
    geo = PageGeometry(index=0, width_pt=595, height_pt=842, rotation=0,
                       derotation_matrix=(1, 0, 0, 1, 0, 0),
                       rotation_matrix=(1, 0, 0, 1, 0, 0))
    return EditorDocument(source_path="x.pdf", source_sha256="0" * 64,
                          page_geometries=[geo])


def test_add_undo_redo():
    doc, h = _doc(), HistoryStack(limit=200)
    el = TextElement(text="hola")
    h.push(AddElement(doc, page=1, element=el))
    assert len(doc.resolved_elements(1)) == 1
    h.undo()
    assert doc.resolved_elements(1) == []
    h.redo()
    assert len(doc.resolved_elements(1)) == 1
    assert h.can_undo and not h.can_redo


def test_move_commands_merge_during_drag():
    doc, h = _doc(), HistoryStack()
    el = TextElement(text="x", frame=Frame(0, 0, 50, 20))
    h.push(AddElement(doc, page=1, element=el))
    # un arrastre = muchos micro-movimientos con el mismo merge_key
    for i in range(1, 11):
        h.push(MoveResize(doc, page=1, element_id=el.id,
                          new_frame=Frame(i * 5.0, i * 2.0, 50, 20),
                          merge_key=f"drag-{el.id}-1"))
    assert h.undo_count == 2              # Add + UN solo MoveResize fusionado
    assert doc.resolved_elements(1)[0].frame == Frame(50.0, 20.0, 50, 20)
    h.undo()
    assert doc.resolved_elements(1)[0].frame == Frame(0, 0, 50, 20)


def test_macro_groups_as_single_step():
    doc, h = _doc(), HistoryStack()
    els = [TextElement(text=f"e{i}") for i in range(3)]
    with h.macro("Pegar 3 elementos"):
        for el in els:
            h.push(AddElement(doc, page=1, element=el))
    assert h.undo_count == 1
    h.undo()
    assert doc.resolved_elements(1) == []
    h.redo()
    assert len(doc.resolved_elements(1)) == 3


def test_set_attrs_roundtrip_and_merge():
    doc, h = _doc(), HistoryStack()
    el = TextElement(text="x", opacity=1.0)
    h.push(AddElement(doc, page=1, element=el))
    h.push(SetElementAttrs(doc, page=1, element_id=el.id,
                           merge_key=f"op-{el.id}", opacity=0.8))
    h.push(SetElementAttrs(doc, page=1, element_id=el.id,
                           merge_key=f"op-{el.id}", opacity=0.5))
    assert h.undo_count == 2              # Add + UN SetElementAttrs fusionado
    assert doc.resolved_elements(1)[0].element.opacity == 0.5
    h.undo()
    assert doc.resolved_elements(1)[0].element.opacity == 1.0


def test_redo_cleared_on_new_command():
    doc, h = _doc(), HistoryStack()
    a, b = TextElement(text="a"), TextElement(text="b")
    h.push(AddElement(doc, page=1, element=a))
    h.undo()
    h.push(AddElement(doc, page=1, element=b))
    assert not h.can_redo


def test_limit_drops_oldest():
    doc, h = _doc(), HistoryStack(limit=3)
    for i in range(5):
        h.push(AddElement(doc, page=1, element=TextElement(text=str(i))))
    assert h.undo_count == 3


def test_remove_element_roundtrip():
    doc, h = _doc(), HistoryStack()
    el = TextElement(text="x")
    h.push(AddElement(doc, page=1, element=el))
    h.push(RemoveElement(doc, page=1, element_id=el.id))
    assert doc.resolved_elements(1) == []
    h.undo()
    assert [r.element.id for r in doc.resolved_elements(1)] == [el.id]
