"""Secure PDF redaction engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Tuple

import fitz


RGBColor = Tuple[float, float, float]


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
        rect: fitz.Rect,
        page_width: float,
        page_height: float,
    ) -> "RedactionRect":
        pw = max(1.0, page_width)
        ph = max(1.0, page_height)
        return cls(
            page_index=page_index,
            x0_norm=rect.x0 / pw,
            y0_norm=rect.y0 / ph,
            x1_norm=rect.x1 / pw,
            y1_norm=rect.y1 / ph,
        )

    def normalized(self) -> "RedactionRect":
        return RedactionRect(
            page_index=max(0, int(self.page_index)),
            x0_norm=max(0.0, min(1.0, min(self.x0_norm, self.x1_norm))),
            y0_norm=max(0.0, min(1.0, min(self.y0_norm, self.y1_norm))),
            x1_norm=max(0.0, min(1.0, max(self.x0_norm, self.x1_norm))),
            y1_norm=max(0.0, min(1.0, max(self.y0_norm, self.y1_norm))),
        )

    def to_display_rect(self, page: fitz.Page) -> fitz.Rect:
        rect = self.normalized()
        pw = max(1.0, page.rect.width)
        ph = max(1.0, page.rect.height)
        return fitz.Rect(
            rect.x0_norm * pw,
            rect.y0_norm * ph,
            rect.x1_norm * pw,
            rect.y1_norm * ph,
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
    """Applies real PDF redactions using PyMuPDF annotations."""

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
            result = self.run_job(job, should_cancel=should_cancel)
            results.append(result)
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
        if not job.rects:
            return RedactionResult(job=job, success=False, error="Agrega al menos una zona de redaccion.")

        doc: fitz.Document | None = None
        try:
            doc = fitz.open(str(source))
            if doc.is_encrypted:
                raise RuntimeError("El PDF esta protegido o cifrado.")
            if doc.page_count <= 0:
                raise RuntimeError("El PDF no tiene paginas.")

            grouped = _group_rects(job.rects, doc.page_count)
            if not grouped:
                raise RuntimeError("No hay zonas de redaccion validas para este PDF.")

            count = 0
            for page_index, rects in grouped.items():
                if should_cancel and should_cancel():
                    raise _CancelledError()
                page = doc[page_index]
                applied_on_page = 0
                for redaction in rects:
                    display_rect = redaction.to_display_rect(page)
                    if display_rect.width < 1.0 or display_rect.height < 1.0:
                        continue
                    pdf_rect = _display_rect_for_page(page, display_rect)
                    page.add_redact_annot(
                        pdf_rect,
                        fill=job.options.fill_color,
                        cross_out=False,
                    )
                    applied_on_page += 1
                if applied_on_page:
                    page.apply_redactions(
                        images=(
                            fitz.PDF_REDACT_IMAGE_PIXELS
                            if job.options.redact_images
                            else fitz.PDF_REDACT_IMAGE_NONE
                        ),
                        graphics=(
                            fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED
                            if job.options.redact_graphics
                            else fitz.PDF_REDACT_LINE_ART_NONE
                        ),
                        text=fitz.PDF_REDACT_TEXT_REMOVE,
                    )
                    count += applied_on_page

            if count <= 0:
                raise RuntimeError("Las zonas eran demasiado pequenas o invalidas.")

            doc.save(str(output), garbage=4, clean=True, deflate=True)
            return RedactionResult(
                job=job,
                output_path=str(output),
                success=True,
                total_pages=doc.page_count,
                redaction_count=count,
            )
        except _CancelledError:
            return RedactionResult(job=job, success=False, error="Operacion cancelada.")
        except Exception as exc:
            return RedactionResult(job=job, success=False, error=str(exc))
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass


def _group_rects(rects: List[RedactionRect], page_count: int) -> dict[int, list[RedactionRect]]:
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


def _display_rect_for_page(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    if not int(page.rotation) % 360:
        return rect
    matrix = page.derotation_matrix
    corners = [
        fitz.Point(rect.x0, rect.y0) * matrix,
        fitz.Point(rect.x1, rect.y0) * matrix,
        fitz.Point(rect.x0, rect.y1) * matrix,
        fitz.Point(rect.x1, rect.y1) * matrix,
    ]
    return fitz.Rect(
        min(point.x for point in corners),
        min(point.y for point in corners),
        max(point.x for point in corners),
        max(point.y for point in corners),
    )


class _CancelledError(Exception):
    pass
