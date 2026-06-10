"""Objetivo de páginas para reglas y aplicación masiva (spec §10.2).

Sintaxis de spec: "1-5,9,12-"  (rangos cerrados, páginas sueltas, rango abierto
al final del documento). 1-based, como todo lo visible al usuario en la suite
(mismo criterio que core/split_ranges.py del Separador).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

_ERR_EMPTY = "El objetivo de páginas está vacío. Ejemplos: 1-5,9,12-"
_ERR_BAD = "Tramo inválido: {part!r}. Usa números (5), rangos (3-8) o abiertos (12-)"


def parse_pages_spec(spec: str, total: int) -> list[int]:
    """Parsea la spec → lista 1-based ordenada y sin duplicados, recortada a [1,total]."""
    spec = (spec or "").strip()
    if not spec:
        raise ValueError(_ERR_EMPTY)
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if part.endswith("-"):
                start = int(part[:-1])
                end = total
            elif "-" in part:
                a, b = part.split("-", 1)
                start, end = int(a), int(b)
            else:
                start = end = int(part)
        except ValueError:
            raise ValueError(_ERR_BAD.format(part=part)) from None
        if start > end:
            raise ValueError(_ERR_BAD.format(part=part))
        start, end = max(1, start), min(total, end)
        pages.update(range(start, end + 1))
    return sorted(pages)


@dataclass(frozen=True)
class PageTarget:
    mode: Literal["all", "current", "pages", "even", "odd"] = "all"
    spec: str = ""

    def resolve(self, total: int, current_page: int = 1) -> list[int]:
        if self.mode == "all":
            return list(range(1, total + 1))
        if self.mode == "current":
            return [current_page]
        if self.mode == "even":
            return list(range(2, total + 1, 2))
        if self.mode == "odd":
            return list(range(1, total + 1, 2))
        return parse_pages_spec(self.spec, total)

    def to_dict(self) -> dict:
        return {"mode": self.mode, "spec": self.spec}

    @classmethod
    def from_dict(cls, d: dict) -> "PageTarget":
        return cls(mode=d.get("mode", "all"), spec=d.get("spec", ""))
