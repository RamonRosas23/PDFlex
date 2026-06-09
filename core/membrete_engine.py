"""Motor de membretado masivo de PDFs.

Para cada documento de entrada, crea un nuevo PDF donde cada página es:
  1. Una copia de la hoja membretada (siempre la primera página del membrete).
  2. El contenido de la página original superpuesto dentro de la zona segura,
     escalado con relación de aspecto conservada y centrado.

La superposición utiliza _place_page():
  - rotation=0: fitz.Page.show_pdf_page() — copia vectorial, calidad perfecta.
  - rotation≠0: get_pixmap() + insert_image() a _RENDER_DPI — necesario porque
    show_pdf_page() en PyMuPDF ≥1.24 ignora /Rotate al calcular la posición del
    contenido, produciendo overflow y transposición de dimensiones en páginas con
    /Rotate=90/180/270 (p.ej. PDFs escaneados con orientación landscape+rotación).
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
#  Constantes
# ====================================================================== #

# DPI para rasterizar páginas con /Rotate≠0 vía get_pixmap().
# 150 DPI produce ~1275×2008 px para A4 portrait — adecuado para impresión
# de oficina y documentos legales, manteniendo tamaños de archivo razonables.
_RENDER_DPI: float = 150.0


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
        lh_w = lh_page.rect.width   # dimensiones de DISPLAY (rotation-aware)
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
                _place_page(new_page, lh_doc, 0, new_page.rect)

                # 2. Superponer página del documento en la zona segura
                src_page = src[page_idx]
                target = _fit_rect(safe, src_page.rect.width, src_page.rect.height)
                _place_page(new_page, src, page_idx, target)

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
#  Utilidades geométricas y de renderizado
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


def _place_page(
    dest_page: fitz.Page,
    src_doc: fitz.Document,
    page_idx: int,
    target: fitz.Rect,
    render_dpi: float = _RENDER_DPI,
) -> None:
    """Coloca src_doc[page_idx] en dest_page dentro de target.

    Para páginas con /Rotate=0 usa show_pdf_page (vectorial, calidad máxima).
    Para páginas con /Rotate≠0 renderiza a pixmap vía get_pixmap() — que sí
    aplica /Rotate correctamente — e inserta la imagen con insert_image().

    Razón del desvío para rotation≠0:
      show_pdf_page() en PyMuPDF calcula el scale usando page.rect
      (rotation-aware) pero aplica ese scale sobre las coordenadas del
      MediaBox (pre-rotación). Para /Rotate=90/270 esto produce dimensiones
      transpuestas con overflow; para /Rotate=180 el contenido queda al revés.
      get_pixmap() aplica /Rotate correctamente: el pixmap resultante siempre
      tiene las dimensiones de page.rect (display), independientemente del
      MediaBox subyacente.
    """
    src_page = src_doc[page_idx]
    if src_page.rotation == 0:
        dest_page.show_pdf_page(target, src_doc, page_idx)
        return

    # Páginas rotadas: renderizar con orientación correcta.
    # El pixmap tiene dimensiones page.rect (display), no del MediaBox.
    scale = render_dpi / 72.0
    mat = fitz.Matrix(scale, scale)
    pm = src_page.get_pixmap(matrix=mat, alpha=False)
    try:
        dest_page.insert_image(target, pixmap=pm)
    finally:
        del pm  # liberar memoria inmediatamente


class _CancelledError(Exception):
    pass
