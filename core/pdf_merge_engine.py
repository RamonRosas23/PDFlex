"""Robust PDF merge engine with post-save validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List
import io

import fitz


ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]

_COMPARE_MAX_SIDE = 360.0
_MAX_AVG_DIFF = 0.20
_MAX_CHANGED_RATIO = 0.001


@dataclass
class PdfMergeOptions:
    blank_between: bool = False
    add_bookmarks: bool = False
    validate_visual: bool = True


@dataclass
class PdfMergeSourceReport:
    path: str
    page_count: int
    inserted_pages: int
    start_page: int
    repaired_on_open: bool = False
    used_pagewise_fallback: bool = False
    normalized_before_insert: bool = False
    used_raster_fallback: bool = False


@dataclass
class PdfMergeResult:
    output_path: str
    success: bool = False
    error: str = ""
    total_pages: int = 0
    expected_pages: int = 0
    source_count: int = 0
    blank_pages: int = 0
    sources: List[PdfMergeSourceReport] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def meta_text(self) -> str:
        if not self.success:
            return self.error
        parts = [
            f"validado contra {self.expected_pages} esperadas",
            f"{self.source_count} documentos",
        ]
        if self.blank_pages:
            parts.append(f"{self.blank_pages} blancas")
        if any(src.repaired_on_open for src in self.sources):
            parts.append("normalizo PDFs reparados")
        if any(src.used_raster_fallback for src in self.sources):
            parts.append("rescate visual")
        if self.warnings:
            parts.append("fallback seguro")
        return " · ".join(parts)


class PdfMergeEngine:
    """Merge PDFs and reject outputs that lose pages or visible content."""

    def run(
        self,
        pdf_paths: Iterable[str],
        output_path: str,
        options: PdfMergeOptions | None = None,
        *,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> PdfMergeResult:
        opts = options or PdfMergeOptions()
        paths = [str(path) for path in pdf_paths if path]
        if len(paths) < 2:
            return PdfMergeResult(
                output_path=output_path,
                success=False,
                error="Agrega al menos 2 archivos PDF para unir.",
                source_count=len(paths),
            )

        errors: list[str] = []
        for mode in ("bulk", "pagewise", "normalized_pagewise", "raster"):
            try:
                _remove_partial(Path(output_path))
                result = self._run_attempt(
                    paths,
                    output_path,
                    opts,
                    mode=mode,
                    progress=progress,
                    should_cancel=should_cancel,
                )
                if mode == "pagewise":
                    result.warnings.append(
                        "La copia completa no paso la verificacion; se rehizo pagina por pagina."
                    )
                    for source in result.sources:
                        source.used_pagewise_fallback = True
                elif mode == "normalized_pagewise":
                    result.warnings.append(
                        "Se normalizaron los PDFs antes de unir porque las copias directas no pasaron la verificacion."
                    )
                    for source in result.sources:
                        source.used_pagewise_fallback = True
                        source.normalized_before_insert = True
                elif mode == "raster":
                    result.warnings.append(
                        "Se uso rescate visual: algunas paginas se reconstruyeron como imagen para evitar perdida de contenido."
                    )
                    for source in result.sources:
                        source.used_raster_fallback = True
                return result
            except _CancelledError:
                _remove_partial(Path(output_path))
                return PdfMergeResult(
                    output_path=output_path,
                    success=False,
                    error="Operacion cancelada.",
                    source_count=len(paths),
                )
            except Exception as exc:  # noqa: BLE001 - returned as user-facing result
                errors.append(f"{_mode_label(mode)}: {exc}")

        _remove_partial(Path(output_path))
        detail = " | ".join(errors)
        return PdfMergeResult(
            output_path=output_path,
            success=False,
            error=f"No se pudo generar un PDF unido valido. {detail}",
            source_count=len(paths),
        )

    def _run_attempt(
        self,
        paths: list[str],
        output_path: str,
        options: PdfMergeOptions,
        *,
        mode: str,
        progress: ProgressCallback | None,
        should_cancel: CancelCallback | None,
    ) -> PdfMergeResult:
        out_doc = fitz.open()
        reports: list[PdfMergeSourceReport] = []
        toc_entries: list[list[int | str]] = []
        expected_pages = 0
        blank_pages = 0
        total = len(paths)

        try:
            for index, raw_path in enumerate(paths):
                _raise_if_cancelled(should_cancel)

                path = Path(raw_path)
                if not path.exists():
                    raise RuntimeError(f"{path.name}: el archivo no existe.")

                if options.blank_between and index > 0:
                    ref_rect = (
                        out_doc[-1].rect
                        if out_doc.page_count > 0
                        else fitz.Rect(0, 0, 595, 842)
                    )
                    out_doc.new_page(width=ref_rect.width, height=ref_rect.height)
                    expected_pages += 1
                    blank_pages += 1

                if progress:
                    progress(index + 1, total, f"Uniendo {path.name}...")

                src_doc, repaired = _open_source(
                    path,
                    force_normalize=mode == "normalized_pagewise",
                )
                try:
                    _assert_source_readable(src_doc, path)
                    start_page = out_doc.page_count + 1
                    before = out_doc.page_count
                    if mode == "bulk":
                        _insert_bulk(out_doc, src_doc)
                    elif mode in {"pagewise", "normalized_pagewise"}:
                        _insert_pagewise(out_doc, src_doc)
                    else:
                        _insert_rasterized(out_doc, src_doc)
                    inserted = out_doc.page_count - before
                    if inserted != src_doc.page_count:
                        _trim_to_page_count(out_doc, before)
                        raise RuntimeError(
                            f"{path.name}: se insertaron {inserted} paginas; "
                            f"se esperaban {src_doc.page_count}."
                        )

                    reports.append(
                        PdfMergeSourceReport(
                            path=str(path),
                            page_count=src_doc.page_count,
                            inserted_pages=inserted,
                            start_page=start_page,
                            repaired_on_open=repaired,
                            normalized_before_insert=mode == "normalized_pagewise",
                            used_raster_fallback=mode == "raster",
                        )
                    )
                    expected_pages += src_doc.page_count
                    if options.add_bookmarks:
                        toc_entries.append([1, path.stem, start_page])
                finally:
                    src_doc.close()

            _raise_if_cancelled(should_cancel)
            if out_doc.page_count != expected_pages:
                raise RuntimeError(
                    f"El documento en memoria tiene {out_doc.page_count} paginas; "
                    f"se esperaban {expected_pages}."
                )

            if options.add_bookmarks and toc_entries:
                out_doc.set_toc(toc_entries)

            if progress:
                progress(total, total, "Guardando y validando...")
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            _save_merged(out_doc, output, mode=mode)
        finally:
            out_doc.close()

        verified_pages = _verify_output(
            Path(output_path),
            expected_pages,
            reports,
            validate_visual=options.validate_visual and mode != "raster",
        )
        return PdfMergeResult(
            output_path=output_path,
            success=True,
            total_pages=verified_pages,
            expected_pages=expected_pages,
            source_count=len(paths),
            blank_pages=blank_pages,
            sources=reports,
        )


def _open_source(path: Path, *, force_normalize: bool = False) -> tuple[fitz.Document, bool]:
    doc = fitz.open(str(path))
    repaired = bool(getattr(doc, "is_repaired", False))
    if (repaired or force_normalize) and not (doc.needs_pass or doc.is_encrypted):
        buffer = io.BytesIO()
        doc.save(buffer, garbage=4, deflate=True, clean=True)
        doc.close()
        doc = fitz.open(stream=buffer.getvalue(), filetype="pdf")
    return doc, repaired


def _assert_source_readable(doc: fitz.Document, path: Path) -> None:
    if doc.needs_pass or doc.is_encrypted:
        raise RuntimeError(f"{path.name}: el PDF esta protegido o cifrado.")
    if doc.page_count <= 0:
        raise RuntimeError(f"{path.name}: el PDF no tiene paginas.")


def _insert_bulk(out_doc: fitz.Document, src_doc: fitz.Document) -> None:
    out_doc.insert_pdf(src_doc, links=1, annots=1, widgets=1)


def _insert_pagewise(out_doc: fitz.Document, src_doc: fitz.Document) -> None:
    for page_index in range(src_doc.page_count):
        out_doc.insert_pdf(
            src_doc,
            from_page=page_index,
            to_page=page_index,
            links=1,
            annots=1,
            widgets=1,
        )


def _insert_rasterized(out_doc: fitz.Document, src_doc: fitz.Document) -> None:
    scale = 150.0 / 72.0
    matrix = fitz.Matrix(scale, scale)
    for page_index in range(src_doc.page_count):
        src_page = src_doc[page_index]
        pix = src_page.get_pixmap(matrix=matrix, alpha=False, annots=True)
        out_page = out_doc.new_page(
            width=src_page.rect.width,
            height=src_page.rect.height,
        )
        out_page.insert_image(out_page.rect, pixmap=pix)


def _save_merged(doc: fitz.Document, output: Path, *, mode: str) -> None:
    doc.save(
        str(output),
        garbage=4 if mode in {"bulk", "normalized_pagewise"} else 2,
        deflate=True,
        encryption=fitz.PDF_ENCRYPT_NONE,
    )


def _verify_output(
    output: Path,
    expected_pages: int,
    sources: list[PdfMergeSourceReport],
    *,
    validate_visual: bool,
) -> int:
    if not output.exists():
        raise RuntimeError("No se genero el PDF unido.")
    if output.stat().st_size <= 0:
        raise RuntimeError("El PDF unido quedo vacio.")

    with fitz.open(str(output)) as merged:
        if merged.needs_pass or merged.is_encrypted:
            raise RuntimeError("El PDF unido quedo protegido o cifrado inesperadamente.")
        if merged.page_count != expected_pages:
            raise RuntimeError(
                f"El PDF unido tiene {merged.page_count} paginas; "
                f"se esperaban {expected_pages}."
            )
        _render_smoke_check(merged)
        if validate_visual:
            _verify_visual_fidelity(merged, sources)
        return merged.page_count


def _render_smoke_check(doc: fitz.Document) -> None:
    for page_index in _sample_page_indexes(doc.page_count):
        doc[page_index].get_pixmap(matrix=fitz.Matrix(0.25, 0.25), alpha=False)


def _verify_visual_fidelity(
    merged: fitz.Document,
    sources: list[PdfMergeSourceReport],
) -> None:
    for source in sources:
        src_doc, _ = _open_source(Path(source.path))
        try:
            for src_index in _sample_page_indexes(source.page_count):
                out_index = source.start_page - 1 + src_index
                if out_index < 0 or out_index >= merged.page_count:
                    raise RuntimeError(
                        f"{Path(source.path).name}: la pagina {src_index + 1} "
                        "no existe en el PDF unido."
                    )
                _assert_pages_render_similarly(
                    src_doc[src_index],
                    merged[out_index],
                    Path(source.path).name,
                    src_index,
                )
        finally:
            src_doc.close()


def _assert_pages_render_similarly(
    source_page: fitz.Page,
    merged_page: fitz.Page,
    source_name: str,
    src_index: int,
) -> None:
    src_pix = _render_for_compare(source_page)
    merged_pix = _render_for_compare(merged_page)
    if (
        src_pix.width != merged_pix.width
        or src_pix.height != merged_pix.height
        or src_pix.n != merged_pix.n
    ):
        raise RuntimeError(
            f"{source_name}: la pagina {src_index + 1} cambio de dimensiones al unir."
        )

    avg_diff, changed_ratio = _pixmap_diff(src_pix.samples, merged_pix.samples)
    if avg_diff > _MAX_AVG_DIFF or changed_ratio > _MAX_CHANGED_RATIO:
        raise RuntimeError(
            f"{source_name}: la pagina {src_index + 1} no conserva su apariencia "
            f"visual en el PDF unido (diferencia {avg_diff:.2f}, "
            f"{changed_ratio:.2%} pixeles alterados)."
        )


def _render_for_compare(page: fitz.Page) -> fitz.Pixmap:
    long_side = max(float(page.rect.width), float(page.rect.height), 1.0)
    scale = min(1.0, max(0.05, _COMPARE_MAX_SIDE / long_side))
    return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, annots=True)


def _pixmap_diff(a: bytes, b: bytes) -> tuple[float, float]:
    if len(a) != len(b):
        return 255.0, 1.0
    if not a:
        return 0.0, 0.0
    total = 0
    changed = 0
    for left, right in zip(a, b):
        delta = abs(left - right)
        if delta:
            total += delta
            changed += 1
    return total / len(a), changed / len(a)


def _sample_page_indexes(page_count: int) -> list[int]:
    if page_count <= 0:
        return []
    if page_count <= 6:
        return list(range(page_count))
    return sorted({0, page_count // 2, page_count - 1})


def _trim_to_page_count(doc: fitz.Document, page_count: int) -> None:
    if doc.page_count <= page_count:
        return
    doc.delete_pages(page_count, doc.page_count - 1)


def _raise_if_cancelled(should_cancel: CancelCallback | None) -> None:
    if should_cancel and should_cancel():
        raise _CancelledError()


def _remove_partial(output: Path) -> None:
    try:
        if output.exists():
            output.unlink()
    except OSError:
        pass


def _mode_label(mode: str) -> str:
    labels = {
        "bulk": "copia completa",
        "pagewise": "copia por pagina",
        "normalized_pagewise": "copia normalizada",
        "raster": "rescate visual",
    }
    return labels.get(mode, mode)


class _CancelledError(Exception):
    pass
