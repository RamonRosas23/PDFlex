"""PDF scan simulation engine.

Transforms clean PDF pages into realistic raster scans while keeping the
physical page size stable. The visual simulation is deterministic from a seed,
source path and page index, which makes batch output reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import io
import math
from pathlib import Path
from typing import Callable, List, Literal, Optional

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from .output_naming import output_stem_for_source
from .pdf_to_images_engine import parse_page_selection

try:  # pragma: no cover - fallback is used only when OpenCV is unavailable.
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


ScanTone = Literal["color", "gray", "bw"]


@dataclass(frozen=True)
class ScanPreset:
    id: str
    label: str
    description: str
    config: "ScanSimulationConfig"


@dataclass(frozen=True)
class ScanSimulationConfig:
    """Controls the visual scan effect.

    Most values are normalized and intentionally conservative. The preset
    values below are tuned for text documents at 180-260 DPI.
    """

    preset_id: str = "office"
    dpi: int = 220
    tone: ScanTone = "gray"
    intensity: float = 0.68
    margin_pct: float = 0.035
    max_rotation_deg: float = 0.9
    max_perspective_pct: float = 0.014
    background_noise: float = 0.44
    paper_noise: float = 0.58
    blur_radius: float = 0.26
    jpeg_quality: int = 82
    show_page_border: bool = True
    add_shadow: bool = True
    add_scan_bands: bool = True
    add_dust: bool = True
    seed: int = 20260626
    page_range: str = ""


@dataclass(frozen=True)
class _DustSpec:
    x: float
    y: float
    radius: float
    delta: float


@dataclass(frozen=True)
class _StreakSpec:
    x: float
    width: float
    delta: float


@dataclass(frozen=True)
class _ScanSessionProfile:
    """Scanner signature shared by every page in one run."""

    source_id: str
    sheet_rect: tuple[float, float, float, float]
    base_angle: float
    base_dx_frac: float
    base_dy_frac: float
    base_scale: float
    corner_offsets: tuple[tuple[float, float], ...]
    exposure: float
    contrast: float
    paper_rgb: tuple[float, float, float]
    bed_rgb: tuple[float, float, float]
    band_seed: int
    dust: tuple[_DustSpec, ...]
    streaks: tuple[_StreakSpec, ...]


@dataclass(frozen=True)
class ScanSimulationJob:
    pdf_path: str
    output_path: str
    base_name: str = ""
    tool_suffix: str = "escaneado"
    add_tool_suffix: bool = True


@dataclass
class ScanSimulationResult:
    job: ScanSimulationJob
    output_path: str = ""
    success: bool = False
    error: str = ""
    warning: str = ""
    preset_label: str = ""
    tone: str = ""
    dpi: int = 0
    page_count: int = 0
    input_bytes: int = 0
    output_bytes: int = 0

    @property
    def meta_text(self) -> str:
        parts = []
        if self.preset_label:
            parts.append(self.preset_label)
        if self.dpi:
            parts.append(f"{self.dpi} DPI")
        if self.tone:
            parts.append(_tone_label(self.tone))
        if self.input_bytes and self.output_bytes:
            parts.append(f"{_format_bytes(self.input_bytes)} -> {_format_bytes(self.output_bytes)}")
        if self.warning:
            parts.append(self.warning)
        return " | ".join(parts)


def _cfg(**kwargs) -> ScanSimulationConfig:
    return ScanSimulationConfig(**kwargs)


SCAN_PRESETS: tuple[ScanPreset, ...] = (
    ScanPreset(
        "clean",
        "Escaner limpio",
        "Borde leve, textura fina y legibilidad alta.",
        _cfg(
            preset_id="clean",
            dpi=240,
            tone="gray",
            intensity=0.24,
            margin_pct=0.014,
            max_rotation_deg=0.16,
            max_perspective_pct=0.0015,
            background_noise=0.18,
            paper_noise=0.18,
            blur_radius=0.08,
            jpeg_quality=90,
        ),
    ),
    ScanPreset(
        "office",
        "Oficina realista",
        "Copiadora de oficina, margen visible y grano moderado.",
        _cfg(
            preset_id="office",
            dpi=220,
            tone="gray",
            intensity=0.46,
            margin_pct=0.020,
            max_rotation_deg=0.36,
            max_perspective_pct=0.0030,
            background_noise=0.30,
            paper_noise=0.36,
            blur_radius=0.16,
            jpeg_quality=86,
        ),
    ),
    ScanPreset(
        "copy",
        "Copia gris",
        "Blanco y negro suave, bandas sutiles y contraste de copiadora.",
        _cfg(
            preset_id="copy",
            dpi=200,
            tone="gray",
            intensity=0.62,
            margin_pct=0.022,
            max_rotation_deg=0.48,
            max_perspective_pct=0.0025,
            background_noise=0.44,
            paper_noise=0.50,
            blur_radius=0.22,
            jpeg_quality=80,
        ),
    ),
    ScanPreset(
        "archive",
        "Archivo envejecido",
        "Papel tibio, desgaste fino y escaneo menos uniforme.",
        _cfg(
            preset_id="archive",
            dpi=220,
            tone="color",
            intensity=0.70,
            margin_pct=0.026,
            max_rotation_deg=0.68,
            max_perspective_pct=0.0040,
            background_noise=0.48,
            paper_noise=0.66,
            blur_radius=0.26,
            jpeg_quality=80,
        ),
    ),
    ScanPreset(
        "mobile",
        "Hoja movida",
        "Captura irregular con mas perspectiva, sombra y margen amplio.",
        _cfg(
            preset_id="mobile",
            dpi=220,
            tone="color",
            intensity=0.88,
            margin_pct=0.045,
            max_rotation_deg=1.50,
            max_perspective_pct=0.016,
            background_noise=0.42,
            paper_noise=0.62,
            blur_radius=0.36,
            jpeg_quality=80,
        ),
    ),
)

_PRESETS_BY_ID = {preset.id: preset for preset in SCAN_PRESETS}


def preset_ids() -> list[str]:
    return [preset.id for preset in SCAN_PRESETS]


def preset_for(preset_id: str) -> ScanPreset:
    return _PRESETS_BY_ID.get(preset_id, _PRESETS_BY_ID["office"])


def config_for_preset(preset_id: str) -> ScanSimulationConfig:
    return preset_for(preset_id).config


class PdfScanSimulatorEngine:
    """Generates scan-looking PDF copies."""

    def run_batch(
        self,
        jobs: List[ScanSimulationJob],
        config: ScanSimulationConfig,
        progress: Optional[Callable[[int, int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> List[ScanSimulationResult]:
        cfg = _normalized_config(config)
        total_pages = self._count_selected_pages(jobs, cfg)
        done_pages = 0
        results: List[ScanSimulationResult] = []
        batch_source_id = _batch_source_id(jobs, cfg)

        for job_index, job in enumerate(jobs):
            if _is_cancelled(should_cancel):
                break

            def _progress(local_done: int, local_total: int, message: str) -> None:
                if progress:
                    progress(
                        min(total_pages, done_pages + local_done),
                        total_pages,
                        message,
                    )

            result = self.run_job(
                job,
                cfg,
                progress=_progress,
                should_cancel=should_cancel,
                session_source_id=batch_source_id,
            )
            results.append(result)
            done_pages += max(0, result.page_count)
            if progress and not _is_cancelled(should_cancel):
                progress(
                    min(total_pages, done_pages),
                    total_pages,
                    f"{job_index + 1}/{len(jobs)} PDFs procesados",
                )

        if progress and not _is_cancelled(should_cancel):
            progress(total_pages, total_pages, "Simulacion completada")
        return results

    def run_job(
        self,
        job: ScanSimulationJob,
        config: ScanSimulationConfig,
        progress: Optional[Callable[[int, int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        *,
        session_source_id: str | None = None,
    ) -> ScanSimulationResult:
        cfg = _normalized_config(config)
        source = Path(job.pdf_path)
        output = Path(job.output_path)
        preset = preset_for(cfg.preset_id)
        input_bytes = _file_size(source)

        if not source.exists():
            return ScanSimulationResult(
                job=job,
                success=False,
                error="El PDF de origen no existe.",
                preset_label=preset.label,
                dpi=cfg.dpi,
                tone=cfg.tone,
                input_bytes=input_bytes,
            )
        if _same_path(source, output):
            return ScanSimulationResult(
                job=job,
                success=False,
                error="La salida no puede ser el mismo archivo de origen.",
                preset_label=preset.label,
                dpi=cfg.dpi,
                tone=cfg.tone,
                input_bytes=input_bytes,
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        src_doc: fitz.Document | None = None
        out_doc = fitz.open()
        processed_pages = 0

        try:
            src_doc = fitz.open(str(source))
            page_indexes = parse_page_selection(cfg.page_range, src_doc.page_count)
            if not page_indexes:
                raise RuntimeError("El rango no contiene paginas validas.")

            total = len(page_indexes)
            page_source_id = str(source.resolve())
            session = _build_scan_session(cfg, session_source_id or page_source_id)
            for local_index, page_index in enumerate(page_indexes):
                if _is_cancelled(should_cancel):
                    raise _CancelledError

                page = src_doc[page_index]
                if progress:
                    progress(
                        local_index,
                        total,
                        f"{source.name}: simulando pagina {page_index + 1}/{src_doc.page_count}",
                    )

                rendered = _render_page(page, cfg.dpi)
                simulated = simulate_scan_image(
                    rendered,
                    cfg,
                    source_id=page_source_id,
                    page_index=page_index,
                    session=session,
                )

                out_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
                out_page.insert_image(out_page.rect, stream=_encode_jpeg(simulated, cfg))
                processed_pages += 1

                if progress:
                    progress(
                        local_index + 1,
                        total,
                        f"{source.name}: pagina {page_index + 1} lista",
                    )

            if processed_pages <= 0:
                raise RuntimeError("No se genero ninguna pagina.")

            _copy_basic_metadata(src_doc, out_doc, source)
            out_doc.save(
                str(output),
                garbage=4,
                deflate=True,
                deflate_images=False,
                use_objstms=1,
            )
        except _CancelledError:
            _remove_file(output)
            return ScanSimulationResult(
                job=job,
                success=False,
                error="Operacion cancelada.",
                preset_label=preset.label,
                dpi=cfg.dpi,
                tone=cfg.tone,
                page_count=processed_pages,
                input_bytes=input_bytes,
            )
        except Exception as exc:
            _remove_file(output)
            return ScanSimulationResult(
                job=job,
                success=False,
                error=str(exc),
                preset_label=preset.label,
                dpi=cfg.dpi,
                tone=cfg.tone,
                page_count=processed_pages,
                input_bytes=input_bytes,
            )
        finally:
            out_doc.close()
            if src_doc is not None:
                src_doc.close()

        try:
            _validate_output(output, processed_pages)
        except Exception as exc:
            _remove_file(output)
            return ScanSimulationResult(
                job=job,
                success=False,
                error=f"No se pudo validar el PDF generado: {exc}",
                preset_label=preset.label,
                dpi=cfg.dpi,
                tone=cfg.tone,
                page_count=processed_pages,
                input_bytes=input_bytes,
            )

        return ScanSimulationResult(
            job=job,
            output_path=str(output),
            success=True,
            preset_label=preset.label,
            dpi=cfg.dpi,
            tone=cfg.tone,
            page_count=processed_pages,
            input_bytes=input_bytes,
            output_bytes=_file_size(output),
        )

    @staticmethod
    def _count_selected_pages(
        jobs: List[ScanSimulationJob],
        cfg: ScanSimulationConfig,
    ) -> int:
        total = 0
        for job in jobs:
            try:
                with fitz.open(job.pdf_path) as doc:
                    total += len(parse_page_selection(cfg.page_range, doc.page_count))
            except Exception:
                total += 1
        return max(1, total)


def build_output_path(
    output_dir: Path,
    source_pdf: str | Path,
    *,
    tool_suffix: str = "escaneado",
    add_tool_suffix: bool = True,
    reserved: set[str] | None = None,
) -> Path:
    from .output_paths import unique_output_path

    base = output_stem_for_source(
        source_pdf,
        tool_suffix=tool_suffix,
        add_tool_suffix=add_tool_suffix,
        fallback="documento",
    )
    return unique_output_path(
        output_dir,
        f"{base}.pdf",
        reserved=reserved,
        fallback="documento",
    )


def _batch_source_id(jobs: List[ScanSimulationJob], cfg: ScanSimulationConfig) -> str:
    payload = "\n".join(str(Path(job.pdf_path).resolve()) for job in jobs)
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"batch:{cfg.seed}:{digest}"


def _build_scan_session(cfg: ScanSimulationConfig, source_id: str) -> _ScanSessionProfile:
    rng = np.random.default_rng(_session_seed(cfg.seed, source_id))
    base_angle = float(rng.normal(0.0, max(0.01, cfg.max_rotation_deg * 0.34)))
    base_angle = _clamp(base_angle, -cfg.max_rotation_deg, cfg.max_rotation_deg)
    margin_x = cfg.margin_pct * (0.48 + 0.60 * cfg.intensity)
    margin_y = cfg.margin_pct * (0.38 + 0.54 * cfg.intensity)
    x_bias = float(rng.normal(0.0, margin_x * 0.20))
    y_bias = float(rng.normal(0.0, margin_y * 0.20))
    left = margin_x * float(rng.uniform(0.86, 1.16)) + x_bias
    right = margin_x * float(rng.uniform(0.86, 1.16)) - x_bias
    top = margin_y * float(rng.uniform(0.86, 1.16)) + y_bias
    bottom = margin_y * float(rng.uniform(0.86, 1.16)) - y_bias
    left = _clamp(left, 0.0015, 0.11)
    right = _clamp(right, 0.0015, 0.11)
    top = _clamp(top, 0.0015, 0.11)
    bottom = _clamp(bottom, 0.0015, 0.11)
    sheet_rect = (left, top, 1.0 - right, 1.0 - bottom)

    base_dx_frac = ((sheet_rect[0] + sheet_rect[2]) * 0.5) - 0.5
    base_dy_frac = ((sheet_rect[1] + sheet_rect[3]) * 0.5) - 0.5
    base_scale = min(sheet_rect[2] - sheet_rect[0], sheet_rect[3] - sheet_rect[1])

    corner_offsets = []
    for _ in range(4):
        corner_offsets.append(
            (
                float(rng.normal(0.0, 0.32)),
                float(rng.normal(0.0, 0.32)),
            )
        )

    if cfg.tone == "color":
        paper_base = np.array([248.0, 246.0, 238.0])
        bed_base = np.array([242.0, 243.0, 240.0])
        warm = rng.normal(0.0, 2.2, size=3)
        warm[2] *= 0.35
    else:
        paper_base = np.array([246.0, 246.0, 244.0])
        bed_base = np.array([241.0, 241.0, 239.0])
        warm = rng.normal(0.0, 1.4, size=3)

    exposure = 1.0 - 0.018 * cfg.intensity + float(rng.normal(0.0, 0.006))
    contrast = 1.0 + 0.055 * cfg.intensity + float(rng.normal(0.0, 0.008))

    dust_count = int(3 + 12 * cfg.intensity)
    dust: list[_DustSpec] = []
    for _ in range(dust_count):
        dust.append(
            _DustSpec(
                x=float(rng.uniform(0.025, 0.975)),
                y=float(rng.uniform(0.025, 0.975)),
                radius=float(rng.uniform(0.00045, 0.00165)),
                delta=float(rng.uniform(-12.0, 8.0)),
            )
        )

    streak_count = int(1 + 3 * cfg.background_noise * cfg.intensity)
    streaks: list[_StreakSpec] = []
    for _ in range(streak_count):
        streaks.append(
            _StreakSpec(
                x=float(rng.uniform(0.06, 0.94)),
                width=float(rng.uniform(0.0008, 0.0028)),
                delta=float(rng.uniform(-4.5, 2.5)),
            )
        )

    return _ScanSessionProfile(
        source_id=source_id,
        sheet_rect=sheet_rect,
        base_angle=base_angle,
        base_dx_frac=base_dx_frac,
        base_dy_frac=base_dy_frac,
        base_scale=base_scale,
        corner_offsets=tuple(corner_offsets),
        exposure=exposure,
        contrast=contrast,
        paper_rgb=tuple(float(v) for v in np.clip(paper_base + warm, 232, 255)),
        bed_rgb=tuple(float(v) for v in np.clip(bed_base + warm * 0.55, 230, 250)),
        band_seed=int(rng.integers(0, 2**31 - 1)),
        dust=tuple(dust),
        streaks=tuple(streaks),
    )


def _page_sheet_rect(
    session: _ScanSessionProfile,
    cfg: ScanSimulationConfig,
    rng: np.random.Generator,
) -> tuple[float, float, float, float]:
    left, top, right, bottom = session.sheet_rect
    width = right - left
    height = bottom - top
    center_x = (left + right) * 0.5
    center_y = (top + bottom) * 0.5
    # A feeder has a stable placement with tiny page-to-page slip.
    slip = cfg.margin_pct * (0.018 + 0.026 * cfg.intensity)
    center_x += float(rng.normal(0.0, slip))
    center_y += float(rng.normal(0.0, slip))
    scale = 1.0 + float(rng.normal(0.0, 0.0007 + 0.0010 * cfg.intensity))
    width *= _clamp(scale, 0.996, 1.004)
    height *= _clamp(scale, 0.996, 1.004)
    left = center_x - width * 0.5
    right = center_x + width * 0.5
    top = center_y - height * 0.5
    bottom = center_y + height * 0.5
    dx = 0.0
    dy = 0.0
    if left < 0.001:
        dx = 0.001 - left
    elif right > 0.999:
        dx = 0.999 - right
    if top < 0.001:
        dy = 0.001 - top
    elif bottom > 0.999:
        dy = 0.999 - bottom
    return (left + dx, top + dy, right + dx, bottom + dy)


def simulate_scan_image(
    image: Image.Image,
    config: ScanSimulationConfig,
    *,
    source_id: str,
    page_index: int,
    session: _ScanSessionProfile | None = None,
) -> Image.Image:
    """Return one simulated scan page as RGB PIL image."""

    cfg = _normalized_config(config)
    img = image.convert("RGB")
    width, height = img.size
    rng = np.random.default_rng(_page_seed(cfg.seed, source_id, page_index))
    scan_session = session or _build_scan_session(cfg, source_id)

    sheet = _prepare_sheet(img, cfg, rng, scan_session)
    page_rect = _page_sheet_rect(scan_session, cfg, rng)
    target_w = max(16, int(round((page_rect[2] - page_rect[0]) * width)))
    target_h = max(16, int(round((page_rect[3] - page_rect[1]) * height)))
    scale = min(
        target_w / max(1, sheet.width),
        target_h / max(1, sheet.height),
    )
    sheet_size = (
        max(16, int(round(sheet.width * scale))),
        max(16, int(round(sheet.height * scale))),
    )
    sheet = sheet.resize(sheet_size, Image.Resampling.LANCZOS)

    if cfg.show_page_border:
        sheet = _draw_page_edge(sheet, cfg, rng)

    background = _make_background((width, height), cfg, rng, scan_session).convert("RGBA")
    warped = _warp_sheet(
        sheet.convert("RGBA"),
        (width, height),
        cfg,
        rng,
        scan_session,
        page_rect,
    )

    if cfg.add_shadow:
        background = _composite_shadow(background, warped, cfg, rng)
    background.alpha_composite(warped)

    final = background.convert("RGB")
    final = _post_process_scan(final, cfg, rng, scan_session)
    return final.convert("RGB")


def _render_page(page: fitz.Page, dpi: int) -> Image.Image:
    scale = dpi / 72.0
    pix = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        colorspace=fitz.csRGB,
        alpha=False,
        annots=True,
    )
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _prepare_sheet(
    image: Image.Image,
    cfg: ScanSimulationConfig,
    rng: np.random.Generator,
    session: _ScanSessionProfile,
) -> Image.Image:
    if cfg.tone == "bw":
        img = _to_black_and_white(image, cfg, rng)
    elif cfg.tone == "gray":
        img = ImageOps.grayscale(image).convert("RGB")
    else:
        img = image.convert("RGB")

    img = ImageOps.autocontrast(img, cutoff=max(0, min(2, cfg.intensity * 0.8)))
    contrast = session.contrast + float(rng.normal(0.0, 0.006 + 0.008 * cfg.intensity))
    brightness = session.exposure + float(rng.normal(0.0, 0.004 + 0.006 * cfg.intensity))
    img = ImageEnhance.Contrast(img).enhance(max(0.75, contrast))
    img = ImageEnhance.Brightness(img).enhance(max(0.80, brightness))

    arr = np.asarray(img, dtype=np.float32)
    h, w = arr.shape[:2]
    mean = arr.mean(axis=2, keepdims=True)
    paper_weight = np.clip((mean - 152.0) / 92.0, 0.0, 1.0)
    paper_rgb = np.array(session.paper_rgb, dtype=np.float32)

    texture = _low_frequency_noise(h, w, rng, grid=max(6, int(10 + 18 * cfg.paper_noise)))
    texture = (texture - 0.5) * (4.0 + 14.0 * cfg.paper_noise * cfg.intensity)
    paper_mix = 0.055 + 0.060 * cfg.intensity
    arr = arr * (1.0 - paper_weight * paper_mix)
    arr += paper_rgb * (paper_weight * paper_mix)
    arr += texture[:, :, None] * (0.18 + 0.58 * paper_weight)

    gray = arr.mean(axis=2)
    dark = gray < (135 + 20 * cfg.intensity)
    if dark.any():
        ink_noise = rng.normal(0.0, 2.2 + 5.6 * cfg.intensity, size=gray.shape)
        arr[dark] += ink_noise[dark, None] * 0.30
        dry = rng.random(gray.shape) < (0.0003 + 0.0011 * cfg.intensity)
        arr[dry & dark] += rng.uniform(8.0, 28.0)

    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    if cfg.blur_radius > 0:
        radius = max(0.0, cfg.blur_radius * (0.45 + cfg.intensity * 0.55))
        img = img.filter(ImageFilter.GaussianBlur(radius=radius))
        img = img.filter(ImageFilter.UnsharpMask(radius=0.8, percent=55, threshold=5))
    return img


def _to_black_and_white(
    image: Image.Image,
    cfg: ScanSimulationConfig,
    rng: np.random.Generator,
) -> Image.Image:
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    arr = np.asarray(gray, dtype=np.float32)
    threshold = 188 + float(rng.normal(0.0, 5.0)) - 14.0 * cfg.intensity
    noise = rng.normal(0.0, 8.0 + 16.0 * cfg.intensity, size=arr.shape)
    bw = np.where(arr + noise < threshold, 25, 248).astype(np.uint8)
    if cfg.intensity < 0.85:
        mixed = (arr * 0.22 + bw.astype(np.float32) * 0.78).astype(np.uint8)
    else:
        mixed = bw
    return Image.fromarray(mixed, "L").convert("RGB")


def _draw_page_edge(
    sheet: Image.Image,
    cfg: ScanSimulationConfig,
    rng: np.random.Generator,
) -> Image.Image:
    rgba = sheet.convert("RGBA")
    draw = ImageDraw.Draw(rgba)
    w, h = rgba.size
    line_w = max(1, int(round(min(w, h) * (0.00055 + 0.00075 * cfg.intensity))))
    alpha = int(24 + 48 * cfg.intensity)
    edge = (142, 142, 136, alpha)
    draw.rectangle((0, 0, w - 1, h - 1), outline=edge, width=line_w)

    wear_count = int((w + h) * 0.006 * cfg.intensity)
    for _ in range(wear_count):
        side = int(rng.integers(0, 4))
        span = int(rng.integers(max(2, line_w), max(3, line_w * 5 + 1)))
        if side == 0:
            x = int(rng.integers(0, max(1, w - span)))
            draw.line((x, 0, x + span, 0), fill=(230, 230, 226, 80), width=line_w)
        elif side == 1:
            x = int(rng.integers(0, max(1, w - span)))
            draw.line((x, h - 1, x + span, h - 1), fill=(230, 230, 226, 80), width=line_w)
        elif side == 2:
            y = int(rng.integers(0, max(1, h - span)))
            draw.line((0, y, 0, y + span), fill=(230, 230, 226, 80), width=line_w)
        else:
            y = int(rng.integers(0, max(1, h - span)))
            draw.line((w - 1, y, w - 1, y + span), fill=(230, 230, 226, 80), width=line_w)
    return rgba


def _make_background(
    size: tuple[int, int],
    cfg: ScanSimulationConfig,
    rng: np.random.Generator,
    session: _ScanSessionProfile,
) -> Image.Image:
    w, h = size
    base = np.array(session.bed_rgb, dtype=np.float32)
    arr = np.tile(base, (h, w, 1))

    low = _low_frequency_noise(h, w, rng, grid=max(4, int(7 + 12 * cfg.background_noise)))
    arr += (low[:, :, None] - 0.5) * (3.0 + 10.0 * cfg.background_noise)
    fine = rng.normal(
        0.0,
        0.5 + 2.2 * cfg.background_noise * cfg.intensity,
        size=(h, w, 1),
    )
    arr += fine

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def _warp_sheet(
    sheet: Image.Image,
    canvas_size: tuple[int, int],
    cfg: ScanSimulationConfig,
    rng: np.random.Generator,
    session: _ScanSessionProfile,
    page_rect: tuple[float, float, float, float],
) -> Image.Image:
    canvas_w, canvas_h = canvas_size
    sw, sh = sheet.size
    cx = (page_rect[0] + page_rect[2]) * canvas_w * 0.5
    cy = (page_rect[1] + page_rect[3]) * canvas_h * 0.5
    half_w = sw / 2.0
    half_h = sh / 2.0
    corners = np.array(
        [
            [cx - half_w, cy - half_h],
            [cx + half_w, cy - half_h],
            [cx + half_w, cy + half_h],
            [cx - half_w, cy + half_h],
        ],
        dtype=np.float32,
    )

    page_angle = float(rng.normal(0.0, max(0.015, cfg.max_rotation_deg * 0.18)))
    angle = math.radians(session.base_angle + page_angle)
    rot = np.array(
        [[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]],
        dtype=np.float32,
    )
    center = np.array([[cx, cy]], dtype=np.float32)
    corners = (corners - center) @ rot.T + center

    p = min(canvas_w, canvas_h) * cfg.max_perspective_pct
    if p > 0:
        jitter = np.array(session.corner_offsets, dtype=np.float32) * p
        jitter += rng.normal(0.0, p * 0.055, size=(4, 2)).astype(np.float32)
        corners += jitter
    corners = _clamp_corners(corners, canvas_w, canvas_h)

    if cv2 is None:
        layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        rotated = sheet.rotate(
            math.degrees(angle),
            resample=Image.Resampling.BICUBIC,
            expand=True,
            fillcolor=(0, 0, 0, 0),
        )
        layer.alpha_composite(
            rotated,
            (
                int(round(canvas_w / 2 - rotated.width / 2)),
                int(round(canvas_h / 2 - rotated.height / 2)),
            ),
        )
        return layer

    src = np.array(
        [[0, 0], [sw - 1, 0], [sw - 1, sh - 1], [0, sh - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(src, corners.astype(np.float32))
    warped = cv2.warpPerspective(
        np.asarray(sheet, dtype=np.uint8),
        matrix,
        (canvas_w, canvas_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    return Image.fromarray(warped, "RGBA")


def _clamp_corners(corners: np.ndarray, width: int, height: int) -> np.ndarray:
    pad = 2.0
    result = corners.copy()
    result[:, 0] = np.clip(result[:, 0], pad, max(pad, width - pad))
    result[:, 1] = np.clip(result[:, 1], pad, max(pad, height - pad))
    return result.astype(np.float32)


def _composite_shadow(
    background: Image.Image,
    sheet: Image.Image,
    cfg: ScanSimulationConfig,
    rng: np.random.Generator,
) -> Image.Image:
    alpha = sheet.getchannel("A")
    blur = max(1.2, min(background.size) * (0.0018 + 0.0045 * cfg.intensity))
    alpha = alpha.filter(ImageFilter.GaussianBlur(radius=blur))
    alpha_arr = np.asarray(alpha, dtype=np.float32)
    alpha_arr *= 0.035 + 0.070 * cfg.intensity
    shadow_alpha = Image.fromarray(np.clip(alpha_arr, 0, 150).astype(np.uint8), "L")
    offset = (
        int(round(float(rng.normal(0.0, 1.1 + 2.8 * cfg.intensity)))),
        int(round(0.8 + 2.6 * cfg.intensity + float(rng.normal(0.0, 0.7)))),
    )
    shifted = _offset_mask(shadow_alpha, offset)
    shadow = Image.new("RGBA", background.size, (0, 0, 0, 0))
    shadow.putalpha(shifted)
    background.alpha_composite(shadow)
    return background


def _offset_mask(mask: Image.Image, offset: tuple[int, int]) -> Image.Image:
    w, h = mask.size
    dx, dy = offset
    result = Image.new("L", mask.size, 0)
    src_left = max(0, -dx)
    src_top = max(0, -dy)
    src_right = min(w, w - dx) if dx >= 0 else w
    src_bottom = min(h, h - dy) if dy >= 0 else h
    if src_right <= src_left or src_bottom <= src_top:
        return result
    dst_left = max(0, dx)
    dst_top = max(0, dy)
    result.paste(mask.crop((src_left, src_top, src_right, src_bottom)), (dst_left, dst_top))
    return result


def _post_process_scan(
    image: Image.Image,
    cfg: ScanSimulationConfig,
    rng: np.random.Generator,
    session: _ScanSessionProfile,
) -> Image.Image:
    img = image.convert("RGB")
    arr = np.asarray(img, dtype=np.float32)
    h, w = arr.shape[:2]

    if cfg.add_scan_bands:
        band_rng = np.random.default_rng(session.band_seed)
        row = band_rng.normal(0.0, 1.0, size=(max(3, h // 34), 1)).astype(np.float32)
        if cv2 is not None:
            row = cv2.resize(row, (1, h), interpolation=cv2.INTER_CUBIC)
        else:
            spread = float(np.ptp(row))
            row = np.array(
                Image.fromarray(
                    ((row - row.min()) * 255 / max(1e-6, spread)).astype(np.uint8),
                    "L",
                ).resize((1, h), Image.Resampling.BICUBIC),
                dtype=np.float32,
            )
            row = row / 255.0 - 0.5
        row = row.reshape(h, 1, 1)
        arr += row * (0.8 + 3.2 * cfg.intensity)
        stripe_every = max(18, int(68 - 28 * cfg.intensity))
        arr[::stripe_every, :, :] -= 0.3 + 1.2 * cfg.intensity

        for streak in session.streaks:
            x = int(streak.x * max(1, w - 1))
            half = max(1, int(streak.width * w / 2.0))
            x0 = max(0, x - half)
            x1 = min(w, x + half + 1)
            if x1 > x0:
                arr[:, x0:x1, :] += streak.delta * cfg.intensity

    sensor_noise = rng.normal(
        0.0,
        0.4 + 2.8 * cfg.background_noise * cfg.intensity,
        size=(h, w, 1),
    )
    arr += sensor_noise

    if cfg.add_dust:
        _add_dust(arr, cfg, rng, session)

    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    if cfg.tone == "gray":
        img = ImageOps.grayscale(img).convert("RGB")
    elif cfg.tone == "bw":
        img = ImageOps.grayscale(img)
        img = ImageOps.autocontrast(img, cutoff=1).convert("RGB")
    return img


def _add_dust(
    arr: np.ndarray,
    cfg: ScanSimulationConfig,
    rng: np.random.Generator,
    session: _ScanSessionProfile,
) -> None:
    h, w = arr.shape[:2]
    for spec in session.dust:
        x = int(spec.x * max(1, w - 1))
        y = int(spec.y * max(1, h - 1))
        radius = max(1, int(spec.radius * min(w, h)))
        _apply_dust_dot(arr, x, y, radius, spec.delta * cfg.intensity)

    area_mp = (w * h) / 1_000_000.0
    count = int(area_mp * (5 + 14 * cfg.intensity))
    if count <= 0:
        return
    for _ in range(count):
        x = int(rng.integers(0, max(1, w)))
        y = int(rng.integers(0, max(1, h)))
        radius = int(rng.integers(1, max(2, int(1 + 3 * cfg.intensity))))
        delta = float(rng.uniform(-9.0, 7.0) * cfg.intensity)
        _apply_dust_dot(arr, x, y, radius, delta)


def _apply_dust_dot(arr: np.ndarray, x: int, y: int, radius: int, delta: float) -> None:
    h, w = arr.shape[:2]
    y0 = max(0, y - radius)
    y1 = min(h, y + radius + 1)
    x0 = max(0, x - radius)
    x1 = min(w, x + radius + 1)
    if y1 <= y0 or x1 <= x0:
        return
    yy, xx = np.ogrid[y0:y1, x0:x1]
    mask = (xx - x) * (xx - x) + (yy - y) * (yy - y) <= radius * radius
    patch = arr[y0:y1, x0:x1]
    patch[mask] += delta


def _low_frequency_noise(
    height: int,
    width: int,
    rng: np.random.Generator,
    *,
    grid: int,
) -> np.ndarray:
    gy = max(2, min(96, int(grid)))
    gx = max(2, min(96, int(round(grid * width / max(1, height)))))
    small = rng.random((gy, gx), dtype=np.float32)
    if cv2 is not None:
        noise = cv2.resize(small, (width, height), interpolation=cv2.INTER_CUBIC)
        noise = cv2.GaussianBlur(noise, (0, 0), sigmaX=max(0.8, min(width, height) / 80.0))
    else:
        pil = Image.fromarray((small * 255).astype(np.uint8), "L")
        noise = np.asarray(
            pil.resize((width, height), Image.Resampling.BICUBIC),
            dtype=np.float32,
        ) / 255.0
    low = float(np.min(noise))
    high = float(np.max(noise))
    if high - low < 1e-6:
        return np.full((height, width), 0.5, dtype=np.float32)
    return ((noise - low) / (high - low)).astype(np.float32)


def _encode_jpeg(image: Image.Image, cfg: ScanSimulationConfig) -> bytes:
    buf = io.BytesIO()
    quality = max(45, min(96, int(cfg.jpeg_quality)))
    image.convert("RGB").save(
        buf,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=False,
        subsampling=0 if quality >= 84 else 1,
    )
    return buf.getvalue()


def _normalized_config(cfg: ScanSimulationConfig | None) -> ScanSimulationConfig:
    raw = cfg or ScanSimulationConfig()
    tone = str(raw.tone or "gray").strip().lower()
    if tone not in {"color", "gray", "bw"}:
        tone = "gray"
    preset_id = preset_for(raw.preset_id).id
    return replace(
        raw,
        preset_id=preset_id,
        dpi=max(96, min(400, int(raw.dpi))),
        tone=tone,  # type: ignore[arg-type]
        intensity=_clamp(float(raw.intensity), 0.0, 1.0),
        margin_pct=_clamp(float(raw.margin_pct), 0.0, 0.11),
        max_rotation_deg=_clamp(float(raw.max_rotation_deg), 0.0, 4.0),
        max_perspective_pct=_clamp(float(raw.max_perspective_pct), 0.0, 0.060),
        background_noise=_clamp(float(raw.background_noise), 0.0, 1.0),
        paper_noise=_clamp(float(raw.paper_noise), 0.0, 1.0),
        blur_radius=_clamp(float(raw.blur_radius), 0.0, 1.2),
        jpeg_quality=max(45, min(96, int(raw.jpeg_quality))),
        seed=int(raw.seed) & 0x7FFFFFFF,
        page_range=(raw.page_range or "").strip(),
    )


def _copy_basic_metadata(src: fitz.Document, out: fitz.Document, source: Path) -> None:
    metadata = dict(src.metadata or {})
    metadata["producer"] = "PDFlex - Simular escaneo"
    metadata["title"] = metadata.get("title") or source.stem
    try:
        out.set_metadata(metadata)
    except Exception:
        pass


def _validate_output(path: Path, expected_pages: int) -> None:
    if not path.exists() or path.stat().st_size <= 0:
        raise RuntimeError("archivo vacio")
    with fitz.open(str(path)) as doc:
        if doc.page_count != expected_pages:
            raise RuntimeError(
                f"paginas inesperadas ({doc.page_count}; se esperaban {expected_pages})"
            )
        for index in range(doc.page_count):
            if doc[index].rect.width <= 0 or doc[index].rect.height <= 0:
                raise RuntimeError(f"pagina {index + 1} sin tamano valido")


def _page_seed(seed: int, source_id: str, page_index: int) -> int:
    payload = f"{seed}\0{source_id}\0{page_index}".encode("utf-8", errors="ignore")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & 0xFFFFFFFF


def _session_seed(seed: int, source_id: str) -> int:
    payload = f"session\0{seed}\0{source_id}".encode("utf-8", errors="ignore")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & 0xFFFFFFFF


def _jitter(value: float, pct: float, rng: np.random.Generator) -> float:
    return value * max(0.55, 1.0 + float(rng.normal(0.0, pct)))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _is_cancelled(callback: Optional[Callable[[], bool]]) -> bool:
    return bool(callback and callback())


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except Exception:
        return str(a) == str(b)


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _remove_file(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _tone_label(tone: str) -> str:
    return {
        "color": "Color",
        "gray": "Grises",
        "bw": "Blanco y negro",
    }.get(tone, tone)


def _format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{int(value)} B"
    if value < 10:
        return f"{value:.1f} {unit}"
    return f"{value:.0f} {unit}"


class _CancelledError(Exception):
    pass
