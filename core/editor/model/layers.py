"""Capas del editor (concepto del editor, no del PDF fuente — spec §10.2)."""
from __future__ import annotations
from dataclasses import dataclass, asdict

GENERAL_LAYER_ID = "general"


@dataclass
class Layer:
    id: str
    name: str
    z: int = 0
    visible: bool = True
    locked: bool = False
    opacity: float = 1.0
    export_as_ocg: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Layer":
        return cls(**d)


class LayerStack:
    """Siempre contiene la capa 'General' (no eliminable)."""

    def __init__(self) -> None:
        self._layers: dict[str, Layer] = {}
        self.add(Layer(id=GENERAL_LAYER_ID, name="General", z=0))

    def add(self, layer: Layer) -> None:
        self._layers[layer.id] = layer

    def get(self, layer_id: str) -> Layer | None:
        return self._layers.get(layer_id)

    def remove(self, layer_id: str) -> None:
        if layer_id == GENERAL_LAYER_ID:
            raise ValueError("La capa General está protegida y no puede eliminarse")
        self._layers.pop(layer_id, None)

    def all(self) -> list[Layer]:
        return sorted(self._layers.values(), key=lambda l: l.z)

    def to_dict(self) -> list[dict]:
        return [l.to_dict() for l in self.all()]

    @classmethod
    def from_dict(cls, items: list[dict]) -> "LayerStack":
        st = cls()
        for d in items:
            st.add(Layer.from_dict(d))
        return st
