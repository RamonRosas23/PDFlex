"""Normalización de imágenes: WebP/JPG/PNG → PNG RGBA con ops horneadas."""
import io

import pytest
from PIL import Image

from core.editor.image_engine import prepare_image_bytes


def _png(mode="RGB", size=(40, 40), color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="PNG")
    return buf.getvalue()


def _webp_with_alpha() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (40, 40), (0, 255, 0, 128)).save(buf, format="WEBP")
    return buf.getvalue()


def test_webp_alpha_normalizes_to_png_rgba():
    out = prepare_image_bytes(_webp_with_alpha())
    img = Image.open(io.BytesIO(out))
    assert img.format == "PNG" and img.mode == "RGBA"
    assert img.getpixel((5, 5))[3] == 128          # alfa preservado


def test_opacity_bakes_into_alpha():
    out = prepare_image_bytes(_png(), opacity=0.5)
    img = Image.open(io.BytesIO(out))
    assert img.mode == "RGBA"
    assert img.getpixel((5, 5))[3] == pytest.approx(127, abs=2)


def test_crop_fractions():
    out = prepare_image_bytes(_png(size=(100, 200)), crop=(0.25, 0.10, 0.75, 0.90))
    img = Image.open(io.BytesIO(out))
    assert img.size == (50, 160)


def test_flips():
    src = Image.new("RGB", (2, 1))
    src.putpixel((0, 0), (255, 0, 0))
    src.putpixel((1, 0), (0, 0, 255))
    buf = io.BytesIO()
    src.save(buf, format="PNG")
    out = prepare_image_bytes(buf.getvalue(), flip_h=True)
    img = Image.open(io.BytesIO(out))
    assert img.getpixel((0, 0))[:3] == (0, 0, 255)  # rojo y azul intercambiados


def test_invalid_crop_raises():
    with pytest.raises(ValueError, match="[Rr]ecorte"):
        prepare_image_bytes(_png(), crop=(0.9, 0.1, 0.1, 0.9))


def test_invalid_bytes_raise_value_error():
    with pytest.raises(ValueError, match="imagen"):
        prepare_image_bytes(b"not an image")
