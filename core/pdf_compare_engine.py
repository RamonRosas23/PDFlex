"""Visual and textual comparison engine for PDF pairs."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Callable, List
import difflib
import re
import uuid

from PIL import Image, ImageChops
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from core.pdf_backend import PdfRenderDocument


@dataclass(frozen=True)
class PdfCompareOptions:
    dpi: int = 110
    pixel_threshold: int = 24
    min_change_ratio: float = 0.001
    compare_text: bool = True
    include_equal_pages: bool = False


@dataclass
class PdfCompareJob:
    base_pdf: str
    compare_pdf: str
    output_path: str
    options: PdfCompareOptions = field(default_factory=PdfCompareOptions)


@dataclass
class PdfComparePageResult:
    page_index: int
    base_exists: bool = True
    compare_exists: bool = True
    visual_changed: bool = False
    text_changed: bool = False
    size_changed: bool = False
    change_ratio: float = 0.0
    base_text: str = ""
    compare_text: str = ""
    text_delta: str = ""

    @property
    def changed(self) -> bool:
        return (
            self.visual_changed
            or self.text_changed
            or self.size_changed
            or not self.base_exists
            or not self.compare_exists
        )

    @property
    def status_label(self) -> str:
        if self.compare_exists and not self.base_exists:
            return "Agregada"
        if self.base_exists and not self.compare_exists:
            return "Eliminada"
        if self.changed:
            return "Diferente"
        return "Igual"


@dataclass
class PdfCompareResult:
    job: PdfCompareJob
    output_path: str = ""
    success: bool = False
    error: str = ""
    total_pages: int = 0
    changed_pages: int = 0
    visual_changed_pages: int = 0
    text_changed_pages: int = 0
    added_pages: int = 0
    removed_pages: int = 0
    page_results: List[PdfComparePageResult] = field(default_factory=list)

    @property
    def meta_text(self) -> str:
        return (
            f"{self.changed_pages}/{self.total_pages} paginas con diferencias"
            f" · visual {self.visual_changed_pages}"
            f" · texto {self.text_changed_pages}"
        )


class PdfCompareEngine:
    """Compares two PDFs and writes a PDF report with visual highlights."""

    def run_batch(
        self,
        jobs: List[PdfCompareJob],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[PdfCompareResult]:
        results: list[PdfCompareResult] = []
        total = len(jobs)
        for index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(index, total, f"Comparando {Path(job.compare_pdf).name}...")
            results.append(self.run_job(job, should_cancel=should_cancel))
            if progress:
                progress(index + 1, total, f"{index + 1}/{total} comparaciones procesadas")
        return results

    def run_job(
        self,
        job: PdfCompareJob,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> PdfCompareResult:
        base_path = Path(job.base_pdf)
        compare_path = Path(job.compare_pdf)
        output = Path(job.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        if not base_path.exists():
            return PdfCompareResult(job=job, success=False, error="El PDF base no existe.")
        if not compare_path.exists():
            return PdfCompareResult(job=job, success=False, error="El PDF a comparar no existe.")

        if output.resolve() in {base_path.resolve(), compare_path.resolve()}:
            return PdfCompareResult(
                job=job,
                success=False,
                error="La salida no puede sobrescribir uno de los PDFs comparados.",
            )

        try:
            with (
                PdfRenderDocument(base_path) as base_doc,
                PdfRenderDocument(compare_path) as compare_doc,
            ):
                _validate_doc(base_doc, "base")
                _validate_doc(compare_doc, "a comparar")

                total_pages = max(base_doc.page_count, compare_doc.page_count)
                page_results: list[PdfComparePageResult] = []
                for page_index in range(total_pages):
                    if should_cancel and should_cancel():
                        break
                    page_results.append(
                        self._compare_page(base_doc, compare_doc, page_index, job.options)
                    )

                result = PdfCompareResult(
                    job=job,
                    output_path=str(output),
                    success=True,
                    total_pages=total_pages,
                    changed_pages=sum(1 for item in page_results if item.changed),
                    visual_changed_pages=sum(
                        1 for item in page_results if item.visual_changed or item.size_changed
                    ),
                    text_changed_pages=sum(1 for item in page_results if item.text_changed),
                    added_pages=sum(
                        1 for item in page_results if item.compare_exists and not item.base_exists
                    ),
                    removed_pages=sum(
                        1 for item in page_results if item.base_exists and not item.compare_exists
                    ),
                    page_results=page_results,
                )
                self._write_report(base_doc, compare_doc, result)
                return result
        except Exception as exc:
            return PdfCompareResult(job=job, success=False, error=str(exc))

    def _compare_page(
        self,
        base_doc: PdfRenderDocument,
        compare_doc: PdfRenderDocument,
        page_index: int,
        options: PdfCompareOptions,
    ) -> PdfComparePageResult:
        base_exists = page_index < base_doc.page_count
        compare_exists = page_index < compare_doc.page_count
        if not base_exists or not compare_exists:
            return PdfComparePageResult(
                page_index=page_index,
                base_exists=base_exists,
                compare_exists=compare_exists,
                visual_changed=True,
                change_ratio=1.0,
                base_text=_page_text(base_doc, page_index) if base_exists else "",
                compare_text=_page_text(compare_doc, page_index) if compare_exists else "",
            )

        base_text = _page_text(base_doc, page_index)
        compare_text = _page_text(compare_doc, page_index)
        text_changed = (
            options.compare_text
            and _normalize_text(base_text) != _normalize_text(compare_text)
        )

        size_changed = _page_size_changed(base_doc, compare_doc, page_index)
        base_image = _render_page_image(base_doc, page_index, options.dpi)
        compare_image = _render_page_image(compare_doc, page_index, options.dpi)
        ratio = _difference_ratio(base_image, compare_image, options.pixel_threshold)
        visual_changed = ratio >= options.min_change_ratio

        return PdfComparePageResult(
            page_index=page_index,
            visual_changed=visual_changed,
            text_changed=text_changed,
            size_changed=size_changed,
            change_ratio=ratio,
            base_text=base_text,
            compare_text=compare_text,
            text_delta=_text_delta_summary(base_text, compare_text) if text_changed else "",
        )

    def _write_report(
        self,
        base_doc: PdfRenderDocument,
        compare_doc: PdfRenderDocument,
        result: PdfCompareResult,
    ) -> None:
        output = Path(result.output_path)
        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        detail_pages = [
            item for item in result.page_results
            if item.changed or result.job.options.include_equal_pages
        ]
        try:
            report = Canvas(str(temporary), pagesize=(595, 842), pageCompression=1)
            self._add_summary_page(report, result)
            report.showPage()
            for page_result in detail_pages:
                self._add_detail_page(report, base_doc, compare_doc, result, page_result)
                report.showPage()
            report.save()

            expected_pages = 1 + len(detail_pages)
            with PdfRenderDocument(temporary) as verification:
                if verification.page_count != expected_pages:
                    raise RuntimeError(
                        f"El reporte contiene {verification.page_count} páginas; "
                        f"se esperaban {expected_pages}."
                    )
                for index in range(expected_pages):
                    verification.render_page(index, scale=0.2)
            os.replace(temporary, output)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _add_summary_page(self, page: Canvas, result: PdfCompareResult) -> None:
        _prepare_page(page, 595, 842)
        _draw_title(page, "Reporte de comparacion PDF", 36, 52, size=20)
        lines = [
            f"PDF base: {Path(result.job.base_pdf).name}",
            f"PDF revisado: {Path(result.job.compare_pdf).name}",
            f"Paginas analizadas: {result.total_pages}",
            f"Paginas con diferencias: {result.changed_pages}",
            f"Diferencias visuales: {result.visual_changed_pages}",
            f"Diferencias de texto: {result.text_changed_pages}",
            f"Paginas agregadas: {result.added_pages}",
            f"Paginas eliminadas: {result.removed_pages}",
            f"Sensibilidad: {result.job.options.dpi} DPI, umbral {result.job.options.pixel_threshold}, minimo {result.job.options.min_change_ratio:.3%}",
        ]
        if result.changed_pages == 0:
            lines.append("Sin diferencias detectadas con la sensibilidad actual.")
        _insert_textbox(page, (36, 82, 559, 240), "\n".join(lines), fontsize=10.5)

        y = 272
        _draw_title(page, "Resumen por pagina", 36, y, size=13)
        y += 24
        for item in result.page_results[:34]:
            detail = _page_detail_label(item)
            _insert_text(page, 44, y, detail, fontsize=9.2, color=_status_color(item))
            y += 16
        if len(result.page_results) > 34:
            _insert_text(page, 44, y + 4, f"... {len(result.page_results) - 34} paginas mas.", fontsize=9)

    def _add_detail_page(
        self,
        page: Canvas,
        base_doc: PdfRenderDocument,
        compare_doc: PdfRenderDocument,
        result: PdfCompareResult,
        page_result: PdfComparePageResult,
    ) -> None:
        _prepare_page(page, 842, 595)
        page_no = page_result.page_index + 1
        _draw_title(page, f"Pagina {page_no} - {page_result.status_label}", 36, 40, size=17)
        _insert_textbox(
            page,
            (36, 58, 806, 92),
            _page_detail_label(page_result),
            fontsize=9.5,
            color=_status_color(page_result),
        )

        left_bounds = (36.0, 126.0, 405.0, 520.0)
        right_bounds = (437.0, 126.0, 806.0, 520.0)
        _insert_text(page, left_bounds[0], 112, "Base", fontsize=10, color=(0.88, 0.88, 0.9))
        _insert_text(page, right_bounds[0], 112, "Revisado con diferencias resaltadas", fontsize=10, color=(0.88, 0.88, 0.9))

        if page_result.base_exists:
            base_img = _render_page_image(base_doc, page_result.page_index, result.job.options.dpi)
            _insert_pil_image(page, base_img, left_bounds)
        else:
            _draw_placeholder(page, left_bounds, "No existe en PDF base")

        if page_result.compare_exists:
            compare_img = _render_page_image(compare_doc, page_result.page_index, result.job.options.dpi)
            if page_result.base_exists:
                base_img = _render_page_image(base_doc, page_result.page_index, result.job.options.dpi)
                compare_img = _highlight_differences(base_img, compare_img, result.job.options.pixel_threshold)
            _insert_pil_image(page, compare_img, right_bounds)
        else:
            _draw_placeholder(page, right_bounds, "No existe en PDF revisado")

        if page_result.text_delta:
            _draw_title(page, "Diferencia textual", 36, 548, size=10)
            _insert_textbox(
                page,
                (150, 536, 806, 584),
                page_result.text_delta,
                fontsize=7.5,
                color=(0.86, 0.86, 0.88),
            )


def _validate_doc(doc: PdfRenderDocument, label: str) -> None:
    if doc.page_count <= 0:
        raise RuntimeError(f"El PDF {label} no tiene paginas.")


def _page_text(doc: PdfRenderDocument, page_index: int) -> str:
    if page_index < 0 or page_index >= doc.page_count:
        return ""
    return doc.extract_text(page_index)


def _normalize_text(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _page_size_changed(
    base_doc: PdfRenderDocument,
    compare_doc: PdfRenderDocument,
    page_index: int,
) -> bool:
    base_page = base_doc.page_info(page_index)
    compare_page = compare_doc.page_info(page_index)
    return (
        abs(base_page.width_pt - compare_page.width_pt) > 0.5
        or abs(base_page.height_pt - compare_page.height_pt) > 0.5
    )


def _render_page_image(
    document: PdfRenderDocument,
    page_index: int,
    dpi: int,
) -> Image.Image:
    scale = max(12, min(240, dpi)) / 72.0
    return document.render_page(page_index, scale=scale).to_pil()


def _normalized_pair(a: Image.Image, b: Image.Image) -> tuple[Image.Image, Image.Image]:
    a = a.convert("RGB")
    b = b.convert("RGB")
    if a.size == b.size:
        return a, b
    width = max(a.width, b.width)
    height = max(a.height, b.height)
    a_canvas = Image.new("RGB", (width, height), "white")
    b_canvas = Image.new("RGB", (width, height), "white")
    a_canvas.paste(a, (0, 0))
    b_canvas.paste(b, (0, 0))
    return a_canvas, b_canvas


def _diff_mask(a: Image.Image, b: Image.Image, threshold: int) -> Image.Image:
    a, b = _normalized_pair(a, b)
    threshold = max(0, min(255, int(threshold)))
    diff = ImageChops.difference(a, b).convert("L")
    return diff.point(lambda value: 255 if value > threshold else 0)


def _difference_ratio(a: Image.Image, b: Image.Image, threshold: int) -> float:
    mask = _diff_mask(a, b, threshold)
    changed = mask.histogram()[255]
    total = max(1, mask.width * mask.height)
    return changed / total


def _highlight_differences(base: Image.Image, compare: Image.Image, threshold: int) -> Image.Image:
    base, compare = _normalized_pair(base, compare)
    mask = _diff_mask(base, compare, threshold)
    alpha = mask.point(lambda value: 115 if value else 0)
    red_layer = Image.new("RGBA", compare.size, (239, 68, 68, 0))
    red_layer.putalpha(alpha)
    return Image.alpha_composite(compare.convert("RGBA"), red_layer)


def _text_delta_summary(base_text: str, compare_text: str, limit: int = 8) -> str:
    base_lines = _normalize_text(base_text).splitlines()
    compare_lines = _normalize_text(compare_text).splitlines()
    diff = list(difflib.unified_diff(base_lines, compare_lines, fromfile="base", tofile="revisado", lineterm=""))
    interesting = [line for line in diff if line and not line.startswith("@@")]
    return "\n".join(interesting[:limit]) or "Texto distinto sin lineas representativas."


def _page_detail_label(item: PdfComparePageResult) -> str:
    parts = [f"Pagina {item.page_index + 1}: {item.status_label}"]
    if item.size_changed:
        parts.append("tamano distinto")
    if item.visual_changed:
        parts.append(f"visual {item.change_ratio:.3%}")
    if item.text_changed:
        parts.append("texto distinto")
    if item.compare_exists and not item.base_exists:
        parts.append("agregada en revisado")
    if item.base_exists and not item.compare_exists:
        parts.append("faltante en revisado")
    return " · ".join(parts)


def _status_color(item: PdfComparePageResult) -> tuple[float, float, float]:
    if item.changed:
        return (0.95, 0.35, 0.35)
    return (0.48, 0.82, 0.54)


def _insert_text(
    page: Canvas,
    x: float,
    y: float,
    text: str,
    *,
    fontsize: float = 10,
    color: tuple[float, float, float] = (0.88, 0.88, 0.9),
) -> None:
    page.setFont("Helvetica", fontsize)
    page.setFillColorRGB(*color)
    page.drawString(x, _page_height(page) - y, text)


def _insert_textbox(
    page: Canvas,
    rect: tuple[float, float, float, float],
    text: str,
    *,
    fontsize: float = 10,
    color: tuple[float, float, float] = (0.82, 0.82, 0.86),
) -> None:
    x0, y0, x1, y1 = rect
    leading = fontsize * 1.35
    baseline = _page_height(page) - y0 - fontsize
    minimum = _page_height(page) - y1
    page.setFont("Helvetica", fontsize)
    page.setFillColorRGB(*color)
    for paragraph in text.splitlines() or [""]:
        for line in _wrap_text(paragraph, "Helvetica", fontsize, max(1.0, x1 - x0)):
            if baseline < minimum:
                return
            page.drawString(x0, baseline, line)
            baseline -= leading


def _draw_title(page: Canvas, text: str, x: float, y: float, *, size: float) -> None:
    _insert_text(page, x, y, text, fontsize=size, color=(0.96, 0.96, 0.98))


def _draw_placeholder(
    page: Canvas,
    rect: tuple[float, float, float, float],
    label: str,
) -> None:
    x0, y0, x1, y1 = rect
    page.setStrokeColorRGB(0.34, 0.34, 0.38)
    page.setFillColorRGB(0.09, 0.09, 0.11)
    page.setLineWidth(0.8)
    page.rect(x0, _page_height(page) - y1, x1 - x0, y1 - y0, stroke=1, fill=1)
    middle = y0 + (y1 - y0) / 2 - 8
    _insert_textbox(page, (x0 + 12, middle, x1 - 12, y1), label, fontsize=12, color=(0.72, 0.72, 0.76))


def _insert_pil_image(
    page: Canvas,
    image: Image.Image,
    bounds: tuple[float, float, float, float],
) -> None:
    rect = _fit_rect(image.size, bounds)
    x0, y0, x1, y1 = bounds
    page.setStrokeColorRGB(0.22, 0.22, 0.26)
    page.setLineWidth(0.6)
    page.rect(x0, _page_height(page) - y1, x1 - x0, y1 - y0, stroke=1, fill=0)
    rx0, ry0, rx1, ry1 = rect
    page.drawImage(
        ImageReader(image),
        rx0,
        _page_height(page) - ry1,
        width=rx1 - rx0,
        height=ry1 - ry0,
        preserveAspectRatio=False,
        mask="auto",
    )


def _fit_rect(
    size: tuple[int, int],
    bounds: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    width, height = max(1, size[0]), max(1, size[1])
    x0, y0, x1, y1 = bounds
    bounds_width = x1 - x0
    bounds_height = y1 - y0
    scale = min(bounds_width / width, bounds_height / height)
    out_w = width * scale
    out_h = height * scale
    left = x0 + (bounds_width - out_w) / 2
    top = y0 + (bounds_height - out_h) / 2
    return left, top, left + out_w, top + out_h


def _prepare_page(page: Canvas, width: float, height: float) -> None:
    page.setPageSize((width, height))
    page.setFillColorRGB(0.055, 0.059, 0.075)
    page.rect(0, 0, width, height, stroke=0, fill=1)


def _page_height(page: Canvas) -> float:
    return float(page._pagesize[1])


def _wrap_text(text: str, font: str, size: float, max_width: float) -> list[str]:
    if not text:
        return [""]
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines
