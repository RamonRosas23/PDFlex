"""LRU con presupuesto en bytes para pixmaps de página (spec §20)."""
from __future__ import annotations
from collections import OrderedDict
from typing import Any, Hashable


class ByteBudgetLRU:
    def __init__(self, budget_bytes: int) -> None:
        self._budget = budget_bytes
        self._items: OrderedDict[Hashable, tuple[Any, int]] = OrderedDict()
        self.used_bytes = 0

    def get(self, key: Hashable):
        entry = self._items.get(key)
        if entry is None:
            return None
        self._items.move_to_end(key)
        return entry[0]

    def put(self, key: Hashable, value: Any, size_bytes: int) -> None:
        if size_bytes > self._budget:
            return  # nunca cabrá; no desalojar todo por gusto
        if key in self._items:
            self.used_bytes -= self._items.pop(key)[1]
        while self.used_bytes + size_bytes > self._budget and self._items:
            _, (_, sz) = self._items.popitem(last=False)
            self.used_bytes -= sz
        self._items[key] = (value, size_bytes)
        self.used_bytes += size_bytes

    def clear(self) -> None:
        self._items.clear()
        self.used_bytes = 0
