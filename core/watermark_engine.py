"""Watermark and stamp engine for PDF files."""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Iterable, List, Tuple

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from core.pdf_backend import PdfRenderDocument, apply_page_overlays


RGBColor = Tuple[float, float, float]


POSITIONS: dict[str, str] = {
    "center": "Centro",
    "top-left": "Superior izquierda",
    "top-center": "Superior centro",
    "top-right": "Superior derecha",
    "bottom-left": "Inferior izquierda",
    "bottom-center": "Inferior centro",
    "bottom-right": "Inferior derecha",
}


@dataclass(frozen=True)
class WatermarkPreset:
    id: str
    label: str
    text: str
    color: RGBColor
    opacity: float
    rotation_deg: float
    position: str
    font_size: float


PRESETS: dict[str, WatermarkPreset] = {
    "confidencial": WatermarkPreset(
        id="confidencial",
        label="Confidencial",
        text="CONFIDENCIAL",
        color=(0.90, 0.12, 0.12),
        opacity=0.18,
        rotation_deg=-35.0,
        position="center",
        font_size=62.0,
    ),
    "copia": WatermarkPreset(
        id="copia",
        label="Copia",
        text="COPIA",
        color=(0.12, 0.18, 0.28),
        opacity=0.16,
        rotation_deg=-35.0,
        position="center",
        font_size=72.0,
    ),
    "pagado": WatermarkPreset(
        id="pagado",
        label="Pagado",
        text="PAGADO",
        color=(0.05, 0.48, 0.28),
        opacity=0.34,
        rotation_deg=-12.0,
        position="bottom-right",
        font_size=34.0,
    ),
    "recibido": WatermarkPreset(
        id="recibido",
        label="Recibido",
        text="RECIBIDO",
        color=(0.02, 0.38, 0.70),
        opacity=0.30,
        rotation_deg=-12.0,
        position="bottom-right",
        font_size=34.0,
    ),
}


COLOR_CHOICES: dict[str, tuple[str, RGBColor]] = {
    "red": ("Rojo", (0.90, 0.12, 0.12)),
    "black": ("Negro", (0.06, 0.07, 0.09)),
    "blue": ("Azul", (0.02, 0.38, 0.70)),
    "green": ("Verde", (0.05, 0.48, 0.28)),
    "gray": ("Gris", (0.35, 0.37, 0.42)),
}


@dataclass(frozen=True)
class WatermarkOptions:
    mode: str = "text"  # "text" | "image"
    text: str = "CONFIDENCIAL"
    image_path: str = ""
    position: str = "center"
    opacity: float = 0.18
    rotation_deg: float = -35.0
    font_size: float = 62.0
    image_width_pct: float = 38.0
    color: RGBColor = (0.90, 0.12, 0.12)
    page_scope: str = "all"  # "all" | "first" | "last" | "custom"
    custom_pages: str = ""
    overlay: bool = True


@dataclass
class WatermarkJob:
    pdf_path: str
    output_path: str
    options: WatermarkOptions = field(default_factory=WatermarkOptions)


@dataclass
class WatermarkResult:
    job: WatermarkJob
    output_path: str = ""
    success: bool = False
    error: str = ""
    total_pages: int = 0
    stamped_pages: int = 0
    mode_label: str = ""

    @property
    def meta_text(self) -> str:
        label = self.mode_label or ("Imagen" if self.job.options.mode == "image" else "Texto")
        return f"{self.stamped_pages}/{self.total_pages} paginas selladas · {label}"


class WatermarkEngine:
    """Applies text or image stamps to PDFs without modifying originals."""

    def run_batch(
        self,
        jobs: List[WatermarkJob],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[WatermarkResult]:
        total = len(jobs)
        results: List[WatermarkResult] = []
        for index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(index, total, f"Sellando {Path(job.pdf_path).name}...")
            result = self.run_job(job, should_cancel=should_cancel)
            results.append(result)
            if progress:
                progress(index + 1, total, f"{index + 1}/{total} PDFs procesados")
        return results

    def run_job(
        self,
        job: WatermarkJob,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> WatermarkResult:
        source = Path(job.pdf_path)
        output = Path(job.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        if not source.exists():
            return WatermarkResult(job=job, success=False, error="El PDF de origen no existe.")

        try:
            self._validate_options(job.options)
            with PdfRenderDocument(source) as document:
                if document.page_count <= 0:
                    raise RuntimeError("El PDF no tiene paginas.")
                page_indexes = parse_page_selection(
                    job.options.page_scope,
                    job.options.custom_pages,
                    document.page_count,
                )
                with TemporaryDirectory(prefix="pdflex-watermark-") as temp_dir:
                    overlay_path = Path(temp_dir) / "overlay.pdf"
                    canvas = Canvas(str(overlay_path), pagesize=(1, 1), pageCompression=1)
                    prepared_image = (
                        _prepare_image(
                            job.options.image_path,
                            job.options.opacity,
                            job.options.rotation_deg,
                        )
                        if job.options.mode == "image"
                        else None
                    )
                    mapping: dict[int, int] = {}
                    for overlay_index, page_index in enumerate(page_indexes):
                        if should_cancel and should_cancel():
                            raise _CancelledError()
                        info = document.page_info(page_index)
                        canvas.setPageSize((info.width_pt, info.height_pt))
                        if prepared_image is not None:
                            _draw_image_watermark(
                                canvas, info.width_pt, info.height_pt,
                                job.options, prepared_image,
                            )
                        else:
                            _draw_text_watermark(
                                canvas, info.width_pt, info.height_pt, job.options
                            )
                        canvas.showPage()
                        mapping[page_index] = overlay_index
                    canvas.save()
                    report = apply_page_overlays(
                        source,
                        overlay_path,
                        mapping,
                        output,
                        over=job.options.overlay,
                    )
            return WatermarkResult(
                job=job,
                output_path=str(output),
                success=True,
                total_pages=report.page_count,
                stamped_pages=len(page_indexes),
                mode_label="Imagen" if job.options.mode == "image" else "Texto",
            )
        except _CancelledError:
            return WatermarkResult(job=job, success=False, error="Operacion cancelada.")
        except Exception as exc:
            return WatermarkResult(job=job, success=False, error=str(exc))

    def _validate_options(self, options: WatermarkOptions) -> None:
        if options.mode not in {"text", "image"}:
            raise ValueError("Tipo de sello no valido.")
        if options.mode == "text" and not options.text.strip():
            raise ValueError("Escribe el texto del sello.")
        if options.mode == "image":
            if not options.image_path.strip():
                raise ValueError("Selecciona una imagen para el sello.")
            if not Path(options.image_path).exists():
                raise ValueError("La imagen del sello no existe.")
        if options.position not in POSITIONS:
            raise ValueError("Posicion de sello no valida.")
        if not 0.01 <= options.opacity <= 1.0:
            raise ValueError("La opacidad debe estar entre 1% y 100%.")
        if options.font_size <= 0:
            raise ValueError("El tamano de texto debe ser mayor a cero.")
        if not 1.0 <= options.image_width_pct <= 95.0:
            raise ValueError("El ancho de imagen debe estar entre 1% y 95%.")

def preset_for(preset_id: str) -> WatermarkPreset:
    return PRESETS.get(preset_id, PRESETS["confidencial"])


def parse_page_selection(scope: str, custom_pages: str, page_count: int) -> list[int]:
    if page_count <= 0:
        return []
    if scope == "all":
        return list(range(page_count))
    if scope == "first":
        return [0]
    if scope == "last":
        return [page_count - 1]
    if scope != "custom":
        raise ValueError("Alcance de paginas no valido.")

    selected: set[int] = set()
    raw = custom_pages.replace(";", ",").replace(" ", "")
    if not raw:
        raise ValueError("Escribe un rango de paginas.")
    for token in (part for part in raw.split(",") if part):
        if "-" in token:
            start_s, end_s = token.split("-", 1)
            start = int(start_s) if start_s else 1
            end = int(end_s) if end_s else page_count
            if start > end:
                start, end = end, start
            _add_range(selected, start, end, page_count)
        else:
            page_num = int(token)
            _add_range(selected, page_num, page_num, page_count)
    if not selected:
        raise ValueError("El rango no contiene paginas validas.")
    return sorted(selected)


def _add_range(target: set[int], start: int, end: int, page_count: int) -> None:
    if end < 1 or start > page_count:
        return
    for page_num in range(max(1, start), min(page_count, end) + 1):
        target.add(page_num - 1)


def _text_width(text: str, fontname: str, fontsize: float) -> float:
    return float(stringWidth(text, "Helvetica", fontsize))


def _position_center(position: str, page_width: float, page_height: float) -> tuple[float, float]:
    mx = page_width * 0.12
    my = page_height * 0.12
    x_map = {
        "left": mx,
        "center": page_width / 2.0,
        "right": page_width - mx,
    }
    y_map = {
        "top": my,
        "center": page_height / 2.0,
        "bottom": page_height - my,
    }
    if position == "center":
        return x_map["center"], y_map["center"]
    vertical, horizontal = position.split("-", 1)
    return x_map[horizontal], y_map[vertical]


def _draw_text_watermark(
    canvas: Canvas,
    page_width: float,
    page_height: float,
    options: WatermarkOptions,
) -> None:
    text = options.text.strip()
    cx, cy = _position_center(options.position, page_width, page_height)
    page_scale = max(0.55, min(2.5, max(page_width, page_height) / 842.0))
    fontsize = max(4.0, options.font_size * page_scale)
    text_width = _text_width(text, "Helvetica", fontsize)
    max_width = page_width * 0.86
    if text_width > max_width:
        fontsize = max(4.0, fontsize * max_width / max(1.0, text_width))
        text_width = _text_width(text, "Helvetica", fontsize)
    canvas.saveState()
    canvas.setFillColorRGB(*options.color)
    canvas.setFillAlpha(options.opacity)
    canvas.setFont("Helvetica", fontsize)
    canvas.translate(cx, page_height - cy)
    canvas.rotate(-float(options.rotation_deg))
    canvas.drawString(-text_width / 2.0, -fontsize * 0.36, text)
    canvas.restoreState()


def _draw_image_watermark(
    canvas: Canvas,
    page_width: float,
    page_height: float,
    options: WatermarkOptions,
    prepared_image: "_PreparedImage",
) -> None:
    cx, cy = _position_center(options.position, page_width, page_height)
    width = page_width * max(1.0, min(95.0, options.image_width_pct)) / 100.0
    ratio = prepared_image.height / max(1.0, prepared_image.width)
    height = width * ratio
    max_height = page_height * 0.92
    if height > max_height:
        height = max_height
        width = height / max(0.001, ratio)
    canvas.drawImage(
        ImageReader(BytesIO(prepared_image.bytes)),
        cx - width / 2.0,
        page_height - (cy + height / 2.0),
        width=width,
        height=height,
        preserveAspectRatio=False,
        mask="auto",
    )


@dataclass(frozen=True)
class _PreparedImage:
    bytes: bytes
    width: int
    height: int


def _prepare_image(path: str, opacity: float, rotation_deg: float) -> _PreparedImage:
    with Image.open(path) as image:
        img = image.convert("RGBA")
        if opacity < 0.999:
            alpha = img.getchannel("A")
            alpha = alpha.point(lambda value: int(value * max(0.0, min(1.0, opacity))))
            img.putalpha(alpha)
        if abs(rotation_deg) > 0.001:
            img = img.rotate(-rotation_deg, expand=True, resample=Image.Resampling.BICUBIC)
        buffer = BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        return _PreparedImage(bytes=buffer.getvalue(), width=img.width, height=img.height)


class _CancelledError(Exception):
    pass
