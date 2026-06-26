"""Natural-looking per-page signature image variation.

The PDF engine already moves, rotates, scales and fades a signature per page.
This module changes the ink image itself: subtle elastic shape drift, pressure
maps, local stroke-width changes and dry-pen texture. All operations are
deterministic from the Variation seed so a batch can be reproduced exactly.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np
from PIL import Image

from .variation import Variation

try:  # pragma: no cover - fallback is exercised only when OpenCV is unavailable.
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


def naturalize_signature(img: Image.Image, variation: Variation) -> Image.Image:
    """Return a deterministic naturalized variant of a signature image."""
    if not variation.has_stroke_variation:
        return img.copy()

    strength = _clamp01(variation.stroke_strength)
    if strength <= 0.0:
        return img.copy()

    rgba = img.convert("RGBA")
    data = np.array(rgba, dtype=np.float32)
    alpha = data[:, :, 3]
    if float(np.max(alpha)) <= 0:
        return rgba

    rng = np.random.default_rng(int(variation.stroke_seed) & 0xFFFFFFFF)
    mode_boost = 1.0 if variation.stroke_mode == "antefirma" else 0.72

    data = _affine_stretch(data, variation)
    data = _elastic_warp(data, rng, strength * mode_boost)
    data = _vary_stroke_width(data, variation, strength)
    data = _vary_ink(data, rng, variation, strength * mode_boost)

    return Image.fromarray(np.clip(data, 0, 255).astype(np.uint8), "RGBA")


def _affine_stretch(data: np.ndarray, variation: Variation) -> np.ndarray:
    sx = float(variation.stretch_x)
    sy = float(variation.stretch_y)
    if cv2 is None or (abs(sx - 1.0) < 0.001 and abs(sy - 1.0) < 0.001):
        return data

    h, w = data.shape[:2]
    matrix = np.array(
        [[sx, 0.0, (1.0 - sx) * w / 2.0],
         [0.0, sy, (1.0 - sy) * h / 2.0]],
        dtype=np.float32,
    )
    return cv2.warpAffine(
        data,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )


def _elastic_warp(data: np.ndarray, rng: np.random.Generator, strength: float) -> np.ndarray:
    if cv2 is None or strength <= 0.0:
        return data

    h, w = data.shape[:2]
    if h < 8 or w < 8:
        return data

    gy = max(4, min(9, h // 18 + 3))
    gx = max(4, min(11, w // 28 + 3))
    dx = _normalized_noise(rng, h, w, gy, gx) * 2.0 - 1.0
    dy = _normalized_noise(rng, h, w, gy, gx) * 2.0 - 1.0

    amp = max(0.35, min(h, w) * 0.028 * strength)
    alpha_weight = _soft_alpha(data[:, :, 3])
    dx *= amp * (0.35 + 0.65 * alpha_weight)
    dy *= amp * 0.62 * (0.35 + 0.65 * alpha_weight)

    x_grid, y_grid = np.meshgrid(
        np.arange(w, dtype=np.float32),
        np.arange(h, dtype=np.float32),
    )
    return cv2.remap(
        data,
        x_grid + dx.astype(np.float32),
        y_grid + dy.astype(np.float32),
        interpolation=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )


def _vary_stroke_width(
    data: np.ndarray, variation: Variation, strength: float
) -> np.ndarray:
    if cv2 is None or abs(variation.stroke_width_delta) < 0.015:
        return data

    result = data.copy()
    alpha = np.clip(result[:, :, 3], 0, 255).astype(np.uint8)
    kernel = np.ones((3, 3), dtype=np.uint8)
    if variation.stroke_width_delta > 0:
        target = cv2.dilate(alpha, kernel, iterations=1).astype(np.float32)
        expanded = target > alpha
        if expanded.any():
            result[expanded, :3] = _median_ink_rgb(result, alpha)
    else:
        target = cv2.erode(alpha, kernel, iterations=1).astype(np.float32)

    mix = min(0.56, abs(float(variation.stroke_width_delta)) * (0.42 + 0.22 * strength))
    result[:, :, 3] = result[:, :, 3] * (1.0 - mix) + target * mix
    return result


def _vary_ink(
    data: np.ndarray,
    rng: np.random.Generator,
    variation: Variation,
    strength: float,
) -> np.ndarray:
    result = data.copy()
    h, w = result.shape[:2]
    alpha = np.clip(result[:, :, 3], 0.0, 255.0)
    alpha_norm = alpha / 255.0

    pressure_map = _normalized_noise(
        rng, h, w, max(3, h // 34 + 3), max(4, w // 42 + 4)
    )
    edge_map = _edge_band(alpha)
    pressure = 1.0 + (pressure_map - 0.5) * (0.34 * strength)
    pressure += float(variation.ink_flow) * 0.055

    edge_noise = _normalized_noise(
        rng, h, w, max(4, h // 18 + 4), max(5, w // 28 + 5)
    )
    edge_pressure = 1.0 + (edge_noise - 0.5) * (0.26 * strength) * edge_map
    alpha = alpha * pressure * edge_pressure

    dry_noise = _normalized_noise(
        rng, h, w, max(7, h // 10 + 4), max(9, w // 15 + 5)
    )
    dry_threshold = 0.84 - 0.13 * strength
    dry_map = np.clip((dry_noise - dry_threshold) / max(1e-6, 1.0 - dry_threshold), 0, 1)
    dry_focus = np.clip(edge_map + (1.0 - alpha_norm) * (alpha_norm > 0.08), 0, 1)
    dry_reduction = dry_map * dry_focus * (0.22 + 0.30 * float(variation.dryness))
    alpha *= 1.0 - dry_reduction

    result[:, :, 3] = np.clip(alpha, 0, 255)

    visible = result[:, :, 3] > 3
    if visible.any():
        rgb = result[:, :, :3]
        darken = np.clip((pressure - 1.0) * 0.10, -0.035, 0.055)
        rgb[visible] = rgb[visible] * (1.0 - darken[visible, None])
        channel_shift = rng.normal(0.0, 1.0, size=(3,)).astype(np.float32)
        channel_shift *= 1.8 * strength
        rgb[visible] += channel_shift
        result[:, :, :3] = np.clip(rgb, 0, 255)

    return result


def _normalized_noise(
    rng: np.random.Generator, h: int, w: int, gy: int, gx: int
) -> np.ndarray:
    small = rng.random((max(2, gy), max(2, gx)), dtype=np.float32)
    if cv2 is not None:
        noise = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
        sigma = max(0.6, min(h, w) / 70.0)
        noise = cv2.GaussianBlur(noise, (0, 0), sigmaX=sigma, sigmaY=sigma)
    else:
        pil = Image.fromarray((small * 255).astype(np.uint8), "L")
        pil = pil.resize((w, h), Image.Resampling.BICUBIC)
        noise = np.asarray(pil, dtype=np.float32) / 255.0

    low = float(np.min(noise))
    high = float(np.max(noise))
    if high - low < 1e-6:
        return np.full((h, w), 0.5, dtype=np.float32)
    return ((noise - low) / (high - low)).astype(np.float32)


def _edge_band(alpha: np.ndarray) -> np.ndarray:
    a = np.clip(alpha, 0, 255).astype(np.uint8)
    if cv2 is None:
        norm = a.astype(np.float32) / 255.0
        return np.clip(1.0 - np.abs(norm * 2.0 - 1.0), 0, 1)

    binary = np.where(a > 5, 255, 0).astype(np.uint8)
    kernel = np.ones((3, 3), dtype=np.uint8)
    band = cv2.dilate(binary, kernel, iterations=1) - cv2.erode(binary, kernel, iterations=1)
    band = band.astype(np.float32) / 255.0
    band = cv2.GaussianBlur(band, (0, 0), sigmaX=0.9, sigmaY=0.9)
    return np.clip(band, 0, 1)


def _soft_alpha(alpha: np.ndarray) -> np.ndarray:
    norm = np.clip(alpha.astype(np.float32) / 255.0, 0, 1)
    if cv2 is not None:
        norm = cv2.GaussianBlur(norm, (0, 0), sigmaX=1.2, sigmaY=1.2)
    return np.clip(norm, 0, 1)


def _median_ink_rgb(data: np.ndarray, alpha: np.ndarray) -> Tuple[float, float, float]:
    mask = alpha > 24
    if not mask.any():
        return (20.0, 60.0, 150.0)
    rgb = data[:, :, :3][mask]
    return tuple(float(v) for v in np.median(rgb, axis=0))


def _clamp01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))
