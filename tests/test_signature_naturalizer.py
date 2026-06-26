import hashlib

import numpy as np
from PIL import Image, ImageDraw

from core.signature_naturalizer import naturalize_signature
from core.variation import Variation, VariationConfig, VariationGenerator


def _sample_signature() -> Image.Image:
    img = Image.new("RGBA", (220, 82), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    ink = (24, 71, 164, 245)
    draw.line(
        [(9, 54), (31, 38), (51, 52), (68, 28), (89, 58), (116, 32)],
        fill=ink,
        width=5,
        joint="curve",
    )
    draw.arc((104, 20, 157, 61), 190, 25, fill=ink, width=4)
    draw.line(
        [(143, 47), (174, 35), (205, 43), (214, 39)],
        fill=ink,
        width=4,
        joint="curve",
    )
    draw.line([(26, 64), (133, 65), (198, 58)], fill=ink, width=2)
    return img


def _digest(img: Image.Image) -> str:
    return hashlib.sha256(img.convert("RGBA").tobytes()).hexdigest()


def _alpha_sum(img: Image.Image) -> float:
    return float(np.asarray(img.convert("RGBA"))[:, :, 3].sum())


def test_exact_variation_keeps_signature_pixels_identical() -> None:
    img = _sample_signature()
    variation = Variation(
        d_angle=0.0,
        scale_factor=1.0,
        d_x=0.0,
        d_y=0.0,
        opacity=1.0,
        pressure=0.0,
        stroke_mode="exacta",
        stroke_strength=0.0,
    )

    out = naturalize_signature(img, variation)

    assert _digest(out) == _digest(img)


def test_antefirma_naturalization_is_deterministic() -> None:
    img = _sample_signature()
    variation = VariationGenerator(
        VariationConfig(
            stroke_mode="antefirma",
            stroke_strength=0.82,
            seed=20260626,
        )
    ).variation_for("contrato.pdf\0firma.png", 3)

    out_a = naturalize_signature(img, variation)
    out_b = naturalize_signature(img, variation)

    assert _digest(out_a) == _digest(out_b)


def test_different_pages_get_different_but_usable_ink_masks() -> None:
    img = _sample_signature()
    generator = VariationGenerator(
        VariationConfig(
            stroke_mode="antefirma",
            stroke_strength=0.88,
            seed=12345,
        )
    )
    page_a = naturalize_signature(img, generator.variation_for("doc.pdf\0firma.png", 0))
    page_b = naturalize_signature(img, generator.variation_for("doc.pdf\0firma.png", 1))

    assert _digest(page_a) != _digest(page_b)

    base_alpha = _alpha_sum(img)
    for page in (page_a, page_b):
        alpha = _alpha_sum(page)
        assert alpha > base_alpha * 0.55
        assert alpha < base_alpha * 1.65


def test_pressure_off_disables_internal_stroke_variation() -> None:
    variation = VariationGenerator(
        VariationConfig(
            enable_pressure_jitter=False,
            stroke_mode="antefirma",
            stroke_strength=1.0,
        )
    ).variation_for("doc.pdf", 0)

    assert variation.stroke_mode == "exacta"
    assert variation.stroke_strength == 0.0
    assert not variation.has_stroke_variation
