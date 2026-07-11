"""Realistic marker/highlighter engine for PDF files."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import math
import random
from tempfile import TemporaryDirectory
from typing import Callable, List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from core.pdf_backend import PdfRenderDocument, Rect, apply_page_overlays


RGBColor = Tuple[float, float, float]


@dataclass(frozen=True)
class HighlightProfile:
    id: str
    label: str
    color: RGBColor
    opacity: float
    roughness: float
    pressure: float
    streakiness: float
    bleed: float
    overshoot: float
    passes: int
    slant_deg: float


HIGHLIGHT_PROFILES: dict[str, HighlightProfile] = {
    "oficina_real": HighlightProfile(
        id="oficina_real",
        label="Oficina real",
        color=(1.0, 0.88, 0.12),
        opacity=0.48,
        roughness=0.46,
        pressure=0.58,
        streakiness=0.34,
        bleed=0.34,
        overshoot=0.42,
        passes=2,
        slant_deg=-0.4,
    ),
    "nuevo_uniforme": HighlightProfile(
        id="nuevo_uniforme",
        label="Marcador nuevo",
        color=(1.0, 0.92, 0.18),
        opacity=0.42,
        roughness=0.18,
        pressure=0.30,
        streakiness=0.12,
        bleed=0.22,
        overshoot=0.26,
        passes=1,
        slant_deg=0.0,
    ),
    "seco_textura": HighlightProfile(
        id="seco_textura",
        label="Marcador seco",
        color=(1.0, 0.84, 0.08),
        opacity=0.54,
        roughness=0.72,
        pressure=0.84,
        streakiness=0.76,
        bleed=0.18,
        overshoot=0.55,
        passes=2,
        slant_deg=-0.8,
    ),
    "suave_revision": HighlightProfile(
        id="suave_revision",
        label="Revision suave",
        color=(0.68, 0.96, 0.40),
        opacity=0.34,
        roughness=0.30,
        pressure=0.36,
        streakiness=0.20,
        bleed=0.24,
        overshoot=0.34,
        passes=1,
        slant_deg=0.3,
    ),
    "neon_intenso": HighlightProfile(
        id="neon_intenso",
        label="Neon intenso",
        color=(1.0, 0.48, 0.76),
        opacity=0.58,
        roughness=0.40,
        pressure=0.46,
        streakiness=0.26,
        bleed=0.38,
        overshoot=0.44,
        passes=2,
        slant_deg=-0.2,
    ),
}


COLOR_CHOICES: dict[str, tuple[str, RGBColor]] = {
    "amarillo": ("Amarillo", (1.0, 0.88, 0.12)),
    "limon": ("Verde limon", (0.68, 0.96, 0.40)),
    "rosa": ("Rosa", (1.0, 0.48, 0.76)),
    "naranja": ("Naranja", (1.0, 0.58, 0.18)),
    "azul": ("Azul", (0.38, 0.78, 1.0)),
    "violeta": ("Violeta", (0.74, 0.56, 1.0)),
}


@dataclass(frozen=True)
class HighlightOptions:
    profile_id: str = "oficina_real"
    color: RGBColor = (1.0, 0.88, 0.12)
    opacity: float = 0.48
    roughness: float = 0.46
    pressure: float = 0.58
    streakiness: float = 0.34
    bleed: float = 0.34
    overshoot: float = 0.42
    passes: int = 2
    slant_deg: float = -0.4
    seed: int = 1947
    overlay: bool = True

    @classmethod
    def from_profile(cls, profile_id: str, *, seed: int = 1947) -> "HighlightOptions":
        profile = HIGHLIGHT_PROFILES.get(profile_id, HIGHLIGHT_PROFILES["oficina_real"])
        return cls(
            profile_id=profile.id,
            color=profile.color,
            opacity=profile.opacity,
            roughness=profile.roughness,
            pressure=profile.pressure,
            streakiness=profile.streakiness,
            bleed=profile.bleed,
            overshoot=profile.overshoot,
            passes=profile.passes,
            slant_deg=profile.slant_deg,
            seed=seed,
        )

    def clamped(self) -> "HighlightOptions":
        return replace(
            self,
            color=tuple(_clamp(float(c), 0.0, 1.0) for c in self.color),  # type: ignore[arg-type]
            opacity=_clamp(float(self.opacity), 0.05, 0.95),
            roughness=_clamp(float(self.roughness), 0.0, 1.0),
            pressure=_clamp(float(self.pressure), 0.0, 1.0),
            streakiness=_clamp(float(self.streakiness), 0.0, 1.0),
            bleed=_clamp(float(self.bleed), 0.0, 1.0),
            overshoot=_clamp(float(self.overshoot), 0.0, 1.0),
            passes=max(1, min(4, int(self.passes))),
            slant_deg=_clamp(float(self.slant_deg), -8.0, 8.0),
            seed=max(0, min(999_999, int(self.seed))),
        )


@dataclass(frozen=True)
class HighlightMark:
    page_index: int
    x0_norm: float
    y0_norm: float
    x1_norm: float
    y1_norm: float

    def normalized(self) -> "HighlightMark":
        return HighlightMark(
            page_index=max(0, int(self.page_index)),
            x0_norm=_clamp(min(self.x0_norm, self.x1_norm), 0.0, 1.0),
            y0_norm=_clamp(min(self.y0_norm, self.y1_norm), 0.0, 1.0),
            x1_norm=_clamp(max(self.x0_norm, self.x1_norm), 0.0, 1.0),
            y1_norm=_clamp(max(self.y0_norm, self.y1_norm), 0.0, 1.0),
        )

    def to_display_rect(self, page_width: float, page_height: float) -> Rect:
        mark = self.normalized()
        pw = max(1.0, page_width)
        ph = max(1.0, page_height)
        return Rect(
            mark.x0_norm * pw,
            mark.y0_norm * ph,
            mark.x1_norm * pw,
            mark.y1_norm * ph,
        )


@dataclass
class HighlightJob:
    pdf_path: str
    output_path: str
    marks: List[HighlightMark] = field(default_factory=list)
    options: HighlightOptions = field(default_factory=HighlightOptions)


@dataclass
class HighlightResult:
    job: HighlightJob
    output_path: str = ""
    success: bool = False
    error: str = ""
    total_pages: int = 0
    mark_count: int = 0

    @property
    def meta_text(self) -> str:
        return f"{self.mark_count} trazos realistas · marcatexto aplanado"


class HighlightEngine:
    """Applies flattened highlighter textures without altering PDF text."""

    def run_batch(
        self,
        jobs: List[HighlightJob],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[HighlightResult]:
        total = len(jobs)
        results: List[HighlightResult] = []
        for index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(index, total, f"Subrayando {Path(job.pdf_path).name}...")
            result = self.run_job(job, should_cancel=should_cancel)
            results.append(result)
            if progress:
                progress(index + 1, total, f"{index + 1}/{total} PDFs procesados")
        return results

    def run_job(
        self,
        job: HighlightJob,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> HighlightResult:
        source = Path(job.pdf_path)
        output = Path(job.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        if not source.exists():
            return HighlightResult(job=job, success=False, error="El PDF de origen no existe.")
        if not job.marks:
            return HighlightResult(job=job, success=False, error="Dibuja al menos un trazo.")

        try:
            options = job.options.clamped()
            with PdfRenderDocument(source) as document:
                grouped = _group_marks(job.marks, document.page_count)
                if not grouped:
                    raise RuntimeError("No hay trazos validos para este PDF.")
                with TemporaryDirectory(prefix="pdflex-highlight-") as temp_dir:
                    overlay_path = Path(temp_dir) / "overlay.pdf"
                    canvas = Canvas(str(overlay_path), pagesize=(1, 1), pageCompression=1)
                    count = 0
                    mapping: dict[int, int] = {}
                    for overlay_index, (page_index, marks) in enumerate(sorted(grouped.items())):
                        if should_cancel and should_cancel():
                            raise _CancelledError()
                        info = document.page_info(page_index)
                        canvas.setPageSize((info.width_pt, info.height_pt))
                        page_rect = Rect(0, 0, info.width_pt, info.height_pt)
                        for mark_index, mark in enumerate(marks):
                            display_rect = mark.to_display_rect(info.width_pt, info.height_pt)
                            if display_rect.width < 1.0 or display_rect.height < 1.0:
                                continue
                            display_rect = expanded_highlight_rect(
                                display_rect, page_rect, options
                            )
                            if display_rect.width < 1.0 or display_rect.height < 1.0:
                                continue
                            stream = _texture_png_for_rect(
                                display_rect, options, page_index, mark_index, mark
                            )
                            canvas.drawImage(
                                ImageReader(BytesIO(stream)),
                                display_rect.x0,
                                info.height_pt - display_rect.y1,
                                width=display_rect.width,
                                height=display_rect.height,
                                preserveAspectRatio=False,
                                mask="auto",
                            )
                            count += 1
                        canvas.showPage()
                        mapping[page_index] = overlay_index
                    canvas.save()
                    if count <= 0:
                        raise RuntimeError("Los trazos eran demasiado pequenos o invalidos.")
                    report = apply_page_overlays(
                        source, overlay_path, mapping, output, over=options.overlay
                    )
            return HighlightResult(
                job=job,
                output_path=str(output),
                success=True,
                total_pages=report.page_count,
                mark_count=count,
            )
        except _CancelledError:
            return HighlightResult(job=job, success=False, error="Operacion cancelada.")
        except Exception as exc:
            return HighlightResult(job=job, success=False, error=str(exc))


def render_highlight_texture(
    width_px: int,
    height_px: int,
    options: HighlightOptions,
    *,
    seed: int | str,
) -> Image.Image:
    """Build a transparent RGBA marker stroke with non-uniform physical texture."""
    options = options.clamped()
    width = max(4, int(width_px))
    height = max(4, int(height_px))
    rng = random.Random(_seed_int(seed, options.seed))
    color = tuple(int(round(_clamp(c, 0.0, 1.0) * 255)) for c in options.color)
    base = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    for pass_index in range(options.passes):
        pass_seed = rng.randint(0, 2_147_483_647)
        pass_rng = random.Random(pass_seed)
        mask = _stroke_mask(width, height, options, pass_rng, pass_index)
        mask = _apply_pressure(mask, options, pass_rng)
        mask = _apply_streaks(mask, options, pass_rng)
        mask = _apply_grain(mask, options, pass_rng)

        if options.bleed > 0.001:
            halo = mask.filter(ImageFilter.GaussianBlur(0.5 + options.bleed * 2.2))
            halo_arr = np.asarray(halo, dtype=np.float32) * (0.16 + options.bleed * 0.18)
            halo_img = _rgba_from_alpha(color, halo_arr)
            base = Image.alpha_composite(base, halo_img)

        layer = _rgba_from_alpha(color, np.asarray(mask, dtype=np.float32))
        base = Image.alpha_composite(base, layer)

    if abs(options.slant_deg) > 0.05:
        base = base.rotate(
            -options.slant_deg,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=(0, 0, 0, 0),
        )
    return base


def expanded_highlight_rect(
    rect: Rect,
    page_rect: Rect,
    options: HighlightOptions,
) -> Rect:
    options = options.clamped()
    x_pad = min(28.0, rect.height * (0.25 + options.overshoot * 1.25))
    y_pad = min(12.0, rect.height * (options.bleed * 0.34 + options.roughness * 0.08))
    expanded = Rect(rect.x0 - x_pad, rect.y0 - y_pad, rect.x1 + x_pad, rect.y1 + y_pad)
    return Rect(
        max(page_rect.x0, expanded.x0),
        max(page_rect.y0, expanded.y0),
        min(page_rect.x1, expanded.x1),
        min(page_rect.y1, expanded.y1),
    )


def _texture_png_for_rect(
    rect: Rect,
    options: HighlightOptions,
    page_index: int,
    mark_index: int,
    mark: HighlightMark,
) -> bytes:
    scale = _texture_scale(rect)
    width_px = max(8, int(math.ceil(rect.width * scale)))
    height_px = max(6, int(math.ceil(rect.height * scale)))
    seed = _mark_seed(options, page_index, mark_index, mark)
    image = render_highlight_texture(width_px, height_px, options, seed=seed)
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _stroke_mask(
    width: int,
    height: int,
    options: HighlightOptions,
    rng: random.Random,
    pass_index: int,
) -> Image.Image:
    alpha = int(round(255 * options.opacity / math.sqrt(max(1, options.passes))))
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)

    x_step = max(3, int(round(width / max(18, min(90, width // 5 or 18)))))
    samples = list(range(0, width + x_step, x_step))
    if samples[-1] != width - 1:
        samples.append(width - 1)

    edge_margin = max(1.0, height * (0.04 + options.bleed * 0.05))
    rough = max(0.2, options.roughness)
    jitter = height * (0.015 + rough * 0.095)
    wave_amp = height * (0.008 + rough * 0.045)
    phase = rng.uniform(0.0, math.tau)
    freq = rng.uniform(1.0, 2.6)
    pass_shift = (pass_index - (options.passes - 1) / 2.0) * height * 0.04

    top: list[tuple[float, float]] = []
    bottom: list[tuple[float, float]] = []
    for x in samples:
        nx = x / max(1.0, width)
        wave = math.sin(nx * math.tau * freq + phase) * wave_amp
        local = rng.uniform(-jitter, jitter)
        top_y = edge_margin + wave + local + pass_shift
        bottom_y = height - edge_margin + wave + rng.uniform(-jitter, jitter) + pass_shift
        if bottom_y - top_y < max(2.0, height * 0.36):
            center = (top_y + bottom_y) / 2.0
            half = max(1.0, height * 0.22)
            top_y = center - half
            bottom_y = center + half
        top.append((x, _clamp(top_y, 0.0, height - 1.0)))
        bottom.append((x, _clamp(bottom_y, 0.0, height - 1.0)))

    draw.polygon(top + list(reversed(bottom)), fill=alpha)

    edge_blur = 0.25 + options.bleed * 1.10 + (1.0 - options.roughness) * 0.28
    if edge_blur > 0.05:
        mask = mask.filter(ImageFilter.GaussianBlur(edge_blur))
    return mask


def _apply_pressure(mask: Image.Image, options: HighlightOptions, rng: random.Random) -> Image.Image:
    alpha = np.asarray(mask, dtype=np.float32)
    height, width = alpha.shape
    anchors = max(4, min(18, width // 42 + 4))
    values = np.array(
        [rng.uniform(1.0 - options.pressure * 0.32, 1.0 + options.pressure * 0.24) for _ in range(anchors)],
        dtype=np.float32,
    )
    xp = np.linspace(0, width - 1, anchors)
    modulation = np.interp(np.arange(width), xp, values).astype(np.float32)
    alpha *= modulation[None, :]
    if options.pressure > 0.2:
        vertical = np.linspace(0.92, 1.05, height, dtype=np.float32)
        if rng.random() < 0.5:
            vertical = vertical[::-1]
        alpha *= vertical[:, None]
    return Image.fromarray(np.clip(alpha, 0, 255).astype(np.uint8), "L")


def _apply_streaks(mask: Image.Image, options: HighlightOptions, rng: random.Random) -> Image.Image:
    alpha = np.asarray(mask, dtype=np.float32).copy()
    height, width = alpha.shape
    streaks = int(round((2 + height / 8.0) * (0.25 + options.streakiness * 1.35)))
    for _ in range(streaks):
        y = rng.randrange(0, max(1, height))
        thickness = rng.randint(1, max(1, int(1 + options.streakiness * 4)))
        factor = rng.uniform(0.35, 0.86 - options.streakiness * 0.18)
        wobble = rng.uniform(-height * 0.05, height * 0.05)
        for x in range(width):
            yy = int(round(y + math.sin(x / max(14.0, width * 0.12) + wobble) * options.roughness * 2.2))
            y0 = max(0, yy)
            y1 = min(height, yy + thickness)
            if y1 > y0:
                alpha[y0:y1, x] *= factor

    dry_spots = int((width * height / 9000.0) * options.streakiness)
    for _ in range(dry_spots):
        cx = rng.randrange(0, width)
        cy = rng.randrange(0, height)
        rx = rng.randint(2, max(3, int(width * 0.018)))
        ry = rng.randint(1, max(2, int(height * 0.12)))
        x0, x1 = max(0, cx - rx), min(width, cx + rx)
        y0, y1 = max(0, cy - ry), min(height, cy + ry)
        alpha[y0:y1, x0:x1] *= rng.uniform(0.38, 0.76)
    return Image.fromarray(np.clip(alpha, 0, 255).astype(np.uint8), "L")


def _apply_grain(mask: Image.Image, options: HighlightOptions, rng: random.Random) -> Image.Image:
    alpha = np.asarray(mask, dtype=np.float32)
    if alpha.size == 0:
        return mask
    noise_strength = 2.0 + options.roughness * 12.0 + options.streakiness * 6.0
    np_rng = np.random.default_rng(rng.randint(0, 2_147_483_647))
    noise = np_rng.normal(0.0, noise_strength, size=alpha.shape).astype(np.float32)
    alpha += noise
    return Image.fromarray(np.clip(alpha, 0, 255).astype(np.uint8), "L")


def _rgba_from_alpha(color: tuple[int, int, int], alpha: np.ndarray) -> Image.Image:
    clipped = np.clip(alpha, 0, 255).astype(np.uint8)
    rgba = np.zeros((clipped.shape[0], clipped.shape[1], 4), dtype=np.uint8)
    rgba[..., 0] = color[0]
    rgba[..., 1] = color[1]
    rgba[..., 2] = color[2]
    rgba[..., 3] = clipped
    return Image.fromarray(rgba, "RGBA")


def _texture_scale(rect: Rect) -> float:
    longest = max(1.0, rect.width, rect.height)
    scale = 2.35
    if longest * scale > 3200:
        scale = max(0.7, 3200.0 / longest)
    return scale


def _group_marks(marks: List[HighlightMark], page_count: int) -> dict[int, list[HighlightMark]]:
    grouped: dict[int, list[HighlightMark]] = {}
    for mark in marks:
        normalized = mark.normalized()
        if normalized.page_index < 0 or normalized.page_index >= page_count:
            continue
        if normalized.x1_norm - normalized.x0_norm <= 0.001:
            continue
        if normalized.y1_norm - normalized.y0_norm <= 0.001:
            continue
        grouped.setdefault(normalized.page_index, []).append(normalized)
    return grouped


def _mark_seed(
    options: HighlightOptions,
    page_index: int,
    mark_index: int,
    mark: HighlightMark,
) -> int:
    payload = (
        f"{options.seed}|{page_index}|{mark_index}|"
        f"{mark.x0_norm:.6f}|{mark.y0_norm:.6f}|{mark.x1_norm:.6f}|{mark.y1_norm:.6f}|"
        f"{options.opacity:.4f}|{options.roughness:.4f}|{options.streakiness:.4f}"
    )
    return _seed_int(payload, options.seed)


def _seed_int(seed: int | str, salt: int = 0) -> int:
    digest = sha256(f"{salt}|{seed}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class _CancelledError(Exception):
    pass
