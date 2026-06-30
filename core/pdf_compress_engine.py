"""PDF compression / optimization engine."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Callable, List
import uuid

import fitz
import numpy as np

from core.pdf_page_rules import (
    EffectivePageCompression,
    PageCompressionPlan,
    PageCompressionRule,
    build_page_compression_plan,
)


_VALIDATION_MAX_SIDE = 1200
_VALIDATION_MIN_DPI = 24.0
_VALIDATION_MAX_DPI = 72.0


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
        label="Correo",
        description="Maxima reduccion razonable para enviar o subir a portales.",
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
        description="Limpieza ligera y reduccion conservadora.",
        dpi_threshold=300,
        dpi_target=240,
        quality=88,
        max_visual_mean_delta=9.0,
        max_visual_p95_delta=42.0,
        max_changed_pixel_ratio=0.12,
    ),
}


@dataclass(frozen=True)
class CompressOptions:
    engine_mode: str = "auto"  # auto, pymupdf, qpdf, ghostscript
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
    oversized_images: int = 0
    risky_images: int = 0
    annotation_count: int = 0
    form_widget_count: int = 0
    link_count: int = 0
    outline_count: int = 0
    image_pages: list[int] = field(default_factory=list)
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


class _VisualSourceCache:
    """Cachea renders del PDF fuente durante la validacion de candidatos.

    La comparacion visual puede validar varios candidatos contra las mismas
    paginas. Renderizar esas paginas fuente una sola vez evita repetir el
    trabajo mas costoso sin relajar los umbrales de fidelidad.
    """

    def __init__(self, source: Path) -> None:
        self.source = source
        self._doc: fitz.Document | None = None
        self._pages: dict[int, np.ndarray] = {}

    def render(self, page_index: int) -> np.ndarray:
        cached = self._pages.get(page_index)
        if cached is not None:
            return cached
        if self._doc is None:
            self._doc = fitz.open(str(self.source))
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
            if job.page_rules and options.engine_mode in {"qpdf", "ghostscript"}:
                raise RuntimeError(
                    "Las reglas por pagina requieren motor Automatico o PyMuPDF interno."
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
            if page_plan.has_explicit_rules and options.engine_mode in {"qpdf", "ghostscript"}:
                raise RuntimeError(
                    "Las reglas por pagina requieren motor Automatico o PyMuPDF interno."
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

            if page_plan.has_explicit_rules:
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
                should_try_images = _should_try_image_rewrite(analysis)

                qpdf_exe = _find_qpdf()
                if _engine_allows(options, "qpdf") and qpdf_exe:
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
                if _engine_allows(options, "pymupdf"):
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

                    if not should_try_images or not image_candidate_useful:
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

                ghostscript_exe = _find_ghostscript()
                if (
                    _engine_allows(options, "ghostscript")
                    and ghostscript_exe
                    and (should_try_images or options.engine_mode == "ghostscript")
                ):
                    ghostscript_path = _temp_output_path(output, "ghostscript")
                    temp_paths.append(ghostscript_path)
                    try:
                        _emit_status(status, 72, "Probando compresion fuerte con Ghostscript...")
                        _write_ghostscript_candidate(
                            source,
                            ghostscript_path,
                            profile,
                            ghostscript_exe,
                        )
                        _emit_status(status, 86, "Validando candidato Ghostscript...")
                        candidates.append(
                            _validate_candidate(
                                source,
                                ghostscript_path,
                                analysis,
                                validation_pages,
                                profile,
                                "ghostscript pdfwrite",
                                visual_cache=visual_cache,
                            )
                        )
                    except Exception as exc:
                        rejected_notes.append(
                            f"ghostscript rechazado: {_short_error(exc)}"
                        )

            _emit_status(status, 92, "Seleccionando el mejor resultado validado...")
            chosen = _choose_candidate(candidates, input_size)
            warning_parts: list[str] = []
            if analysis.repaired_on_open:
                warning_parts.append("estructura reparada al abrir")

            if chosen is None:
                _emit_status(status, 96, "Conservando original: no hubo mejora segura...")
                _copy_original(source, output)
                warning_parts.append("ya estaba optimizado")
                if not candidates and rejected_notes:
                    warning_parts.append("no se acepto ningun candidato")
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
    if engine_mode not in {"auto", "pymupdf", "qpdf", "ghostscript"}:
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
    if options.engine_mode == "ghostscript" and not _find_ghostscript():
        raise RuntimeError("Ghostscript no esta disponible en esta PC.")


def _engine_allows(options: CompressOptions, engine: str) -> bool:
    if options.engine_mode == "auto":
        return True
    if options.engine_mode == "pymupdf":
        return engine == "pymupdf"
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
    doc = fitz.open(str(source))
    try:
        _assert_readable(doc)
        if doc.page_count <= 0:
            raise RuntimeError("El PDF no tiene paginas.")

        analysis = _PdfAnalysis(
            page_count=doc.page_count,
            signature_flags=_signature_flags(doc),
            has_forms=bool(getattr(doc, "is_form_pdf", False)),
            repaired_on_open=bool(getattr(doc, "is_repaired", False)),
        )
        try:
            analysis.outline_count = len(doc.get_toc(simple=True))
        except Exception:
            analysis.outline_count = 0
        for page_index in range(doc.page_count):
            page = doc[page_index]
            analysis.annotation_count += _page_annotation_count(page)
            analysis.form_widget_count += _page_widget_count(page)
            analysis.link_count += _page_link_count(page)
            try:
                images = page.get_image_info(xrefs=True)
            except Exception:
                _append_unique(analysis.risky_pages, page_index)
                continue
            if images:
                _append_unique(analysis.image_pages, page_index)
            for info in images:
                analysis.image_count += 1
                effective_dpi = _effective_image_dpi(info)
                has_mask = bool(info.get("has-mask"))
                if has_mask:
                    analysis.risky_images += 1
                    _append_unique(analysis.risky_pages, page_index)
                if effective_dpi >= profile.dpi_threshold:
                    analysis.oversized_images += 1
                    _append_unique(analysis.oversized_pages, page_index)
        return analysis
    finally:
        doc.close()


def _assert_readable(doc: fitz.Document) -> None:
    if doc.needs_pass or doc.is_encrypted:
        raise RuntimeError("El PDF esta protegido o cifrado.")


def _signature_flags(doc: fitz.Document) -> int:
    try:
        return int(doc.get_sigflags())
    except Exception:
        return -1


def _page_annotation_count(page: fitz.Page) -> int:
    try:
        annots = page.annots()
        if annots is None:
            return 0
        return sum(1 for _ in annots)
    except Exception:
        return 0


def _page_widget_count(page: fitz.Page) -> int:
    try:
        widgets = page.widgets()
        if widgets is None:
            return 0
        return sum(1 for _ in widgets)
    except Exception:
        return 0


def _page_link_count(page: fitz.Page) -> int:
    try:
        return len(page.get_links())
    except Exception:
        return 0


def _effective_image_dpi(info: dict) -> float:
    width = float(info.get("width") or 0)
    height = float(info.get("height") or 0)
    try:
        bbox = fitz.Rect(info.get("bbox"))
    except Exception:
        return 0.0
    if width <= 0 or height <= 0 or bbox.width <= 0 or bbox.height <= 0:
        return 0.0
    dpi_x = width * 72.0 / bbox.width
    dpi_y = height * 72.0 / bbox.height
    return max(dpi_x, dpi_y)


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


def _should_try_image_rewrite(analysis: _PdfAnalysis) -> bool:
    return analysis.image_count > 0 and analysis.oversized_images > 0


def _write_safe_candidate(source: Path, output: Path) -> None:
    doc = fitz.open(str(source))
    try:
        _assert_readable(doc)
        _save_optimized(doc, output)
    finally:
        doc.close()


def _write_image_candidate(source: Path, output: Path, profile: CompressProfile) -> None:
    doc = fitz.open(str(source))
    try:
        _assert_readable(doc)
        doc.rewrite_images(
            dpi_threshold=profile.dpi_threshold,
            dpi_target=profile.dpi_target,
            quality=profile.quality,
            lossy=profile.rewrite_lossy,
            lossless=profile.rewrite_lossless,
            bitonal=False,
            color=True,
            gray=True,
            set_to_gray=profile.set_to_gray,
        )
        _save_optimized(doc, output)
    finally:
        doc.close()


def _write_page_rules_candidate(
    source: Path,
    output: Path,
    global_profile_id: str,
    options: CompressOptions,
    page_plan: PageCompressionPlan,
) -> list[str]:
    warnings = _shared_image_rule_warnings(source, page_plan)
    src = fitz.open(str(source))
    out = fitz.open()
    try:
        _assert_readable(src)
        for start, end, effective in _page_rule_segments(page_plan):
            if effective.excluded:
                out.insert_pdf(
                    src,
                    from_page=start,
                    to_page=end,
                    links=1,
                    annots=1,
                    widgets=1,
                )
                continue

            segment = fitz.open()
            try:
                segment.insert_pdf(
                    src,
                    from_page=start,
                    to_page=end,
                    links=1,
                    annots=1,
                    widgets=1,
                )
                profile = _profile_for_effective_rule(
                    effective,
                    global_profile_id,
                    options,
                )
                segment.rewrite_images(
                    dpi_threshold=profile.dpi_threshold,
                    dpi_target=profile.dpi_target,
                    quality=profile.quality,
                    lossy=profile.rewrite_lossy,
                    lossless=profile.rewrite_lossless,
                    bitonal=False,
                    color=True,
                    gray=True,
                    set_to_gray=profile.set_to_gray,
                )
                out.insert_pdf(segment, links=1, annots=1, widgets=1)
            finally:
                segment.close()

        if out.page_count != src.page_count:
            raise RuntimeError("el candidato por reglas produjo un numero inesperado de paginas")
        try:
            out.set_metadata(src.metadata or {})
        except Exception:
            pass
        try:
            toc = src.get_toc(simple=False)
            if toc:
                out.set_toc(toc)
        except Exception:
            warnings.append("no se pudieron conservar todos los marcadores")
        _save_optimized(out, output)
        return warnings
    finally:
        out.close()
        src.close()


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
            engine_mode="pymupdf",
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
    _run_command(command, "ghostscript")


def _save_optimized(doc: fitz.Document, output: Path) -> None:
    doc.save(
        str(output),
        # garbage=4 compara streams para deduplicar objetos y puede dominar el
        # tiempo en PDFs largos de texto. garbage=2 compacta xref y limpia
        # objetos no referenciados con una reduccion casi igual en la practica.
        garbage=2,
        clean=False,
        deflate=True,
        deflate_images=True,
        deflate_fonts=True,
        use_objstms=1,
        preserve_metadata=1,
        encryption=fitz.PDF_ENCRYPT_NONE,
    )


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

    doc = fitz.open(str(candidate))
    try:
        _assert_readable(doc)
        if doc.page_count != source_analysis.page_count:
            raise RuntimeError(
                "paginas inesperadas "
                f"({doc.page_count}; se esperaban {source_analysis.page_count})"
            )
        _validate_structural_fidelity(doc, source_analysis)
    finally:
        doc.close()

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

    doc = fitz.open(str(candidate))
    try:
        _assert_readable(doc)
        if doc.page_count != source_analysis.page_count:
            raise RuntimeError(
                "paginas inesperadas "
                f"({doc.page_count}; se esperaban {source_analysis.page_count})"
            )
        _validate_structural_fidelity(doc, source_analysis)
    finally:
        doc.close()

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
    candidate_doc: fitz.Document,
    source_analysis: _PdfAnalysis,
) -> None:
    if source_analysis.has_forms and not bool(getattr(candidate_doc, "is_form_pdf", False)):
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
        for page in candidate_doc:
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
        try:
            candidate_outline_count = len(candidate_doc.get_toc(simple=True))
        except Exception:
            candidate_outline_count = 0
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
    source_doc: fitz.Document | None = None
    candidate_doc = fitz.open(str(candidate))
    try:
        if source_cache is None:
            source_doc = fitz.open(str(source))
        for page_index in pages:
            source_img = (
                source_cache.render(page_index)
                if source_cache is not None
                else _render_page_array(source_doc, page_index)
            )
            candidate_img = _render_page_array(candidate_doc, page_index)
            _assert_visual_arrays_match(source_img, candidate_img, page_index, profile)
    finally:
        candidate_doc.close()
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
    source_doc: fitz.Document | None = None
    candidate_doc = fitz.open(str(candidate))
    try:
        if source_cache is None:
            source_doc = fitz.open(str(source))
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
    finally:
        candidate_doc.close()
        if source_doc is not None:
            source_doc.close()


def _compare_visual_page_pair(
    source_doc: fitz.Document,
    candidate_doc: fitz.Document,
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


def _render_page_array(doc: fitz.Document, page_index: int) -> np.ndarray:
    page = doc[page_index]
    page_long = max(1.0, page.rect.width, page.rect.height)
    dpi = min(
        _VALIDATION_MAX_DPI,
        max(_VALIDATION_MIN_DPI, _VALIDATION_MAX_SIDE * 72.0 / page_long),
    )
    scale = dpi / 72.0
    pix = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        colorspace=fitz.csRGB,
        alpha=False,
        annots=True,
    )
    data = np.frombuffer(pix.samples, dtype=np.uint8)
    return data.reshape((pix.height, pix.width, pix.n)).copy()


def _choose_candidate(candidates: list[_Candidate], input_size: int) -> _Candidate | None:
    valid = [candidate for candidate in candidates if _candidate_is_useful(candidate, input_size)]
    if not valid:
        return None
    return min(valid, key=lambda candidate: candidate.size)


def _candidate_is_useful(candidate: _Candidate, input_size: int) -> bool:
    return 0 < candidate.size < input_size


def _shared_image_rule_warnings(
    source: Path,
    page_plan: PageCompressionPlan,
) -> list[str]:
    xref_rules: dict[int, set[tuple]] = {}
    doc = fitz.open(str(source))
    try:
        for page_index in range(min(doc.page_count, page_plan.page_count)):
            rule_key = _effective_rule_key(page_plan.rule_for_page(page_index))
            try:
                images = doc[page_index].get_image_info(xrefs=True)
            except Exception:
                continue
            for info in images:
                xref = int(info.get("xref") or 0)
                if xref > 0:
                    xref_rules.setdefault(xref, set()).add(rule_key)
    finally:
        doc.close()
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


def _run_command(command: list[str], label: str) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=180,
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
