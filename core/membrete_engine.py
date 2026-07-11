"""Motor de membretado masivo de PDFs basado en PDFium, QPDF y ReportLab."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, List, Optional
import os
import uuid

import pikepdf
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from core.pdf_backend import PdfRenderDocument, Rect

from .margin_detector import MembreteMargins


@dataclass
class MembreteJob:
    """Un documento a membretar."""

    pdf_path: str
    output_path: str
    pages_to_letterhead: Optional[List[int]] = None
    preserve_unselected: bool = True
    preserve_source_background: bool = True


@dataclass
class MembreteJobResult:
    """Resultado de un MembreteJob. Compatible con GenericPdfViewer."""

    job: MembreteJob
    output_path: str = ""
    success: bool = True
    error: str = ""
    page_count: int = 0
    pages_letterheaded: int = 0
    pages_preserved: int = 0
    pages_omitted: int = 0
    meta_text: str = ""


_RENDER_DPI: float = 150.0


class MembreteEngine:
    """Aplica un membrete a cada página de los documentos indicados."""

    def run_batch(
        self,
        jobs: List[MembreteJob],
        letterhead_path: str,
        margins: MembreteMargins,
        progress: Optional[Callable[[int, int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> List[MembreteJobResult]:
        try:
            with PdfRenderDocument(letterhead_path) as letterhead:
                if letterhead.page_count <= 0:
                    raise RuntimeError("El membrete no tiene páginas.")
                lh_info = letterhead.page_info(0)
        except Exception as e:
            raise RuntimeError(f"No se pudo abrir el membrete: {e}") from e

        safe = Rect(
            margins.left_pt,
            margins.top_pt,
            lh_info.width_pt - margins.right_pt,
            lh_info.height_pt - margins.bottom_pt,
        )

        results: List[MembreteJobResult] = []
        total = len(jobs)
        for i, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(i, total, f"Membretando: {Path(job.pdf_path).name}")
            results.append(
                self._process_job(
                    job,
                    letterhead_path,
                    lh_info.width_pt,
                    lh_info.height_pt,
                    lh_info.rotation,
                    safe,
                    should_cancel=should_cancel,
                )
            )

        if progress and not (should_cancel and should_cancel()):
            progress(total, total, "Membretado completado")
        return results

    def _process_job(
        self,
        job: MembreteJob,
        letterhead_path: str,
        lh_w: float,
        lh_h: float,
        lh_rotation: int,
        safe: Rect,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> MembreteJobResult:
        source = Path(job.pdf_path).resolve()
        letterhead = Path(letterhead_path).resolve()
        output = Path(job.output_path)
        try:
            if output.resolve() in {source, letterhead}:
                raise ValueError("La salida no puede sobrescribir un PDF de origen.")

            with PdfRenderDocument(source) as render_doc:
                page_count = render_doc.page_count
                if page_count <= 0:
                    raise RuntimeError("El PDF no tiene páginas.")
                page_infos = [render_doc.page_info(index) for index in range(page_count)]
                selected = _normalized_page_selection(job.pages_to_letterhead, page_count)

                with ExitStack() as stack:
                    src_pdf = stack.enter_context(_open_pdf(source))
                    lh_pdf = stack.enter_context(_open_pdf(letterhead))
                    out_pdf = stack.enter_context(pikepdf.Pdf.new())
                    temp_dir = Path(stack.enter_context(TemporaryDirectory(
                        prefix="pdflex-membrete-"
                    )))

                    letterheaded = 0
                    preserved = 0
                    omitted = 0

                    for page_idx, info in enumerate(page_infos):
                        if should_cancel and should_cancel():
                            raise _CancelledError()

                        should_letterhead = selected is None or page_idx in selected
                        if not should_letterhead:
                            if job.preserve_unselected:
                                out_pdf.add_pages_from(
                                    src_pdf,
                                    pages=[page_idx],
                                    forms="preserve",
                                )
                                preserved += 1
                            else:
                                omitted += 1
                            continue

                        out_pdf.add_blank_page(page_size=(lh_w, lh_h))
                        dest_page = out_pdf.pages[-1]
                        full_rect = Rect(0.0, 0.0, lh_w, lh_h)
                        _place_letterhead(
                            dest_page,
                            lh_pdf,
                            render_doc_path=letterhead,
                            page_width=lh_w,
                            page_height=lh_h,
                            rotation=lh_rotation,
                            temp_dir=temp_dir,
                        )

                        target = _fit_rect(safe, info.width_pt, info.height_pt)
                        if job.preserve_source_background:
                            _paint_white_rect(dest_page, _to_pdf_rect(target, lh_h))

                        if info.rotation == 0 and not _page_has_annotations(src_pdf.pages[page_idx]):
                            dest_page.add_overlay(
                                src_pdf.pages[page_idx],
                                _to_pdf_rect(target, lh_h),
                            )
                        else:
                            overlay_path = temp_dir / f"source-{page_idx}.pdf"
                            _write_raster_overlay_pdf(
                                render_doc,
                                page_idx,
                                overlay_path,
                                page_width=lh_w,
                                page_height=lh_h,
                                target=target,
                                preserve_background=job.preserve_source_background,
                            )
                            with _open_pdf(overlay_path) as overlay_pdf:
                                dest_page.add_overlay(overlay_pdf.pages[0])
                        letterheaded += 1

                    if len(out_pdf.pages) <= 0:
                        raise RuntimeError("La selección de páginas no produjo salida.")

                    output.parent.mkdir(parents=True, exist_ok=True)
                    _save_atomic(out_pdf, output)
                    n_pages = len(out_pdf.pages)

        except _CancelledError:
            return MembreteJobResult(
                job=job,
                output_path="",
                success=False,
                error="Operación cancelada.",
            )
        except Exception as e:
            return MembreteJobResult(job=job, output_path="", success=False, error=str(e))

        with PdfRenderDocument(output) as verify:
            if verify.page_count != n_pages:
                return MembreteJobResult(
                    job=job,
                    output_path="",
                    success=False,
                    error=(
                        f"El resultado tiene {verify.page_count} páginas; "
                        f"se esperaban {n_pages}."
                    ),
                )

        return MembreteJobResult(
            job=job,
            output_path=job.output_path,
            success=True,
            page_count=n_pages,
            pages_letterheaded=letterheaded,
            pages_preserved=preserved,
            pages_omitted=omitted,
            meta_text=_result_meta_text(letterheaded, preserved, omitted),
        )


def _fit_rect(container: Rect, src_w: float, src_h: float) -> Rect:
    """Encaja src_w x src_h dentro de container conservando aspecto."""
    if src_w <= 0 or src_h <= 0:
        return container
    scale = min(container.width / src_w, container.height / src_h)
    fw = src_w * scale
    fh = src_h * scale
    x0 = container.x0 + (container.width - fw) / 2.0
    y0 = container.y0 + (container.height - fh) / 2.0
    return Rect(x0, y0, x0 + fw, y0 + fh)


def _place_letterhead(
    dest_page: pikepdf.Page,
    lh_pdf: pikepdf.Pdf,
    *,
    render_doc_path: Path,
    page_width: float,
    page_height: float,
    rotation: int,
    temp_dir: Path,
) -> None:
    if rotation == 0:
        dest_page.add_overlay(
            lh_pdf.pages[0],
            _to_pdf_rect(Rect(0.0, 0.0, page_width, page_height), page_height),
        )
        return

    overlay_path = temp_dir / "letterhead-raster.pdf"
    with PdfRenderDocument(render_doc_path) as document:
        rendered = document.render_page(
            0,
            scale=_RENDER_DPI / 72.0,
            include_annotations=True,
        )
    _write_image_pdf(
        rendered.to_pil(),
        overlay_path,
        page_width=page_width,
        page_height=page_height,
        target=Rect(0.0, 0.0, page_width, page_height),
    )
    with _open_pdf(overlay_path) as overlay_pdf:
        dest_page.add_overlay(overlay_pdf.pages[0])


def _write_raster_overlay_pdf(
    document: PdfRenderDocument,
    page_index: int,
    output_path: Path,
    *,
    page_width: float,
    page_height: float,
    target: Rect,
    preserve_background: bool,
) -> None:
    rendered = document.render_page(
        page_index,
        scale=_RENDER_DPI / 72.0,
        include_annotations=True,
        transparent_background=not preserve_background,
    )
    _write_image_pdf(
        rendered.to_pil(),
        output_path,
        page_width=page_width,
        page_height=page_height,
        target=target,
    )


def _write_image_pdf(
    image,
    output_path: Path,
    *,
    page_width: float,
    page_height: float,
    target: Rect,
) -> None:
    canvas = Canvas(str(output_path), pagesize=(page_width, page_height), pageCompression=1)
    canvas.drawImage(
        ImageReader(image),
        target.x0,
        page_height - target.y1,
        width=target.width,
        height=target.height,
        preserveAspectRatio=False,
        mask="auto",
    )
    canvas.showPage()
    canvas.save()


def _paint_white_rect(page: pikepdf.Page, rect: pikepdf.Rectangle) -> None:
    width = float(rect.urx) - float(rect.llx)
    height = float(rect.ury) - float(rect.lly)
    content = (
        "q 1 1 1 rg "
        f"{float(rect.llx):.6f} {float(rect.lly):.6f} "
        f"{width:.6f} {height:.6f} re f Q\n"
    ).encode("ascii")
    page.contents_add(content)


def _to_pdf_rect(rect: Rect, page_height: float) -> pikepdf.Rectangle:
    return pikepdf.Rectangle(rect.x0, page_height - rect.y1, rect.x1, page_height - rect.y0)


def _page_has_annotations(page: pikepdf.Page) -> bool:
    try:
        annots = page.obj.get("/Annots", [])
        return bool(annots)
    except Exception:
        return False


def _open_pdf(path: str | Path) -> pikepdf.Pdf:
    return pikepdf.Pdf.open(path, suppress_warnings=True, attempt_recovery=True)


def _save_atomic(document: pikepdf.Pdf, output: Path) -> None:
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        document.save(
            temporary,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )
        os.replace(temporary, output)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _normalized_page_selection(
    page_indexes: Optional[List[int]],
    page_count: int,
) -> Optional[set[int]]:
    if page_indexes is None:
        return None
    return {
        index
        for index in page_indexes
        if 0 <= int(index) < page_count
    }


def _result_meta_text(letterheaded: int, preserved: int, omitted: int) -> str:
    parts = [
        f"{letterheaded} membretada" + ("" if letterheaded == 1 else "s")
    ]
    if preserved:
        parts.append(f"{preserved} sin cambios")
    if omitted:
        parts.append(f"{omitted} omitida" + ("" if omitted == 1 else "s"))
    return " · ".join(parts)


def parse_membrete_page_scope(mode: str, text: str, page_count: int) -> List[int]:
    """Parsea el alcance de membretado y devuelve índices 0-based en orden natural."""
    if page_count <= 0:
        raise ValueError("El PDF no tiene páginas.")

    clean_mode = (mode or "all").strip().lower()
    all_pages = list(range(page_count))

    if clean_mode in {"all", "todas", "todo"}:
        return all_pages
    if clean_mode in {"even", "pares", "par"}:
        return [idx for idx in all_pages if (idx + 1) % 2 == 0]
    if clean_mode in {"odd", "impares", "impar"}:
        return [idx for idx in all_pages if (idx + 1) % 2 == 1]

    if clean_mode in {"include", "custom", "solo"}:
        pages = _parse_page_spec(text, page_count)
        if not pages:
            raise ValueError("El rango no contiene páginas para membretar.")
        return pages

    if clean_mode in {"exclude", "except", "excepto"}:
        excluded = set(_parse_page_spec(text, page_count))
        remaining = [idx for idx in all_pages if idx not in excluded]
        return remaining

    raise ValueError("Modo de páginas no reconocido.")


def compact_page_indexes(page_indexes: List[int]) -> str:
    if not page_indexes:
        return "Ninguna"
    pages = sorted({idx + 1 for idx in page_indexes})
    ranges: list[str] = []
    start = prev = pages[0]
    for page in pages[1:]:
        if page == prev + 1:
            prev = page
            continue
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = page
    ranges.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(ranges)


def _parse_page_spec(text: str, page_count: int) -> List[int]:
    raw = (text or "").strip().lower()
    if not raw:
        raise ValueError("Escribe un rango de páginas.")
    if raw in {"todas", "todo", "all", "*"}:
        return list(range(page_count))
    if raw in {"pares", "par", "even"}:
        return [idx for idx in range(page_count) if (idx + 1) % 2 == 0]
    if raw in {"impares", "impar", "odd"}:
        return [idx for idx in range(page_count) if (idx + 1) % 2 == 1]

    selected: set[int] = set()
    tokens = [
        token.strip()
        for chunk in raw.replace(";", ",").split(",")
        for token in chunk.split()
        if token.strip()
    ]
    for token in tokens:
        if "-" in token:
            left, right = token.split("-", 1)
            start = _parse_page_token(left, page_count, default=1)
            end = _parse_page_token(right, page_count, default=page_count)
            if start > end:
                raise ValueError(f"Rango invertido: {token}")
            selected.update(range(start - 1, end))
        else:
            page_num = _parse_page_token(token, page_count)
            selected.add(page_num - 1)

    if not selected:
        raise ValueError("El rango no contiene páginas válidas.")
    return sorted(selected)


def _parse_page_token(
    token: str,
    page_count: int,
    *,
    default: int | None = None,
) -> int:
    clean = token.strip().lower()
    if not clean:
        if default is None:
            raise ValueError("Página vacía en el rango.")
        return default
    if clean in {"final", "fin", "ultima", "última", "last"}:
        return page_count
    if not clean.isdigit():
        raise ValueError(f"Página inválida: {token}")
    value = int(clean)
    if value < 1 or value > page_count:
        raise ValueError(f"Página fuera de rango: {token}")
    return value


class _CancelledError(Exception):
    pass
