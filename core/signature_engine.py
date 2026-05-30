"""
Motor de firma masiva — v2.

Soporta múltiples firmas por documento en una sola pasada,
sin archivos temporales intermedios.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
import io
import os
import tempfile

import fitz
from PIL import Image, ImageEnhance, ImageFilter

from .pdf_analyzer import PdfAnalyzer, PageAnalysis
from .safe_zone import SafeZoneFinder, Placement
from .variation import VariationGenerator, VariationConfig


def _open_pdf_safe(path: str) -> fitz.Document:
    """Abre un PDF y repara su xref si es necesario.

    Algunos PDFs tienen tablas xref corruptas que MuPDF puede recuperar
    automáticamente. Si se detecta reparación, se guarda una copia limpia
    en un buffer temporal para que el save final sea estable.
    """
    doc = fitz.open(path)
    # is_repaired indica que MuPDF tuvo que reconstruir el xref
    if getattr(doc, "is_repaired", False):
        buf = io.BytesIO()
        doc.save(buf, garbage=4, deflate=True, clean=True)
        doc.close()
        buf.seek(0)
        doc = fitz.open(stream=buf, filetype="pdf")
    return doc


@dataclass
class SigPlacement:
    """Posición y tamaño de una firma individual dentro de un job."""
    signature_path: str
    base_x_norm: float       # centro X normalizado (0..1)
    base_y_norm: float       # centro Y normalizado (0..1)
    base_width_pt: float     # ancho en puntos PDF
    base_height_pt: float    # alto en puntos PDF
    base_angle: float = 0.0  # ángulo base en grados


@dataclass
class SignJob:
    """Una instrucción de firma para un documento (soporta N firmas)."""
    pdf_path: str
    output_path: str
    signatures: List[SigPlacement]     # Una o más firmas
    pages: Optional[List[int]] = None  # None = todas las páginas


@dataclass
class PageResult:
    page_index: int
    placement: Placement
    snapped_to_line: bool = False
    clean: bool = True


@dataclass
class JobResult:
    job: SignJob
    output_path: str
    page_results: List[PageResult] = field(default_factory=list)
    success: bool = True
    error: str = ""


class SignatureEngine:
    """Aplica múltiples firmas con variación natural y validación anti-texto."""

    def __init__(
        self,
        variation: VariationConfig,
        margin: float = 18.0,
        text_padding: float = 4.0,
    ):
        self.variation_gen = VariationGenerator(variation)
        self.analyzer = PdfAnalyzer()
        self.finder = SafeZoneFinder(margin=margin, text_padding=text_padding)
        # Caché de imágenes para no reabrir el mismo archivo N veces
        self._img_cache: Dict[str, Image.Image] = {}

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #

    def run_job(
        self,
        job: SignJob,
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> JobResult:
        """Procesa un documento aplicando todas las firmas en una sola pasada."""
        try:
            doc = _open_pdf_safe(job.pdf_path)
        except Exception as e:
            return JobResult(job=job, output_path="", success=False,
                             error=f"No se pudo abrir PDF: {e}")

        results: List[PageResult] = []
        target_pages = (job.pages if job.pages is not None
                        else list(range(doc.page_count)))
        total = len(target_pages)

        try:
            for i, page_idx in enumerate(target_pages):
                if progress:
                    progress(i, total, f"Página {page_idx + 1}/{doc.page_count}")

                analysis = self.analyzer.analyze_page(doc, page_idx)
                page = doc[page_idx]
                primary_placement: Optional[Placement] = None

                for sig_conf in job.signatures:
                    base_img = self._get_image(sig_conf.signature_path)
                    placement = self._compute_placement(
                        sig_conf, analysis, job.pdf_path, page_idx
                    )
                    self._apply_signature(
                        page, placement, base_img,
                        job.pdf_path, sig_conf.signature_path, page_idx
                    )
                    if primary_placement is None:
                        primary_placement = placement

                if primary_placement is not None:
                    results.append(PageResult(
                        page_index=page_idx,
                        placement=primary_placement,
                        snapped_to_line=primary_placement.snapped_to_line,
                        clean=primary_placement.clean,
                    ))

            os.makedirs(os.path.dirname(os.path.abspath(job.output_path)), exist_ok=True)
            doc.save(job.output_path, garbage=4, deflate=True)
            if progress:
                progress(total, total, "Guardado")

        except Exception as e:
            doc.close()
            return JobResult(job=job, output_path="", success=False, error=str(e))
        finally:
            try:
                doc.close()
            except Exception:
                pass

        return JobResult(
            job=job,
            output_path=job.output_path,
            page_results=results,
            success=True,
        )

    # ------------------------------------------------------------------ #
    # Privados
    # ------------------------------------------------------------------ #

    def _get_image(self, path: str) -> Image.Image:
        if path not in self._img_cache:
            self._img_cache[path] = Image.open(path).convert("RGBA")
        return self._img_cache[path]

    def _compute_placement(
        self,
        sig_conf: SigPlacement,
        analysis: PageAnalysis,
        doc_id: str,
        page_index: int,
    ) -> Placement:
        base_x = sig_conf.base_x_norm * analysis.width
        base_y = sig_conf.base_y_norm * analysis.height

        # Semilla única por (doc, firma, página).
        # Usamos solo el nombre del archivo (sin path completo) para estabilidad.
        import os as _os
        doc_name = _os.path.basename(doc_id)
        sig_name = _os.path.basename(sig_conf.signature_path)
        seed_key = doc_name + "\x00" + sig_name
        v = self.variation_gen.variation_for(seed_key, page_index)

        w = sig_conf.base_width_pt * v.scale_factor
        h = sig_conf.base_height_pt * v.scale_factor
        x = base_x + v.d_x
        y = base_y + v.d_y
        angle = sig_conf.base_angle + v.d_angle

        desired = Placement(
            x=x, y=y, width=w, height=h,
            angle=angle, opacity=v.opacity,
        )
        return self.finder.find_safe_placement(analysis, desired)

    def _apply_signature(
        self,
        page: fitz.Page,
        placement: Placement,
        base_img: Image.Image,
        doc_id: str,
        sig_path: str,
        page_index: int,
    ) -> None:
        import os as _os
        doc_name = _os.path.basename(doc_id)
        sig_name = _os.path.basename(sig_path)
        seed_key = doc_name + "\x00" + sig_name
        v = self.variation_gen.variation_for(seed_key, page_index)
        img = self._transform_image(base_img, placement, v.pressure)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        target = placement.rotated_bbox
        try:
            page.insert_image(target, stream=img_bytes, keep_proportion=False, overlay=True)
        except TypeError:
            page.insert_image(target, stream=img_bytes, overlay=True)

    def _transform_image(
        self, base: Image.Image, placement: Placement, pressure: float
    ) -> Image.Image:
        img = base.copy()

        if pressure > 0:
            contrast = 0.95 + 0.10 * pressure
            img = ImageEnhance.Contrast(img).enhance(contrast)
            if pressure > 0.7:
                img = img.filter(ImageFilter.GaussianBlur(radius=0.3))
            brightness = 0.97 + 0.06 * (1.0 - pressure)
            img = ImageEnhance.Brightness(img).enhance(brightness)

        if placement.opacity < 0.999:
            r, g, b, a = img.split()
            a = a.point(lambda v: int(v * placement.opacity))
            img = Image.merge("RGBA", (r, g, b, a))

        if abs(placement.angle) > 0.01:
            img = img.rotate(
                placement.angle,
                expand=True,
                resample=Image.BICUBIC,
                fillcolor=(0, 0, 0, 0),
            )

        return img
