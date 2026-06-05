"""Motor de separación de PDFs.

Extrae tramos de páginas de un PDF fuente y los guarda como archivos
independientes, usando fitz.Document.insert_pdf para copiar las páginas
sin reprocesarlas (preserva calidad, fuentes y metadatos).

Flujo:
    SplitterEngine.run_job(SplitterJob, progress)
      → para cada SplitRange:
           new_doc = fitz.open()
           new_doc.insert_pdf(src, from_page=r.start-1, to_page=r.end-1)
           new_doc.save(output_path)
      → retorna SplitterJobResult con una SplitResult por tramo
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import fitz

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
            src = fitz.open(job.pdf_path)
        except Exception as e:
            return SplitterJobResult(job=job, success=False, error=str(e))

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
                    new_doc = fitz.open()
                    # from_page / to_page son 0-based en PyMuPDF
                    new_doc.insert_pdf(
                        src,
                        from_page=rng.start - 1,
                        to_page=rng.end - 1,
                    )
                    new_doc.save(str(out_path), garbage=4, deflate=True)
                    new_doc.close()
                    split_results.append(SplitResult(
                        range=rng,
                        output_path=str(out_path),
                        success=True,
                        page_count=rng.page_count,
                    ))
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
        finally:
            try:
                src.close()
            except Exception:
                pass

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
