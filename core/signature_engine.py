"""
Motor de firma masiva — v2.

Soporta múltiples firmas por documento en una sola pasada,
sin archivos temporales intermedios.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
import io
import os
import tempfile

import fitz
from PIL import Image, ImageEnhance, ImageFilter

from .pdf_analyzer import PdfAnalyzer, PageAnalysis
from .safe_zone import SafeZoneFinder, Placement, fit_placement_inside_page
from .variation import Variation, VariationGenerator, VariationConfig


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
    excluded_pages: frozenset = field(default_factory=frozenset)  # 0-based indices a omitir


@dataclass
class SignJob:
    """Una instrucción de firma para un documento (soporta N firmas)."""
    pdf_path: str
    output_path: str
    signatures: List[SigPlacement]     # Una o más firmas
    pages: Optional[List[int]] = None  # None = todas las páginas
    smart_placement: bool = True       # False = desactiva el buscador de zona segura


@dataclass
class SignaturePageResult:
    signature_path: str
    placement: Placement


@dataclass
class PageResult:
    page_index: int
    placement: Placement
    snapped_to_line: bool = False
    clean: bool = True
    signature_results: List[SignaturePageResult] = field(default_factory=list)


@dataclass
class JobResult:
    job: SignJob
    output_path: str
    page_results: List[PageResult] = field(default_factory=list)
    success: bool = True
    error: str = ""


@dataclass
class BoundsPreflight:
    """Resumen rápido de ajustes físicos previstos antes de firmar."""
    signatures_checked: int = 0
    adjusted_to_page: int = 0
    scaled_to_fit: int = 0
    skipped_documents: int = 0


class SignatureEngine:
    """Aplica múltiples firmas con variación natural y validación anti-texto."""

    def __init__(
        self,
        variation: VariationConfig,
        margin: float = 0.0,
        text_padding: float = 4.0,
    ):
        self.variation_gen = VariationGenerator(variation)
        self.analyzer = PdfAnalyzer()
        self.finder = SafeZoneFinder(margin=margin, text_padding=text_padding)
        # Caché de imágenes para no reabrir el mismo archivo N veces
        self._img_cache: Dict[str, Image.Image] = {}
        # Caché acotada de PNGs transformados. Normalmente cada página varía,
        # pero cuando la transformación coincide evitamos repetir PIL + zlib.
        self._transformed_png_cache: OrderedDict[
            Tuple[str, float, float, float], bytes
        ] = OrderedDict()
        self._transformed_png_cache_limit = 16

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #

    def preflight_bounds(self, jobs: List[SignJob]) -> BoundsPreflight:
        """Calcula ajustes de borde previstos sin rasterizar ni modificar PDFs."""
        summary = BoundsPreflight()
        for job in jobs:
            try:
                doc = _open_pdf_safe(job.pdf_path)
            except Exception:
                summary.skipped_documents += 1
                continue
            try:
                target_pages = (
                    job.pages if job.pages is not None
                    else list(range(doc.page_count))
                )
                for page_idx in target_pages:
                    page = doc[page_idx]
                    for sig_conf in job.signatures:
                        if page_idx in sig_conf.excluded_pages:
                            continue
                        desired = self._desired_placement(
                            sig_conf,
                            page.rect.width,
                            page.rect.height,
                            job.pdf_path,
                            page_idx,
                        )[0]
                        bounded = fit_placement_inside_page(
                            desired, page.rect.width, page.rect.height, margin=0.0
                        )
                        summary.signatures_checked += 1
                        if bounded.adjusted_to_page:
                            summary.adjusted_to_page += 1
                        if bounded.scaled_to_fit:
                            summary.scaled_to_fit += 1
            finally:
                doc.close()
        return summary

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
            image_xrefs: Dict[Tuple, int] = {}
            for i, page_idx in enumerate(target_pages):
                if progress:
                    progress(i, total, f"Página {page_idx + 1}/{doc.page_count}")

                analysis = self.analyzer.analyze_page(doc, page_idx)
                page = doc[page_idx]
                primary_placement: Optional[Placement] = None
                signature_results: List[SignaturePageResult] = []
                occupied_rects: List[fitz.Rect] = []

                for sig_conf in job.signatures:
                    if page_idx in sig_conf.excluded_pages:
                        continue
                    base_img = self._get_image(sig_conf.signature_path)
                    placement, variation = self._compute_placement(
                        sig_conf, analysis, job.pdf_path, page_idx, occupied_rects,
                        smart=job.smart_placement,
                    )
                    placement = self._apply_signature(
                        page,
                        placement,
                        base_img,
                        sig_conf.signature_path,
                        variation,
                        image_xrefs,
                    )
                    occupied_rects.append(placement.rotated_bbox)
                    signature_results.append(SignaturePageResult(
                        signature_path=sig_conf.signature_path,
                        placement=placement,
                    ))
                    if primary_placement is None:
                        primary_placement = placement

                if primary_placement is not None:
                    results.append(PageResult(
                        page_index=page_idx,
                        placement=primary_placement,
                        snapped_to_line=any(
                            result.placement.snapped_to_line
                            for result in signature_results
                        ),
                        clean=all(
                            result.placement.clean
                            for result in signature_results
                        ),
                        signature_results=signature_results,
                    ))

            os.makedirs(os.path.dirname(os.path.abspath(job.output_path)), exist_ok=True)
            # Elimina objetos sin referencia y compacta xref, pero evita comparar
            # todos los streams: garbage=4 domina el tiempo en PDFs con mucho texto.
            doc.save(job.output_path, garbage=2, deflate=True)
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
        occupied_rects: List[fitz.Rect],
        smart: bool = True,
    ) -> Tuple[Placement, Variation]:
        desired, variation = self._desired_placement(
            sig_conf, analysis.width, analysis.height, doc_id, page_index
        )
        if not smart:
            # Solo barrera física (fit_placement_inside_page en _apply_signature)
            return desired, variation
        return (
            self.finder.find_safe_placement(
                analysis, desired, occupied_rects=occupied_rects
            ),
            variation,
        )

    def _desired_placement(
        self,
        sig_conf: SigPlacement,
        page_width: float,
        page_height: float,
        doc_id: str,
        page_index: int,
    ) -> Tuple[Placement, Variation]:
        base_x = sig_conf.base_x_norm * page_width
        base_y = sig_conf.base_y_norm * page_height

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
        return desired, v

    def _apply_signature(
        self,
        page: fitz.Page,
        placement: Placement,
        base_img: Image.Image,
        sig_path: str,
        variation: Variation,
        image_xrefs: Dict[Tuple, int],
    ) -> Placement:
        # Segunda barrera: fit dentro de los límites de display de la página.
        placement = fit_placement_inside_page(
            placement, page.rect.width, page.rect.height, margin=0.0
        )
        target = placement.rotated_bbox
        if not self._inside_physical_page(target, page.rect.width, page.rect.height):
            raise ValueError("No fue posible encajar la firma dentro de la página.")

        rot = int(page.rotation) % 360

        if rot != 0:
            # insert_image() usa coordenadas NATIVAS del PDF (igual que insert_text).
            # Para páginas rotadas grandes, el rect en display space puede exceder
            # las dimensiones nativas → la imagen se descarta silenciosamente.
            # Solución: transformar los 4 vértices del rect display → nativo y
            # tomar el bounding box resultante (que sigue siendo un rectángulo
            # válido para rotaciones de 90° / 180° / 270°).
            derot = page.derotation_matrix
            corners = [
                fitz.Point(target.x0, target.y0) * derot,
                fitz.Point(target.x1, target.y0) * derot,
                fitz.Point(target.x0, target.y1) * derot,
                fitz.Point(target.x1, target.y1) * derot,
            ]
            xs = [p.x for p in corners]
            ys = [p.y for p in corners]
            target = fitz.Rect(min(xs), min(ys), max(xs), max(ys))

        # La clave de caché incluye rot para que imágenes pre-rotadas no se
        # reutilicen en páginas con orientación diferente.
        base_key = self._transformed_image_key(sig_path, placement, variation.pressure)
        cache_key = (*base_key, rot)
        xref = image_xrefs.get(cache_key, 0)

        try:
            if xref:
                page.insert_image(
                    target, xref=xref, keep_proportion=False, overlay=True
                )
            else:
                img_bytes = self._transformed_png_bytes(
                    base_key, base_img, placement, variation.pressure, page_rot=rot
                )
                xref = page.insert_image(
                    target,
                    stream=img_bytes,
                    keep_proportion=False,
                    overlay=True,
                )
        except TypeError:
            if xref:
                page.insert_image(target, xref=xref, overlay=True)
            else:
                img_bytes = self._transformed_png_bytes(
                    base_key, base_img, placement, variation.pressure, page_rot=rot
                )
                xref = page.insert_image(target, stream=img_bytes, overlay=True)

        image_xrefs[cache_key] = xref
        return placement

    @staticmethod
    def _transformed_image_key(
        sig_path: str,
        placement: Placement,
        pressure: float,
    ) -> Tuple[str, float, float, float]:
        return (sig_path, placement.angle, placement.opacity, pressure)

    def _transformed_png_bytes(
        self,
        image_key: Tuple[str, float, float, float],
        base_img: Image.Image,
        placement: Placement,
        pressure: float,
        page_rot: int = 0,
    ) -> bytes:
        # La clave de caché incluye page_rot para separar variantes por orientación
        cache_key = (*image_key, page_rot)
        cached = self._transformed_png_cache.get(cache_key)
        if cached is not None:
            self._transformed_png_cache.move_to_end(cache_key)
            return cached

        img = self._transform_image(base_img, placement, pressure)

        if page_rot != 0:
            # Pre-rotar la imagen CCW para compensar la rotación del visor.
            # El visor aplica Rotate grados CW; pre-rotar Rotate grados CCW
            # → la firma aparece correctamente orientada en pantalla.
            # Mismo razonamiento que fitz.Matrix(rot) en el foleador.
            img = img.rotate(
                page_rot,
                expand=True,
                resample=Image.BICUBIC,
                fillcolor=(0, 0, 0, 0),
            )

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()
        self._transformed_png_cache[cache_key] = img_bytes
        self._transformed_png_cache.move_to_end(cache_key)
        while len(self._transformed_png_cache) > self._transformed_png_cache_limit:
            self._transformed_png_cache.popitem(last=False)
        return img_bytes

    @staticmethod
    def _inside_physical_page(
        rect: fitz.Rect,
        page_width: float,
        page_height: float,
        tolerance: float = 1e-6,
    ) -> bool:
        return (
            rect.x0 >= -tolerance
            and rect.y0 >= -tolerance
            and rect.x1 <= page_width + tolerance
            and rect.y1 <= page_height + tolerance
        )

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


_PROCESS_ENGINE: Optional[SignatureEngine] = None
_PROCESS_VARIATION: Optional[VariationConfig] = None


def run_job_in_process(job: SignJob, variation: VariationConfig) -> JobResult:
    """Ejecuta un job en un proceso aislado, reutilizando cachés locales."""
    global _PROCESS_ENGINE, _PROCESS_VARIATION
    if _PROCESS_ENGINE is None or _PROCESS_VARIATION != variation:
        _PROCESS_ENGINE = SignatureEngine(variation)
        _PROCESS_VARIATION = variation
    return _PROCESS_ENGINE.run_job(job)
