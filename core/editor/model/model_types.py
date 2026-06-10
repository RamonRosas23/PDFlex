"""Tipos de salida de la resolución (separados para evitar import circular)."""
from __future__ import annotations
from dataclasses import dataclass

from .placement import Frame


@dataclass(frozen=True)
class ResolvedElement:
    """Instancia lista para pintar/exportar en UNA página concreta."""
    element: object
    frame: Frame
    effective_opacity: float
    layer_z: int
    text: str | None = None          # texto final con variables sustituidas
    from_rule_id: str | None = None  # None = elemento concreto

    @property
    def is_ghost(self) -> bool:
        return self.from_rule_id is not None
