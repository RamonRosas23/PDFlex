"""Small PDF geometry values independent from any native PDF library."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def intersects(self, other) -> bool:
        return not (
            self.x1 <= float(other.x0)
            or self.x0 >= float(other.x1)
            or self.y1 <= float(other.y0)
            or self.y0 >= float(other.y1)
        )
