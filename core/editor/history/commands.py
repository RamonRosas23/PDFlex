"""Comandos undoables. Guardan DELTAS, no snapshots (spec §20).

Los elementos son dataclasses frozen: 'mover' = reemplazar el objeto por una
copia con frame nuevo. El comando guarda referencias old/new — barato y exacto.
"""
from __future__ import annotations
from dataclasses import replace


class Command:
    """Interfaz: do()/undo(); merge_key opcional para fusionar arrastres."""
    text: str = ""
    merge_key: str | None = None

    def do(self) -> None: ...
    def undo(self) -> None: ...

    def merge_with(self, newer: "Command") -> bool:
        """Absorbe un comando más nuevo con el mismo merge_key. False = no fusiona."""
        return False


class AddElement(Command):
    def __init__(self, doc, page: int, element) -> None:
        self.text = "Agregar elemento"
        self._doc, self._page, self._element = doc, page, element

    def do(self) -> None:
        self._doc.add_element(self._page, self._element)

    def undo(self) -> None:
        self._doc.remove_element(self._page, self._element.id)


class RemoveElement(Command):
    def __init__(self, doc, page: int, element_id: str) -> None:
        self.text = "Eliminar elemento"
        self._doc, self._page, self._eid = doc, page, element_id
        self._removed = None

    def do(self) -> None:
        self._removed = self._doc.remove_element(self._page, self._eid)

    def undo(self) -> None:
        if self._removed is not None:
            self._doc.add_element(self._page, self._removed)


class MoveResize(Command):
    def __init__(self, doc, page: int, element_id: str, new_frame,
                 merge_key: str | None = None) -> None:
        self.text = "Mover/redimensionar"
        self.merge_key = merge_key
        self._doc, self._page, self._eid = doc, page, element_id
        self._new_frame = new_frame
        self._old_frame = None

    def _swap(self, frame) -> None:
        items = self._doc.elements_by_page.get(self._page, [])
        for i, el in enumerate(items):
            if el.id == self._eid:
                items[i] = replace(el, frame=frame)
                return

    def do(self) -> None:
        if self._old_frame is None:
            for el in self._doc.elements_by_page.get(self._page, []):
                if el.id == self._eid:
                    self._old_frame = el.frame
                    break
        self._swap(self._new_frame)

    def undo(self) -> None:
        if self._old_frame is not None:
            self._swap(self._old_frame)

    def merge_with(self, newer: "Command") -> bool:
        if isinstance(newer, MoveResize) and newer._eid == self._eid:
            self._new_frame = newer._new_frame   # newer ya hizo do(); estado al día
            return True
        return False


class SetElementAttrs(Command):
    """Cambio de estilo/atributos: opacity, color, font_size, text, etc."""

    def __init__(self, doc, page: int, element_id: str,
                 merge_key: str | None = None, **attrs) -> None:
        self.text = "Cambiar propiedades"
        self.merge_key = merge_key
        self._doc, self._page, self._eid, self._attrs = doc, page, element_id, attrs
        self._old: dict | None = None

    def do(self) -> None:
        items = self._doc.elements_by_page.get(self._page, [])
        for i, el in enumerate(items):
            if el.id == self._eid:
                if self._old is None:
                    self._old = {k: getattr(el, k) for k in self._attrs}
                items[i] = replace(el, **self._attrs)
                return

    def undo(self) -> None:
        if self._old is None:
            return
        items = self._doc.elements_by_page.get(self._page, [])
        for i, el in enumerate(items):
            if el.id == self._eid:
                items[i] = replace(el, **self._old)
                return

    def merge_with(self, newer: "Command") -> bool:
        if isinstance(newer, SetElementAttrs) and newer._eid == self._eid \
                and set(newer._attrs) == set(self._attrs):
            self._attrs = newer._attrs           # newer ya hizo do(); estado al día
            return True
        return False
