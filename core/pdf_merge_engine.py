"""Robust, form-aware PDF merge engine with cross-engine validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Iterable, List

from core.pdf_backend import (
    MergeReport,
    PdfCancelledError,
    merge_documents,
    normalize_pdf,
    raster_merge_documents,
)


ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]


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


@dataclass(frozen=True)
class _AttemptReport:
    backend: MergeReport
    repaired_sources: tuple[bool, ...]
    normalized: bool = False
    rasterized: bool = False


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
        attempts = (
            ("direct", _merge_direct),
            ("normalized", _merge_normalized),
            ("raster", _merge_raster),
        )
        for mode, operation in attempts:
            try:
                _remove_partial(Path(output_path))
                attempt = operation(
                    paths,
                    output_path,
                    opts,
                    progress=progress,
                    should_cancel=should_cancel,
                )
                return _result_from_attempt(paths, output_path, attempt)
            except PdfCancelledError:
                _remove_partial(Path(output_path))
                return PdfMergeResult(
                    output_path=output_path,
                    success=False,
                    error="Operacion cancelada.",
                    source_count=len(paths),
                )
            except Exception as exc:  # noqa: BLE001 - user-facing aggregate
                errors.append(f"{_mode_label(mode)}: {exc}")

        _remove_partial(Path(output_path))
        return PdfMergeResult(
            output_path=output_path,
            success=False,
            error="No se pudo generar un PDF unido valido. " + " | ".join(errors),
            source_count=len(paths),
        )


def _merge_direct(
    paths: list[str],
    output_path: str,
    options: PdfMergeOptions,
    *,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
) -> _AttemptReport:
    backend = merge_documents(
        paths,
        output_path,
        blank_between=options.blank_between,
        add_bookmarks=options.add_bookmarks,
        validate_visual=options.validate_visual,
        progress=_backend_progress(progress),
        should_cancel=should_cancel,
    )
    return _AttemptReport(
        backend=backend,
        repaired_sources=tuple(item.repaired_on_open for item in backend.sources),
    )


def _merge_normalized(
    paths: list[str],
    output_path: str,
    options: PdfMergeOptions,
    *,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
) -> _AttemptReport:
    repaired: list[bool] = []
    with TemporaryDirectory(prefix="pdflex-merge-normalized-") as temp_dir:
        normalized_paths: list[str] = []
        total = len(paths)
        for index, raw_path in enumerate(paths):
            if should_cancel and should_cancel():
                raise PdfCancelledError("Operación cancelada.")
            source = Path(raw_path)
            normalized = Path(temp_dir) / f"{index:04d}-{source.name}"
            if progress:
                progress(index, total, f"Normalizando {source.name}...")
            report = normalize_pdf(source, normalized)
            normalized_paths.append(str(normalized))
            repaired.append(report.repaired_on_open)

        backend = merge_documents(
            normalized_paths,
            output_path,
            blank_between=options.blank_between,
            add_bookmarks=options.add_bookmarks,
            bookmark_titles=[Path(path).stem for path in paths],
            validate_visual=options.validate_visual,
            progress=_backend_progress(progress),
            should_cancel=should_cancel,
        )
        return _AttemptReport(
            backend=backend,
            repaired_sources=tuple(repaired),
            normalized=True,
        )


def _merge_raster(
    paths: list[str],
    output_path: str,
    options: PdfMergeOptions,
    *,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
) -> _AttemptReport:
    backend = raster_merge_documents(
        paths,
        output_path,
        blank_between=options.blank_between,
        add_bookmarks=options.add_bookmarks,
        progress=_backend_progress(progress),
        should_cancel=should_cancel,
    )
    return _AttemptReport(
        backend=backend,
        repaired_sources=(False,) * len(paths),
        rasterized=True,
    )


def _result_from_attempt(
    original_paths: list[str],
    output_path: str,
    attempt: _AttemptReport,
) -> PdfMergeResult:
    reports: list[PdfMergeSourceReport] = []
    for index, backend_source in enumerate(attempt.backend.sources):
        reports.append(
            PdfMergeSourceReport(
                path=original_paths[index],
                page_count=backend_source.page_count,
                inserted_pages=backend_source.page_count,
                start_page=backend_source.start_page,
                repaired_on_open=attempt.repaired_sources[index],
                used_pagewise_fallback=attempt.normalized,
                normalized_before_insert=attempt.normalized,
                used_raster_fallback=attempt.rasterized,
            )
        )

    warnings: list[str] = []
    if attempt.normalized:
        warnings.append(
            "Se normalizaron los PDFs antes de unir porque la copia directa "
            "no pasó la verificación."
        )
    if attempt.rasterized:
        warnings.append(
            "Se usó rescate visual: las páginas se reconstruyeron como imagen "
            "para evitar pérdida de contenido."
        )
    return PdfMergeResult(
        output_path=output_path,
        success=True,
        total_pages=attempt.backend.page_count,
        expected_pages=attempt.backend.page_count,
        source_count=len(original_paths),
        blank_pages=attempt.backend.blank_pages,
        sources=reports,
        warnings=warnings,
    )


def _backend_progress(
    callback: ProgressCallback | None,
) -> Callable[[int, int, str], None] | None:
    if callback is None:
        return None

    def forward(current: int, total: int, path: str) -> None:
        callback(current, total, f"Uniendo {Path(path).name}...")

    return forward


def _remove_partial(output: Path) -> None:
    try:
        output.unlink(missing_ok=True)
    except OSError:
        pass


def _mode_label(mode: str) -> str:
    return {
        "direct": "copia QPDF",
        "normalized": "copia normalizada",
        "raster": "rescate visual",
    }.get(mode, mode)
