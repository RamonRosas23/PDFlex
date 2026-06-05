"""Motor de foliado masivo de PDFs.

Aplica números de folio a las páginas de uno o varios PDFs, respetando
la posición, estilo y formato configurados por el usuario.

Flujo:
    FoleadorEngine.run_batch(jobs, config, style, progress)
      → para cada FolioJob:
           - abre el PDF con fitz
           - por cada página objetivo: renderiza el folio y lo inserta
           - guarda el PDF foliado
      → retorna List[FolioJobResult]
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import fitz

from .folio_format import FolioConfig, render


# ====================================================================== #
#  Tipos de datos
# ====================================================================== #

# Colores como tuplas RGB 0-1 (formato PyMuPDF)
RGBColor = Tuple[float, float, float]

# Mapa de variantes de fuente para los 3 tipos de fuente integrados en PyMuPDF
_FONT_VARIANTS: dict = {
    # (base, bold, italic) → nombre interno PyMuPDF
    ("helv", False, False): "helv",
    ("helv", True,  False): "hebo",
    ("helv", False, True):  "heit",
    ("helv", True,  True):  "hebi",
    ("tiro", False, False): "tiro",
    ("tiro", True,  False): "tibo",
    ("tiro", False, True):  "tiit",
    ("tiro", True,  True):  "tibi",
    ("cour", False, False): "cour",
    ("cour", True,  False): "cobo",
    ("cour", False, True):  "coit",
    ("cour", True,  True):  "cobi",
}


def _text_width(text: str, fontname: str, fontsize: float) -> float:
    """Measure text width across PyMuPDF versions."""
    get_text_length = getattr(fitz, "get_text_length", None)
    if get_text_length is None:
        get_text_length = getattr(fitz, "get_textlength", None)
    if get_text_length is not None:
        return get_text_length(text, fontname=fontname, fontsize=fontsize)
    return fitz.Font(fontname).text_length(text, fontsize=fontsize)


@dataclass
class FolioStyle:
    """Aspecto visual del texto de folio."""
    fontbase: str = "helv"           # "helv" | "tiro" | "cour"
    fontsize: float = 10.0
    bold: bool = False
    italic: bool = False
    color: RGBColor = (0.0, 0.0, 0.0)      # negro
    bg_color: RGBColor | None = None        # None = sin fondo

    @property
    def fontname(self) -> str:
        """Nombre interno PyMuPDF para esta combinación de fuente/variante."""
        return _FONT_VARIANTS.get(
            (self.fontbase, self.bold, self.italic),
            self.fontbase,
        )


@dataclass
class FolioJob:
    """Un documento a foliar."""
    pdf_path: str
    output_path: str
    # Posición del placeholder: centro normalizado en la página [0,1]
    x_norm: float
    y_norm: float
    # Tamaño del placeholder como fracción de la página de referencia [0,1]
    # (normalizado para que escale correctamente en páginas de distinto tamaño)
    width_norm: float
    height_norm: float
    # Dimensiones de la página de referencia en puntos PDF.
    # Se usan AMBAS para calcular el lado mayor y escalar el fontsize de forma
    # consistente sin importar la orientación (portrait/landscape) del doc.
    ref_page_height_pt: float = 842.0
    ref_page_width_pt: float = 595.0
    # Si True, intenta subir el folio un poco si tapa texto.
    smart_position: bool = True


@dataclass
class FolioPageResult:
    page_index: int     # 0-based
    folio_text: str
    success: bool = True
    error: str = ""


@dataclass
class FolioJobResult:
    job: FolioJob
    output_path: str
    page_results: List[FolioPageResult] = field(default_factory=list)
    success: bool = True
    error: str = ""


# ====================================================================== #
#  Motor
# ====================================================================== #

class FoleadorEngine:
    """Aplica números de folio a un lote de documentos."""

    def run_batch(
        self,
        jobs: List[FolioJob],
        config: FolioConfig,
        style: FolioStyle,
        progress: Optional[Callable[[int, int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> List[FolioJobResult]:
        """Procesa todos los documentos del lote.

        Si scope == "continuous", el contador n avanza sin reiniciarse entre docs.
        Si scope == "per_doc", cada documento comienza desde config.start.
        """
        results: List[FolioJobResult] = []
        n = config.start  # contador global o reiniciado

        total_docs = len(jobs)
        for doc_idx, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if config.scope == "per_doc":
                n = config.start

            if progress:
                progress(doc_idx, total_docs, f"Foliando: {Path(job.pdf_path).name}")

            result, pages_foliated = self._process_job(
                job,
                config,
                style,
                n,
                should_cancel=should_cancel,
            )
            results.append(result)

            if result.success and config.scope == "continuous":
                n += pages_foliated * config.step

        if progress and not (should_cancel and should_cancel()):
            progress(total_docs, total_docs, "Completado")

        return results

    # ------------------------------------------------------------------ #

    def _process_job(
        self,
        job: FolioJob,
        config: FolioConfig,
        style: FolioStyle,
        start_n: int,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> tuple[FolioJobResult, int]:
        """Procesa un documento. Retorna (result, páginas_foliadas)."""
        try:
            doc = fitz.open(job.pdf_path)
        except Exception as e:
            return (
                FolioJobResult(job=job, output_path="", success=False, error=str(e)),
                0,
            )

        page_results: List[FolioPageResult] = []
        n = start_n
        total_pages = doc.page_count
        doc_name = Path(job.pdf_path).stem

        try:
            for page_idx in range(total_pages):
                if should_cancel and should_cancel():
                    raise _CancelledError()

                # Determinar si esta página se folia
                if config.skip_first_page and page_idx == 0:
                    continue
                if config.only_pages is not None:
                    if (page_idx + 1) not in config.only_pages:
                        continue

                folio_text = render(config.pattern, n, doc_name, total_pages)
                page = doc[page_idx]

                try:
                    self._insert_folio(page, job, folio_text, style)
                    page_results.append(FolioPageResult(
                        page_index=page_idx,
                        folio_text=folio_text,
                        success=True,
                    ))
                except Exception as e:
                    page_results.append(FolioPageResult(
                        page_index=page_idx,
                        folio_text=folio_text,
                        success=False,
                        error=str(e),
                    ))

                n += config.step

            out_path = Path(job.output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            doc.save(str(out_path), garbage=4, deflate=True)

        except _CancelledError:
            doc.close()
            return (
                FolioJobResult(
                    job=job,
                    output_path="",
                    success=False,
                    error="Operación cancelada.",
                ),
                len(page_results),
            )
        except Exception as e:
            doc.close()
            return (
                FolioJobResult(job=job, output_path="", success=False, error=str(e)),
                len(page_results),
            )
        finally:
            try:
                doc.close()
            except Exception:
                pass

        failed_pages = [page for page in page_results if not page.success]
        success = not failed_pages
        error = ""
        if failed_pages:
            error = (
                f"No se pudieron foliar {len(failed_pages)} "
                f"página{'s' if len(failed_pages) != 1 else ''}."
            )

        return (
            FolioJobResult(
                job=job,
                output_path=job.output_path,
                page_results=page_results,
                success=success,
                error=error,
            ),
            len(page_results),
        )

    # ------------------------------------------------------------------ #

    def _insert_folio(
        self,
        page: fitz.Page,
        job: FolioJob,
        text: str,
        style: FolioStyle,
    ) -> None:
        """Inserta el texto de folio sobre la página.

        Diseño robusto:
        - El fontsize escala por el LADO MAYOR de la página vs el lado mayor
          de la referencia.  Esto garantiza tamaño consistente sea portrait,
          landscape o scaneado a diferente DPI.
        - El morph solo se usa cuando rot != 0, y el anchor se calcula
          EXACTAMENTE en (cx - text_w/2, cy + cap_offset) sin ningún clamp
          previo — el clamp pre-morph desplazaba el centro y mandaba el texto
          fuera de página.
        - smart_position sube el folio un máximo del 3 % de la página; si no
          hay hueco, se queda en la posición original.
        """
        rot = int(page.rotation) % 360  # normalizar: 0, 90, 180 o 270

        # page.rect refleja las dimensiones de display (ya rotadas).
        # Es el espacio de trabajo coherente con get_text("blocks").
        pw = page.rect.width
        ph = page.rect.height

        if pw <= 0 or ph <= 0:
            raise ValueError(f"Dimensiones de página inválidas: {pw:.1f}×{ph:.1f} pt")

        # ── Fontsize: escala por lado MAYOR para ser invariante a orientación ──
        # Si la referencia es portrait (842×595) o landscape (595×842), el lado
        # mayor es 842 en ambos casos.  Lo mismo para la página actual.
        ref_long = max(job.ref_page_height_pt, job.ref_page_width_pt)
        ref_long = ref_long if ref_long > 0 else 842.0
        page_long = max(pw, ph)
        # Limitar escala a [0.33 – 4×] para evitar extremos por scans con DPI incorrecto
        scale = max(0.33, min(4.0, page_long / ref_long))
        fontsize = max(4.0, style.fontsize * scale)
        fontname = style.fontname

        # ── Tamaño del recuadro proporcional a la página actual ────────
        box_w = max(4.0, job.width_norm * pw)
        box_h = max(2.0, job.height_norm * ph)
        hw = box_w / 2.0
        hh = box_h / 2.0

        # Reducir fontsize si el texto no cabe en el ancho del recuadro
        text_w = _text_width(text, fontname=fontname, fontsize=fontsize)
        if text_w > box_w * 0.92:
            fontsize = max(4.0, fontsize * (box_w * 0.92) / max(1.0, text_w))
            text_w = _text_width(text, fontname=fontname, fontsize=fontsize)

        # ── Margen de seguridad adaptativo ────────────────────────────
        # • EDGE_ABS: nunca menor de 2 pt (imprecisiones de fuente)
        # • EDGE_REL: 0.4 % del lado corto de la página — para páginas
        #   gigantes (escaneos 3500 pt) 2 pt es proporcioalmente cero;
        #   con 0.4 % siempre hay al menos ~10–14 pt de colchón.
        # El mayor de los dos garantiza robustez en todos los formatos.
        EDGE = max(2.0, min(pw, ph) * 0.004)

        # Para páginas rotadas (rot != 0) el morph desplaza el texto
        # en la dirección perpendicular al eje X de display.
        # El desplazamiento neto en esa dirección es ≈ text_w/2.
        # cy debe mantenerse al menos text_w/2 + EDGE desde cada borde
        # vertical para que la rotación no expulse el texto de la página.
        cy_extra = (text_w / 2.0) if rot != 0 else 0.0

        # Límites del centro en X: el box y el texto no deben tocar el borde
        cx_lo = max(hw + EDGE, text_w / 2.0 + EDGE)
        cx_hi = min(pw - hw - EDGE, pw - text_w / 2.0 - EDGE)
        if cx_lo > cx_hi:
            cx_lo = cx_hi = pw / 2.0

        # Límites del centro en Y: igual que X, más margen extra si hay rotación
        cy_lo = max(hh + EDGE, cy_extra + EDGE)
        cy_hi = min(ph - hh - EDGE, ph - cy_extra - EDGE)
        if cy_lo > cy_hi:
            cy_lo = cy_hi = ph / 2.0

        cx = max(cx_lo, min(cx_hi, job.x_norm * pw))
        cy = max(cy_lo, min(cy_hi, job.y_norm * ph))

        # ── Smart position: sube el folio si tapa texto (rango corto) ─
        if job.smart_position:
            cx, cy = self._find_clean_position(page, cx, cy, box_w, box_h, pw, ph)

        # ── Fondo opcional ─────────────────────────────────────────────
        # draw_rect también usa coordenadas nativas, igual que insert_text.
        # Para rot != 0 se transforma el rect de display → nativo.
        if style.bg_color is not None:
            if rot == 0:
                bg_rect = fitz.Rect(cx - hw, cy - hh, cx + hw, cy + hh)
            else:
                derot = page.derotation_matrix
                corners_bg = [
                    fitz.Point(cx - hw, cy - hh) * derot,
                    fitz.Point(cx + hw, cy - hh) * derot,
                    fitz.Point(cx - hw, cy + hh) * derot,
                    fitz.Point(cx + hw, cy + hh) * derot,
                ]
                xs_bg = [p.x for p in corners_bg]
                ys_bg = [p.y for p in corners_bg]
                bg_rect = fitz.Rect(min(xs_bg), min(ys_bg), max(xs_bg), max(ys_bg))
            page.draw_rect(bg_rect, color=None, fill=style.bg_color)

        # ── Texto centrado ─────────────────────────────────────────────
        # insert_text sitúa el BASELINE en el punto (x, y).
        # cap_height ≈ 0.72·fs → centro visual a 0.36·fs sobre el baseline.
        # IMPORTANTE: NO clampar text_x antes del morph.  Si se clampea, el
        # centro visual se aleja de (cx, cy) y tras la rotación el texto sale
        # de la página.  Dejamos que PyMuPDF recorte si es necesario.
        cap_offset = fontsize * 0.36
        anchor_x = cx - text_w / 2.0
        anchor_y = cy + cap_offset

        if rot == 0:
            # Clamp final con margen: garantiza que la tinta nunca toque el borde.
            # El cx ya fue clampado arriba, pero lo repetimos para el anchor_x por
            # si smart_position cambió algo que pudiera desplazar ligeramente el cx.
            anchor_x = max(EDGE, min(pw - text_w - EDGE, anchor_x))
            page.insert_text(
                (anchor_x, anchor_y),
                text,
                fontname=fontname,
                fontsize=fontsize,
                color=style.color,
            )
        else:
            # ── Páginas rotadas ─────────────────────────────────────────
            # insert_text usa coordenadas NATIVAS (antes de la rotación PDF),
            # no el espacio de display que devuelve page.rect.
            # Para páginas grandes con Rotate=90, display_x puede exceder el
            # ancho nativo → texto fuera de página → recortado o silenciado.
            #
            # Solución A: transformar display → nativo con derotation_matrix.
            # Solución B: aplicar margen en espacio nativo para que el morph
            #             (que desplaza el texto perpendicular al eje de avance)
            #             no empuje glifos más allá del borde de la MediaBox.
            derot = page.derotation_matrix
            mbox = page.mediabox

            native_anchor = fitz.Point(anchor_x, anchor_y) * derot
            native_center = fitz.Point(cx, cy) * derot

            # ── Clamp en espacio nativo ────────────────────────────────
            # El morph desplaza el texto ~text_w/2 en la dirección perpendicular.
            # Garantizamos que native_center esté suficientemente lejos de cada
            # borde nativo para absorber ese desplazamiento.
            native_half = text_w / 2.0 + fontsize + EDGE
            nc_x = max(native_half, min(mbox.width  - native_half, native_center.x))
            nc_y = max(native_half, min(mbox.height - native_half, native_center.y))

            # Trasladar el anchor por el mismo delta que el center (preserva la
            # posición relativa anchor→center, que determina la alineación del texto).
            shift_x = nc_x - native_center.x
            shift_y = nc_y - native_center.y
            native_anchor = fitz.Point(native_anchor.x + shift_x,
                                        native_anchor.y + shift_y)
            native_center = fitz.Point(nc_x, nc_y)

            result = page.insert_text(
                native_anchor,
                text,
                fontname=fontname,
                fontsize=fontsize,
                color=style.color,
                morph=(native_center, fitz.Matrix(rot)),
            )
            # Fallback: si insert_text no pudo colocar ningún carácter,
            # insertar sin rotación en el punto nativo clampeado.
            if not result:
                fb_x = max(EDGE, min(mbox.width  - text_w - EDGE,
                                     nc_x - text_w / 2.0))
                fb_y = max(EDGE, min(mbox.height - fontsize - EDGE,
                                     nc_y + cap_offset))
                page.insert_text(
                    (fb_x, fb_y),
                    text,
                    fontname=fontname,
                    fontsize=fontsize,
                    color=style.color,
                )

    # ------------------------------------------------------------------ #

    def _find_clean_position(
        self,
        page: fitz.Page,
        cx: float,
        cy: float,
        box_w: float,
        box_h: float,
        pw: float,
        ph: float,
    ) -> Tuple[float, float]:
        """Ajusta el folio hacia ARRIBA si su posición exacta tapa texto.

        Filosofía: conservadora y predecible.
        - Si la posición original está limpia → se usa tal cual.
        - Solo busca hacia ARRIBA, máximo 3 % de la altura de página.
        - Nunca desplaza horizontalmente (el usuario eligió la columna X).
        - Nunca baja (bajar el folio lo aleja del margen y empeora el resultado).
        - Si no encuentra hueco → regresa la posición original (el folio se
          estampa aunque tape texto; siempre visible, nunca perdido).
        """
        try:
            raw_blocks = page.get_text("blocks") or []
        except Exception:
            return cx, cy

        text_rects: List[fitz.Rect] = [
            fitz.Rect(b[0], b[1], b[2], b[3])
            for b in raw_blocks
            if len(b) >= 5 and isinstance(b[4], str) and b[4].strip()
        ]
        if not text_rects:
            return cx, cy

        hw = box_w / 2.0
        hh = box_h / 2.0
        # Padding mínimo: solo detecta solapamiento real, no proximidad
        PAD = 1.0

        # Rango corto: paso = 0.4 % de altura; máximo = 3 % de altura
        step_pt = max(2.0, ph * 0.004)
        max_shift = max(12.0, ph * 0.03)
        n_steps = int(max_shift / step_pt)

        def _clean(y: float) -> bool:
            """¿El folio centrado en (cx, y) no intersecta texto?"""
            # Fuera de la página → no válido
            if y - hh < 0.0 or y + hh > ph:
                return False
            probe = fitz.Rect(cx - hw - PAD, y - hh - PAD, cx + hw + PAD, y + hh + PAD)
            return not any(probe.intersects(tr) for tr in text_rects)

        # 1. Posición original — respetarla si está limpia
        if _clean(cy):
            return cx, cy

        # 2. Subir hasta encontrar hueco (rango corto)
        for k in range(1, n_steps + 1):
            if _clean(cy - k * step_pt):
                return cx, cy - k * step_pt

        # 3. Fallback: posición original (folio siempre visible)
        return cx, cy


class _CancelledError(Exception):
    pass
