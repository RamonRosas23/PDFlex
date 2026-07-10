"""Form-aware PDF structure operations powered by QPDF/pikepdf."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
import os
import uuid
from typing import Callable

import pikepdf
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from .errors import PdfBackendError, PdfCancelledError, PdfPasswordError
from .rendering import PdfRenderDocument


@dataclass(frozen=True, slots=True)
class SourcePage:
    """One zero-based source page and an optional clockwise rotation delta."""

    path: str
    index: int
    rotation: int = 0


@dataclass(frozen=True, slots=True)
class AssemblyReport:
    page_count: int
    source_count: int
    renamed_form_fields: dict[str, str] = field(default_factory=dict)
    partial_form_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NormalizeReport:
    page_count: int
    repaired_on_open: bool
    rebuilt_pages: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MergeSourceReport:
    path: str
    page_count: int
    start_page: int
    repaired_on_open: bool = False


@dataclass(frozen=True, slots=True)
class MergeReport:
    page_count: int
    blank_pages: int
    sources: tuple[MergeSourceReport, ...]
    renamed_form_fields: dict[str, str] = field(default_factory=dict)


def assemble_pages(
    pages: list[SourcePage],
    output_path: str | Path,
    *,
    progress: Callable[[int, int, SourcePage], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> AssemblyReport:
    """Build a PDF from arbitrary source pages while preserving AcroForms."""
    if not pages:
        raise ValueError("No hay páginas para ensamblar.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    normalized_sources = {str(Path(item.path).resolve()) for item in pages}
    if str(output.resolve()) in normalized_sources:
        raise ValueError("La salida no puede sobrescribir un PDF de origen.")

    renamed_fields: dict[str, str] = {}
    partial_fields: list[str] = []

    try:
        with ExitStack() as stack:
            source_docs: dict[str, pikepdf.Pdf] = {}
            destination = stack.enter_context(pikepdf.Pdf.new())

            total = len(pages)
            for position, item in enumerate(pages):
                if should_cancel and should_cancel():
                    raise PdfCancelledError("Operación cancelada.")
                rotation = _normalize_rotation(item.rotation)
                source_path = str(Path(item.path).resolve())
                source = source_docs.get(source_path)
                if source is None:
                    source = stack.enter_context(_open_pdf(source_path))
                    source_docs[source_path] = source
                if not 0 <= item.index < len(source.pages):
                    raise IndexError(
                        f"Página {item.index + 1} fuera de rango en "
                        f"{Path(source_path).name}."
                    )

                source_rotation = int(source.pages[item.index].obj.get("/Rotate", 0)) % 360
                copy_result = destination.add_pages_from(
                    source,
                    pages=[item.index],
                    forms="preserve",
                )
                renamed_fields.update(dict(copy_result.renamed_fields))
                partial_fields.extend(str(value) for value in copy_result.partial_fields)
                # pikepdf memoizes copied foreign objects. When the same source
                # page is imported twice, the second copy may initially inherit
                # changes made to the first imported page. Set the absolute
                # angle every time so duplicate pages remain independent.
                destination.pages[-1].rotate(
                    (source_rotation + rotation) % 360,
                    relative=False,
                )
                if progress:
                    progress(position + 1, total, item)

            _save_atomic(destination, output)
            page_count = len(destination.pages)
            source_count = len(source_docs)
    except (PdfBackendError, ValueError, IndexError):
        raise
    except pikepdf.PasswordError as exc:
        raise PdfPasswordError("El PDF requiere una contraseña válida.") from exc
    except pikepdf.PdfError as exc:
        raise PdfBackendError(f"No se pudo ensamblar el PDF: {exc}") from exc

    _verify_page_count(output, page_count)
    return AssemblyReport(
        page_count=page_count,
        source_count=source_count,
        renamed_form_fields=renamed_fields,
        partial_form_fields=tuple(partial_fields),
    )


def extract_pages(
    source_path: str | Path,
    page_indexes: list[int] | range,
    output_path: str | Path,
    *,
    progress: Callable[[int, int, SourcePage], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> AssemblyReport:
    """Copy selected pages from one document to a new form-aware PDF."""
    indexes = list(page_indexes)
    if not indexes:
        raise ValueError("No hay páginas para extraer.")
    return assemble_pages(
        [SourcePage(str(source_path), index) for index in indexes],
        output_path,
        progress=progress,
        should_cancel=should_cancel,
    )


def normalize_pdf(
    source_path: str | Path,
    output_path: str | Path,
    *,
    preserve_metadata: bool = True,
    normalize_content: bool = True,
    generate_object_streams: bool = True,
    fallback_rebuild: bool = True,
) -> NormalizeReport:
    """Repair and normalize a PDF, then verify it with PDFium."""
    source = Path(source_path)
    output = Path(output_path)
    if source.resolve() == output.resolve():
        raise ValueError("La salida no puede ser el mismo archivo de origen.")
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        with _open_pdf(source) as document:
            page_count = len(document.pages)
            if page_count <= 0:
                raise PdfBackendError("El PDF no tiene páginas.")
            warnings = tuple(document.get_warnings())
            repaired_on_open = bool(warnings)
            if not preserve_metadata:
                _clear_metadata(document)

            rebuilt_pages = False
            try:
                _save_atomic(
                    document,
                    output,
                    normalize_content=normalize_content,
                    object_stream_mode=(
                        pikepdf.ObjectStreamMode.generate
                        if generate_object_streams
                        else pikepdf.ObjectStreamMode.preserve
                    ),
                )
            except (pikepdf.PdfError, OSError):
                if not fallback_rebuild:
                    raise
                rebuilt_pages = True
                with pikepdf.Pdf.new() as rebuilt:
                    rebuilt.add_pages_from(document, forms="preserve")
                    _save_atomic(
                        rebuilt,
                        output,
                        normalize_content=normalize_content,
                        object_stream_mode=(
                            pikepdf.ObjectStreamMode.generate
                            if generate_object_streams
                            else pikepdf.ObjectStreamMode.preserve
                        ),
                    )
    except PdfBackendError:
        raise
    except pikepdf.PasswordError as exc:
        raise PdfPasswordError("El PDF está protegido o cifrado.") from exc
    except (pikepdf.PdfError, OSError) as exc:
        raise PdfBackendError(f"No se pudo normalizar el PDF: {exc}") from exc

    _verify_page_count(output, page_count)
    return NormalizeReport(
        page_count=page_count,
        repaired_on_open=repaired_on_open,
        rebuilt_pages=rebuilt_pages,
        warnings=warnings,
    )


def merge_documents(
    source_paths: list[str | Path],
    output_path: str | Path,
    *,
    blank_between: bool = False,
    add_bookmarks: bool = False,
    bookmark_titles: list[str] | None = None,
    validate_visual: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> MergeReport:
    """Concatenate complete PDFs with form-aware copies and verification."""
    if len(source_paths) < 2:
        raise ValueError("Agrega al menos 2 archivos PDF para unir.")
    if bookmark_titles is not None and len(bookmark_titles) != len(source_paths):
        raise ValueError("La cantidad de títulos no coincide con los PDFs de origen.")

    output = Path(output_path)
    sources_resolved = [Path(path).resolve() for path in source_paths]
    if output.resolve() in sources_resolved:
        raise ValueError("La salida no puede sobrescribir un PDF de origen.")
    output.parent.mkdir(parents=True, exist_ok=True)

    reports: list[MergeSourceReport] = []
    renamed_fields: dict[str, str] = {}
    bookmark_specs: list[tuple[str, int]] = []
    blank_pages = 0
    last_display_size = (595.0, 842.0)

    try:
        with ExitStack() as stack:
            destination = stack.enter_context(pikepdf.Pdf.new())
            total = len(sources_resolved)
            for position, path in enumerate(sources_resolved):
                if should_cancel and should_cancel():
                    raise PdfCancelledError("Operación cancelada.")
                if not path.exists():
                    raise FileNotFoundError(f"{path.name}: el archivo no existe.")

                source = stack.enter_context(_open_pdf(path))
                page_count = len(source.pages)
                if page_count <= 0:
                    raise PdfBackendError(f"{path.name}: el PDF no tiene páginas.")

                if blank_between and position > 0:
                    destination.add_blank_page(page_size=last_display_size)
                    blank_pages += 1

                start_page = len(destination.pages) + 1
                copy_result = destination.add_pages_from(source, forms="preserve")
                renamed_fields.update(dict(copy_result.renamed_fields))
                if add_bookmarks:
                    title = bookmark_titles[position] if bookmark_titles else path.stem
                    bookmark_specs.append((title, start_page - 1))

                with PdfRenderDocument(path) as render_doc:
                    last = render_doc.page_info(page_count - 1)
                    last_display_size = (last.width_pt, last.height_pt)

                reports.append(
                    MergeSourceReport(
                        path=str(path),
                        page_count=page_count,
                        start_page=start_page,
                        repaired_on_open=bool(source.get_warnings()),
                    )
                )
                if progress:
                    progress(position + 1, total, str(path))

            if bookmark_specs:
                with destination.open_outline() as outline:
                    outline.root.extend(
                        pikepdf.OutlineItem(title, page_index)
                        for title, page_index in bookmark_specs
                    )

            expected = sum(item.page_count for item in reports) + blank_pages
            if len(destination.pages) != expected:
                raise PdfBackendError(
                    f"El documento en memoria tiene {len(destination.pages)} páginas; "
                    f"se esperaban {expected}."
                )
            _save_atomic(
                destination,
                output,
                object_stream_mode=pikepdf.ObjectStreamMode.generate,
            )
    except (PdfBackendError, PdfCancelledError, ValueError, FileNotFoundError):
        raise
    except pikepdf.PasswordError as exc:
        raise PdfPasswordError("El PDF está protegido o cifrado.") from exc
    except (pikepdf.PdfError, OSError) as exc:
        raise PdfBackendError(f"No se pudo unir el PDF: {exc}") from exc

    _verify_page_count(output, expected)
    if validate_visual:
        _verify_merged_visuals(output, reports)
    return MergeReport(expected, blank_pages, tuple(reports), renamed_fields)


def raster_merge_documents(
    source_paths: list[str | Path],
    output_path: str | Path,
    *,
    blank_between: bool = False,
    add_bookmarks: bool = False,
    dpi: int = 150,
    progress: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> MergeReport:
    """Last-resort visual merge that rebuilds pages from PDFium rasters."""
    if len(source_paths) < 2:
        raise ValueError("Agrega al menos 2 archivos PDF para unir.")
    if dpi < 72:
        raise ValueError("El rescate visual requiere al menos 72 DPI.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    reports: list[MergeSourceReport] = []
    blank_pages = 0
    page_cursor = 0
    last_size = (595.0, 842.0)
    canvas = Canvas(str(temporary), pagesize=last_size, pageCompression=1)

    try:
        total = len(source_paths)
        for position, raw_path in enumerate(source_paths):
            if should_cancel and should_cancel():
                raise PdfCancelledError("Operación cancelada.")
            path = Path(raw_path).resolve()
            with PdfRenderDocument(path) as source:
                if source.page_count <= 0:
                    raise PdfBackendError(f"{path.name}: el PDF no tiene páginas.")
                if blank_between and position > 0:
                    canvas.setPageSize(last_size)
                    canvas.showPage()
                    page_cursor += 1
                    blank_pages += 1

                start_page = page_cursor + 1
                if add_bookmarks:
                    key = f"source-{position}"
                    canvas.bookmarkPage(key)
                    canvas.addOutlineEntry(path.stem, key, level=0, closed=False)

                for page_index in range(source.page_count):
                    if should_cancel and should_cancel():
                        raise PdfCancelledError("Operación cancelada.")
                    info = source.page_info(page_index)
                    last_size = (info.width_pt, info.height_pt)
                    rendered = source.render_page(page_index, scale=dpi / 72.0)
                    canvas.setPageSize(last_size)
                    canvas.drawImage(
                        ImageReader(rendered.to_pil()),
                        0,
                        0,
                        width=info.width_pt,
                        height=info.height_pt,
                        preserveAspectRatio=False,
                        mask="auto",
                    )
                    canvas.showPage()
                    page_cursor += 1

                reports.append(
                    MergeSourceReport(
                        path=str(path),
                        page_count=source.page_count,
                        start_page=start_page,
                    )
                )
            if progress:
                progress(position + 1, total, str(path))

        canvas.save()
        os.replace(temporary, output)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass

    _verify_page_count(output, page_cursor)
    return MergeReport(page_cursor, blank_pages, tuple(reports))


def _open_pdf(path: str | Path) -> pikepdf.Pdf:
    try:
        return pikepdf.Pdf.open(
            path,
            suppress_warnings=True,
            attempt_recovery=True,
        )
    except pikepdf.PasswordError as exc:
        raise PdfPasswordError("El PDF está protegido o cifrado.") from exc
    except pikepdf.PdfError as exc:
        raise PdfBackendError(f"No se pudo abrir el PDF: {exc}") from exc


def _save_atomic(document: pikepdf.Pdf, output: Path, **kwargs) -> None:
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        document.save(
            temporary,
            compress_streams=True,
            recompress_flate=True,
            **kwargs,
        )
        os.replace(temporary, output)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _clear_metadata(document: pikepdf.Pdf) -> None:
    for key in list(document.docinfo.keys()):
        del document.docinfo[key]
    try:
        with document.open_metadata(set_pikepdf_as_editor=False) as metadata:
            metadata.clear()
    except (ValueError, pikepdf.PdfError):
        # A malformed XMP packet should not prevent removal of DocumentInfo.
        if "/Metadata" in document.Root:
            del document.Root.Metadata


def _verify_page_count(path: Path, expected: int) -> None:
    with PdfRenderDocument(path) as document:
        if document.page_count != expected:
            raise PdfBackendError(
                f"El resultado tiene {document.page_count} páginas; "
                f"se esperaban {expected}."
            )
        # Cross-engine smoke check of the first and final pages.
        indexes = sorted({0, expected - 1}) if expected else []
        for index in indexes:
            document.render_page(index, scale=0.2)


def _verify_merged_visuals(
    output: Path,
    sources: list[MergeSourceReport],
) -> None:
    with PdfRenderDocument(output) as merged:
        for source in sources:
            with PdfRenderDocument(source.path) as original:
                for source_index in _sample_page_indexes(source.page_count):
                    output_index = source.start_page - 1 + source_index
                    original_info = original.page_info(source_index)
                    merged_info = merged.page_info(output_index)
                    if (
                        abs(original_info.width_pt - merged_info.width_pt) > 0.01
                        or abs(original_info.height_pt - merged_info.height_pt) > 0.01
                    ):
                        raise PdfBackendError(
                            f"{Path(source.path).name}: la página {source_index + 1} "
                            "cambió de dimensiones al unir."
                        )
                    long_side = max(original_info.width_pt, original_info.height_pt, 1.0)
                    scale = min(1.0, max(0.05, 360.0 / long_side))
                    left = original.render_page(source_index, scale=scale).data
                    right = merged.render_page(output_index, scale=scale).data
                    average, changed_ratio = _raster_difference(left, right)
                    if average > 0.20 or changed_ratio > 0.001:
                        raise PdfBackendError(
                            f"{Path(source.path).name}: la página {source_index + 1} "
                            "no conserva su apariencia visual al unir "
                            f"(diferencia {average:.2f}, {changed_ratio:.2%})."
                        )


def _sample_page_indexes(page_count: int) -> list[int]:
    if page_count <= 6:
        return list(range(page_count))
    return sorted({0, page_count // 2, page_count - 1})


def _raster_difference(left: bytes, right: bytes) -> tuple[float, float]:
    if len(left) != len(right):
        return 255.0, 1.0
    if not left:
        return 0.0, 0.0
    total = 0
    changed = 0
    for first, second in zip(left, right):
        delta = abs(first - second)
        if delta:
            total += delta
            changed += 1
    return total / len(left), changed / len(left)


def _normalize_rotation(value: int) -> int:
    return (int(round(int(value) / 90.0)) * 90) % 360
