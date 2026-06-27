"""Motor de membretado masivo de PDFs.

Para cada documento de entrada, crea un nuevo PDF donde cada página es:
  1. Una copia de la hoja membretada (siempre la primera página del membrete).
  2. El contenido de la página original superpuesto dentro de la zona segura,
     escalado con relación de aspecto conservada y centrado.

La superposición utiliza _place_page():
  - rotation=0: fitz.Page.show_pdf_page() — copia vectorial, calidad perfecta.
  - Páginas con anotaciones: primero se aplanan en una copia en memoria, porque
    show_pdf_page() copia el contenido de la página pero no su capa de anotaciones
    (subrayados, resaltados, comentarios visuales, etc.).
  - rotation≠0: get_pixmap() + insert_image() a _RENDER_DPI — necesario porque
    show_pdf_page() en PyMuPDF ≥1.24 ignora /Rotate al calcular la posición del
    contenido, produciendo overflow y transposición de dimensiones en páginas con
    /Rotate=90/180/270 (p.ej. PDFs escaneados con orientación landscape+rotación).
"""
from __future__ import annotations
from dataclasses import dataclass
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
    pages_to_letterhead: Optional[List[int]] = None  # 0-based; None = todas
    preserve_unselected: bool = True


@dataclass
class MembreteJobResult:
    """Resultado de un MembreteJob. Compatible con GenericPdfViewer."""
    job: MembreteJob
    output_path: str = ""
    success: bool = True
    error: str = ""
    page_count: int = 0
    pages_letterheaded: int = 0
    pages_preserved: int = 0
    pages_omitted: int = 0
    meta_text: str = ""


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

        selected = _normalized_page_selection(job.pages_to_letterhead, src.page_count)
        annotated_pages = _annotated_selected_pages(src, selected)
        placement_src = src
        rasterize_annotation_pages: set[int] = set()
        if annotated_pages:
            try:
                placement_src = _copy_with_baked_annotations(src)
            except Exception:
                placement_src = src
                rasterize_annotation_pages = annotated_pages

        out = fitz.open()
        letterheaded = 0
        preserved = 0
        omitted = 0

        try:
            for page_idx in range(src.page_count):
                if should_cancel and should_cancel():
                    raise _CancelledError()

                should_letterhead = selected is None or page_idx in selected
                if not should_letterhead:
                    if job.preserve_unselected:
                        out.insert_pdf(src, from_page=page_idx, to_page=page_idx)
                        preserved += 1
                    else:
                        omitted += 1
                    continue

                new_page = out.new_page(width=lh_w, height=lh_h)

                # 1. Fondo: copiar membrete completo
                _place_page(new_page, lh_doc, 0, new_page.rect)

                # 2. Superponer página del documento en la zona segura
                src_page = src[page_idx]
                target = _fit_rect(safe, src_page.rect.width, src_page.rect.height)
                _place_page(
                    new_page,
                    placement_src,
                    page_idx,
                    target,
                    force_raster=page_idx in rasterize_annotation_pages,
                )
                letterheaded += 1

            if out.page_count <= 0:
                raise RuntimeError("La selección de páginas no produjo salida.")

            out_path = Path(job.output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out.save(str(out_path), garbage=4, deflate=True)
            n_pages = out.page_count

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
                if placement_src is not src:
                    placement_src.close()
                src.close()
                out.close()
            except Exception:
                pass

        return MembreteJobResult(
            job=job,
            output_path=job.output_path,
            success=True,
            page_count=n_pages,
            pages_letterheaded=letterheaded,
            pages_preserved=preserved,
            pages_omitted=omitted,
            meta_text=_result_meta_text(letterheaded, preserved, omitted),
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


def _normalized_page_selection(
    page_indexes: Optional[List[int]],
    page_count: int,
) -> Optional[set[int]]:
    if page_indexes is None:
        return None
    return {
        index
        for index in page_indexes
        if 0 <= int(index) < page_count
    }


def _annotated_selected_pages(
    doc: fitz.Document,
    selected: Optional[set[int]],
) -> set[int]:
    indexes = range(doc.page_count) if selected is None else selected
    return {
        page_idx
        for page_idx in indexes
        if 0 <= page_idx < doc.page_count and _page_has_annotations(doc[page_idx])
    }


def _page_has_annotations(page: fitz.Page) -> bool:
    try:
        annots = page.annots()
        if annots is None:
            return False
        return any(True for _ in annots)
    except Exception:
        return False


def _copy_with_baked_annotations(doc: fitz.Document) -> fitz.Document:
    baked = fitz.open("pdf", doc.tobytes())
    try:
        baked.bake(annots=True, widgets=False)
    except Exception:
        baked.close()
        raise
    return baked


def _result_meta_text(letterheaded: int, preserved: int, omitted: int) -> str:
    parts = [
        f"{letterheaded} membretada" + ("" if letterheaded == 1 else "s")
    ]
    if preserved:
        parts.append(f"{preserved} sin cambios")
    if omitted:
        parts.append(f"{omitted} omitida" + ("" if omitted == 1 else "s"))
    return " · ".join(parts)


def parse_membrete_page_scope(mode: str, text: str, page_count: int) -> List[int]:
    """Parsea el alcance de membretado y devuelve índices 0-based en orden natural."""
    if page_count <= 0:
        raise ValueError("El PDF no tiene páginas.")

    clean_mode = (mode or "all").strip().lower()
    all_pages = list(range(page_count))

    if clean_mode in {"all", "todas", "todo"}:
        return all_pages
    if clean_mode in {"even", "pares", "par"}:
        return [idx for idx in all_pages if (idx + 1) % 2 == 0]
    if clean_mode in {"odd", "impares", "impar"}:
        return [idx for idx in all_pages if (idx + 1) % 2 == 1]

    if clean_mode in {"include", "custom", "solo"}:
        pages = _parse_page_spec(text, page_count)
        if not pages:
            raise ValueError("El rango no contiene páginas para membretar.")
        return pages

    if clean_mode in {"exclude", "except", "excepto"}:
        excluded = set(_parse_page_spec(text, page_count))
        remaining = [idx for idx in all_pages if idx not in excluded]
        return remaining

    raise ValueError("Modo de páginas no reconocido.")


def compact_page_indexes(page_indexes: List[int]) -> str:
    if not page_indexes:
        return "Ninguna"
    pages = sorted({idx + 1 for idx in page_indexes})
    ranges: list[str] = []
    start = prev = pages[0]
    for page in pages[1:]:
        if page == prev + 1:
            prev = page
            continue
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = page
    ranges.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(ranges)


def _parse_page_spec(text: str, page_count: int) -> List[int]:
    raw = (text or "").strip().lower()
    if not raw:
        raise ValueError("Escribe un rango de páginas.")
    if raw in {"todas", "todo", "all", "*"}:
        return list(range(page_count))
    if raw in {"pares", "par", "even"}:
        return [idx for idx in range(page_count) if (idx + 1) % 2 == 0]
    if raw in {"impares", "impar", "odd"}:
        return [idx for idx in range(page_count) if (idx + 1) % 2 == 1]

    selected: set[int] = set()
    tokens = [
        token.strip()
        for chunk in raw.replace(";", ",").split(",")
        for token in chunk.split()
        if token.strip()
    ]
    for token in tokens:
        if "-" in token:
            left, right = token.split("-", 1)
            start = _parse_page_token(left, page_count, default=1)
            end = _parse_page_token(right, page_count, default=page_count)
            if start > end:
                raise ValueError(f"Rango invertido: {token}")
            selected.update(range(start - 1, end))
        else:
            page_num = _parse_page_token(token, page_count)
            selected.add(page_num - 1)

    if not selected:
        raise ValueError("El rango no contiene páginas válidas.")
    return sorted(selected)


def _parse_page_token(
    token: str,
    page_count: int,
    *,
    default: int | None = None,
) -> int:
    clean = token.strip().lower()
    if not clean:
        if default is None:
            raise ValueError("Página vacía en el rango.")
        return default
    if clean in {"final", "fin", "ultima", "última", "last"}:
        return page_count
    if not clean.isdigit():
        raise ValueError(f"Página inválida: {token}")
    value = int(clean)
    if value < 1 or value > page_count:
        raise ValueError(f"Página fuera de rango: {token}")
    return value


def _place_page(
    dest_page: fitz.Page,
    src_doc: fitz.Document,
    page_idx: int,
    target: fitz.Rect,
    render_dpi: float = _RENDER_DPI,
    force_raster: bool = False,
) -> None:
    """Coloca src_doc[page_idx] en dest_page dentro de target.

    Para páginas con /Rotate=0 usa show_pdf_page (vectorial, calidad máxima)
    salvo que force_raster=True.
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
    if src_page.rotation == 0 and not force_raster:
        dest_page.show_pdf_page(target, src_doc, page_idx)
        return

    # Páginas rotadas: renderizar con orientación correcta.
    # El pixmap tiene dimensiones page.rect (display), no del MediaBox.
    scale = render_dpi / 72.0
    mat = fitz.Matrix(scale, scale)
    pm = src_page.get_pixmap(matrix=mat, alpha=False, annots=True)
    try:
        dest_page.insert_image(target, pixmap=pm)
    finally:
        del pm  # liberar memoria inmediatamente


class _CancelledError(Exception):
    pass
