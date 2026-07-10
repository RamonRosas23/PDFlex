"""Motor de separación de PDFs.

Extrae tramos de páginas de un PDF fuente y los guarda como archivos
independientes mediante QPDF, sin reprocesar su contenido y preservando
calidad, fuentes, anotaciones y formularios AcroForm.

Flujo:
    SplitterEngine.run_job(SplitterJob, progress)
      → para cada SplitRange:
           extract_pages(src, range(r.start-1, r.end), output_path)
      → retorna SplitterJobResult con una SplitResult por tramo
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from core.pdf_backend import PdfCancelledError, extract_pages, pdf_page_count

from .split_ranges import SplitRange
from .output_paths import unique_output_path
from .output_naming import output_stem_for_source


# ====================================================================== #
#  Tipos de datos
# ====================================================================== #

@dataclass
class SplitterJob:
    """Una tarea de separación: un PDF fuente → N archivos."""
    pdf_path: str
    output_dir: str
    ranges: List[SplitRange]
    base_name: str = ""   # prefijo para nombres auto (usa stem del PDF si vacío)
    tool_suffix: str = "separado"
    add_tool_suffix: bool = True


@dataclass
class SplitResult:
    """Resultado de un tramo individual.  Compatible con GenericPdfViewer."""
    range: SplitRange
    output_path: str = ""
    success: bool = True
    error: str = ""
    page_count: int = 0


@dataclass
class SplitterJobResult:
    """Resultado completo de un SplitterJob."""
    job: SplitterJob
    split_results: List[SplitResult] = field(default_factory=list)
    success: bool = True
    error: str = ""

    @property
    def output_path(self) -> str:
        """Primer archivo generado (para compatibilidad con GenericPdfViewer)."""
        for r in self.split_results:
            if r.success and r.output_path:
                return r.output_path
        return ""


# ====================================================================== #
#  Motor
# ====================================================================== #

class SplitterEngine:
    """Ejecuta la separación de un documento según los rangos configurados."""

    def run_job(
        self,
        job: SplitterJob,
        progress: Optional[Callable[[int, int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> SplitterJobResult:
        try:
            source_page_count = pdf_page_count(job.pdf_path)
        except Exception as e:
            return SplitterJobResult(job=job, success=False, error=str(e))
        if source_page_count <= 0:
            return SplitterJobResult(
                job=job,
                success=False,
                error="El PDF no tiene páginas.",
            )

        base = job.base_name or Path(job.pdf_path).stem
        out_dir = Path(job.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        split_results: List[SplitResult] = []
        total = len(job.ranges)
        reserved: set[str] = set()

        try:
            for i, rng in enumerate(job.ranges):
                if should_cancel and should_cancel():
                    raise _CancelledError()

                if progress:
                    progress(i, total, f"Extrayendo tramo {i + 1}/{total}…")

                range_name = rng.name.strip() or f"parte-{i + 1:02d}"
                out_name = output_stem_for_source(
                    base,
                    tool_suffix=job.tool_suffix,
                    add_tool_suffix=job.add_tool_suffix,
                    technical_suffix=range_name,
                    fallback=f"parte-{i + 1:02d}",
                )
                out_path = unique_output_path(
                    out_dir,
                    f"{out_name}.pdf",
                    reserved=reserved,
                    fallback=f"parte-{i + 1:02d}",
                )

                try:
                    report = extract_pages(
                        job.pdf_path,
                        range(rng.start - 1, rng.end),
                        out_path,
                        should_cancel=should_cancel,
                    )
                    split_results.append(SplitResult(
                        range=rng,
                        output_path=str(out_path),
                        success=True,
                        page_count=report.page_count,
                    ))
                except PdfCancelledError:
                    raise _CancelledError()
                except Exception as e:
                    split_results.append(SplitResult(
                        range=rng,
                        output_path="",
                        success=False,
                        error=str(e),
                    ))

            if progress and not (should_cancel and should_cancel()):
                progress(total, total, "Separación completada")

        except _CancelledError:
            split_results.append(SplitResult(
                range=SplitRange(start=1, end=1, name="cancelado"),
                output_path="",
                success=False,
                error="Operación cancelada.",
            ))

        ok = sum(1 for r in split_results if r.success)
        return SplitterJobResult(
            job=job,
            split_results=split_results,
            success=ok > 0,
            error="" if ok > 0 else "Ningún tramo se generó correctamente",
        )


# ====================================================================== #
#  Utilidades
# ====================================================================== #

_UNSAFE_CHARS = r'\/:*?"<>|'

def _sanitize_filename(name: str) -> str:
    for c in _UNSAFE_CHARS:
        name = name.replace(c, "_")
    return name.strip() or "tramo"
