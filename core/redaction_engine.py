"""Secure PDF redaction engine using selective page rasterization."""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, List, Tuple

from PIL import ImageDraw

from core.pdf_backend import (
    ImagePdfPage,
    PdfRenderDocument,
    Rect,
    SourcePage,
    assemble_pages,
    create_image_pdf,
)


RGBColor = Tuple[float, float, float]
_REDACTION_DPI = 300


@dataclass(frozen=True)
class RedactionRect:
    page_index: int
    x0_norm: float
    y0_norm: float
    x1_norm: float
    y1_norm: float

    @classmethod
    def from_page_rect(
        cls,
        page_index: int,
        rect,
        page_width: float,
        page_height: float,
    ) -> "RedactionRect":
        pw = max(1.0, page_width)
        ph = max(1.0, page_height)
        return cls(
            page_index=page_index,
            x0_norm=float(rect.x0) / pw,
            y0_norm=float(rect.y0) / ph,
            x1_norm=float(rect.x1) / pw,
            y1_norm=float(rect.y1) / ph,
        )

    def normalized(self) -> "RedactionRect":
        return RedactionRect(
            page_index=max(0, int(self.page_index)),
            x0_norm=max(0.0, min(1.0, min(self.x0_norm, self.x1_norm))),
            y0_norm=max(0.0, min(1.0, min(self.y0_norm, self.y1_norm))),
            x1_norm=max(0.0, min(1.0, max(self.x0_norm, self.x1_norm))),
            y1_norm=max(0.0, min(1.0, max(self.y0_norm, self.y1_norm))),
        )

    def to_display_rect(self, page_width: float, page_height: float) -> Rect:
        rect = self.normalized()
        return Rect(
            rect.x0_norm * max(1.0, page_width),
            rect.y0_norm * max(1.0, page_height),
            rect.x1_norm * max(1.0, page_width),
            rect.y1_norm * max(1.0, page_height),
        )


@dataclass(frozen=True)
class RedactionOptions:
    fill_color: RGBColor = (0.0, 0.0, 0.0)
    redact_images: bool = True
    redact_graphics: bool = True


@dataclass
class RedactionJob:
    pdf_path: str
    output_path: str
    rects: List[RedactionRect] = field(default_factory=list)
    options: RedactionOptions = field(default_factory=RedactionOptions)


@dataclass
class RedactionResult:
    job: RedactionJob
    output_path: str = ""
    success: bool = False
    error: str = ""
    total_pages: int = 0
    redaction_count: int = 0

    @property
    def meta_text(self) -> str:
        return f"{self.redaction_count} redacciones reales · contenido eliminado"


class RedactionEngine:
    """Permanently removes content by rasterizing only affected pages."""

    def run_batch(
        self,
        jobs: List[RedactionJob],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[RedactionResult]:
        total = len(jobs)
        results: List[RedactionResult] = []
        for index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(index, total, f"Redactando {Path(job.pdf_path).name}...")
            results.append(self.run_job(job, should_cancel=should_cancel))
            if progress:
                progress(index + 1, total, f"{index + 1}/{total} PDFs procesados")
        return results

    def run_job(
        self,
        job: RedactionJob,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> RedactionResult:
        source = Path(job.pdf_path)
        output = Path(job.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            return RedactionResult(job=job, success=False, error="El PDF de origen no existe.")
        if source.resolve() == output.resolve():
            return RedactionResult(
                job=job, success=False, error="La salida no puede sobrescribir el PDF de origen."
            )
        if not job.rects:
            return RedactionResult(
                job=job, success=False, error="Agrega al menos una zona de redaccion."
            )

        try:
            with PdfRenderDocument(source) as document:
                grouped = _group_rects(job.rects, document.page_count)
                if not grouped:
                    raise RuntimeError("No hay zonas de redaccion validas para este PDF.")
                with TemporaryDirectory(prefix="pdflex-redaction-") as temp_dir:
                    raster_pdf = Path(temp_dir) / "redacted-pages.pdf"
                    affected_indexes = sorted(grouped)
                    local_by_source = {
                        page_index: local_index
                        for local_index, page_index in enumerate(affected_indexes)
                    }
                    count = 0

                    def redacted_pages():
                        nonlocal count
                        fill = tuple(
                            max(0, min(255, round(channel * 255)))
                            for channel in job.options.fill_color
                        )
                        scale = _REDACTION_DPI / 72.0
                        for page_index in affected_indexes:
                            if should_cancel and should_cancel():
                                raise _CancelledError()
                            info = document.page_info(page_index)
                            image = document.render_page(page_index, scale=scale).to_pil()
                            painter = ImageDraw.Draw(image)
                            for redaction in grouped[page_index]:
                                rect = redaction.to_display_rect(info.width_pt, info.height_pt)
                                if rect.width < 1.0 or rect.height < 1.0:
                                    continue
                                painter.rectangle(
                                    (
                                        round(rect.x0 * scale),
                                        round(rect.y0 * scale),
                                        round(rect.x1 * scale),
                                        round(rect.y1 * scale),
                                    ),
                                    fill=fill,
                                )
                                count += 1
                            buffer = BytesIO()
                            image.save(buffer, format="JPEG", quality=94, optimize=True)
                            yield ImagePdfPage(buffer.getvalue(), info.width_pt, info.height_pt)

                    create_image_pdf(redacted_pages(), raster_pdf)
                    if count <= 0:
                        raise RuntimeError("Las zonas eran demasiado pequenas o invalidas.")
                    pages = [
                        SourcePage(
                            str(raster_pdf),
                            local_by_source[index],
                        )
                        if index in local_by_source
                        else SourcePage(str(source), index)
                        for index in range(document.page_count)
                    ]
                    report = assemble_pages(pages, output)

            return RedactionResult(
                job=job,
                output_path=str(output),
                success=True,
                total_pages=report.page_count,
                redaction_count=count,
            )
        except _CancelledError:
            return RedactionResult(job=job, success=False, error="Operacion cancelada.")
        except Exception as exc:  # noqa: BLE001 - surfaced as result
            return RedactionResult(job=job, success=False, error=str(exc))


def _group_rects(
    rects: List[RedactionRect],
    page_count: int,
) -> dict[int, list[RedactionRect]]:
    grouped: dict[int, list[RedactionRect]] = {}
    for rect in rects:
        normalized = rect.normalized()
        if normalized.page_index < 0 or normalized.page_index >= page_count:
            continue
        if normalized.x1_norm - normalized.x0_norm <= 0.001:
            continue
        if normalized.y1_norm - normalized.y0_norm <= 0.001:
            continue
        grouped.setdefault(normalized.page_index, []).append(normalized)
    return grouped


class _CancelledError(Exception):
    pass
