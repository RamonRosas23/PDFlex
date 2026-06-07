"""PDF compression / optimization engine."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Callable, List
import uuid

import fitz


@dataclass(frozen=True)
class CompressProfile:
    id: str
    label: str
    description: str
    dpi_threshold: int
    dpi_target: int
    quality: int
    set_to_gray: bool = False


PROFILES: dict[str, CompressProfile] = {
    "email": CompressProfile(
        id="email",
        label="Correo",
        description="Maxima reduccion razonable para enviar o subir a portales.",
        dpi_threshold=130,
        dpi_target=110,
        quality=58,
    ),
    "balanced": CompressProfile(
        id="balanced",
        label="Equilibrado",
        description="Buen balance entre legibilidad y tamano final.",
        dpi_threshold=180,
        dpi_target=150,
        quality=74,
    ),
    "quality": CompressProfile(
        id="quality",
        label="Alta calidad",
        description="Limpieza ligera y reduccion conservadora.",
        dpi_threshold=300,
        dpi_target=240,
        quality=88,
    ),
}


@dataclass
class CompressJob:
    pdf_path: str
    output_path: str
    profile_id: str = "balanced"


@dataclass
class CompressResult:
    job: CompressJob
    output_path: str = ""
    success: bool = False
    error: str = ""
    warning: str = ""
    profile_label: str = ""
    input_bytes: int = 0
    output_bytes: int = 0
    total_pages: int = 0

    @property
    def reduction_pct(self) -> float:
        if self.input_bytes <= 0:
            return 0.0
        return max(0.0, (1.0 - (self.output_bytes / self.input_bytes)) * 100.0)

    @property
    def meta_text(self) -> str:
        before = format_bytes(self.input_bytes)
        after = format_bytes(self.output_bytes)
        ratio = f"{self.reduction_pct:.1f}% menos"
        if self.warning:
            return f"{before} -> {after} · {ratio} · {self.warning}"
        return f"{before} -> {after} · {ratio}"


class PdfCompressEngine:
    """Optimizes PDF files using PyMuPDF image rewriting and clean saves."""

    def run_batch(
        self,
        jobs: List[CompressJob],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[CompressResult]:
        total = len(jobs)
        results: List[CompressResult] = []
        for index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(index, total, f"Optimizando {Path(job.pdf_path).name}...")
            result = self.run_job(job)
            results.append(result)
            if progress:
                progress(index + 1, total, f"{index + 1}/{total} PDFs procesados")
        return results

    def run_job(self, job: CompressJob) -> CompressResult:
        profile = profile_for(job.profile_id)
        source = Path(job.pdf_path)
        output = Path(job.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        if not source.exists():
            return CompressResult(
                job=job,
                success=False,
                error="El PDF de origen no existe.",
                profile_label=profile.label,
            )

        input_size = source.stat().st_size
        temp_output = output.with_name(
            f"{output.stem}.tmp-{uuid.uuid4().hex[:8]}{output.suffix or '.pdf'}"
        )
        doc: fitz.Document | None = None

        try:
            doc = fitz.open(str(source))
            if doc.is_encrypted:
                raise RuntimeError("El PDF esta protegido o cifrado.")
            total_pages = doc.page_count
            if total_pages <= 0:
                raise RuntimeError("El PDF no tiene paginas.")

            doc.rewrite_images(
                dpi_threshold=profile.dpi_threshold,
                dpi_target=profile.dpi_target,
                quality=profile.quality,
                lossy=True,
                lossless=True,
                bitonal=False,
                color=True,
                gray=True,
                set_to_gray=profile.set_to_gray,
            )
            doc.save(
                str(temp_output),
                garbage=4,
                clean=True,
                deflate=True,
                deflate_images=True,
                deflate_fonts=True,
                use_objstms=1,
                compression_effort=75,
            )
            doc.close()
            doc = None

            temp_size = temp_output.stat().st_size
            warning = ""
            if temp_size > input_size:
                shutil.copy2(str(source), str(output))
                output_size = output.stat().st_size
                warning = "ya estaba optimizado"
            else:
                _replace_file(temp_output, output)
                output_size = output.stat().st_size

            return CompressResult(
                job=job,
                output_path=str(output),
                success=True,
                warning=warning,
                profile_label=profile.label,
                input_bytes=input_size,
                output_bytes=output_size,
                total_pages=total_pages,
            )
        except Exception as exc:
            return CompressResult(
                job=job,
                success=False,
                error=str(exc),
                profile_label=profile.label,
                input_bytes=input_size,
            )
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass
            try:
                if temp_output.exists():
                    temp_output.unlink()
            except OSError:
                pass


def profile_for(profile_id: str) -> CompressProfile:
    return PROFILES.get(profile_id, PROFILES["balanced"])


def format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


def _replace_file(source: Path, dest: Path) -> None:
    try:
        source.replace(dest)
    except OSError:
        shutil.copy2(str(source), str(dest))
        source.unlink(missing_ok=True)
