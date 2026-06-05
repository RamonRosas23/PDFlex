"""Motor de membretado masivo de PDFs.

Para cada documento de entrada, crea un nuevo PDF donde cada página es:
  1. Una copia de la hoja membretada (siempre la primera página del membrete).
  2. El contenido de la página original superpuesto dentro de la zona segura,
     escalado con relación de aspecto conservada y centrado.

La superposición se realiza con fitz.Page.show_pdf_page(), que copia el
contenido vectorial sin reprocesarlo (calidad perfecta, sin rasterización).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import fitz

from .margin_detector import MembreteMargins


# ====================================================================== #
#  Tipos de datos
# ====================================================================== #

@dataclass
class MembreteJob:
    """Un documento a membretar."""
    pdf_path: str
    output_path: str


@dataclass
class MembreteJobResult:
    """Resultado de un MembreteJob. Compatible con GenericPdfViewer."""
    job: MembreteJob
    output_path: str = ""
    success: bool = True
    error: str = ""
    page_count: int = 0


# ====================================================================== #
#  Motor
# ====================================================================== #

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
            lh_doc = fitz.open(letterhead_path)
        except Exception as e:
            raise RuntimeError(f"No se pudo abrir el membrete: {e}")

        lh_page = lh_doc[0]
        lh_w = lh_page.rect.width
        lh_h = lh_page.rect.height

        # Zona segura (donde va el contenido del documento)
        safe = fitz.Rect(
            margins.left_pt,
            margins.top_pt,
            lh_w - margins.right_pt,
            lh_h - margins.bottom_pt,
        )

        results: List[MembreteJobResult] = []
        total = len(jobs)

        try:
            for i, job in enumerate(jobs):
                if should_cancel and should_cancel():
                    break
                if progress:
                    progress(i, total, f"Membretando: {Path(job.pdf_path).name}")
                result = self._process_job(
                    job,
                    lh_doc,
                    lh_w,
                    lh_h,
                    safe,
                    should_cancel=should_cancel,
                )
                results.append(result)
        finally:
            lh_doc.close()

        if progress and not (should_cancel and should_cancel()):
            progress(total, total, "Membretado completado")

        return results

    # ------------------------------------------------------------------ #

    def _process_job(
        self,
        job: MembreteJob,
        lh_doc: fitz.Document,
        lh_w: float,
        lh_h: float,
        safe: fitz.Rect,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> MembreteJobResult:
        try:
            src = fitz.open(job.pdf_path)
        except Exception as e:
            return MembreteJobResult(job=job, output_path="", success=False, error=str(e))

        out = fitz.open()

        try:
            for page_idx in range(src.page_count):
                if should_cancel and should_cancel():
                    raise _CancelledError()

                new_page = out.new_page(width=lh_w, height=lh_h)

                # 1. Fondo: copiar membrete completo
                new_page.show_pdf_page(new_page.rect, lh_doc, 0)

                # 2. Superponer página del documento en la zona segura
                src_page = src[page_idx]
                target = _fit_rect(safe, src_page.rect.width, src_page.rect.height)
                new_page.show_pdf_page(target, src, page_idx)

            out_path = Path(job.output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out.save(str(out_path), garbage=4, deflate=True)
            n_pages = src.page_count

        except _CancelledError:
            src.close()
            out.close()
            return MembreteJobResult(
                job=job,
                output_path="",
                success=False,
                error="Operación cancelada.",
            )
        except Exception as e:
            src.close()
            out.close()
            return MembreteJobResult(job=job, output_path="", success=False, error=str(e))
        finally:
            try:
                src.close()
                out.close()
            except Exception:
                pass

        return MembreteJobResult(
            job=job,
            output_path=job.output_path,
            success=True,
            page_count=n_pages,
        )


# ====================================================================== #
#  Utilidades geométricas
# ====================================================================== #

def _fit_rect(container: fitz.Rect, src_w: float, src_h: float) -> fitz.Rect:
    """Devuelve el rect que encaja src_w × src_h dentro de container
    conservando la relación de aspecto y centrando el resultado."""
    if src_w <= 0 or src_h <= 0:
        return container
    cw = container.width
    ch = container.height
    scale = min(cw / src_w, ch / src_h)
    fw = src_w * scale
    fh = src_h * scale
    x0 = container.x0 + (cw - fw) / 2
    y0 = container.y0 + (ch - fh) / 2
    return fitz.Rect(x0, y0, x0 + fw, y0 + fh)


class _CancelledError(Exception):
    pass
