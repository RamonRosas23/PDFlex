"""PDF repair and normalization engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List

from core.pdf_backend import normalize_pdf


@dataclass(frozen=True)
class PdfRepairOptions:
    clean: bool = True
    garbage: int = 4
    deflate: bool = True
    deflate_images: bool = True
    deflate_fonts: bool = True
    use_objstms: bool = True
    preserve_metadata: bool = True
    fallback_rebuild: bool = True


@dataclass
class PdfRepairJob:
    pdf_path: str
    output_path: str
    options: PdfRepairOptions = field(default_factory=PdfRepairOptions)


@dataclass
class PdfRepairResult:
    job: PdfRepairJob
    output_path: str = ""
    success: bool = False
    error: str = ""
    page_count: int = 0
    original_size: int = 0
    output_size: int = 0
    repaired_on_open: bool = False
    rebuilt_pages: bool = False
    warnings: List[str] = field(default_factory=list)

    @property
    def meta_text(self) -> str:
        size_text = f"{_format_size(self.original_size)} -> {_format_size(self.output_size)}"
        mode = "reparado" if self.repaired_on_open else "normalizado"
        if self.rebuilt_pages:
            mode += " · paginas reconstruidas"
        return f"{self.page_count} paginas · {size_text} · {mode}"


class PdfRepairEngine:
    """Rewrites PDFs with cleanup options and verifies the generated output."""

    def run_batch(
        self,
        jobs: List[PdfRepairJob],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[PdfRepairResult]:
        total = len(jobs)
        results: list[PdfRepairResult] = []
        for index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(index, total, f"Normalizando {Path(job.pdf_path).name}...")
            results.append(self.run_job(job))
            if progress:
                progress(index + 1, total, f"{index + 1}/{total} PDFs procesados")
        return results

    def run_job(self, job: PdfRepairJob) -> PdfRepairResult:
        source = Path(job.pdf_path)
        output = Path(job.output_path)
        if not source.exists():
            return PdfRepairResult(job=job, success=False, error="El PDF de origen no existe.")
        if _same_path(source, output):
            return PdfRepairResult(
                job=job,
                success=False,
                error="La salida no puede ser el mismo archivo de origen.",
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        original_size = source.stat().st_size
        try:
            report = normalize_pdf(
                source,
                output,
                preserve_metadata=job.options.preserve_metadata,
                normalize_content=job.options.clean,
                generate_object_streams=job.options.use_objstms,
                fallback_rebuild=job.options.fallback_rebuild,
            )
            page_count = report.page_count
            repaired_on_open = report.repaired_on_open
            rebuilt_pages = report.rebuilt_pages
            warnings = list(report.warnings)
            if repaired_on_open:
                warnings.append("QPDF reparo la estructura al abrir el documento.")
            if rebuilt_pages:
                warnings.append("Se reconstruyeron las paginas porque el guardado directo fallo.")

            output_size = output.stat().st_size if output.exists() else 0
            if output_size > original_size and not repaired_on_open:
                warnings.append("El PDF normalizado pesa mas que el original.")

            return PdfRepairResult(
                job=job,
                output_path=str(output),
                success=True,
                page_count=page_count,
                original_size=original_size,
                output_size=output_size,
                repaired_on_open=repaired_on_open,
                rebuilt_pages=rebuilt_pages,
                warnings=warnings,
            )
        except Exception as exc:
            return PdfRepairResult(
                job=job,
                success=False,
                error=str(exc),
                original_size=original_size,
            )


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except Exception:
        return str(a) == str(b)


def _format_size(size: int) -> str:
    value = float(max(0, size))
    units = ["B", "KB", "MB", "GB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
