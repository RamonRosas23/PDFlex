"""Form-aware PDF structure operations powered by QPDF/pikepdf."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
import os
import uuid
from typing import Callable

import pikepdf

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


def _normalize_rotation(value: int) -> int:
    return (int(round(int(value) / 90.0)) * 90) % 360
