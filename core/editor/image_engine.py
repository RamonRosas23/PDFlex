"""Preparación de imágenes para inserción (spec §6-6, §21-5, §21-12).

Pipeline: bytes (PNG/JPG/WebP/...) → PIL → [crop fracciones] → [flips] →
[opacidad horneada en alfa] → PNG RGBA bytes listos para insert_image.
La rotación NO se hornea aquí: la maneja stamp_image_rotated (primitives).
"""
from __future__ import annotations
import io

from PIL import Image, UnidentifiedImageError

CropBox = tuple[float, float, float, float]   # l, t, r, b en fracciones [0,1]


def prepare_image_bytes(data: bytes, *, opacity: float = 1.0,
                        crop: CropBox | None = None,
                        flip_h: bool = False, flip_v: bool = False) -> bytes:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"No es una imagen válida: {exc}") from exc

    img = img.convert("RGBA")

    if crop is not None:
        w, h = img.size
        l, t, r, b = crop
        box = (round(w * l), round(h * t), round(w * r), round(h * b))
        if box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError(f"Recorte de imagen inválido: {crop}")
        img = img.crop(box)

    if flip_h:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if flip_v:
        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    if opacity < 1.0:
        alpha = img.getchannel("A").point(lambda a: round(a * max(0.0, opacity)))
        img.putalpha(alpha)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
