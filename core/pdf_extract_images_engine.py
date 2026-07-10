"""Embedded image/resource extraction engine for PDFs."""
from __future__ import annotations

from dataclasses import dataclass, field
import io
from pathlib import Path
from typing import Callable, List

import pikepdf

from core.output_naming import output_stem_for_source
from core.output_paths import unique_output_path


@dataclass(frozen=True)
class ExtractImagesConfig:
    deduplicate: bool = True
    min_width: int = 1
    min_height: int = 1


@dataclass
class ExtractImagesJob:
    pdf_path: str
    output_dir: str
    base_name: str = ""
    tool_suffix: str = "recursos"
    add_tool_suffix: bool = True


@dataclass
class ExtractedImageResult:
    output_path: str = ""
    success: bool = True
    error: str = ""
    page_index: int = 0
    xref: int = 0
    width: int = 0
    height: int = 0
    ext: str = ""
    duplicate: bool = False

    @property
    def meta_text(self) -> str:
        page = f"pagina {self.page_index + 1}" if self.page_index >= 0 else "sin pagina"
        size = f"{self.width} x {self.height} px" if self.width and self.height else "tamano desconocido"
        fmt = self.ext.upper() if self.ext else "formato desconocido"
        return f"{fmt} · {size} · {page} · xref {self.xref}"


@dataclass
class ExtractImagesJobResult:
    job: ExtractImagesJob
    image_results: List[ExtractedImageResult] = field(default_factory=list)
    success: bool = True
    error: str = ""
    skipped_duplicates: int = 0
    skipped_small: int = 0

    @property
    def output_path(self) -> str:
        for result in self.image_results:
            if result.success and result.output_path:
                return result.output_path
        return ""


class PdfExtractImagesEngine:
    """Extracts embedded image resources without rendering full PDF pages."""

    def run_batch(
        self,
        jobs: List[ExtractImagesJob],
        config: ExtractImagesConfig,
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[ExtractImagesJobResult]:
        results: List[ExtractImagesJobResult] = []
        total = len(jobs)
        for index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(index, total, f"Extrayendo recursos de {Path(job.pdf_path).name}...")
            results.append(self.run_job(job, config, should_cancel=should_cancel))
            if progress:
                progress(index + 1, total, f"{index + 1}/{total} PDFs procesados")
        return results

    def run_job(
        self,
        job: ExtractImagesJob,
        config: ExtractImagesConfig,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ExtractImagesJobResult:
        out_dir = Path(job.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        source = Path(job.pdf_path)
        if not source.exists():
            return ExtractImagesJobResult(
                job=job,
                success=False,
                error="El PDF de origen no existe.",
            )

        try:
            document = pikepdf.Pdf.open(source)
            if document.is_encrypted:
                document.close()
                raise RuntimeError("El PDF esta protegido o cifrado.")
            if len(document.pages) <= 0:
                document.close()
                raise RuntimeError("El PDF no tiene paginas.")

            with document:
                base = output_stem_for_source(
                    job.base_name or job.pdf_path,
                    tool_suffix=job.tool_suffix,
                    add_tool_suffix=job.add_tool_suffix,
                    fallback="documento",
                )
                seen_objects: set[tuple[int, int]] = set()
                reserved: set[str] = set()
                results: list[ExtractedImageResult] = []
                skipped_duplicates = 0
                skipped_small = 0

                for page_index, page in enumerate(document.pages):
                    if should_cancel and should_cancel():
                        break
                    for _resource_name, image_object in page.get_images(recursive=True).items():
                        object_id = tuple(image_object.objgen)
                        if config.deduplicate and object_id != (0, 0) and object_id in seen_objects:
                            skipped_duplicates += 1
                            continue
                        if object_id != (0, 0):
                            seen_objects.add(object_id)
                        result = self._extract_one(
                            image_object,
                            int(object_id[0]),
                            out_dir,
                            base,
                            page_index,
                            reserved,
                            config,
                        )
                        if result is None:
                            skipped_small += 1
                        else:
                            results.append(result)

                ok = [result for result in results if result.success]
                return ExtractImagesJobResult(
                    job=job,
                    image_results=results,
                    success=bool(ok),
                    error="" if ok else "No se encontraron imagenes embebidas.",
                    skipped_duplicates=skipped_duplicates,
                    skipped_small=skipped_small,
                )
        except pikepdf.PasswordError:
            return ExtractImagesJobResult(
                job=job,
                success=False,
                error="El PDF esta protegido o cifrado.",
            )
        except Exception as exc:
            return ExtractImagesJobResult(job=job, success=False, error=str(exc))

    def _extract_one(
        self,
        image_object: pikepdf.Stream,
        xref: int,
        out_dir: Path,
        base: str,
        page_index: int,
        reserved: set[str],
        config: ExtractImagesConfig,
    ) -> ExtractedImageResult | None:
        try:
            image = pikepdf.PdfImage(image_object)
            width = int(image.width)
            height = int(image.height)
            if width < config.min_width or height < config.min_height:
                return None
            buffer = io.BytesIO()
            ext = _normalize_ext(image.extract_to(stream=buffer))
            filename = f"{base}_p{page_index + 1:03d}_x{xref}.{ext}"
            output = unique_output_path(out_dir, filename, reserved=reserved, fallback="imagen")
            output.write_bytes(buffer.getvalue())
            return ExtractedImageResult(
                output_path=str(output),
                success=True,
                page_index=page_index,
                xref=xref,
                width=width,
                height=height,
                ext=ext,
            )
        except Exception as exc:
            return ExtractedImageResult(
                output_path="",
                success=False,
                error=str(exc),
                page_index=page_index,
                xref=xref,
            )


def _normalize_ext(ext: str) -> str:
    clean = ext.lower().strip().lstrip(".")
    if clean == "jpeg":
        return "jpg"
    return clean or "bin"
