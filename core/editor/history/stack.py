"""Pila undo/redo pura (sin Qt — decisión registrada en el plan, spec §10.4)."""
from __future__ import annotations
from contextlib import contextmanager


class Macro:
    """Agrupa comandos hijos como UN paso."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.merge_key = None
        self.children: list = []

    def do(self) -> None:
        for c in self.children:
            c.do()

    def undo(self) -> None:
        for c in reversed(self.children):
            c.undo()

    def merge_with(self, newer) -> bool:
        return False


class HistoryStack:
    def __init__(self, limit: int = 200) -> None:
        self._limit = limit
        self._undo: list = []
        self._redo: list = []
        self._macro: Macro | None = None

    # ── push / macro ────────────────────────────────────────────────
    def push(self, cmd) -> None:
        cmd.do()
        self._redo.clear()
        if self._macro is not None:
            self._macro.children.append(cmd)
            return
        if (self._undo and cmd.merge_key
                and self._undo[-1].merge_key == cmd.merge_key
                and self._undo[-1].merge_with(cmd)):
            return
        self._undo.append(cmd)
        if len(self._undo) > self._limit:
            self._undo.pop(0)

    @contextmanager
    def macro(self, text: str):
        self._macro = Macro(text)
        try:
            yield self._macro
        finally:
            macro, self._macro = self._macro, None
            if macro.children:
                self._redo.clear()
                self._undo.append(macro)
                if len(self._undo) > self._limit:
                    self._undo.pop(0)

    # ── undo / redo ─────────────────────────────────────────────────
    def undo(self) -> None:
        if self._undo:
            cmd = self._undo.pop()
            cmd.undo()
            self._redo.append(cmd)

    def redo(self) -> None:
        if self._redo:
            cmd = self._redo.pop()
            cmd.do()
            self._undo.append(cmd)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_count(self) -> int:
        return len(self._undo)
