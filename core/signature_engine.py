"""
Motor de firma masiva.

Combina:
  - Análisis de cada página (texto, líneas de firma)
  - Generador de variación natural
  - Buscador de zona segura
  - Aplicación efectiva de la firma sobre el PDF (PyMuPDF)

Produce un PDF firmado y un log de colocaciones (para el visor de resultados).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Callable
import io
import os

import fitz
from PIL import Image, ImageEnhance, ImageFilter

from .pdf_analyzer import PdfAnalyzer, PageAnalysis
from .safe_zone import SafeZoneFinder, Placement
from .variation import VariationGenerator, VariationConfig


@dataclass
class SignJob:
    """Una instrucción de firma para un documento."""
    pdf_path: str
    output_path: str
    # Punto base normalizado (0..1) sobre la primera página, definido en el preview
    base_x_norm: float
    base_y_norm: float
    # Tamaño base en puntos PDF (calculado desde el preview)
    base_width_pt: float
    base_height_pt: float
    base_angle: float = 0.0  # ángulo base elegido por el usuario
    pages: Optional[List[int]] = None  # None = todas


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
    """Aplica firmas con variación natural y validación anti-texto."""

    def __init__(
        self,
        signature_png_path: str,
        variation: VariationConfig,
        margin: float = 18.0,
        text_padding: float = 4.0,
    ):
        self.signature_png_path = signature_png_path
        self.variation_gen = VariationGenerator(variation)
        self.analyzer = PdfAnalyzer()
        self.finder = SafeZoneFinder(margin=margin, text_padding=text_padding)
        # Pre-cargar firma RGBA
        self._base_image = Image.open(signature_png_path).convert("RGBA")

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #

    def run_job(
        self,
        job: SignJob,
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> JobResult:
        """Procesa un documento. `progress(current, total, msg)` opcional."""
        try:
            doc = fitz.open(job.pdf_path)
        except Exception as e:
            return JobResult(job=job, output_path="", success=False,
                             error=f"No se pudo abrir PDF: {e}")

        results: List[PageResult] = []
        target_pages = job.pages if job.pages is not None else list(range(doc.page_count))
        total = len(target_pages)

        try:
            for i, page_idx in enumerate(target_pages):
                if progress:
                    progress(i, total, f"Página {page_idx + 1}/{doc.page_count}")

                analysis = self.analyzer.analyze_page(doc, page_idx)
                placement = self._compute_placement(job, analysis, page_idx)

                self._apply_signature(doc[page_idx], placement, page_idx, job)

                results.append(PageResult(
                    page_index=page_idx,
                    placement=placement,
                    snapped_to_line=placement.snapped_to_line,
                    clean=placement.clean,
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
    # Cálculo de colocación
    # ------------------------------------------------------------------ #

    def _compute_placement(
        self, job: SignJob, analysis: PageAnalysis, page_index: int
    ) -> Placement:
        # Punto base en coordenadas reales de la página
        base_x = job.base_x_norm * analysis.width
        base_y = job.base_y_norm * analysis.height

        # Variación determinista para esta página
        v = self.variation_gen.variation_for(job.pdf_path, page_index)

        # Aplicar variación
        w = job.base_width_pt * v.scale_factor
        h = job.base_height_pt * v.scale_factor
        x = base_x + v.d_x
        y = base_y + v.d_y
        angle = job.base_angle + v.d_angle

        desired = Placement(
            x=x, y=y, width=w, height=h,
            angle=angle, opacity=v.opacity,
        )

        # Buscar zona segura
        return self.finder.find_safe_placement(analysis, desired)

    # ------------------------------------------------------------------ #
    # Aplicación de la imagen
    # ------------------------------------------------------------------ #

    def _apply_signature(
        self,
        page: fitz.Page,
        placement: Placement,
        page_index: int,
        job: SignJob,
    ) -> None:
        """Inserta la imagen de la firma con rotación y opacidad."""
        v = self.variation_gen.variation_for(job.pdf_path, page_index)
        img = self._transform_image(self._base_image, placement, v.pressure)

        # Bytes PNG con alpha
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        # Rectángulo destino: el bbox rotado, porque la imagen ya viene rotada con expand=True
        target = placement.rotated_bbox

        try:
            page.insert_image(target, stream=img_bytes, keep_proportion=False, overlay=True)
        except TypeError:
            # Versiones viejas no soportan keep_proportion=False
            page.insert_image(target, stream=img_bytes, overlay=True)

    def _transform_image(
        self, base: Image.Image, placement: Placement, pressure: float
    ) -> Image.Image:
        """Aplica rotación, opacidad y "pressure jitter" a la imagen."""
        img = base.copy()

        # Pressure jitter sutil: pequeñas variaciones de contraste/blur
        if pressure > 0:
            # Contraste leve
            contrast = 0.95 + 0.10 * pressure
            img = ImageEnhance.Contrast(img).enhance(contrast)
            # A veces aplica un blur muy ligero
            if pressure > 0.7:
                img = img.filter(ImageFilter.GaussianBlur(radius=0.3))
            # Brillo leve
            brightness = 0.97 + 0.06 * (1.0 - pressure)
            img = ImageEnhance.Brightness(img).enhance(brightness)

        # Opacidad: multiplicar canal alpha
        if placement.opacity < 0.999:
            r, g, b, a = img.split()
            a = a.point(lambda v: int(v * placement.opacity))
            img = Image.merge("RGBA", (r, g, b, a))

        # Rotación (positivo = antihorario en PIL)
        if abs(placement.angle) > 0.01:
            img = img.rotate(
                placement.angle,
                expand=True,
                resample=Image.BICUBIC,
                fillcolor=(0, 0, 0, 0),
            )

        return img
