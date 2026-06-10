"""Elementos del editor: dataclasses serializables, sin Qt y sin fitz.

Serialización: to_dict()/element_from_dict() con campo "schema" para
migraciones futuras (spec §17). Las imágenes referencian assets por hash
SHA-256 (el binario vive en el AssetStore del proyecto).
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field, asdict
from typing import Literal

from .placement import Frame, Placement

SCHEMA_VERSION = 1
RGB = tuple[float, float, float]


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class _Base:
    id: str = field(default_factory=_new_id)
    frame: Frame = field(default_factory=Frame)
    placement: Placement = field(default_factory=Placement)
    rotation_deg: float = 0.0      # positivo = horario (paridad Qt)
    opacity: float = 1.0
    locked: bool = False
    hidden: bool = False
    layer_id: str = "general"
    z: int = 0


@dataclass(frozen=True)
class TextElement(_Base):
    kind: str = field(default="text", init=False)
    text: str = ""
    font_family: str = "helv"      # MVP: helv|tiro|cour (catálogo foleador)
    font_size: float = 12.0
    bold: bool = False
    italic: bool = False
    color: RGB = (0.0, 0.0, 0.0)
    align: Literal["left", "center", "right", "justify"] = "left"
    line_height: float = 1.2
    box_fill: RGB | None = None
    box_fill_opacity: float = 1.0
    variables_enabled: bool = False

    def to_dict(self) -> dict:
        return _serialize(self)


@dataclass(frozen=True)
class ImageElement(_Base):
    kind: str = field(default="image", init=False)
    asset_id: str = ""
    crop: tuple[float, float, float, float] | None = None   # l,t,r,b en fracciones
    keep_aspect: bool = True
    flip_h: bool = False
    flip_v: bool = False

    def to_dict(self) -> dict:
        return _serialize(self)


_KINDS = {"text": TextElement, "image": ImageElement}


def _serialize(el) -> dict:
    d = asdict(el)
    d["schema"] = SCHEMA_VERSION
    d["frame"] = asdict(el.frame)
    d["placement"] = el.placement.to_dict()
    if d.get("color") is not None:
        d["color"] = list(d["color"])
    if d.get("box_fill") is not None:
        d["box_fill"] = list(d["box_fill"])
    if d.get("crop") is not None:
        d["crop"] = list(d["crop"])
    return d


def element_from_dict(d: dict):
    d = dict(d)
    d.pop("schema", None)
    kind = d.pop("kind", None)
    cls = _KINDS.get(kind)
    if cls is None:
        raise ValueError(f"kind de elemento desconocido: {kind!r}")
    d["frame"] = Frame(**d["frame"])
    d["placement"] = Placement.from_dict(d["placement"])
    if d.get("color") is not None:
        d["color"] = tuple(d["color"])
    if d.get("box_fill") is not None:
        d["box_fill"] = tuple(d["box_fill"])
    if d.get("crop") is not None:
        d["crop"] = tuple(d["crop"])
    return cls(**d)
