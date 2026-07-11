"""PDF compression / optimization engine."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from io import BytesIO
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Callable, List
import uuid

import numpy as np
import pikepdf

from core.pdf_backend import (
    ImagePdfPage,
    PdfRenderDocument,
    Rect,
    SourcePage,
    assemble_pages,
    create_image_pdf,
    normalize_pdf,
)
from core.pdf_page_rules import (
    EffectivePageCompression,
    PageCompressionPlan,
    PageCompressionRule,
    build_page_compression_plan,
)


_VALIDATION_MAX_SIDE = 1200
_VALIDATION_MIN_DPI = 24.0
_VALIDATION_MAX_DPI = 72.0
_AUTO_GHOSTSCRIPT_FAST_ACCEPT_REDUCTION = 10.0
_AUTO_FAST_GHOSTSCRIPT_ACCEPT_REDUCTION = 25.0
_AUTO_FAST_GHOSTSCRIPT_QUALITY_ACCEPT_REDUCTION = 20.0
_MIN_USEFUL_REDUCTION_PCT = 1.0
_LEGACY_INTERNAL_ENGINE = "py" + "mu" + "pdf"


@dataclass(frozen=True)
class CompressProfile:
    id: str
    label: str
    description: str
    dpi_threshold: int
    dpi_target: int
    quality: int
    set_to_gray: bool = False
    rewrite_lossy: bool = True
    rewrite_lossless: bool = True
    max_visual_mean_delta: float = 14.0
    max_visual_p95_delta: float = 64.0
    max_changed_pixel_ratio: float = 0.18
    max_validation_pages: int = 8


PROFILES: dict[str, CompressProfile] = {
    "email": CompressProfile(
        id="email",
        label="Maxima reduccion",
        description="Peso minimo razonable para enviar o subir a portales.",
        dpi_threshold=130,
        dpi_target=110,
        quality=62,
        max_visual_mean_delta=22.0,
        max_visual_p95_delta=92.0,
        max_changed_pixel_ratio=0.28,
    ),
    "balanced": CompressProfile(
        id="balanced",
        label="Equilibrado",
        description="Buen balance entre legibilidad y tamano final.",
        dpi_threshold=180,
        dpi_target=150,
        quality=76,
        max_visual_mean_delta=14.0,
        max_visual_p95_delta=64.0,
        max_changed_pixel_ratio=0.18,
    ),
    "quality": CompressProfile(
        id="quality",
        label="Alta calidad",
        description="Alta legibilidad con reduccion real en escaneos de oficina.",
        dpi_threshold=220,
        dpi_target=200,
        quality=86,
        max_visual_mean_delta=10.0,
        max_visual_p95_delta=48.0,
        max_changed_pixel_ratio=0.14,
    ),
}


@dataclass(frozen=True)
class CompressOptions:
    engine_mode: str = "auto"  # auto, internal, qpdf, ghostscript, fast, turbo
    dpi_threshold: int | None = None
    dpi_target: int | None = None
    quality: int | None = None
    set_to_gray: bool | None = None
    validation_level: str = "standard"  # strict, standard, relaxed


@dataclass
class CompressJob:
    pdf_path: str
    output_path: str
    profile_id: str = "balanced"
    options: CompressOptions = field(default_factory=CompressOptions)
    page_rules: List[PageCompressionRule] = field(default_factory=list)


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
    strategy: str = ""
    validation_pages: int = 0
    pages_compressed: int = 0
    pages_excluded: int = 0
    pages_custom: int = 0
    page_rule_summary: str = ""
    rule_warnings: list[str] = field(default_factory=list)

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
        parts = [f"{before} -> {after}", ratio]
        if self.strategy:
            parts.append(self.strategy)
        if self.page_rule_summary:
            parts.append(self.page_rule_summary)
        if self.warning:
            parts.append(self.warning)
        parts.extend(self.rule_warnings)
        return " · ".join(parts)


def compress_job_to_dict(job: CompressJob) -> dict:
    return {
        "pdf_path": job.pdf_path,
        "output_path": job.output_path,
        "profile_id": job.profile_id,
        "options": asdict(job.options),
        "page_rules": [asdict(rule) for rule in job.page_rules],
    }


def compress_job_from_dict(data: dict) -> CompressJob:
    options_data = data.get("options") or {}
    rule_items = data.get("page_rules") or []
    return CompressJob(
        pdf_path=str(data.get("pdf_path", "")),
        output_path=str(data.get("output_path", "")),
        profile_id=str(data.get("profile_id", "balanced")),
        options=CompressOptions(**options_data),
        page_rules=[PageCompressionRule(**rule) for rule in rule_items],
    )


def compress_result_to_dict(result: CompressResult) -> dict:
    payload = asdict(result)
    payload["job"] = compress_job_to_dict(result.job)
    return payload


def compress_result_from_dict(data: dict) -> CompressResult:
    payload = dict(data)
    payload["job"] = compress_job_from_dict(payload.get("job") or {})
    return CompressResult(**payload)


@dataclass(frozen=True)
class OptionalEngineStatus:
    id: str
    label: str
    available: bool
    path: str = ""
    source: str = ""


@dataclass
class _PdfAnalysis:
    page_count: int
    image_count: int = 0
    image_bytes: int = 0
    oversized_images: int = 0
    risky_images: int = 0
    annotation_count: int = 0
    form_widget_count: int = 0
    link_count: int = 0
    outline_count: int = 0
    image_pages: list[int] = field(default_factory=list)
    large_image_pages: list[int] = field(default_factory=list)
    large_image_bytes: int = 0
    large_image_pixels: int = 0
    oversized_pages: list[int] = field(default_factory=list)
    risky_pages: list[int] = field(default_factory=list)
    signature_flags: int = -1
    has_forms: bool = False
    repaired_on_open: bool = False


@dataclass(frozen=True)
class _Candidate:
    path: Path
    size: int
    strategy: str


@dataclass(frozen=True)
class _ImageOccurrence:
    name: str
    image_object: pikepdf.Object
    rect: Rect


class _VisualSourceCache:
    """Cachea renders del PDF fuente durante la validacion de candidatos.

    La comparacion visual puede validar varios candidatos contra las mismas
    paginas. Renderizar esas paginas fuente una sola vez evita repetir el
    trabajo mas costoso sin relajar los umbrales de fidelidad.
    """

    def __init__(self, source: Path) -> None:
        self.source = source
        self._doc: PdfRenderDocument | None = None
        self._pages: dict[int, np.ndarray] = {}

    def render(self, page_index: int) -> np.ndarray:
        cached = self._pages.get(page_index)
        if cached is not None:
            return cached
        if self._doc is None:
            self._doc = PdfRenderDocument(self.source)
        rendered = _render_page_array(self._doc, page_index)
        self._pages[page_index] = rendered
        return rendered

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        self._pages.clear()


class PdfCompressEngine:
    """Optimizes PDF files with validated candidates and conservative fallback."""

    def run_batch(
        self,
        jobs: List[CompressJob],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[CompressResult]:
        total = len(jobs)
        total_units = max(1, total) * 100
        results: List[CompressResult] = []
        for index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(index * 100, total_units, f"Preparando {Path(job.pdf_path).name}...")

            def _stage(stage_pct: int, message: str, *, _index: int = index) -> None:
                if progress:
                    pct = max(0, min(99, int(stage_pct)))
                    progress(_index * 100 + pct, total_units, message)

            result = self.run_job(job, status=_stage)
            results.append(result)
            if progress:
                progress((index + 1) * 100, total_units, f"{index + 1}/{total} PDFs procesados")
        return results

    def run_job(
        self,
        job: CompressJob,
        *,
        status: Callable[[int, str], None] | None = None,
    ) -> CompressResult:
        base_profile = profile_for(job.profile_id)
        try:
            options = _normalized_options(job.options)
            if job.page_rules and options.engine_mode in {
                "qpdf",
                "ghostscript",
                "fast",
                "turbo",
            }:
                raise RuntimeError(
                    "Las reglas por pagina requieren motor Automatico o Motor interno libre."
                )
            profile = _effective_profile(base_profile, options)
            _validate_engine_availability(options)
        except Exception as exc:
            return CompressResult(
                job=job,
                success=False,
                error=str(exc),
                profile_label=base_profile.label,
                input_bytes=_file_size(Path(job.pdf_path)),
            )
        source = Path(job.pdf_path)
        output = Path(job.output_path)

        if not source.exists():
            return CompressResult(
                job=job,
                success=False,
                error="El PDF de origen no existe.",
                profile_label=profile.label,
            )
        if _same_path(source, output):
            return CompressResult(
                job=job,
                success=False,
                error="La salida no puede ser el mismo archivo de origen.",
                profile_label=profile.label,
                input_bytes=_file_size(source),
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        input_size = source.stat().st_size
        temp_paths: list[Path] = []
        rejected_notes: list[str] = []
        visual_cache = _VisualSourceCache(source)

        try:
            _emit_status(status, 5, "Analizando estructura del PDF...")
            analysis = _inspect_source(source, profile)
            page_plan = build_page_compression_plan(
                analysis.page_count,
                job.profile_id,
                job.page_rules,
            )
            if page_plan.has_explicit_rules and options.engine_mode in {
                "qpdf",
                "ghostscript",
                "fast",
                "turbo",
            }:
                raise RuntimeError(
                    "Las reglas por pagina requieren motor Automatico o Motor interno libre."
                )
            validation_pages = (
                _select_page_rule_validation_pages(analysis, profile, page_plan)
                if page_plan.has_explicit_rules
                else _select_validation_pages(analysis, profile)
            )
            rule_warnings: list[str] = []

            if analysis.signature_flags > 0:
                _emit_status(status, 95, "PDF firmado: conservando original...")
                _copy_original(source, output)
                return CompressResult(
                    job=job,
                    output_path=str(output),
                    success=True,
                    warning="contiene firmas; se conservo el original",
                    profile_label=profile.label,
                    input_bytes=input_size,
                    output_bytes=output.stat().st_size,
                    total_pages=analysis.page_count,
                    strategy="original validado",
                    validation_pages=len(validation_pages),
                    **_page_rule_result_fields(page_plan, rule_warnings),
                )

            candidates: list[_Candidate] = []
            early_chosen: _Candidate | None = None

            if page_plan.has_explicit_rules:
                if analysis.risky_images > 0:
                    _emit_status(
                        status,
                        95,
                        "Imagenes con mascara: conservando original seguro...",
                    )
                    _copy_original(source, output)
                    return CompressResult(
                        job=job,
                        output_path=str(output),
                        success=True,
                        warning=(
                            "se conservo el original: las reglas por pagina no se "
                            "aplicaron porque el PDF contiene imagenes con mascara "
                            "incompatibles con la recompresion interna segura"
                        ),
                        profile_label=profile.label,
                        input_bytes=input_size,
                        output_bytes=output.stat().st_size,
                        total_pages=analysis.page_count,
                        strategy="original conservado",
                        validation_pages=len(validation_pages),
                        **_page_rule_result_fields(page_plan, rule_warnings),
                    )
                if page_plan.pages_compressible <= 0:
                    _emit_status(status, 95, "Todas las paginas estan excluidas...")
                    _copy_original(source, output)
                    return CompressResult(
                        job=job,
                        output_path=str(output),
                        success=True,
                        warning="todas las paginas quedaron excluidas",
                        profile_label=profile.label,
                        input_bytes=input_size,
                        output_bytes=output.stat().st_size,
                        total_pages=analysis.page_count,
                        strategy="original conservado",
                        validation_pages=len(validation_pages),
                        **_page_rule_result_fields(page_plan, rule_warnings),
                    )
                rules_path = _temp_output_path(output, "reglas")
                temp_paths.append(rules_path)
                try:
                    _emit_status(status, 36, "Aplicando reglas por pagina...")
                    rule_warnings.extend(
                        _write_page_rules_candidate(
                            source,
                            rules_path,
                            job.profile_id,
                            options,
                            page_plan,
                        )
                    )
                    _emit_status(status, 72, "Validando reglas por pagina...")
                    candidates.append(
                        _validate_page_rules_candidate(
                            source,
                            rules_path,
                            analysis,
                            validation_pages,
                            job.profile_id,
                            options,
                            page_plan,
                            "reglas por pagina",
                            visual_cache=visual_cache,
                        )
                    )
                except Exception as exc:
                    rejected_notes.append(f"reglas por pagina rechazadas: {_short_error(exc)}")
            else:
                has_image_optimization = _has_visual_compression_opportunity(analysis)
                should_try_images = _should_try_image_rewrite(analysis)
                should_try_pagewise_images = _should_try_pagewise_image_rewrite(analysis)
                if (
                    _engine_allows(options, "internal")
                    and has_image_optimization
                    and not should_try_images
                    and analysis.risky_images
                ):
                    rejected_notes.append(
                        "recompresion visual directa omitida por imagenes con mascara"
                    )

                qpdf_exe = _find_qpdf()
                ghostscript_exe = _find_ghostscript()
                ghostscript_attempted = False
                fast_ghostscript_attempted = False

                def _try_fast_ghostscript_candidate(*, allow_early: bool = True) -> _Candidate | None:
                    nonlocal fast_ghostscript_attempted, early_chosen
                    fast_ghostscript_attempted = True
                    fast_path = _temp_output_path(output, "rapido")
                    temp_paths.append(fast_path)
                    try:
                        _emit_status(status, 24, "Probando compresion rapida con Ghostscript...")
                        _write_ghostscript_fast_candidate(
                            source,
                            fast_path,
                            ghostscript_exe or "",
                        )
                        _emit_status(status, 38, "Validando candidato rapido...")
                        fast_candidate = _validate_candidate(
                            source,
                            fast_path,
                            analysis,
                            validation_pages,
                            profile,
                            "ghostscript rapido",
                            visual_cache=visual_cache,
                        )
                        candidates.append(fast_candidate)
                        if (
                            allow_early
                            and _should_accept_fast_ghostscript_candidate(
                                analysis,
                                options,
                                profile,
                                fast_candidate,
                                input_size,
                            )
                        ):
                            early_chosen = fast_candidate
                        return fast_candidate
                    except Exception as exc:
                        rejected_notes.append(
                            f"ghostscript rapido rechazado: {_short_error(exc)}"
                        )
                        return None

                def _try_ghostscript_candidate() -> None:
                    nonlocal ghostscript_attempted, early_chosen
                    ghostscript_attempted = True
                    ghostscript_path = _temp_output_path(output, "ghostscript")
                    temp_paths.append(ghostscript_path)
                    strategy = (
                        "qpdf visual reforzado"
                        if options.engine_mode == "qpdf"
                        else "ghostscript pdfwrite"
                    )
                    try:
                        _emit_status(status, 72, "Probando compresion fuerte con Ghostscript...")
                        _write_ghostscript_candidate(
                            source,
                            ghostscript_path,
                            profile,
                            ghostscript_exe or "",
                        )
                        _emit_status(status, 86, "Validando candidato Ghostscript...")
                        ghostscript_candidate = _validate_candidate(
                            source,
                            ghostscript_path,
                            analysis,
                            validation_pages,
                            profile,
                            strategy,
                            visual_cache=visual_cache,
                        )
                        candidates.append(ghostscript_candidate)
                        if _should_accept_fast_ghostscript(
                            analysis,
                            options,
                            ghostscript_candidate,
                            input_size,
                        ):
                            early_chosen = ghostscript_candidate
                    except Exception as exc:
                        rejected_notes.append(
                            f"ghostscript rechazado: {_short_error(exc)}"
                        )

                if _should_prioritize_fast_ghostscript(
                    analysis,
                    options,
                    profile,
                    ghostscript_exe,
                ):
                    _try_fast_ghostscript_candidate()

                if early_chosen is None and _should_prioritize_ghostscript(
                    analysis,
                    options,
                    ghostscript_exe,
                    should_try_images,
                ):
                    _try_ghostscript_candidate()

                if (
                    early_chosen is None
                    and _engine_allows(options, "qpdf")
                    and qpdf_exe
                ):
                    qpdf_path = _temp_output_path(output, "qpdf")
                    temp_paths.append(qpdf_path)
                    try:
                        _emit_status(status, 18, "Probando optimizacion estructural con QPDF...")
                        _write_qpdf_candidate(source, qpdf_path, qpdf_exe)
                        _emit_status(status, 26, "Validando candidato QPDF...")
                        candidates.append(
                            _validate_candidate(
                                source,
                                qpdf_path,
                                analysis,
                                validation_pages,
                                profile,
                                "qpdf estructural",
                                visual_validation=False,
                            )
                        )
                    except Exception as exc:
                        rejected_notes.append(f"qpdf rechazado: {_short_error(exc)}")

                image_candidate_useful = False
                turbo_candidate_useful = False
                if early_chosen is None and _engine_allows(options, "internal_turbo"):
                    turbo_path = _temp_output_path(output, "turbo")
                    temp_paths.append(turbo_path)
                    try:
                        _emit_status(status, 34, "Probando turbo libre aislado...")
                        _write_isolated_image_candidate(
                            source,
                            turbo_path,
                            _turbo_worker_profile(profile),
                        )
                        _emit_status(status, 58, "Validando candidato turbo...")
                        turbo_candidate = _validate_candidate(
                            source,
                            turbo_path,
                            analysis,
                            validation_pages,
                            profile,
                            "turbo libre aislado",
                            visual_cache=visual_cache,
                        )
                        candidates.append(turbo_candidate)
                        turbo_candidate_useful = _candidate_is_useful(
                            turbo_candidate,
                            input_size,
                        )
                    except Exception as exc:
                        rejected_notes.append(
                            f"turbo libre rechazado: {_short_error(exc)}"
                        )

                if (
                    early_chosen is None
                    and options.engine_mode == "turbo"
                    and not turbo_candidate_useful
                    and ghostscript_exe
                    and not fast_ghostscript_attempted
                ):
                    _try_fast_ghostscript_candidate(allow_early=False)

                if early_chosen is None and _engine_allows(options, "internal"):
                    if should_try_images:
                        image_path = _temp_output_path(output, "imagenes")
                        temp_paths.append(image_path)
                        try:
                            _emit_status(status, 35, "Recomprimiendo imagenes internas...")
                            _write_image_candidate(source, image_path, profile)
                            _emit_status(status, 58, "Validando fidelidad visual interna...")
                            image_candidate = _validate_candidate(
                                source,
                                image_path,
                                analysis,
                                validation_pages,
                                profile,
                                "imagenes optimizadas",
                                visual_cache=visual_cache,
                            )
                            candidates.append(image_candidate)
                            image_candidate_useful = _candidate_is_useful(
                                image_candidate, input_size
                            )
                        except Exception as exc:
                            rejected_notes.append(
                                f"recompresion visual rechazada: {_short_error(exc)}"
                            )

                    if not should_try_images and should_try_pagewise_images:
                        pagewise_path = _temp_output_path(output, "paginas")
                        temp_paths.append(pagewise_path)
                        try:
                            _emit_status(
                                status,
                                44,
                                "Recomprimiendo imagenes internas por pagina...",
                            )
                            _write_pagewise_image_candidate(
                                source,
                                pagewise_path,
                                profile,
                            )
                            _emit_status(
                                status,
                                64,
                                "Validando fidelidad visual por pagina...",
                            )
                            pagewise_candidate = _validate_candidate(
                                source,
                                pagewise_path,
                                analysis,
                                validation_pages,
                                profile,
                                "imagenes optimizadas por pagina",
                                visual_cache=visual_cache,
                            )
                            candidates.append(pagewise_candidate)
                            image_candidate_useful = _candidate_is_useful(
                                pagewise_candidate, input_size
                            )
                        except Exception as exc:
                            rejected_notes.append(
                                f"recompresion por pagina rechazada: {_short_error(exc)}"
                            )

                    if (
                        (not should_try_images and not should_try_pagewise_images)
                        or not image_candidate_useful
                    ):
                        safe_path = _temp_output_path(output, "seguro")
                        temp_paths.append(safe_path)
                        try:
                            _emit_status(status, 68, "Generando respaldo seguro interno...")
                            _write_safe_candidate(source, safe_path)
                            _emit_status(status, 76, "Validando respaldo seguro...")
                            candidates.append(
                                _validate_candidate(
                                    source,
                                    safe_path,
                                    analysis,
                                    validation_pages,
                                    profile,
                                    "optimizacion segura",
                                    visual_validation=False,
                                )
                            )
                        except Exception as exc:
                            rejected_notes.append(f"modo seguro rechazado: {_short_error(exc)}")

                if (
                    early_chosen is None
                    and _engine_allows(options, "ghostscript")
                    and ghostscript_exe
                    and (has_image_optimization or options.engine_mode == "ghostscript")
                    and not ghostscript_attempted
                ):
                    _try_ghostscript_candidate()

            _emit_status(status, 92, "Seleccionando el mejor resultado validado...")
            chosen = early_chosen or _choose_candidate(candidates, input_size)
            warning_parts: list[str] = []
            if analysis.repaired_on_open:
                warning_parts.append("estructura reparada al abrir")

            if chosen is None:
                _emit_status(status, 96, "Conservando original: no hubo mejora segura...")
                _copy_original(source, output)
                warning_parts.append("ya estaba optimizado")
                if rejected_notes:
                    warning_parts.extend(_result_warning_notes(rejected_notes))
                return CompressResult(
                    job=job,
                    output_path=str(output),
                    success=True,
                    warning="; ".join(warning_parts),
                    profile_label=profile.label,
                    input_bytes=input_size,
                    output_bytes=output.stat().st_size,
                    total_pages=analysis.page_count,
                    strategy="original conservado",
                    validation_pages=len(validation_pages),
                    **_page_rule_result_fields(page_plan, rule_warnings),
                )

            _emit_status(status, 98, "Guardando PDF comprimido...")
            _replace_file(chosen.path, output)
            output_size = output.stat().st_size
            if chosen.strategy == "optimizacion segura" and rejected_notes:
                warning_parts.append("se uso modo seguro")
            warning_parts.extend(
                note for note in _result_warning_notes(rejected_notes)
                if note not in warning_parts
            )

            return CompressResult(
                job=job,
                output_path=str(output),
                success=True,
                warning="; ".join(warning_parts),
                profile_label=profile.label,
                input_bytes=input_size,
                output_bytes=output_size,
                total_pages=analysis.page_count,
                strategy=chosen.strategy,
                validation_pages=len(validation_pages),
                **_page_rule_result_fields(page_plan, rule_warnings),
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
            visual_cache.close()
            for temp_path in temp_paths:
                _remove_file(temp_path)


def profile_for(profile_id: str) -> CompressProfile:
    return PROFILES.get(profile_id, PROFILES["balanced"])


def available_optional_engines() -> list[str]:
    return [engine.label for engine in optional_engine_status() if engine.available]


def optional_engine_status() -> list[OptionalEngineStatus]:
    qpdf = _find_qpdf()
    ghostscript = _find_ghostscript()
    return [
        OptionalEngineStatus(
            id="qpdf",
            label="QPDF",
            available=bool(qpdf),
            path=qpdf or "",
            source=_engine_source(qpdf),
        ),
        OptionalEngineStatus(
            id="ghostscript",
            label="Ghostscript",
            available=bool(ghostscript),
            path=ghostscript or "",
            source=_engine_source(ghostscript),
        ),
    ]


def _normalized_options(options: CompressOptions | None) -> CompressOptions:
    raw = options or CompressOptions()
    engine_mode = (raw.engine_mode or "auto").strip().lower()
    if engine_mode == _LEGACY_INTERNAL_ENGINE:
        engine_mode = "internal"
    if engine_mode not in {"auto", "internal", "qpdf", "ghostscript", "fast", "turbo"}:
        raise RuntimeError("Motor de compresion no reconocido.")
    validation_level = (raw.validation_level or "standard").strip().lower()
    if validation_level not in {"strict", "standard", "relaxed"}:
        raise RuntimeError("Nivel de validacion no reconocido.")
    return CompressOptions(
        engine_mode=engine_mode,
        dpi_threshold=raw.dpi_threshold,
        dpi_target=raw.dpi_target,
        quality=raw.quality,
        set_to_gray=raw.set_to_gray,
        validation_level=validation_level,
    )


def _effective_profile(
    profile: CompressProfile,
    options: CompressOptions,
) -> CompressProfile:
    dpi_threshold = _clamp_int(
        options.dpi_threshold if options.dpi_threshold is not None else profile.dpi_threshold,
        72,
        900,
    )
    dpi_target = _clamp_int(
        options.dpi_target if options.dpi_target is not None else profile.dpi_target,
        50,
        600,
    )
    if dpi_target >= dpi_threshold:
        dpi_threshold = min(900, dpi_target + 10)
    quality = _clamp_int(
        options.quality if options.quality is not None else profile.quality,
        35,
        100,
    )
    set_to_gray = (
        bool(options.set_to_gray)
        if options.set_to_gray is not None
        else profile.set_to_gray
    )
    mean_delta = profile.max_visual_mean_delta
    p95_delta = profile.max_visual_p95_delta
    changed_ratio = profile.max_changed_pixel_ratio
    max_pages = profile.max_validation_pages
    if options.validation_level == "strict":
        mean_delta *= 0.65
        p95_delta *= 0.65
        changed_ratio *= 0.65
        max_pages = max(10, max_pages + 4)
    elif options.validation_level == "relaxed":
        mean_delta *= 1.45
        p95_delta *= 1.35
        changed_ratio *= 1.30
        max_pages = max(4, max_pages - 2)
    return replace(
        profile,
        dpi_threshold=dpi_threshold,
        dpi_target=dpi_target,
        quality=quality,
        set_to_gray=set_to_gray,
        max_visual_mean_delta=mean_delta,
        max_visual_p95_delta=p95_delta,
        max_changed_pixel_ratio=changed_ratio,
        max_validation_pages=max_pages,
    )


def _validate_engine_availability(options: CompressOptions) -> None:
    if options.engine_mode == "qpdf" and not _find_qpdf():
        raise RuntimeError("QPDF no esta disponible en esta PC.")
    if options.engine_mode in {"ghostscript", "fast"} and not _find_ghostscript():
        raise RuntimeError("Ghostscript no esta disponible en esta PC.")


def _engine_allows(options: CompressOptions, engine: str) -> bool:
    if options.engine_mode == "auto":
        return engine != "internal_turbo"
    if options.engine_mode == "internal":
        return engine == "internal"
    if options.engine_mode == "turbo":
        return engine == "internal_turbo"
    return options.engine_mode == engine


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


def _emit_status(
    callback: Callable[[int, str], None] | None,
    percent: int,
    message: str,
) -> None:
    if callback:
        callback(percent, message)


def _inspect_source(source: Path, profile: CompressProfile) -> _PdfAnalysis:
    with PdfRenderDocument(source) as render_doc, pikepdf.Pdf.open(source) as pdf_doc:
        if render_doc.page_count <= 0:
            raise RuntimeError("El PDF no tiene paginas.")

        analysis = _PdfAnalysis(
            page_count=render_doc.page_count,
            signature_flags=_signature_flags(pdf_doc),
            has_forms=_has_forms(pdf_doc),
            repaired_on_open=bool(pdf_doc.get_warnings()),
        )
        analysis.outline_count = _outline_count(pdf_doc)
        for page_index, page in enumerate(pdf_doc.pages):
            analysis.annotation_count += _page_annotation_count(page)
            analysis.form_widget_count += _page_widget_count(page)
            analysis.link_count += _page_link_count(page)
            try:
                images = _page_image_occurrences(page, render_doc, page_index)
            except Exception:
                _append_unique(analysis.risky_pages, page_index)
                continue
            if images:
                _append_unique(analysis.image_pages, page_index)
            for occurrence in images:
                analysis.image_count += 1
                image_size = _image_stream_size(occurrence.image_object)
                image_pixels = _image_pixel_count(occurrence.image_object)
                analysis.image_bytes += image_size
                effective_dpi = _effective_image_dpi(occurrence)
                if _image_area_ratio(occurrence.rect, render_doc.page_info(page_index)) >= 0.20:
                    _append_unique(analysis.large_image_pages, page_index)
                    analysis.large_image_bytes += image_size
                    analysis.large_image_pixels += image_pixels
                has_mask = _image_has_mask(occurrence.image_object)
                if has_mask:
                    analysis.risky_images += 1
                    _append_unique(analysis.risky_pages, page_index)
                if effective_dpi >= profile.dpi_threshold:
                    analysis.oversized_images += 1
                    _append_unique(analysis.oversized_pages, page_index)
        return analysis


def _signature_flags(pdf_doc: pikepdf.Pdf) -> int:
    try:
        acroform = pdf_doc.Root.get("/AcroForm", {})
        return int(acroform.get("/SigFlags", 0))
    except Exception:
        return -1


def _has_forms(pdf_doc: pikepdf.Pdf) -> bool:
    try:
        acroform = pdf_doc.Root.get("/AcroForm", {})
        fields = acroform.get("/Fields", [])
        return bool(fields)
    except Exception:
        return False


def _outline_count(pdf_doc: pikepdf.Pdf) -> int:
    try:
        with pdf_doc.open_outline() as outline:
            return _count_outline_items(outline.root)
    except Exception:
        return 0


def _count_outline_items(items) -> int:
    total = 0
    for item in items:
        total += 1
        try:
            total += _count_outline_items(item.children)
        except Exception:
            pass
    return total


def _page_annotations(page: pikepdf.Page) -> list[pikepdf.Object]:
    try:
        annots = page.obj.get("/Annots", [])
        return list(annots) if annots else []
    except Exception:
        return []


def _page_annotation_count(page: pikepdf.Page) -> int:
    return sum(
        1
        for annot in _page_annotations(page)
        if annot.get("/Subtype") not in {"/Link", "/Widget"}
    )


def _page_widget_count(page: pikepdf.Page) -> int:
    return sum(1 for annot in _page_annotations(page) if annot.get("/Subtype") == "/Widget")


def _page_link_count(page: pikepdf.Page) -> int:
    return sum(1 for annot in _page_annotations(page) if annot.get("/Subtype") == "/Link")


def _page_image_occurrences(
    page: pikepdf.Page,
    render_doc: PdfRenderDocument,
    page_index: int,
) -> list[_ImageOccurrence]:
    image_resources = {
        str(name): image_object
        for name, image_object in page.get_images(recursive=True).items()
    }
    if not image_resources:
        return []
    bounds = [
        Rect(item.left, item.top, item.right, item.bottom)
        for item in render_doc.object_bounds(page_index, kinds=("image",))
        if item.width >= 1.0 and item.height >= 1.0
    ]
    if not bounds:
        return []
    draw_names = [name for name in _image_draw_names(page) if name in image_resources]
    if len(draw_names) == len(bounds):
        return [
            _ImageOccurrence(name, image_resources[name], rect)
            for name, rect in zip(draw_names, bounds)
        ]
    if len(image_resources) == 1:
        name, image_object = next(iter(image_resources.items()))
        return [_ImageOccurrence(name, image_object, rect) for rect in bounds]
    return [
        _ImageOccurrence(name, image_resources[name], rect)
        for name, rect in zip(draw_names, bounds)
        if name in image_resources
    ]


def _image_draw_names(page: pikepdf.Page) -> list[str]:
    names: list[str] = []
    for stream in _content_streams(page):
        try:
            text = stream.read_bytes().decode("latin1", errors="ignore")
        except Exception:
            continue
        for match in re.finditer(r"/([A-Za-z0-9_.#-]+)\s+Do\b", text):
            names.append(f"/{_decode_pdf_name(match.group(1))}")
    return names


def _content_streams(page: pikepdf.Page) -> list[pikepdf.Object]:
    try:
        contents = page.Contents
    except Exception:
        return []
    if isinstance(contents, pikepdf.Array):
        return [item for item in contents if hasattr(item, "read_bytes")]
    if hasattr(contents, "read_bytes"):
        return [contents]
    return []


def _decode_pdf_name(raw: str) -> str:
    def replace(match) -> str:
        try:
            return bytes([int(match.group(1), 16)]).decode("latin1")
        except ValueError:
            return match.group(0)

    return re.sub(r"#([0-9A-Fa-f]{2})", replace, raw)


def _effective_image_dpi(occurrence: _ImageOccurrence) -> float:
    width, height = _image_size(occurrence.image_object)
    if width <= 0 or height <= 0 or occurrence.rect.width <= 0 or occurrence.rect.height <= 0:
        return 0.0
    dpi_x = width * 72.0 / occurrence.rect.width
    dpi_y = height * 72.0 / occurrence.rect.height
    return max(dpi_x, dpi_y)


def _image_stream_size(image_object: pikepdf.Object) -> int:
    try:
        return max(0, len(image_object.read_raw_bytes()))
    except Exception:
        try:
            return max(0, len(image_object.read_bytes()))
        except Exception:
            return 0


def _image_pixel_count(image_object: pikepdf.Object) -> int:
    width, height = _image_size(image_object)
    return width * height


def _image_size(image_object: pikepdf.Object) -> tuple[int, int]:
    try:
        image = pikepdf.PdfImage(image_object)
        return max(0, int(image.width)), max(0, int(image.height))
    except Exception:
        return 0, 0


def _image_has_mask(image_object: pikepdf.Object) -> bool:
    try:
        return bool(
            image_object.get("/SMask")
            or image_object.get("/Mask")
            or pikepdf.PdfImage(image_object).image_mask
        )
    except Exception:
        return True


def _image_area_ratio(rect: Rect, page_info) -> float:
    page_area = max(1.0, float(page_info.width_pt * page_info.height_pt))
    image_area = max(0.0, float(rect.width * rect.height))
    return image_area / page_area


def _append_unique(values: list[int], value: int) -> None:
    if value not in values:
        values.append(value)


def _select_validation_pages(
    analysis: _PdfAnalysis,
    profile: CompressProfile,
) -> list[int]:
    if analysis.page_count <= 0:
        return []
    ordered: list[int] = []
    anchors = [0, analysis.page_count // 2, analysis.page_count - 1]
    for page_index in (
        anchors
        + analysis.risky_pages
        + analysis.oversized_pages
        + analysis.image_pages
    ):
        if 0 <= page_index < analysis.page_count:
            _append_unique(ordered, page_index)
        if len(ordered) >= profile.max_validation_pages:
            break
    return sorted(ordered)


def _select_page_rule_validation_pages(
    analysis: _PdfAnalysis,
    profile: CompressProfile,
    page_plan: PageCompressionPlan,
) -> list[int]:
    ordered = _select_validation_pages(analysis, profile)
    limit = min(
        analysis.page_count,
        max(profile.max_validation_pages, min(24, page_plan.pages_with_rules + 6)),
    )
    explicit_pages = [
        item.page_index
        for item in page_plan.effective
        if item.source_rule_id is not None
    ]
    excluded_pages = [
        item.page_index
        for item in page_plan.effective
        if item.excluded
    ]
    segment_starts = [start for start, _end, _rule in _page_rule_segments(page_plan)]
    for page_index in excluded_pages + explicit_pages + segment_starts:
        if 0 <= page_index < analysis.page_count:
            _append_unique(ordered, page_index)
        if len(ordered) >= limit:
            break
    return sorted(ordered)


def _has_image_optimization_opportunity(analysis: _PdfAnalysis) -> bool:
    return analysis.image_count > 0 and analysis.oversized_images > 0


def _has_visual_compression_opportunity(analysis: _PdfAnalysis) -> bool:
    return (
        _has_image_optimization_opportunity(analysis)
        or analysis.risky_images > 0
        or _has_dense_large_images(analysis)
    )


def _is_image_heavy_pdf(analysis: _PdfAnalysis) -> bool:
    if analysis.image_count <= 0 or analysis.page_count <= 0:
        return False
    large_pages = len(analysis.large_image_pages)
    if large_pages <= 0:
        return False
    return large_pages >= max(1, int(analysis.page_count * 0.35))


def _has_dense_large_images(analysis: _PdfAnalysis) -> bool:
    if not _is_image_heavy_pdf(analysis):
        return False
    if analysis.large_image_bytes <= 0:
        return False
    if analysis.large_image_pixels <= 0:
        return False
    bytes_per_pixel = analysis.large_image_bytes / analysis.large_image_pixels
    return bytes_per_pixel >= 0.18


def _should_try_image_rewrite(analysis: _PdfAnalysis) -> bool:
    # Direct structural image rewriting is intentionally skipped for masked /
    # soft-masked images. Page rasterization or external engines are safer.
    return _has_image_optimization_opportunity(analysis) and analysis.risky_images <= 0


def _should_try_pagewise_image_rewrite(analysis: _PdfAnalysis) -> bool:
    return (
        analysis.risky_images > 0
        and _has_visual_compression_opportunity(analysis)
        and _is_image_heavy_pdf(analysis)
    )


def _is_long_visual_workload(analysis: _PdfAnalysis) -> bool:
    return (
        _is_image_heavy_pdf(analysis)
        and (
            analysis.page_count >= 80
            or analysis.image_count >= 700
            or analysis.large_image_pixels >= 120_000_000
        )
    )


def _should_prioritize_fast_ghostscript(
    analysis: _PdfAnalysis,
    options: CompressOptions,
    profile: CompressProfile,
    ghostscript_exe: str | None,
) -> bool:
    if not ghostscript_exe:
        return False
    if options.engine_mode == "fast":
        return True
    return (
        options.engine_mode == "auto"
        and profile.id in {"balanced", "quality"}
        and _has_visual_compression_opportunity(analysis)
        and _is_long_visual_workload(analysis)
    )


def _should_prioritize_ghostscript(
    analysis: _PdfAnalysis,
    options: CompressOptions,
    ghostscript_exe: str | None,
    should_try_images: bool,
) -> bool:
    if options.engine_mode == "qpdf":
        return bool(ghostscript_exe) and _has_visual_compression_opportunity(analysis)
    return (
        options.engine_mode == "auto"
        and bool(ghostscript_exe)
        and _has_visual_compression_opportunity(analysis)
        and (
            _is_image_heavy_pdf(analysis)
            or analysis.risky_images > 0
            or not should_try_images
        )
    )


def _should_accept_fast_ghostscript_candidate(
    analysis: _PdfAnalysis,
    options: CompressOptions,
    profile: CompressProfile,
    candidate: _Candidate,
    input_size: int,
) -> bool:
    if options.engine_mode == "fast":
        return True
    if options.engine_mode != "auto" or not _is_long_visual_workload(analysis):
        return False
    reduction = _candidate_reduction_pct(candidate, input_size)
    if profile.id == "quality":
        return reduction >= _AUTO_FAST_GHOSTSCRIPT_QUALITY_ACCEPT_REDUCTION
    if profile.id == "balanced":
        return reduction >= _AUTO_FAST_GHOSTSCRIPT_ACCEPT_REDUCTION
    return False


def _should_accept_fast_ghostscript(
    analysis: _PdfAnalysis,
    options: CompressOptions,
    candidate: _Candidate,
    input_size: int,
) -> bool:
    return (
        options.engine_mode in {"auto", "qpdf"}
        and _has_visual_compression_opportunity(analysis)
        and _candidate_reduction_pct(candidate, input_size)
        >= _AUTO_GHOSTSCRIPT_FAST_ACCEPT_REDUCTION
    )


def _turbo_worker_profile(profile: CompressProfile) -> CompressProfile:
    return replace(
        profile,
        dpi_threshold=min(profile.dpi_threshold, 130),
        dpi_target=min(profile.dpi_target, 110),
        quality=min(profile.quality, 62),
    )


def _candidate_reduction_pct(candidate: _Candidate, input_size: int) -> float:
    if input_size <= 0:
        return 0.0
    return max(0.0, (1.0 - candidate.size / input_size) * 100.0)


def _write_safe_candidate(source: Path, output: Path) -> None:
    normalize_pdf(
        source,
        output,
        preserve_metadata=True,
        normalize_content=True,
        generate_object_streams=True,
    )


def _write_image_candidate(source: Path, output: Path, profile: CompressProfile) -> None:
    _write_raster_image_candidate(source, output, profile)


def _write_pagewise_image_candidate(
    source: Path,
    output: Path,
    profile: CompressProfile,
) -> None:
    _write_raster_image_candidate(source, output, profile)


def _write_raster_image_candidate(
    source: Path,
    output: Path,
    profile: CompressProfile,
    *,
    page_indexes: list[int] | None = None,
) -> None:
    with PdfRenderDocument(source) as document:
        indexes = list(range(document.page_count)) if page_indexes is None else list(page_indexes)
        for page_index in indexes:
            if page_index < 0 or page_index >= document.page_count:
                raise RuntimeError("pagina fuera de rango")

        scale = max(0.1, float(profile.dpi_target) / 72.0)

        def pages():
            for page_index in indexes:
                info = document.page_info(page_index)
                image = document.render_page(page_index, scale=scale).to_pil().convert("RGB")
                if profile.set_to_gray:
                    image = image.convert("L").convert("RGB")
                buffer = BytesIO()
                image.save(
                    buffer,
                    format="JPEG",
                    quality=max(35, min(100, int(profile.quality))),
                    optimize=True,
                )
                yield ImagePdfPage(
                    buffer.getvalue(),
                    info.width_pt,
                    info.height_pt,
                )

        create_image_pdf(pages(), output)


def _write_single_page_image_candidate_in_process(
    source: Path,
    output: Path,
    page_index: int,
    profile: CompressProfile,
) -> None:
    command_args = [
        "--page-source",
        str(source),
        "--page-output",
        str(output),
        "--page-index",
        str(int(page_index)),
        "--dpi-threshold",
        str(int(profile.dpi_threshold)),
        "--dpi-target",
        str(int(profile.dpi_target)),
        "--quality",
        str(int(profile.quality)),
        "--lossy",
        "1" if profile.rewrite_lossy else "0",
        "--lossless",
        "1" if profile.rewrite_lossless else "0",
        "--set-to-gray",
        "1" if profile.set_to_gray else "0",
    ]
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--pdflex-compress-page-worker", *command_args]
    else:
        command = [
            sys.executable,
            "-m",
            "core.pdf_compress_process",
            "--page-rewrite",
            *command_args,
        ]
    _run_command(command, "compresion interna por pagina", timeout=420)


def _write_isolated_image_candidate(
    source: Path,
    output: Path,
    profile: CompressProfile,
) -> None:
    command_args = [
        "--doc-source",
        str(source),
        "--doc-output",
        str(output),
        "--dpi-threshold",
        str(int(profile.dpi_threshold)),
        "--dpi-target",
        str(int(profile.dpi_target)),
        "--quality",
        str(int(profile.quality)),
        "--lossy",
        "1" if profile.rewrite_lossy else "0",
        "--lossless",
        "1" if profile.rewrite_lossless else "0",
        "--set-to-gray",
        "1" if profile.set_to_gray else "0",
    ]
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--pdflex-compress-doc-worker", *command_args]
    else:
        command = [
            sys.executable,
            "-m",
            "core.pdf_compress_process",
            "--doc-rewrite",
            *command_args,
        ]
    _run_command(command, "turbo libre", timeout=420)


def _write_single_page_image_candidate(
    source: Path,
    output: Path,
    page_index: int,
    profile: CompressProfile,
) -> None:
    _write_raster_image_candidate(source, output, profile, page_indexes=[page_index])


def _write_page_rules_candidate(
    source: Path,
    output: Path,
    global_profile_id: str,
    options: CompressOptions,
    page_plan: PageCompressionPlan,
) -> list[str]:
    warnings = _shared_image_rule_warnings(source, page_plan)
    with PdfRenderDocument(source) as document, TemporaryDirectory(
        prefix="pdflex-compress-rules-"
    ) as temp_dir:
        pages: list[SourcePage] = []
        for start, end, effective in _page_rule_segments(page_plan):
            for page_index in range(start, end + 1):
                if effective.excluded:
                    pages.append(SourcePage(str(source), page_index))
                    continue
                profile = _profile_for_effective_rule(
                    effective,
                    global_profile_id,
                    options,
                )
                page_path = Path(temp_dir) / f"page-{page_index + 1:04d}.pdf"
                _write_single_page_image_candidate(
                    source,
                    page_path,
                    page_index,
                    profile,
                )
                pages.append(SourcePage(str(page_path), 0))

        if len(pages) != document.page_count:
            raise RuntimeError("el candidato por reglas produjo un numero inesperado de paginas")
        assemble_pages(pages, output)
        return warnings


def _page_rule_segments(
    page_plan: PageCompressionPlan,
) -> list[tuple[int, int, EffectivePageCompression]]:
    if page_plan.page_count <= 0:
        return []
    segments: list[tuple[int, int, EffectivePageCompression]] = []
    start = 0
    current = page_plan.rule_for_page(0)
    current_key = _effective_rule_key(current)
    for page_index in range(1, page_plan.page_count):
        item = page_plan.rule_for_page(page_index)
        key = _effective_rule_key(item)
        if key == current_key:
            continue
        segments.append((start, page_index - 1, current))
        start = page_index
        current = item
        current_key = key
    segments.append((start, page_plan.page_count - 1, current))
    return segments


def _effective_rule_key(rule: EffectivePageCompression) -> tuple:
    option_items = tuple(sorted((str(k), str(v)) for k, v in rule.options.items()))
    return (
        rule.excluded,
        rule.preset,
        rule.profile_id,
        option_items,
    )


def _profile_for_effective_rule(
    rule: EffectivePageCompression,
    global_profile_id: str,
    global_options: CompressOptions,
) -> CompressProfile:
    if rule.source_rule_id is None:
        return _effective_profile(profile_for(global_profile_id), global_options)
    if rule.excluded:
        return _effective_profile(
            profile_for("quality"),
            CompressOptions(validation_level="strict"),
        )
    if rule.preset == "custom":
        return _effective_profile(
            profile_for(rule.profile_id),
            _options_from_rule(rule.options, global_options),
        )
    return _effective_profile(
        profile_for(rule.profile_id),
        CompressOptions(validation_level=global_options.validation_level),
    )


def _options_from_rule(
    raw_options: dict,
    fallback: CompressOptions,
) -> CompressOptions:
    return _normalized_options(
        CompressOptions(
            engine_mode="internal",
            dpi_threshold=_optional_int(raw_options.get("dpi_threshold")),
            dpi_target=_optional_int(raw_options.get("dpi_target")),
            quality=_optional_int(raw_options.get("quality")),
            set_to_gray=_optional_bool(raw_options.get("set_to_gray")),
            validation_level=str(raw_options.get("validation_level") or fallback.validation_level),
        )
    )


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí"}


def _write_qpdf_candidate(source: Path, output: Path, executable: str) -> None:
    _run_command(
        [
            executable,
            "--warning-exit-0",
            str(source),
            "--object-streams=generate",
            "--stream-data=compress",
            "--recompress-flate",
            "--compression-level=9",
            str(output),
        ],
        "qpdf",
    )


def _write_ghostscript_candidate(
    source: Path,
    output: Path,
    profile: CompressProfile,
    executable: str,
) -> None:
    command = [
        executable,
        "-dSAFER",
        "-dBATCH",
        "-dNOPAUSE",
        "-dQUIET",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.7",
        "-dAutoRotatePages=/None",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dEmbedAllFonts=true",
        "-dDownsampleColorImages=true",
        "-dColorImageDownsampleType=/Bicubic",
        f"-dColorImageResolution={profile.dpi_target}",
        "-dColorImageDownsampleThreshold=1.1",
        "-dColorImageFilter=/DCTEncode",
        "-dDownsampleGrayImages=true",
        "-dGrayImageDownsampleType=/Bicubic",
        f"-dGrayImageResolution={profile.dpi_target}",
        "-dGrayImageDownsampleThreshold=1.1",
        "-dGrayImageFilter=/DCTEncode",
        "-dDownsampleMonoImages=true",
        "-dMonoImageDownsampleType=/Subsample",
        f"-dMonoImageResolution={_ghostscript_mono_dpi(profile)}",
        "-dMonoImageDownsampleThreshold=1.1",
        f"-dJPEGQ={profile.quality}",
        f"-sOutputFile={output}",
        str(source),
    ]
    _run_command(command, "ghostscript", timeout=420)


def _write_ghostscript_fast_candidate(
    source: Path,
    output: Path,
    executable: str,
) -> None:
    command = [
        executable,
        "-dSAFER",
        "-dBATCH",
        "-dNOPAUSE",
        "-dQUIET",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.7",
        "-dPDFSETTINGS=/printer",
        "-dAutoRotatePages=/None",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dEmbedAllFonts=true",
        f"-sOutputFile={output}",
        str(source),
    ]
    _run_command(command, "ghostscript rapido", timeout=240)


def _validate_candidate(
    source: Path,
    candidate: Path,
    source_analysis: _PdfAnalysis,
    validation_pages: list[int],
    profile: CompressProfile,
    strategy: str,
    *,
    visual_cache: _VisualSourceCache | None = None,
    visual_validation: bool = True,
) -> _Candidate:
    if not candidate.exists():
        raise RuntimeError("no se genero archivo")
    size = candidate.stat().st_size
    if size <= 0:
        raise RuntimeError("archivo vacio")

    with PdfRenderDocument(candidate) as render_doc, pikepdf.Pdf.open(candidate) as pdf_doc:
        if render_doc.page_count != source_analysis.page_count:
            raise RuntimeError(
                "paginas inesperadas "
                f"({render_doc.page_count}; se esperaban {source_analysis.page_count})"
            )
        _validate_structural_fidelity(pdf_doc, source_analysis)

    if visual_validation:
        _call_compare_visual_pages(
            source,
            candidate,
            validation_pages,
            profile,
            source_cache=visual_cache,
        )
    return _Candidate(candidate, size, strategy)


def _call_compare_visual_pages(
    source: Path,
    candidate: Path,
    validation_pages: list[int],
    profile: CompressProfile,
    *,
    source_cache: _VisualSourceCache | None,
) -> None:
    if source_cache is not None and _accepts_keyword(_compare_visual_pages, "source_cache"):
        _compare_visual_pages(
            source,
            candidate,
            validation_pages,
            profile,
            source_cache=source_cache,
        )
        return
    _compare_visual_pages(source, candidate, validation_pages, profile)


def _accepts_keyword(callback: Callable, name: str) -> bool:
    code = getattr(callback, "__code__", None)
    if code is None:
        return False
    return name in code.co_varnames


def _validate_page_rules_candidate(
    source: Path,
    candidate: Path,
    source_analysis: _PdfAnalysis,
    validation_pages: list[int],
    global_profile_id: str,
    options: CompressOptions,
    page_plan: PageCompressionPlan,
    strategy: str,
    *,
    visual_cache: _VisualSourceCache | None = None,
) -> _Candidate:
    if not candidate.exists():
        raise RuntimeError("no se genero archivo")
    size = candidate.stat().st_size
    if size <= 0:
        raise RuntimeError("archivo vacio")

    with PdfRenderDocument(candidate) as render_doc, pikepdf.Pdf.open(candidate) as pdf_doc:
        if render_doc.page_count != source_analysis.page_count:
            raise RuntimeError(
                "paginas inesperadas "
                f"({render_doc.page_count}; se esperaban {source_analysis.page_count})"
            )
        _validate_structural_fidelity(pdf_doc, source_analysis)

    _compare_visual_pages_by_rules(
        source,
        candidate,
        validation_pages,
        global_profile_id,
        options,
        page_plan,
        source_cache=visual_cache,
    )
    return _Candidate(candidate, size, strategy)


def _validate_structural_fidelity(
    candidate_doc: pikepdf.Pdf,
    source_analysis: _PdfAnalysis,
) -> None:
    if source_analysis.has_forms and not _has_forms(candidate_doc):
        raise RuntimeError("se perdieron campos de formulario")

    needs_page_scan = (
        source_analysis.form_widget_count > 0
        or source_analysis.annotation_count > 0
        or source_analysis.link_count > 0
    )
    if needs_page_scan:
        candidate_widgets = 0
        candidate_annots = 0
        candidate_links = 0
        for page in candidate_doc.pages:
            candidate_widgets += _page_widget_count(page)
            candidate_annots += _page_annotation_count(page)
            candidate_links += _page_link_count(page)

        if candidate_widgets < source_analysis.form_widget_count:
            raise RuntimeError("se perdieron campos interactivos")
        if candidate_annots < source_analysis.annotation_count:
            raise RuntimeError("se perdieron anotaciones")
        if candidate_links < source_analysis.link_count:
            raise RuntimeError("se perdieron enlaces")

    if source_analysis.outline_count > 0:
        candidate_outline_count = _outline_count(candidate_doc)
        if candidate_outline_count < source_analysis.outline_count:
            raise RuntimeError("se perdieron marcadores")


def _compare_visual_pages(
    source: Path,
    candidate: Path,
    pages: list[int],
    profile: CompressProfile,
    *,
    source_cache: _VisualSourceCache | None = None,
) -> None:
    if not pages:
        return
    source_doc: PdfRenderDocument | None = None
    with PdfRenderDocument(candidate) as candidate_doc:
        if source_cache is None:
            source_doc = PdfRenderDocument(source)
        for page_index in pages:
            source_img = (
                source_cache.render(page_index)
                if source_cache is not None
                else _render_page_array(source_doc, page_index)
            )
            candidate_img = _render_page_array(candidate_doc, page_index)
            _assert_visual_arrays_match(source_img, candidate_img, page_index, profile)
        if source_doc is not None:
            source_doc.close()


def _compare_visual_pages_by_rules(
    source: Path,
    candidate: Path,
    pages: list[int],
    global_profile_id: str,
    options: CompressOptions,
    page_plan: PageCompressionPlan,
    *,
    source_cache: _VisualSourceCache | None = None,
) -> None:
    if not pages:
        return
    source_doc: PdfRenderDocument | None = None
    with PdfRenderDocument(candidate) as candidate_doc:
        if source_cache is None:
            source_doc = PdfRenderDocument(source)
        for page_index in pages:
            effective = page_plan.rule_for_page(page_index)
            profile = _profile_for_effective_rule(
                effective,
                global_profile_id,
                options,
            )
            source_img = (
                source_cache.render(page_index)
                if source_cache is not None
                else _render_page_array(source_doc, page_index)
            )
            candidate_img = _render_page_array(candidate_doc, page_index)
            _assert_visual_arrays_match(source_img, candidate_img, page_index, profile)
        if source_doc is not None:
            source_doc.close()


def _compare_visual_page_pair(
    source_doc: PdfRenderDocument,
    candidate_doc: PdfRenderDocument,
    page_index: int,
    profile: CompressProfile,
) -> None:
    source_img = _render_page_array(source_doc, page_index)
    candidate_img = _render_page_array(candidate_doc, page_index)
    _assert_visual_arrays_match(source_img, candidate_img, page_index, profile)


def _assert_visual_arrays_match(
    source_img: np.ndarray,
    candidate_img: np.ndarray,
    page_index: int,
    profile: CompressProfile,
) -> None:
    if source_img.shape != candidate_img.shape:
        raise RuntimeError(f"pagina {page_index + 1} cambio de tamano visual")
    diff = np.abs(
        source_img.astype(np.int16, copy=False)
        - candidate_img.astype(np.int16, copy=False)
    )
    mean_delta = float(diff.mean())
    p95_delta = float(np.percentile(diff, 95))
    changed_ratio = float((diff.max(axis=2) > 40).mean())
    if mean_delta > profile.max_visual_mean_delta:
        raise RuntimeError(
            f"pagina {page_index + 1} cambio demasiado ({mean_delta:.1f})"
        )
    if (
        p95_delta > profile.max_visual_p95_delta
        and changed_ratio > profile.max_changed_pixel_ratio
    ):
        raise RuntimeError(
            f"pagina {page_index + 1} perdio fidelidad visual ({p95_delta:.1f})"
        )


def _render_page_array(doc: PdfRenderDocument, page_index: int) -> np.ndarray:
    info = doc.page_info(page_index)
    page_long = max(1.0, info.width_pt, info.height_pt)
    dpi = min(
        _VALIDATION_MAX_DPI,
        max(_VALIDATION_MIN_DPI, _VALIDATION_MAX_SIDE * 72.0 / page_long),
    )
    scale = dpi / 72.0
    rendered = doc.render_page(page_index, scale=scale)
    data = np.frombuffer(rendered.data, dtype=np.uint8)
    return data.reshape((rendered.height, rendered.width, len(rendered.mode))).copy()


def _choose_candidate(candidates: list[_Candidate], input_size: int) -> _Candidate | None:
    valid = [candidate for candidate in candidates if _candidate_is_useful(candidate, input_size)]
    if not valid:
        return None
    return min(valid, key=lambda candidate: candidate.size)


def _candidate_is_useful(candidate: _Candidate, input_size: int) -> bool:
    return (
        0 < candidate.size < input_size
        and _candidate_reduction_pct(candidate, input_size) >= _MIN_USEFUL_REDUCTION_PCT
    )


def _shared_image_rule_warnings(
    source: Path,
    page_plan: PageCompressionPlan,
) -> list[str]:
    xref_rules: dict[int, set[tuple]] = {}
    with pikepdf.Pdf.open(source) as doc:
        for page_index in range(min(len(doc.pages), page_plan.page_count)):
            rule_key = _effective_rule_key(page_plan.rule_for_page(page_index))
            try:
                images = doc.pages[page_index].get_images(recursive=True).values()
            except Exception:
                continue
            for image_object in images:
                xref = int(image_object.objgen[0])
                if xref > 0:
                    xref_rules.setdefault(xref, set()).add(rule_key)
    shared = sum(1 for rules in xref_rules.values() if len(rules) > 1)
    if shared <= 0:
        return []
    if shared == 1:
        return [
            "1 imagen compartida se aislo para proteger reglas por pagina"
        ]
    return [
        f"{shared} imagenes compartidas se aislaron para proteger reglas por pagina"
    ]


def _page_rule_result_fields(
    page_plan: PageCompressionPlan,
    warnings: list[str],
) -> dict:
    if not page_plan.has_explicit_rules:
        return {
            "pages_compressed": 0,
            "pages_excluded": 0,
            "pages_custom": 0,
            "page_rule_summary": "",
            "rule_warnings": [],
        }
    return {
        "pages_compressed": page_plan.pages_compressible,
        "pages_excluded": page_plan.pages_excluded,
        "pages_custom": page_plan.pages_custom,
        "page_rule_summary": page_plan.summary,
        "rule_warnings": list(warnings),
    }


def _result_warning_notes(notes: list[str]) -> list[str]:
    if not notes:
        return []
    warnings: list[str] = []
    joined = " ".join(notes)
    if "recompresion visual directa omitida" in joined:
        warnings.append("se omitio recompresion directa por imagenes con mascara")
    elif "recompresion visual interna omitida" in joined:
        warnings.append("se omitio recompresion interna por imagenes con mascara")
    if "rechazad" in joined:
        warnings.append("algunas estrategias no pasaron validacion segura")
    if not warnings:
        warnings.append("no se acepto ningun candidato")
    return warnings


def _find_qpdf() -> str | None:
    return _find_executable(
        ["qpdf.exe", "qpdf"],
        [
            *_app_local_matches("tools/qpdf/qpdf.exe"),
            *_app_local_matches("tools/qpdf/bin/qpdf.exe"),
            *_app_local_matches("qpdf/qpdf.exe"),
            *_app_local_matches("qpdf/bin/qpdf.exe"),
            *_program_file_matches("qpdf*/bin/qpdf.exe"),
            Path(os.environ.get("ProgramData", "")) / "chocolatey" / "bin" / "qpdf.exe",
        ],
    )


def _find_ghostscript() -> str | None:
    return _find_executable(
        ["gswin64c.exe", "gswin32c.exe", "gs"],
        [
            *_app_local_matches("tools/ghostscript/bin/gswin64c.exe"),
            *_app_local_matches("tools/ghostscript/bin/gswin32c.exe"),
            *_app_local_matches("tools/ghostscript/gswin64c.exe"),
            *_app_local_matches("tools/ghostscript/gswin32c.exe"),
            *_app_local_matches("ghostscript/bin/gswin64c.exe"),
            *_app_local_matches("ghostscript/bin/gswin32c.exe"),
            *_app_local_matches("gs/bin/gswin64c.exe"),
            *_app_local_matches("gs/bin/gswin32c.exe"),
            *_program_file_matches("gs/gs*/bin/gswin64c.exe"),
            *_program_file_matches("gs/gs*/bin/gswin32c.exe"),
            *_program_file_matches("PDF24/gs/bin/gswin64c.exe"),
            *_program_file_matches("PDF24/gs/bin/gswin32c.exe"),
            *_program_file_matches("PDF24/gs/gswin64c.exe"),
            *_program_file_matches("PDF24/gs/gswin32c.exe"),
        ],
    )


def _find_executable(names: list[str], candidates: list[Path]) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def _app_local_matches(relative_pattern: str) -> list[Path]:
    matches: list[Path] = []
    seen: set[Path] = set()
    for root in _app_local_roots():
        try:
            for candidate in root.glob(relative_pattern):
                if candidate not in seen:
                    seen.add(candidate)
                    matches.append(candidate)
        except OSError:
            continue
    return matches


def _app_local_roots() -> list[Path]:
    roots: list[Path] = []
    for raw in (
        Path(sys.executable).resolve().parent,
        Path(__file__).resolve().parent.parent,
        Path.cwd(),
    ):
        if raw not in roots:
            roots.append(raw)
    return roots


def _program_file_matches(pattern: str) -> list[Path]:
    matches: list[Path] = []
    seen: set[Path] = set()
    for root in _program_file_roots():
        try:
            for candidate in root.glob(pattern):
                if candidate not in seen:
                    seen.add(candidate)
                    matches.append(candidate)
        except OSError:
            continue
    return matches


def _program_file_roots() -> list[Path]:
    roots: list[Path] = []
    for key in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        raw = os.environ.get(key)
        if not raw:
            continue
        path = Path(raw)
        if path not in roots:
            roots.append(path)
    return roots


def _engine_source(path: str | None) -> str:
    if not path:
        return "no detectado"
    try:
        resolved = Path(path).resolve()
        for root in _app_local_roots():
            try:
                resolved.relative_to(root.resolve())
                return "empaquetado"
            except ValueError:
                continue
    except OSError:
        pass
    return "instalado"


def _run_command(command: list[str], label: str, *, timeout: int = 180) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=flags,
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        if details:
            raise RuntimeError(f"{label} fallo: {_short_error_text(details)}")
        raise RuntimeError(f"{label} fallo con codigo {completed.returncode}")


def _ghostscript_mono_dpi(profile: CompressProfile) -> int:
    if profile.id == "quality":
        return 600
    return max(300, int(profile.dpi_target) * 2)


def _temp_output_path(output: Path, suffix: str) -> Path:
    extension = output.suffix or ".pdf"
    token = uuid.uuid4().hex[:8]
    return output.with_name(f"{output.stem}.tmp-{suffix}-{token}{extension}")


def _replace_file(source: Path, dest: Path) -> None:
    try:
        source.replace(dest)
    except OSError:
        shutil.copy2(str(source), str(dest))
        source.unlink(missing_ok=True)


def _copy_original(source: Path, output: Path) -> None:
    shutil.copy2(str(source), str(output))


def _remove_file(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except Exception:
        return str(a) == str(b)


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _short_error(exc: Exception) -> str:
    text = str(exc).strip()
    return _short_error_text(text) or exc.__class__.__name__


def _short_error_text(text: str) -> str:
    if len(text) > 110:
        return text[:107] + "..."
    return text
