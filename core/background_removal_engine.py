"""Batch engine for removing uniform backgrounds from images."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

from PIL import Image

from core.output_naming import unique_output_path_for_source
from core.sig_processing import remove_background


@dataclass
class BackgroundRemovalJob:
    image_path: str
    output_dir: str
    tolerance: float = 30.0
    add_tool_suffix: bool = True


@dataclass
class BackgroundRemovalResult:
    job: BackgroundRemovalJob
    output_path: str = ""
    success: bool = False
    error: str = ""
    width: int = 0
    height: int = 0


class BackgroundRemovalEngine:
    """Runs background removal for image batches and writes transparent PNGs."""

    def run_batch(
        self,
        jobs: List[BackgroundRemovalJob],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[BackgroundRemovalResult]:
        total = len(jobs)
        results: List[BackgroundRemovalResult] = []
        reserved: set[str] = set()

        for index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break

            source = Path(job.image_path)
            if progress:
                progress(index, total, f"Limpiando {source.name}...")

            try:
                output_dir = Path(job.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = unique_output_path_for_source(
                    output_dir,
                    source,
                    extension=".png",
                    tool_suffix="sin_fondo",
                    add_tool_suffix=job.add_tool_suffix,
                    reserved=reserved,
                    fallback="imagen",
                )

                with Image.open(source) as img:
                    cleaned = remove_background(img, tolerance=job.tolerance)
                    cleaned.save(output_path, format="PNG")
                    width, height = cleaned.size

                results.append(
                    BackgroundRemovalResult(
                        job=job,
                        output_path=str(output_path),
                        success=True,
                        width=width,
                        height=height,
                    )
                )
            except Exception as exc:
                results.append(
                    BackgroundRemovalResult(
                        job=job,
                        success=False,
                        error=f"{source.name}: {exc}",
                    )
                )

            if progress:
                progress(index + 1, total, f"{index + 1}/{total} imágenes procesadas")

        return results
