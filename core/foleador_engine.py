"""Motor de foliado masivo mediante overlays vectoriales QPDF."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, List, Optional, Tuple

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from core.pdf_analyzer import PageAnalysis, PdfAnalyzer
from core.pdf_backend import PdfRenderDocument, Rect, apply_page_overlays
from .folio_format import FolioConfig, render


RGBColor = Tuple[float, float, float]

_FONT_VARIANTS: dict[tuple[str, bool, bool], str] = {
    ("helv", False, False): "helv", ("helv", True, False): "hebo",
    ("helv", False, True): "heit", ("helv", True, True): "hebi",
    ("tiro", False, False): "tiro", ("tiro", True, False): "tibo",
    ("tiro", False, True): "tiit", ("tiro", True, True): "tibi",
    ("cour", False, False): "cour", ("cour", True, False): "cobo",
    ("cour", False, True): "coit", ("cour", True, True): "cobi",
}

_REPORTLAB_FONTS = {
    "helv": "Helvetica", "hebo": "Helvetica-Bold",
    "heit": "Helvetica-Oblique", "hebi": "Helvetica-BoldOblique",
    "tiro": "Times-Roman", "tibo": "Times-Bold",
    "tiit": "Times-Italic", "tibi": "Times-BoldItalic",
    "cour": "Courier", "cobo": "Courier-Bold",
    "coit": "Courier-Oblique", "cobi": "Courier-BoldOblique",
}


def _text_width(text: str, fontname: str, fontsize: float) -> float:
    return float(stringWidth(text, _REPORTLAB_FONTS.get(fontname, "Helvetica"), fontsize))


@dataclass
class FolioStyle:
    fontbase: str = "helv"
    fontsize: float = 10.0
    bold: bool = False
    italic: bool = False
    color: RGBColor = (0.0, 0.0, 0.0)
    bg_color: RGBColor | None = None

    @property
    def fontname(self) -> str:
        return _FONT_VARIANTS.get((self.fontbase, self.bold, self.italic), self.fontbase)

    @property
    def reportlab_fontname(self) -> str:
        return _REPORTLAB_FONTS.get(self.fontname, "Helvetica")


@dataclass
class FolioJob:
    pdf_path: str
    output_path: str
    x_norm: float
    y_norm: float
    width_norm: float
    height_norm: float
    ref_page_height_pt: float = 842.0
    ref_page_width_pt: float = 595.0
    smart_position: bool = True


@dataclass
class FolioPageResult:
    page_index: int
    folio_text: str
    success: bool = True
    error: str = ""


@dataclass
class FolioJobResult:
    job: FolioJob
    output_path: str
    page_results: List[FolioPageResult] = field(default_factory=list)
    success: bool = True
    error: str = ""


class FoleadorEngine:
    """Aplica números de folio conservando texto, formularios y rotaciones."""

    def run_batch(
        self,
        jobs: List[FolioJob],
        config: FolioConfig,
        style: FolioStyle,
        progress: Optional[Callable[[int, int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> List[FolioJobResult]:
        results: List[FolioJobResult] = []
        number = config.start
        total_docs = len(jobs)
        for doc_index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if config.scope == "per_doc":
                number = config.start
            if progress:
                progress(doc_index, total_docs, f"Foliando: {Path(job.pdf_path).name}")
            result, pages_foliated = self._process_job(
                job, config, style, number, should_cancel=should_cancel
            )
            results.append(result)
            if result.success and config.scope == "continuous":
                number += pages_foliated * config.step
        if progress and not (should_cancel and should_cancel()):
            progress(total_docs, total_docs, "Completado")
        return results

    def _process_job(
        self,
        job: FolioJob,
        config: FolioConfig,
        style: FolioStyle,
        start_n: int,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> tuple[FolioJobResult, int]:
        source = Path(job.pdf_path)
        output = Path(job.output_path)
        if not source.exists():
            return FolioJobResult(job, "", success=False, error="El PDF no existe."), 0
        if source.resolve() == output.resolve():
            return (
                FolioJobResult(job, "", success=False, error="La salida no puede sobrescribir el origen."),
                0,
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        page_results: List[FolioPageResult] = []
        number = start_n
        try:
            with PdfRenderDocument(source) as document:
                total_pages = document.page_count
                doc_name = source.stem
                with TemporaryDirectory(prefix="pdflex-folio-") as temp_dir:
                    overlay_path = Path(temp_dir) / "overlay.pdf"
                    canvas = Canvas(str(overlay_path), pagesize=(1, 1), pageCompression=1)
                    mapping: dict[int, int] = {}
                    overlay_index = 0
                    analyzer = PdfAnalyzer()
                    for page_index in range(total_pages):
                        if should_cancel and should_cancel():
                            raise _CancelledError()
                        if config.skip_first_page and page_index == 0:
                            continue
                        if config.only_pages is not None and page_index + 1 not in config.only_pages:
                            continue
                        folio_text = render(config.pattern, number, doc_name, total_pages)
                        info = document.page_info(page_index)
                        canvas.setPageSize((info.width_pt, info.height_pt))
                        try:
                            analysis = (
                                analyzer.analyze_page(document, page_index)
                                if job.smart_position
                                else None
                            )
                            _draw_folio(canvas, info.width_pt, info.height_pt, analysis, job, folio_text, style)
                            page_results.append(FolioPageResult(page_index, folio_text))
                        except Exception as exc:
                            page_results.append(
                                FolioPageResult(page_index, folio_text, False, str(exc))
                            )
                        canvas.showPage()
                        mapping[page_index] = overlay_index
                        overlay_index += 1
                        number += config.step
                    canvas.save()
                    apply_page_overlays(source, overlay_path, mapping, output)
        except _CancelledError:
            return FolioJobResult(job, "", page_results, False, "Operación cancelada."), len(page_results)
        except Exception as exc:
            return FolioJobResult(job, "", page_results, False, str(exc)), len(page_results)

        failed = [page for page in page_results if not page.success]
        error = (
            f"No se pudieron foliar {len(failed)} página{'s' if len(failed) != 1 else ''}."
            if failed else ""
        )
        return FolioJobResult(job, str(output), page_results, not failed, error), len(page_results)


def _draw_folio(
    canvas: Canvas,
    page_width: float,
    page_height: float,
    analysis: PageAnalysis | None,
    job: FolioJob,
    text: str,
    style: FolioStyle,
) -> None:
    if page_width <= 0 or page_height <= 0:
        raise ValueError("Dimensiones de página inválidas.")
    ref_long = max(job.ref_page_height_pt, job.ref_page_width_pt, 1.0)
    scale = max(0.33, min(4.0, max(page_width, page_height) / ref_long))
    fontsize = max(4.0, style.fontsize * scale)
    box_width = max(4.0, job.width_norm * page_width)
    box_height = max(2.0, job.height_norm * page_height)
    text_width = _text_width(text, style.fontname, fontsize)
    if text_width > box_width * 0.92:
        fontsize = max(4.0, fontsize * (box_width * 0.92) / max(1.0, text_width))
        text_width = _text_width(text, style.fontname, fontsize)

    edge = max(2.0, min(page_width, page_height) * 0.004)
    half_width, half_height = box_width / 2.0, box_height / 2.0
    cx_low = max(half_width + edge, text_width / 2.0 + edge)
    cx_high = min(page_width - half_width - edge, page_width - text_width / 2.0 - edge)
    cy_low = half_height + edge
    cy_high = page_height - half_height - edge
    if cx_low > cx_high:
        cx_low = cx_high = page_width / 2.0
    if cy_low > cy_high:
        cy_low = cy_high = page_height / 2.0
    cx = max(cx_low, min(cx_high, job.x_norm * page_width))
    cy = max(cy_low, min(cy_high, job.y_norm * page_height))
    if analysis is not None:
        cx, cy = _find_clean_position(analysis, cx, cy, box_width, box_height)

    if style.bg_color is not None:
        canvas.setFillColorRGB(*style.bg_color)
        canvas.rect(
            cx - half_width,
            page_height - (cy + half_height),
            box_width,
            box_height,
            stroke=0,
            fill=1,
        )
    canvas.setFillColorRGB(*style.color)
    canvas.setFont(style.reportlab_fontname, fontsize)
    canvas.drawString(
        max(edge, min(page_width - text_width - edge, cx - text_width / 2.0)),
        page_height - (cy + fontsize * 0.36),
        text,
    )


def _find_clean_position(
    analysis: PageAnalysis,
    cx: float,
    cy: float,
    box_width: float,
    box_height: float,
) -> tuple[float, float]:
    if not analysis.text_blocks:
        return cx, cy
    half_width, half_height = box_width / 2.0, box_height / 2.0
    step = max(2.0, analysis.height * 0.004)
    steps = int(max(12.0, analysis.height * 0.03) / step)

    def clean(y: float) -> bool:
        if y - half_height < 0 or y + half_height > analysis.height:
            return False
        probe = Rect(
            cx - half_width - 1,
            y - half_height - 1,
            cx + half_width + 1,
            y + half_height + 1,
        )
        return not analysis.intersects_text(probe, padding=0)

    if clean(cy):
        return cx, cy
    for index in range(1, steps + 1):
        candidate = cy - index * step
        if clean(candidate):
            return cx, candidate
    return cx, cy


class _CancelledError(Exception):
    pass
