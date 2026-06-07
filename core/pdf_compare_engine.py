"""Visual and textual comparison engine for PDF pairs."""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Callable, List
import difflib
import re

import fitz
from PIL import Image, ImageChops


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

        base_doc: fitz.Document | None = None
        compare_doc: fitz.Document | None = None
        try:
            base_doc = fitz.open(str(base_path))
            compare_doc = fitz.open(str(compare_path))
            _validate_doc(base_doc, "base")
            _validate_doc(compare_doc, "a comparar")

            total_pages = max(base_doc.page_count, compare_doc.page_count)
            page_results: list[PdfComparePageResult] = []
            for page_index in range(total_pages):
                if should_cancel and should_cancel():
                    break
                page_results.append(self._compare_page(base_doc, compare_doc, page_index, job.options))

            result = PdfCompareResult(
                job=job,
                output_path=str(output),
                success=True,
                total_pages=total_pages,
                changed_pages=sum(1 for item in page_results if item.changed),
                visual_changed_pages=sum(1 for item in page_results if item.visual_changed or item.size_changed),
                text_changed_pages=sum(1 for item in page_results if item.text_changed),
                added_pages=sum(1 for item in page_results if item.compare_exists and not item.base_exists),
                removed_pages=sum(1 for item in page_results if item.base_exists and not item.compare_exists),
                page_results=page_results,
            )
            self._write_report(base_doc, compare_doc, result)
            return result
        except Exception as exc:
            return PdfCompareResult(job=job, success=False, error=str(exc))
        finally:
            for doc in (base_doc, compare_doc):
                if doc is not None:
                    try:
                        doc.close()
                    except Exception:
                        pass

    def _compare_page(
        self,
        base_doc: fitz.Document,
        compare_doc: fitz.Document,
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

        base_page = base_doc[page_index]
        compare_page = compare_doc[page_index]
        size_changed = _page_size_changed(base_page, compare_page)
        base_image = _render_page_image(base_page, options.dpi)
        compare_image = _render_page_image(compare_page, options.dpi)
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
        base_doc: fitz.Document,
        compare_doc: fitz.Document,
        result: PdfCompareResult,
    ) -> None:
        output = Path(result.output_path)
        report = fitz.open()
        try:
            self._add_summary_page(report, result)
            detail_pages = [
                item for item in result.page_results
                if item.changed or result.job.options.include_equal_pages
            ]
            for page_result in detail_pages:
                self._add_detail_page(report, base_doc, compare_doc, result, page_result)
            report.save(
                str(output),
                garbage=4,
                clean=True,
                deflate=True,
                deflate_images=True,
                deflate_fonts=True,
                use_objstms=1,
            )
        finally:
            report.close()

    def _add_summary_page(self, report: fitz.Document, result: PdfCompareResult) -> None:
        page = report.new_page(width=595, height=842)
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
        _insert_textbox(page, fitz.Rect(36, 82, 559, 240), "\n".join(lines), fontsize=10.5)

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
        report: fitz.Document,
        base_doc: fitz.Document,
        compare_doc: fitz.Document,
        result: PdfCompareResult,
        page_result: PdfComparePageResult,
    ) -> None:
        page = report.new_page(width=842, height=595)
        page_no = page_result.page_index + 1
        _draw_title(page, f"Pagina {page_no} - {page_result.status_label}", 36, 40, size=17)
        _insert_textbox(
            page,
            fitz.Rect(36, 58, 806, 92),
            _page_detail_label(page_result),
            fontsize=9.5,
            color=_status_color(page_result),
        )

        left_bounds = fitz.Rect(36, 126, 405, 520)
        right_bounds = fitz.Rect(437, 126, 806, 520)
        _insert_text(page, left_bounds.x0, 112, "Base", fontsize=10, color=(0.88, 0.88, 0.9))
        _insert_text(page, right_bounds.x0, 112, "Revisado con diferencias resaltadas", fontsize=10, color=(0.88, 0.88, 0.9))

        if page_result.base_exists:
            base_img = _render_page_image(base_doc[page_result.page_index], result.job.options.dpi)
            _insert_pil_image(page, base_img, left_bounds)
        else:
            _draw_placeholder(page, left_bounds, "No existe en PDF base")

        if page_result.compare_exists:
            compare_img = _render_page_image(compare_doc[page_result.page_index], result.job.options.dpi)
            if page_result.base_exists:
                base_img = _render_page_image(base_doc[page_result.page_index], result.job.options.dpi)
                compare_img = _highlight_differences(base_img, compare_img, result.job.options.pixel_threshold)
            _insert_pil_image(page, compare_img, right_bounds)
        else:
            _draw_placeholder(page, right_bounds, "No existe en PDF revisado")

        if page_result.text_delta:
            _draw_title(page, "Diferencia textual", 36, 548, size=10)
            _insert_textbox(
                page,
                fitz.Rect(150, 536, 806, 584),
                page_result.text_delta,
                fontsize=7.5,
                color=(0.86, 0.86, 0.88),
            )


def _validate_doc(doc: fitz.Document, label: str) -> None:
    if doc.is_encrypted:
        raise RuntimeError(f"El PDF {label} esta protegido o cifrado.")
    if doc.page_count <= 0:
        raise RuntimeError(f"El PDF {label} no tiene paginas.")


def _page_text(doc: fitz.Document, page_index: int) -> str:
    if page_index < 0 or page_index >= doc.page_count:
        return ""
    return doc[page_index].get_text("text") or ""


def _normalize_text(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _page_size_changed(base_page: fitz.Page, compare_page: fitz.Page) -> bool:
    return (
        abs(base_page.rect.width - compare_page.rect.width) > 0.5
        or abs(base_page.rect.height - compare_page.rect.height) > 0.5
    )


def _render_page_image(page: fitz.Page, dpi: int) -> Image.Image:
    scale = max(12, min(240, dpi)) / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


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
    page: fitz.Page,
    x: float,
    y: float,
    text: str,
    *,
    fontsize: float = 10,
    color: tuple[float, float, float] = (0.88, 0.88, 0.9),
) -> None:
    page.insert_text((x, y), text, fontsize=fontsize, fontname="helv", color=color)


def _insert_textbox(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    fontsize: float = 10,
    color: tuple[float, float, float] = (0.82, 0.82, 0.86),
) -> None:
    page.insert_textbox(rect, text, fontsize=fontsize, fontname="helv", color=color)


def _draw_title(page: fitz.Page, text: str, x: float, y: float, *, size: float) -> None:
    _insert_text(page, x, y, text, fontsize=size, color=(0.96, 0.96, 0.98))


def _draw_placeholder(page: fitz.Page, rect: fitz.Rect, label: str) -> None:
    page.draw_rect(rect, color=(0.34, 0.34, 0.38), fill=(0.09, 0.09, 0.11), width=0.8)
    _insert_textbox(page, rect + (0, rect.height / 2 - 12, 0, 0), label, fontsize=12, color=(0.72, 0.72, 0.76))


def _insert_pil_image(page: fitz.Page, image: Image.Image, bounds: fitz.Rect) -> None:
    rect = _fit_rect(image.size, bounds)
    page.draw_rect(bounds, color=(0.22, 0.22, 0.26), width=0.6)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(rect, stream=buffer.getvalue(), keep_proportion=True)


def _fit_rect(size: tuple[int, int], bounds: fitz.Rect) -> fitz.Rect:
    width, height = max(1, size[0]), max(1, size[1])
    scale = min(bounds.width / width, bounds.height / height)
    out_w = width * scale
    out_h = height * scale
    x0 = bounds.x0 + (bounds.width - out_w) / 2
    y0 = bounds.y0 + (bounds.height - out_h) / 2
    return fitz.Rect(x0, y0, x0 + out_w, y0 + out_h)
