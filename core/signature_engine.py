"""
Motor de firma masiva — v2.

Soporta múltiples firmas por documento en una sola pasada,
sin archivos temporales intermedios.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Dict, List, Optional, Tuple
import io

from PIL import Image, ImageEnhance, ImageFilter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from core.pdf_backend import (
    PdfRenderDocument,
    Rect,
    apply_page_overlays,
    normalize_pdf,
)
from .pdf_analyzer import PdfAnalyzer, PageAnalysis
from .safe_zone import SafeZoneFinder, Placement, fit_placement_inside_page
from .signature_naturalizer import naturalize_signature
from .variation import Variation, VariationGenerator, VariationConfig


_SIGNATURE_PROCESS_DPI = 360.0


def _process_image_size(
    base_size: Tuple[int, int],
    placement: Placement,
) -> Tuple[int, int]:
    base_w, base_h = max(1, int(base_size[0])), max(1, int(base_size[1]))
    target_w = max(
        1,
        int((max(1.0, placement.width) * _SIGNATURE_PROCESS_DPI / 72.0) + 0.999),
    )
    target_h = max(
        1,
        int((max(1.0, placement.height) * _SIGNATURE_PROCESS_DPI / 72.0) + 0.999),
    )
    scale = min(1.0, target_w / base_w, target_h / base_h)
    if scale >= 0.98:
        return base_w, base_h
    return max(1, int(base_w * scale)), max(1, int(base_h * scale))


def _prepare_image_for_placement(
    base: Image.Image,
    placement: Placement,
) -> Image.Image:
    target_size = _process_image_size(base.size, placement)
    if target_size == base.size:
        return base
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    return base.resize(target_size, resampling)


@dataclass
class SigPlacement:
    """Posición y tamaño de una firma individual dentro de un job."""
    signature_path: str
    base_x_norm: float       # centro X normalizado (0..1)
    base_y_norm: float       # centro Y normalizado (0..1)
    base_width_pt: float     # ancho en puntos PDF
    base_height_pt: float    # alto en puntos PDF
    base_angle: float = 0.0  # ángulo base en grados
    signature_uid: str = ""
    signature_label: str = ""
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
    signature_uid: str = ""
    signature_label: str = ""


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


@dataclass(frozen=True)
class _SignatureOverlay:
    page_index: int
    image_bytes: bytes
    left: float
    top: float
    width: float
    height: float


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
        self._transformed_png_cache: OrderedDict[Tuple[object, ...], bytes] = OrderedDict()
        self._transformed_png_cache_limit = 16

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #

    def preflight_bounds(self, jobs: List[SignJob]) -> BoundsPreflight:
        """Calcula ajustes de borde previstos sin rasterizar ni modificar PDFs."""
        summary = BoundsPreflight()
        for job in jobs:
            try:
                document = PdfRenderDocument(job.pdf_path)
            except Exception:
                summary.skipped_documents += 1
                continue
            try:
                target_pages = (
                    job.pages if job.pages is not None
                    else list(range(document.page_count))
                )
                for page_idx in target_pages:
                    info = document.page_info(page_idx)
                    for sig_conf in job.signatures:
                        if page_idx in sig_conf.excluded_pages:
                            continue
                        desired = self._desired_placement(
                            sig_conf,
                            info.width_pt,
                            info.height_pt,
                            job.pdf_path,
                            page_idx,
                        )[0]
                        bounded = fit_placement_inside_page(
                            desired, info.width_pt, info.height_pt, margin=0.0
                        )
                        summary.signatures_checked += 1
                        if bounded.adjusted_to_page:
                            summary.adjusted_to_page += 1
                        if bounded.scaled_to_fit:
                            summary.scaled_to_fit += 1
            finally:
                document.close()
        return summary

    def run_job(
        self,
        job: SignJob,
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> JobResult:
        """Procesa un documento aplicando todas las firmas en una sola pasada."""
        try:
            analysis_document = PdfRenderDocument(job.pdf_path)
        except Exception as e:
            return JobResult(job=job, output_path="", success=False,
                             error=f"No se pudo abrir PDF: {e}")

        total_pages = (
            len(job.pages) if job.pages is not None else analysis_document.page_count
        )

        try:
            results, overlays = self._process_job_pages(
                analysis_document,
                job,
                progress=progress,
                apply_images=True,
            )
            self._write_signature_overlays(job.pdf_path, job.output_path, overlays)
            if progress:
                progress(total_pages, total_pages, "Guardado")

        except Exception as e:
            return JobResult(job=job, output_path="", success=False, error=str(e))
        finally:
            analysis_document.close()

        return JobResult(
            job=job,
            output_path=job.output_path,
            page_results=results,
            success=True,
        )

    def plan_job(
        self,
        job: SignJob,
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> JobResult:
        """Calcula colocaciones y advertencias sin escribir un PDF borrador.

        La etapa de revision solo necesita metadatos: el visor carga el PDF
        original y dibuja las firmas encima. Evitar el guardado del borrador
        ahorra la rasterizacion de firmas y una escritura completa del PDF.
        """
        try:
            analysis_document = PdfRenderDocument(job.pdf_path)
        except Exception as e:
            return JobResult(job=job, output_path="", success=False,
                             error=f"No se pudo abrir PDF: {e}")

        try:
            results, _ = self._process_job_pages(
                analysis_document,
                job,
                progress=progress,
                apply_images=False,
            )
            target_pages = (job.pages if job.pages is not None
                            else list(range(analysis_document.page_count)))
            if progress:
                progress(len(target_pages), len(target_pages), "Plan listo")
        except Exception as e:
            return JobResult(job=job, output_path="", success=False, error=str(e))
        finally:
            analysis_document.close()

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

    def _process_job_pages(
        self,
        analysis_document: PdfRenderDocument,
        job: SignJob,
        *,
        progress: Optional[Callable[[int, int, str], None]],
        apply_images: bool,
    ) -> tuple[List[PageResult], list[_SignatureOverlay]]:
        results: List[PageResult] = []
        target_pages = (job.pages if job.pages is not None
                        else list(range(analysis_document.page_count)))
        total = len(target_pages)
        overlays: list[_SignatureOverlay] = []

        for i, page_idx in enumerate(target_pages):
            if progress:
                progress(i, total, f"Página {page_idx + 1}/{analysis_document.page_count}")

            analysis = self.analyzer.analyze_page(analysis_document, page_idx)
            info = analysis_document.page_info(page_idx)
            primary_placement: Optional[Placement] = None
            signature_results: List[SignaturePageResult] = []
            occupied_rects: List[Rect] = []

            for sig_conf in job.signatures:
                if page_idx in sig_conf.excluded_pages:
                    continue
                placement, variation = self._compute_placement(
                    sig_conf, analysis, job.pdf_path, page_idx, occupied_rects,
                    smart=job.smart_placement,
                )
                if apply_images:
                    base_img = self._get_image(sig_conf.signature_path)
                    placement = self._fit_placement_for_page_size(
                        info.width_pt,
                        info.height_pt,
                        placement,
                    )
                    overlays.append(
                        self._signature_overlay(
                            page_idx,
                            sig_conf.signature_path,
                            placement,
                            base_img,
                            variation,
                        )
                    )
                else:
                    placement = self._fit_placement_for_page_size(
                        info.width_pt,
                        info.height_pt,
                        placement,
                    )
                occupied_rects.append(placement.rotated_bbox)
                signature_results.append(SignaturePageResult(
                    signature_path=sig_conf.signature_path,
                    placement=placement,
                    signature_uid=sig_conf.signature_uid,
                    signature_label=sig_conf.signature_label,
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

        return results, overlays

    def _compute_placement(
        self,
        sig_conf: SigPlacement,
        analysis: PageAnalysis,
        doc_id: str,
        page_index: int,
        occupied_rects: List[Rect],
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

        v = self.variation_for_signature(doc_id, sig_conf.signature_path, page_index)

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

    def variation_for_signature(
        self,
        doc_id: str,
        signature_path: str,
        page_index: int,
    ) -> Variation:
        """Devuelve la variación determinista usada para una firma/página."""
        # Semilla única por (doc, firma, página). Usamos solo nombres de archivo
        # para mantener estabilidad aunque el directorio temporal cambie.
        import os as _os
        doc_name = _os.path.basename(doc_id)
        sig_name = _os.path.basename(signature_path)
        seed_key = doc_name + "\x00" + sig_name
        return self.variation_gen.variation_for(seed_key, page_index)

    def preview_image(
        self,
        signature_path: str,
        placement: Placement,
        doc_id: str,
        page_index: int,
    ) -> Image.Image:
        """Imagen RGBA naturalizada para preview; la rotación la aplica Qt."""
        base_img = self._get_image(signature_path)
        variation = self.variation_for_signature(doc_id, signature_path, page_index)
        return self._transform_image(
            base_img, placement, variation, apply_rotation=False
        )

    def export_review_instances(
        self,
        source_path: str,
        output_path: str,
        placements_by_page: dict[int, list[tuple[str, Placement]]],
        *,
        progress: Optional[Callable[[int, int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> int:
        """Exporta instancias revisadas sin recalcular zona segura."""
        overlays: list[_SignatureOverlay] = []
        with PdfRenderDocument(source_path) as document:
            total = document.page_count
            for page_index in range(total):
                if should_cancel and should_cancel():
                    raise RuntimeError("Exportacion cancelada por el usuario")
                if progress:
                    progress(
                        page_index,
                        max(1, total),
                        f"Generando pagina {page_index + 1}/{total}",
                    )
                info = document.page_info(page_index)
                for signature_path, placement in placements_by_page.get(page_index, ()):
                    base_img = self._get_image(signature_path)
                    variation = self.variation_for_signature(
                        source_path, signature_path, page_index
                    )
                    fitted = self._fit_placement_for_page_size(
                        info.width_pt,
                        info.height_pt,
                        placement,
                    )
                    overlays.append(
                        self._signature_overlay(
                            page_index,
                            signature_path,
                            fitted,
                            base_img,
                            variation,
                        )
                    )
        self._write_signature_overlays(source_path, output_path, overlays)
        return total

    def _signature_overlay(
        self,
        page_index: int,
        sig_path: str,
        placement: Placement,
        base_img: Image.Image,
        variation: Variation,
    ) -> _SignatureOverlay:
        bounds = placement.rotated_bbox
        base_key = self._transformed_image_key(
            sig_path, placement, variation, base_img.size
        )
        return _SignatureOverlay(
            page_index=page_index,
            image_bytes=self._transformed_png_bytes(
                base_key, base_img, placement, variation
            ),
            left=bounds.x0,
            top=bounds.y0,
            width=bounds.width,
            height=bounds.height,
        )

    def _write_signature_overlays(
        self,
        source_path: str,
        output_path: str,
        overlays: list[_SignatureOverlay],
    ) -> None:
        source = Path(source_path).resolve()
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.resolve() == source:
            raise ValueError("La salida no puede sobrescribir el PDF de origen.")
        if not overlays:
            normalize_pdf(source, output)
            return

        grouped: dict[int, list[_SignatureOverlay]] = {}
        for overlay in overlays:
            grouped.setdefault(overlay.page_index, []).append(overlay)

        with PdfRenderDocument(source) as document:
            with TemporaryDirectory(prefix="pdflex-signature-") as temp_dir:
                overlay_path = Path(temp_dir) / "overlay.pdf"
                canvas = Canvas(
                    str(overlay_path),
                    pagesize=(1, 1),
                    pageCompression=1,
                )
                mapping: dict[int, int] = {}
                reader_cache: dict[bytes, ImageReader] = {}
                for overlay_index, page_index in enumerate(sorted(grouped)):
                    info = document.page_info(page_index)
                    canvas.setPageSize((info.width_pt, info.height_pt))
                    for overlay in grouped[page_index]:
                        reader = reader_cache.get(overlay.image_bytes)
                        if reader is None:
                            reader = ImageReader(io.BytesIO(overlay.image_bytes))
                            reader_cache[overlay.image_bytes] = reader
                        canvas.drawImage(
                            reader,
                            overlay.left,
                            info.height_pt - overlay.top - overlay.height,
                            width=overlay.width,
                            height=overlay.height,
                            preserveAspectRatio=False,
                            mask="auto",
                        )
                    canvas.showPage()
                    mapping[page_index] = overlay_index
                canvas.save()
                apply_page_overlays(source, overlay_path, mapping, output, over=True)

    def _fit_placement_for_page_size(
        self,
        page_width: float,
        page_height: float,
        placement: Placement,
    ) -> Placement:
        placement = fit_placement_inside_page(
            placement, page_width, page_height, margin=0.0
        )
        target = placement.rotated_bbox
        if not self._inside_physical_page(target, page_width, page_height):
            raise ValueError("No fue posible encajar la firma dentro de la página.")
        return placement

    @staticmethod
    def _transformed_image_key(
        sig_path: str,
        placement: Placement,
        variation: Variation,
        base_size: Tuple[int, int],
    ) -> Tuple[object, ...]:
        process_size = _process_image_size(base_size, placement)
        if variation.has_stroke_variation or abs(float(variation.pressure)) > 1e-9:
            stroke_fields: Tuple[object, ...] = (
                round(float(variation.pressure), 6),
                variation.stroke_seed,
                variation.stroke_mode,
                round(float(variation.stroke_strength), 6),
                round(float(variation.stretch_x), 6),
                round(float(variation.stretch_y), 6),
                round(float(variation.stroke_width_delta), 6),
                round(float(variation.ink_flow), 6),
                round(float(variation.dryness), 6),
            )
        else:
            stroke_fields = (0.0, 0, "exacta", 0.0, 1.0, 1.0, 0.0, 0.0, 0.0)
        return (
            sig_path,
            process_size,
            round(float(placement.angle), 6),
            round(float(placement.opacity), 6),
            *stroke_fields,
        )

    def _transformed_png_bytes(
        self,
        image_key: Tuple[object, ...],
        base_img: Image.Image,
        placement: Placement,
        variation: Variation,
    ) -> bytes:
        cache_key = image_key
        cached = self._transformed_png_cache.get(cache_key)
        if cached is not None:
            self._transformed_png_cache.move_to_end(cache_key)
            return cached

        img = self._transform_image(base_img, placement, variation)

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
        rect: Rect,
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
        self,
        base: Image.Image,
        placement: Placement,
        variation: Variation,
        *,
        apply_rotation: bool = True,
    ) -> Image.Image:
        img = naturalize_signature(
            _prepare_image_for_placement(base, placement),
            variation,
        )
        pressure = variation.pressure

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

        if apply_rotation and abs(placement.angle) > 0.01:
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


def plan_job_in_process(job: SignJob, variation: VariationConfig) -> JobResult:
    """Calcula un borrador editable en un proceso aislado."""
    global _PROCESS_ENGINE, _PROCESS_VARIATION
    if _PROCESS_ENGINE is None or _PROCESS_VARIATION != variation:
        _PROCESS_ENGINE = SignatureEngine(variation)
        _PROCESS_VARIATION = variation
    return _PROCESS_ENGINE.plan_job(job)
