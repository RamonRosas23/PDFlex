"""PDF repair and normalization engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List

import fitz


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
        doc: fitz.Document | None = None
        try:
            doc = fitz.open(str(source))
            if doc.needs_pass or doc.is_encrypted:
                raise RuntimeError("El PDF esta protegido o cifrado.")
            if doc.page_count <= 0:
                raise RuntimeError("El PDF no tiene paginas.")

            page_count = doc.page_count
            repaired_on_open = bool(getattr(doc, "is_repaired", False))
            warnings: list[str] = []
            if repaired_on_open:
                warnings.append("MuPDF reparo la estructura al abrir el documento.")

            if not job.options.preserve_metadata:
                _clear_metadata(doc)

            rebuilt_pages = False
            try:
                _save_normalized(doc, output, job.options)
            except Exception:
                if not job.options.fallback_rebuild:
                    raise
                rebuilt_pages = True
                warnings.append("Se reconstruyeron las paginas porque el guardado directo fallo.")
                _remove_partial(output)
                _rebuild_pages(doc, output, job.options)

            output_size = output.stat().st_size if output.exists() else 0
            verified_pages = _verify_output(output)
            if verified_pages != page_count:
                raise RuntimeError(
                    f"El resultado tiene {verified_pages} paginas; se esperaban {page_count}."
                )
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
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass


def _save_normalized(doc: fitz.Document, output: Path, options: PdfRepairOptions) -> None:
    doc.save(
        str(output),
        garbage=max(0, min(4, int(options.garbage))),
        clean=options.clean,
        deflate=options.deflate,
        deflate_images=options.deflate_images,
        deflate_fonts=options.deflate_fonts,
        use_objstms=1 if options.use_objstms else 0,
        preserve_metadata=1 if options.preserve_metadata else 0,
        encryption=fitz.PDF_ENCRYPT_NONE,
    )


def _rebuild_pages(doc: fitz.Document, output: Path, options: PdfRepairOptions) -> None:
    rebuilt = fitz.open()
    try:
        rebuilt.insert_pdf(doc)
        if options.preserve_metadata:
            rebuilt.set_metadata(doc.metadata or {})
        _save_normalized(
            rebuilt,
            output,
            PdfRepairOptions(
                clean=options.clean,
                garbage=options.garbage,
                deflate=options.deflate,
                deflate_images=options.deflate_images,
                deflate_fonts=options.deflate_fonts,
                use_objstms=options.use_objstms,
                preserve_metadata=options.preserve_metadata,
                fallback_rebuild=False,
            ),
        )
    finally:
        rebuilt.close()


def _verify_output(output: Path) -> int:
    if not output.exists():
        raise RuntimeError("No se genero el PDF de salida.")
    doc = fitz.open(str(output))
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise RuntimeError("El PDF generado quedo protegido o cifrado inesperadamente.")
        return doc.page_count
    finally:
        doc.close()


def _clear_metadata(doc: fitz.Document) -> None:
    try:
        doc.set_metadata({})
    except Exception:
        pass
    try:
        doc.del_xml_metadata()
    except Exception:
        pass


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except Exception:
        return str(a) == str(b)


def _remove_partial(output: Path) -> None:
    try:
        if output.exists():
            output.unlink()
    except Exception:
        pass


def _format_size(size: int) -> str:
    value = float(max(0, size))
    units = ["B", "KB", "MB", "GB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
