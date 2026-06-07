"""PDF to editable Word conversion engine."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

from core.ocr_engine import OcrConfig, OcrEngine, OcrJob, OcrJobResult, validate_tessdata
from core.output_paths import sanitize_filename


@dataclass(frozen=True)
class PdfToWordConfig:
    languages: str = "spa+eng"
    dpi: int = 300
    precision_mode: str = "balanced"
    preserve_native_text: bool = True
    enhance_scans: bool = True
    recover_rotated_pages: bool = True
    add_tool_suffix: bool = True


@dataclass
class PdfToWordJob:
    pdf_path: str
    output_dir: str
    base_name: str = ""
    config: PdfToWordConfig = PdfToWordConfig()


class PdfToWordEngine:
    """Converts PDFs into editable DOCX files using native text and OCR fallback."""

    def run_batch(
        self,
        jobs: List[PdfToWordJob],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[OcrJobResult]:
        if not jobs:
            return []
        config = jobs[0].config
        model_error = validate_tessdata(config.languages)
        if model_error:
            raise RuntimeError(model_error)
        _validate_docx_dependency()

        ocr_jobs = _to_ocr_jobs(jobs)
        return OcrEngine().run_batch(
            ocr_jobs,
            _to_ocr_config(config),
            progress=progress,
            should_cancel=should_cancel,
        )

    def run_job(
        self,
        job: PdfToWordJob,
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> OcrJobResult:
        results = self.run_batch([job], progress=progress, should_cancel=should_cancel)
        if results:
            return results[0]
        ocr_job = _to_ocr_jobs([job])[0]
        return OcrJobResult(job=ocr_job, success=False, error="No se genero ningun resultado.")


def make_pdf_to_word_jobs(
    pdf_paths: list[str],
    output_dir: str,
    config: PdfToWordConfig,
) -> list[PdfToWordJob]:
    used: set[str] = set()
    jobs: list[PdfToWordJob] = []
    for pdf_path in pdf_paths:
        base = sanitize_filename(Path(pdf_path).stem, fallback="documento")
        unique = base
        index = 2
        while unique.casefold() in used:
            unique = f"{base}_{index}"
            index += 1
        used.add(unique.casefold())
        jobs.append(
            PdfToWordJob(
                pdf_path=pdf_path,
                output_dir=output_dir,
                base_name=unique,
                config=config,
            )
        )
    return jobs


def _to_ocr_jobs(jobs: list[PdfToWordJob]) -> list[OcrJob]:
    return [
        OcrJob(
            pdf_path=job.pdf_path,
            output_dir=job.output_dir,
            base_name=job.base_name,
            tool_suffix="Word",
            add_tool_suffix=job.config.add_tool_suffix,
        )
        for job in jobs
    ]


def _to_ocr_config(config: PdfToWordConfig) -> OcrConfig:
    return OcrConfig(
        languages=config.languages,
        dpi=config.dpi,
        precision_mode=config.precision_mode,  # type: ignore[arg-type]
        preserve_native_text=config.preserve_native_text,
        enhance_scans=config.enhance_scans,
        recover_rotated_pages=config.recover_rotated_pages,
        output_mode="docx",
    )


def _validate_docx_dependency() -> None:
    try:
        import docx  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "La exportacion Word requiere python-docx. "
            "Instala dependencias con: pip install -r requirements.txt"
        ) from exc
