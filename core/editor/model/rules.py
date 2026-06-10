"""Reglas de página: UN elemento + UN objetivo → instancias fantasma (spec §10.3)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field

from .elements import element_from_dict
from .page_target import PageTarget


@dataclass(frozen=True)
class PageRule:
    element: object                       # TextElement | ImageElement | …
    target: PageTarget
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {"id": self.id, "element": self.element.to_dict(),
                "target": self.target.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "PageRule":
        return cls(id=d["id"], element=element_from_dict(d["element"]),
                   target=PageTarget.from_dict(d["target"]))
