"""Motor de conversión PDF → Imágenes.

Exporta cada página de un PDF como imagen de alta resolución (PNG, JPG o WebP).
También soporta modo "imagen panorámica vertical": concatena todas las páginas
en una sola imagen alta.

La renderización usa fitz.Page.get_pixmap() sin rasterización intermedia,
conservando la calidad máxima posible al DPI configurado.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Literal, Optional

import fitz
from PIL import Image

from .output_naming import output_stem_for_source


# ====================================================================== #
#  Tipos de datos
# ====================================================================== #

ImageFormat = Literal["png", "jpg", "webp"]


@dataclass
class PdfToImagesConfig:
    format: ImageFormat = "png"
    dpi: int = 150
    panoramic: bool = False   # True = una sola imagen vertical con todas las páginas
    jpg_quality: int = 90     # solo aplica para JPG/WebP


@dataclass
class PdfToImagesJob:
    pdf_path: str
    output_dir: str
    base_name: str = ""       # vacío = usa el stem del PDF
    tool_suffix: str = "imagenes"
    add_tool_suffix: bool = True


@dataclass
class ImageResult:
    """Resultado de una imagen exportada. Compatible con GenericPdfViewer."""
    output_path: str = ""
    success: bool = True
    error: str = ""
    page_index: int = 0       # -1 si es imagen panorámica


@dataclass
class PdfToImagesJobResult:
    """Resultado de un PdfToImagesJob."""
    job: PdfToImagesJob
    image_results: List[ImageResult] = field(default_factory=list)
    success: bool = True
    error: str = ""

    @property
    def output_path(self) -> str:
        """Primer archivo generado (compatibilidad con GenericPdfViewer)."""
        for r in self.image_results:
            if r.success and r.output_path:
                return r.output_path
        return ""


# ====================================================================== #
#  Motor
# ====================================================================== #

class PdfToImagesEngine:
    """Convierte páginas PDF a imágenes."""

    def run_batch(
        self,
        jobs: List[PdfToImagesJob],
        config: PdfToImagesConfig,
        progress: Optional[Callable[[int, int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> List[PdfToImagesJobResult]:
        results: List[PdfToImagesJobResult] = []
        total = len(jobs)

        for i, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(i, total, f"Convirtiendo: {Path(job.pdf_path).name}")
            result = self._process_job(job, config, should_cancel=should_cancel)
            results.append(result)

        if progress and not (should_cancel and should_cancel()):
            progress(total, total, "Conversion completada")

        return results

    def _process_job(
        self,
        job: PdfToImagesJob,
        cfg: PdfToImagesConfig,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> PdfToImagesJobResult:
        try:
            doc = fitz.open(job.pdf_path)
        except Exception as e:
            return PdfToImagesJobResult(job=job, success=False, error=str(e))

        base = output_stem_for_source(
            job.base_name or job.pdf_path,
            tool_suffix=job.tool_suffix,
            add_tool_suffix=job.add_tool_suffix,
            fallback="documento",
        )
        out_dir = Path(job.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        mat = fitz.Matrix(cfg.dpi / 72.0, cfg.dpi / 72.0)
        image_results: List[ImageResult] = []

        try:
            if cfg.panoramic:
                image_results.append(
                    self._export_panoramic(
                        doc,
                        mat,
                        cfg,
                        out_dir,
                        base,
                        should_cancel=should_cancel,
                    )
                )
            else:
                for page_idx in range(doc.page_count):
                    if should_cancel and should_cancel():
                        break
                    image_results.append(
                        self._export_page(doc, page_idx, mat, cfg, out_dir, base)
                    )
        finally:
            doc.close()

        ok = sum(1 for r in image_results if r.success)
        return PdfToImagesJobResult(
            job=job,
            image_results=image_results,
            success=ok > 0,
            error="" if ok > 0 else "Ninguna imagen se generó",
        )

    def _export_page(
        self,
        doc: fitz.Document,
        page_idx: int,
        mat: fitz.Matrix,
        cfg: PdfToImagesConfig,
        out_dir: Path,
        base: str,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> ImageResult:
        out_path = out_dir / f"{base}_p{page_idx + 1:03d}.{cfg.format}"
        try:
            pm = doc[page_idx].get_pixmap(matrix=mat, alpha=(cfg.format == "png"))
            img = self._pixmap_to_pil(pm, cfg.format)
            self._save_image(img, out_path, cfg)
            return ImageResult(output_path=str(out_path), success=True, page_index=page_idx)
        except Exception as e:
            return ImageResult(output_path="", success=False, error=str(e), page_index=page_idx)

    def _export_panoramic(
        self,
        doc: fitz.Document,
        mat: fitz.Matrix,
        cfg: PdfToImagesConfig,
        out_dir: Path,
        base: str,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> ImageResult:
        out_path = out_dir / f"{base}_panoramico.{cfg.format}"
        try:
            pages_pil: List[Image.Image] = []
            for page_idx in range(doc.page_count):
                if should_cancel and should_cancel():
                    return ImageResult(
                        output_path="",
                        success=False,
                        error="Operación cancelada.",
                        page_index=-1,
                    )
                pm = doc[page_idx].get_pixmap(matrix=mat, alpha=False)
                pages_pil.append(self._pixmap_to_pil(pm, "png"))

            total_h = sum(p.height for p in pages_pil)
            max_w = max(p.width for p in pages_pil)
            combined = Image.new("RGB", (max_w, total_h), color=(255, 255, 255))
            y_offset = 0
            for p in pages_pil:
                x_offset = (max_w - p.width) // 2
                combined.paste(p, (x_offset, y_offset))
                y_offset += p.height

            self._save_image(combined, out_path, cfg)
            return ImageResult(output_path=str(out_path), success=True, page_index=-1)
        except Exception as e:
            return ImageResult(output_path="", success=False, error=str(e), page_index=-1)

    @staticmethod
    def _pixmap_to_pil(pm: fitz.Pixmap, fmt: str) -> Image.Image:
        mode = "RGBA" if pm.alpha else "RGB"
        img = Image.frombytes(mode, (pm.width, pm.height), pm.samples)
        if fmt != "png" and mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            return bg
        return img

    @staticmethod
    def _save_image(img: Image.Image, path: Path, cfg: PdfToImagesConfig) -> None:
        fmt = cfg.format.upper()
        if fmt == "JPG":
            fmt = "JPEG"
        kwargs = {}
        if fmt in ("JPEG", "WEBP"):
            kwargs["quality"] = cfg.jpg_quality
        img.save(str(path), format=fmt, **kwargs)
