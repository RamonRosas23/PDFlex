"""Hybrid PDF logo detection and removal engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable, List, Sequence

import fitz
import numpy as np
from PIL import Image, ImageDraw

try:
    import cv2
except ImportError:  # pragma: no cover - exercised only in incomplete installs
    cv2 = None


SUPPORTED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DETECTION_MODES = {"hybrid", "embedded", "visual"}
FILL_MODES = {"none", "white"}


@dataclass(frozen=True)
class LogoRemovalOptions:
    detection_mode: str = "hybrid"
    similarity: float = 0.88
    page_scope: str = "all"
    custom_pages: str = ""
    min_width_pct: float = 2.0
    max_width_pct: float = 40.0
    render_dpi: int = 120
    detect_quarter_turns: bool = False
    padding_pt: float = 1.0
    fill_mode: str = "none"
    remove_vector_graphics: bool = True
    max_matches_per_page: int = 60


@dataclass
class LogoRemovalJob:
    pdf_path: str
    output_path: str
    logo_paths: List[str] = field(default_factory=list)
    options: LogoRemovalOptions = field(default_factory=LogoRemovalOptions)


@dataclass(frozen=True)
class LogoMatch:
    page_index: int
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float
    logo_path: str
    method: str

    @property
    def rect(self) -> fitz.Rect:
        return fitz.Rect(self.x0, self.y0, self.x1, self.y1)


@dataclass
class LogoRemovalResult:
    job: LogoRemovalJob
    output_path: str = ""
    success: bool = False
    error: str = ""
    total_pages: int = 0
    scanned_pages: int = 0
    pages_changed: int = 0
    match_count: int = 0
    embedded_matches: int = 0
    visual_matches: int = 0

    @property
    def meta_text(self) -> str:
        if self.match_count <= 0:
            return "Sin coincidencias detectadas"
        return (
            f"{self.match_count} logo{'s' if self.match_count != 1 else ''} eliminado"
            f"{'s' if self.match_count != 1 else ''} · {self.pages_changed} página"
            f"{'s' if self.pages_changed != 1 else ''}"
        )


@dataclass(frozen=True)
class _PreparedLogo:
    path: str
    rgba: Image.Image
    rgb: np.ndarray
    gray: np.ndarray
    alpha: np.ndarray
    aspect: float


class LogoRemovalEngine:
    """Detects supplied logo images and removes matching PDF occurrences."""

    def run_batch(
        self,
        jobs: List[LogoRemovalJob],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[LogoRemovalResult]:
        total = len(jobs)
        results: List[LogoRemovalResult] = []
        for index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(index, total, f"Analizando {Path(job.pdf_path).name}...")
            result = self.run_job(
                job,
                should_cancel=should_cancel,
                page_progress=(
                    lambda current, page_total, source_name=Path(job.pdf_path).name: progress(
                        index,
                        total,
                        f"{source_name} · página {current}/{page_total}",
                    )
                    if progress
                    else None
                ),
            )
            results.append(result)
            if progress:
                progress(index + 1, total, f"{index + 1}/{total} PDFs procesados")
        return results

    def run_job(
        self,
        job: LogoRemovalJob,
        *,
        should_cancel: Callable[[], bool] | None = None,
        page_progress: Callable[[int, int], None] | None = None,
    ) -> LogoRemovalResult:
        source = Path(job.pdf_path)
        output = Path(job.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        doc: fitz.Document | None = None

        try:
            self._validate_job(job)
            logos = _load_logos(job.logo_paths)
            doc = fitz.open(str(source))
            if doc.needs_pass:
                raise RuntimeError("El PDF está protegido o cifrado.")
            if doc.page_count <= 0:
                raise RuntimeError("El PDF no tiene páginas.")

            page_indexes = parse_page_selection(
                job.options.page_scope,
                job.options.custom_pages,
                doc.page_count,
            )
            all_matches: list[LogoMatch] = []
            for page_position, page_index in enumerate(page_indexes, start=1):
                if should_cancel and should_cancel():
                    raise _CancelledError()
                if page_progress:
                    page_progress(page_position, len(page_indexes))
                matches = self.detect_page(
                    doc,
                    page_index,
                    logos,
                    job.options,
                    should_cancel=should_cancel,
                )
                all_matches.extend(matches)

            grouped = _group_matches(all_matches)
            changed_pages = 0
            for page_index, matches in grouped.items():
                if should_cancel and should_cancel():
                    raise _CancelledError()
                page = doc[page_index]
                applied = self._apply_matches(page, matches, job.options)
                if applied:
                    changed_pages += 1

            doc.save(str(output), garbage=4, clean=True, deflate=True)
            embedded = sum(match.method == "embedded" for match in all_matches)
            visual = sum(match.method == "visual" for match in all_matches)
            return LogoRemovalResult(
                job=job,
                output_path=str(output),
                success=True,
                total_pages=doc.page_count,
                scanned_pages=len(page_indexes),
                pages_changed=changed_pages,
                match_count=len(all_matches),
                embedded_matches=embedded,
                visual_matches=visual,
            )
        except _CancelledError:
            return LogoRemovalResult(
                job=job,
                output_path=str(output),
                success=False,
                error="Operación cancelada.",
            )
        except Exception as exc:
            return LogoRemovalResult(
                job=job,
                output_path=str(output),
                success=False,
                error=str(exc) or type(exc).__name__,
            )
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass

    def detect_page(
        self,
        doc: fitz.Document,
        page_index: int,
        logos: Sequence[_PreparedLogo],
        options: LogoRemovalOptions,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[LogoMatch]:
        if should_cancel and should_cancel():
            raise _CancelledError()
        if page_index < 0 or page_index >= doc.page_count:
            return []
        page = doc[page_index]
        matches: list[LogoMatch] = []

        if options.detection_mode in {"hybrid", "embedded"}:
            matches.extend(
                self._detect_embedded(
                    doc,
                    page,
                    page_index,
                    logos,
                    options,
                    should_cancel=should_cancel,
                )
            )

        if options.detection_mode in {"hybrid", "visual"}:
            if cv2 is None and options.detection_mode == "hybrid":
                # Embedded detection remains useful in reduced installations.
                # A missing optional visual backend must not invalidate the PDF.
                visual = []
            elif options.detection_mode == "visual":
                visual = self._detect_visual(
                    page,
                    page_index,
                    logos,
                    options,
                    should_cancel=should_cancel,
                )
            else:
                embedded_paths = {match.logo_path for match in matches}
                missing_logos = [logo for logo in logos if logo.path not in embedded_paths]
                found_logos = [logo for logo in logos if logo.path in embedded_paths]
                visual = []
                if missing_logos:
                    visual.extend(
                        self._detect_visual(
                            page,
                            page_index,
                            missing_logos,
                            options,
                            should_cancel=should_cancel,
                        )
                    )
                container_rect = _hybrid_container_rect(page, matches)
                if found_logos and container_rect is not None:
                    visual.extend(
                        self._detect_visual(
                            page,
                            page_index,
                            found_logos,
                            options,
                            search_rect=container_rect,
                            should_cancel=should_cancel,
                        )
                    )
            matches.extend(visual)

        matches = _deduplicate_matches(matches)
        matches.sort(key=lambda item: (item.page_index, item.y0, item.x0))
        return matches[: max(1, options.max_matches_per_page)]

    def build_preview(
        self,
        pdf_path: str,
        page_index: int,
        logo_paths: Sequence[str],
        options: LogoRemovalOptions,
        *,
        max_side: int = 1500,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[Image.Image, list[LogoMatch], int]:
        self._validate_options(options)
        logos = _load_logos(logo_paths)
        doc = fitz.open(pdf_path)
        try:
            if doc.needs_pass:
                raise RuntimeError("El PDF está protegido o cifrado.")
            if doc.page_count <= 0:
                raise RuntimeError("El PDF no tiene páginas.")
            page_index = max(0, min(int(page_index), doc.page_count - 1))
            page = doc[page_index]
            dpi = _bounded_dpi(page, options.render_dpi, max_side)
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
            matches = self.detect_page(
                doc,
                page_index,
                logos,
                options,
                should_cancel=should_cancel,
            )

            scale_x = image.width / max(1.0, page.rect.width)
            scale_y = image.height / max(1.0, page.rect.height)
            draw = ImageDraw.Draw(image, "RGBA")
            for match in matches:
                rect = (
                    round(match.x0 * scale_x),
                    round(match.y0 * scale_y),
                    round(match.x1 * scale_x),
                    round(match.y1 * scale_y),
                )
                color = (20, 184, 166, 230) if match.method == "embedded" else (245, 158, 11, 230)
                draw.rectangle(rect, outline=color, width=max(2, round(min(image.size) / 350)))
                label = f"{round(match.confidence * 100)}% · {match.method}"
                text_box = draw.textbbox((rect[0], rect[1]), label)
                label_h = max(16, text_box[3] - text_box[1] + 6)
                label_y = max(0, rect[1] - label_h)
                label_w = text_box[2] - text_box[0] + 8
                draw.rectangle(
                    (rect[0], label_y, rect[0] + label_w, label_y + label_h),
                    fill=color,
                )
                draw.text((rect[0] + 4, label_y + 3), label, fill=(8, 10, 12, 255))
            return image, matches, doc.page_count
        finally:
            doc.close()

    def _detect_embedded(
        self,
        doc: fitz.Document,
        page: fitz.Page,
        page_index: int,
        logos: Sequence[_PreparedLogo],
        options: LogoRemovalOptions,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[LogoMatch]:
        matches: list[LogoMatch] = []
        seen_xrefs: set[int] = set()
        threshold = max(0.68, options.similarity - 0.09)

        for info in page.get_images(full=True):
            if should_cancel and should_cancel():
                raise _CancelledError()
            xref = int(info[0])
            smask = int(info[1]) if len(info) > 1 else 0
            if xref <= 0 or xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                candidate = _prepare_logo_image(_extract_pdf_image(doc, xref, smask), f"xref:{xref}")
            except Exception:
                continue

            best_logo: _PreparedLogo | None = None
            best_score = 0.0
            for logo in logos:
                score = _image_similarity(candidate, logo)
                if score > best_score:
                    best_score = score
                    best_logo = logo
            if best_logo is None or best_score < threshold:
                continue

            try:
                rects = page.get_image_rects(xref, transform=False)
            except Exception:
                rects = []
            for rect in rects:
                display_rect = _native_rect_to_display(page, fitz.Rect(rect))
                clipped = display_rect & page.rect
                if clipped.width < 1.0 or clipped.height < 1.0:
                    continue
                matches.append(
                    LogoMatch(
                        page_index=page_index,
                        x0=clipped.x0,
                        y0=clipped.y0,
                        x1=clipped.x1,
                        y1=clipped.y1,
                        confidence=min(1.0, best_score),
                        logo_path=best_logo.path,
                        method="embedded",
                    )
                )
        return matches

    def _detect_visual(
        self,
        page: fitz.Page,
        page_index: int,
        logos: Sequence[_PreparedLogo],
        options: LogoRemovalOptions,
        *,
        search_rect: fitz.Rect | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[LogoMatch]:
        if cv2 is None:
            raise RuntimeError(
                "La detección visual requiere OpenCV. Reinstala PDFlex para completar la dependencia."
            )

        dpi = _bounded_dpi(page, options.render_dpi, 1700)
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
        page_rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        page_rgb = page_rgb[:, :, :3].copy()
        offset_x = 0
        offset_y = 0
        full_width = pix.width
        if search_rect is not None:
            clipped = fitz.Rect(search_rect) & page.rect
            if clipped.width < 2.0 or clipped.height < 2.0:
                return []
            offset_x = max(0, int(np.floor(clipped.x0 / page.rect.width * pix.width)))
            offset_y = max(0, int(np.floor(clipped.y0 / page.rect.height * pix.height)))
            crop_x1 = min(pix.width, int(np.ceil(clipped.x1 / page.rect.width * pix.width)))
            crop_y1 = min(pix.height, int(np.ceil(clipped.y1 / page.rect.height * pix.height)))
            page_rgb = page_rgb[offset_y:crop_y1, offset_x:crop_x1]
            if page_rgb.shape[0] < 8 or page_rgb.shape[1] < 8:
                return []
        page_gray = cv2.cvtColor(page_rgb, cv2.COLOR_RGB2GRAY)
        page_edges = cv2.Canny(page_gray, 50, 150)
        scale_x = page.rect.width / max(1, pix.width)
        scale_y = page.rect.height / max(1, pix.height)
        threshold = max(0.60, min(0.995, options.similarity))
        required_score = 0.60 + (threshold - 0.50) * 0.60
        candidates: list[LogoMatch] = []

        region_height, region_width = page_gray.shape[:2]
        coarse_scale = min(1.0, 760.0 / max(pix.width, pix.height))
        coarse_size = (
            max(1, round(region_width * coarse_scale)),
            max(1, round(region_height * coarse_scale)),
        )
        if coarse_scale < 0.999:
            coarse_gray = cv2.resize(page_gray, coarse_size, interpolation=cv2.INTER_AREA)
        else:
            coarse_gray = page_gray
        coarse_edges = cv2.Canny(coarse_gray, 45, 145)

        min_width = max(
            10,
            round(full_width * coarse_scale * options.min_width_pct / 100.0),
        )
        max_width = min(
            coarse_gray.shape[1],
            round(full_width * coarse_scale * options.max_width_pct / 100.0),
        )
        if max_width < min_width:
            min_width, max_width = max_width, min_width
        widths = _geometric_widths(min_width, max_width, 11)

        for logo in logos:
            if should_cancel and should_cancel():
                raise _CancelledError()
            angles = (0, 90, 180, 270) if options.detect_quarter_turns else (0,)
            for angle in angles:
                if should_cancel and should_cancel():
                    raise _CancelledError()
                rotated = logo.rgba if angle == 0 else logo.rgba.rotate(-angle, expand=True)
                prepared = _prepare_logo_image(rotated, logo.path)
                proposals: list[tuple[float, int, int, int, int]] = []
                for target_width in widths:
                    if should_cancel and should_cancel():
                        raise _CancelledError()
                    natural_height = target_width / max(0.05, prepared.aspect)
                    for height_factor in (0.68, 0.82, 1.0, 1.20, 1.40):
                        target_height = max(7, round(natural_height * height_factor))
                        if (
                            target_width > coarse_gray.shape[1]
                            or target_height > coarse_gray.shape[0]
                        ):
                            continue
                        template_gray = cv2.resize(
                            prepared.gray,
                            (target_width, target_height),
                            interpolation=cv2.INTER_AREA if target_width < prepared.gray.shape[1] else cv2.INTER_CUBIC,
                        )
                        score_map = _template_score_map(coarse_gray, coarse_edges, template_gray)
                        points = _top_local_maxima(
                            score_map,
                            max(0.32, required_score - 0.34),
                            limit=3,
                        )
                        proposals.extend(
                            (score, x, y, target_width, target_height)
                            for x, y, score in points
                        )

                proposals = _nms_pixel_candidates(proposals, limit=14)
                for coarse_score, coarse_x, coarse_y, coarse_w, coarse_h in proposals:
                    if should_cancel and should_cancel():
                        raise _CancelledError()
                    base_width = coarse_w / max(0.001, coarse_scale)
                    base_height = coarse_h / max(0.001, coarse_scale)
                    center_x = (coarse_x + coarse_w / 2.0) / max(0.001, coarse_scale)
                    center_y = (coarse_y + coarse_h / 2.0) / max(0.001, coarse_scale)
                    refined_widths = {
                        max(8, round(base_width * factor))
                        for factor in (0.80, 0.87, 0.94, 1.0, 1.07, 1.14, 1.22)
                    }
                    roi_margin_x = max(12, round(base_width * 0.38))
                    roi_margin_y = max(10, round(base_height * 0.70))
                    roi_x0 = max(0, round(center_x - base_width / 2 - roi_margin_x))
                    roi_y0 = max(0, round(center_y - base_height / 2 - roi_margin_y))
                    roi_x1 = min(region_width, round(center_x + base_width / 2 + roi_margin_x))
                    roi_y1 = min(region_height, round(center_y + base_height / 2 + roi_margin_y))
                    roi_gray = page_gray[roi_y0:roi_y1, roi_x0:roi_x1]
                    roi_edges = page_edges[roi_y0:roi_y1, roi_x0:roi_x1]

                    for target_width in sorted(refined_widths):
                        scale_change = target_width / max(1.0, base_width)
                        refined_heights = {
                            max(7, round(base_height * scale_change * factor))
                            for factor in (0.88, 1.0, 1.13)
                        }
                        for target_height in sorted(refined_heights):
                            if target_width > roi_gray.shape[1] or target_height > roi_gray.shape[0]:
                                continue
                            template_gray = cv2.resize(
                                prepared.gray,
                                (target_width, target_height),
                                interpolation=cv2.INTER_AREA if target_width < prepared.gray.shape[1] else cv2.INTER_CUBIC,
                            )
                            score_map = _template_score_map(roi_gray, roi_edges, template_gray)
                            points = _top_local_maxima(score_map, max(0.34, required_score - 0.30), limit=2)
                            if not points:
                                continue
                            alpha = cv2.resize(
                                prepared.alpha,
                                (target_width, target_height),
                                interpolation=cv2.INTER_AREA,
                            )
                            template_rgb = cv2.resize(
                                prepared.rgb,
                                (target_width, target_height),
                                interpolation=cv2.INTER_AREA if target_width < prepared.rgb.shape[1] else cv2.INTER_CUBIC,
                            )
                            for local_x, local_y, raw_score in points:
                                x = roi_x0 + local_x
                                y = roi_y0 + local_y
                                patch = page_rgb[y:y + target_height, x:x + target_width]
                                verified = _patch_similarity(
                                    patch,
                                    template_gray,
                                    alpha,
                                    template_rgb,
                                )
                                combined = 0.12 * coarse_score + 0.32 * raw_score + 0.56 * verified
                                if combined < required_score:
                                    continue
                                candidates.append(
                                    LogoMatch(
                                        page_index=page_index,
                                        x0=(offset_x + x) * scale_x,
                                        y0=(offset_y + y) * scale_y,
                                        x1=(offset_x + x + target_width) * scale_x,
                                        y1=(offset_y + y + target_height) * scale_y,
                                        confidence=min(1.0, combined),
                                        logo_path=logo.path,
                                        method="visual",
                                    )
                                )

        candidates = _deduplicate_matches(candidates)
        candidates.sort(key=lambda item: item.confidence, reverse=True)
        return candidates[: max(1, options.max_matches_per_page)]

    def _apply_matches(
        self,
        page: fitz.Page,
        matches: Sequence[LogoMatch],
        options: LogoRemovalOptions,
    ) -> int:
        applied = 0
        fill = (1.0, 1.0, 1.0) if options.fill_mode == "white" else None
        for match in matches:
            rect = fitz.Rect(match.rect)
            if options.padding_pt:
                rect += (
                    -options.padding_pt,
                    -options.padding_pt,
                    options.padding_pt,
                    options.padding_pt,
                )
            rect &= page.rect
            if rect.width < 1.0 or rect.height < 1.0:
                continue
            native_rect = _display_rect_for_page(page, rect)
            page.add_redact_annot(native_rect, fill=fill, cross_out=False)
            applied += 1

        if applied:
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_PIXELS,
                graphics=(
                    fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED
                    if options.remove_vector_graphics
                    else fitz.PDF_REDACT_LINE_ART_NONE
                ),
                text=fitz.PDF_REDACT_TEXT_NONE,
            )
        return applied

    def _validate_job(self, job: LogoRemovalJob) -> None:
        if not Path(job.pdf_path).exists():
            raise ValueError("El PDF de origen no existe.")
        if not job.logo_paths:
            raise ValueError("Agrega al menos una imagen de logo.")
        self._validate_options(job.options)

    @staticmethod
    def _validate_options(options: LogoRemovalOptions) -> None:
        if options.detection_mode not in DETECTION_MODES:
            raise ValueError("Modo de detección no válido.")
        if not 0.50 <= options.similarity <= 0.999:
            raise ValueError("La similitud debe estar entre 50% y 99.9%.")
        if options.fill_mode not in FILL_MODES:
            raise ValueError("Relleno de eliminación no válido.")
        if not 0.2 <= options.min_width_pct <= 95.0:
            raise ValueError("El tamaño mínimo debe estar entre 0.2% y 95%.")
        if not options.min_width_pct <= options.max_width_pct <= 98.0:
            raise ValueError("El tamaño máximo debe ser mayor o igual al mínimo.")
        if not 72 <= int(options.render_dpi) <= 300:
            raise ValueError("La resolución de análisis debe estar entre 72 y 300 DPI.")
        if not 0.0 <= options.padding_pt <= 36.0:
            raise ValueError("El margen de eliminación debe estar entre 0 y 36 pt.")


def parse_page_selection(scope: str, custom_pages: str, page_count: int) -> list[int]:
    if page_count <= 0:
        return []
    if scope == "all":
        return list(range(page_count))
    if scope == "first":
        return [0]
    if scope != "custom":
        raise ValueError("Alcance de páginas no válido.")

    selected: set[int] = set()
    raw = custom_pages.replace(";", ",").replace(" ", "")
    if not raw:
        raise ValueError("Escribe un rango de páginas.")
    for token in (part for part in raw.split(",") if part):
        if "-" in token:
            start_s, end_s = token.split("-", 1)
            start = int(start_s) if start_s else 1
            end = int(end_s) if end_s else page_count
            if start > end:
                start, end = end, start
        else:
            start = end = int(token)
        if end < 1 or start > page_count:
            continue
        selected.update(range(max(1, start) - 1, min(page_count, end)))
    if not selected:
        raise ValueError("El rango no contiene páginas válidas.")
    return sorted(selected)


def _load_logos(paths: Iterable[str]) -> list[_PreparedLogo]:
    logos: list[_PreparedLogo] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix.lower() not in SUPPORTED_LOGO_EXTENSIONS:
            raise ValueError(f"Formato de logo no compatible: {path.name}")
        if not path.exists():
            raise ValueError(f"No existe la imagen de logo: {path.name}")
        try:
            with Image.open(path) as image:
                logos.append(_prepare_logo_image(image.convert("RGBA"), str(path)))
        except Exception as exc:
            raise ValueError(f"No se pudo abrir {path.name}: {exc}") from exc
    if not logos:
        raise ValueError("No se cargaron imágenes de logo válidas.")
    return logos


def _prepare_logo_image(image: Image.Image, path: str) -> _PreparedLogo:
    rgba = _crop_logo_content(image.convert("RGBA"))
    if rgba.width < 2 or rgba.height < 2:
        raise ValueError("La imagen de logo es demasiado pequeña.")
    alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    white.alpha_composite(rgba)
    rgb = np.asarray(white.convert("RGB"), dtype=np.uint8).copy()
    if cv2 is not None:
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    else:
        gray = np.asarray(white.convert("L"), dtype=np.uint8).copy()
    return _PreparedLogo(
        path=path,
        rgba=rgba.copy(),
        rgb=rgb,
        gray=gray,
        alpha=alpha.copy(),
        aspect=rgba.width / max(1.0, rgba.height),
    )


def _crop_transparent_border(image: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    extrema = alpha.getextrema()
    if extrema[0] == 255:
        return image.copy()
    bbox = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
    return image.crop(bbox) if bbox else image.copy()


def _crop_logo_content(image: Image.Image) -> Image.Image:
    """Remove transparent and near-uniform outer margins from a logo image."""
    cropped = _crop_transparent_border(image.convert("RGBA"))
    alpha = np.asarray(cropped.getchannel("A"), dtype=np.uint8)
    if alpha.size == 0 or int(alpha.min()) < 250:
        return cropped

    rgb = np.asarray(cropped.convert("RGB"), dtype=np.int16)
    if rgb.shape[0] < 4 or rgb.shape[1] < 4:
        return cropped
    border = np.concatenate(
        (rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]),
        axis=0,
    )
    background = np.median(border, axis=0)
    border_noise = np.max(np.abs(border - background), axis=1)
    tolerance = max(12.0, float(np.percentile(border_noise, 85)) + 7.0)
    foreground = np.max(np.abs(rgb - background), axis=2) > tolerance
    ys, xs = np.where(foreground)
    if len(xs) < max(6, round(foreground.size * 0.002)):
        return cropped

    pad = max(1, round(min(cropped.size) * 0.018))
    x0 = max(0, int(xs.min()) - pad)
    y0 = max(0, int(ys.min()) - pad)
    x1 = min(cropped.width, int(xs.max()) + pad + 1)
    y1 = min(cropped.height, int(ys.max()) + pad + 1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return cropped
    return cropped.crop((x0, y0, x1, y1))


def _extract_pdf_image(doc: fitz.Document, xref: int, smask: int) -> Image.Image:
    base_info = doc.extract_image(xref)
    if not base_info or not base_info.get("image"):
        raise ValueError("No se pudo extraer la imagen embebida.")
    base = Image.open(BytesIO(base_info["image"])).convert("RGBA")
    if smask > 0:
        try:
            mask_info = doc.extract_image(smask)
            mask = Image.open(BytesIO(mask_info["image"])).convert("L")
            if mask.size != base.size:
                mask = mask.resize(base.size, Image.Resampling.LANCZOS)
            base.putalpha(mask)
        except Exception:
            pass
    return base


def _image_similarity(first: _PreparedLogo, second: _PreparedLogo) -> float:
    aspect_ratio = max(first.aspect, second.aspect) / max(0.01, min(first.aspect, second.aspect))
    if aspect_ratio > 1.28:
        return 0.0
    size = (72, 72)
    a = _letterbox_gray(first.gray, size)
    b = _letterbox_gray(second.gray, size)
    corr = _normalized_corr(a, b)
    if cv2 is not None:
        corr = max(
            corr,
            _normalized_corr(
                cv2.GaussianBlur(a, (5, 5), 0),
                cv2.GaussianBlur(b, (5, 5), 0),
            ),
        )
        edge_a = cv2.Canny(a, 45, 145)
        edge_b = cv2.Canny(b, 45, 145)
        edge_corr = _edge_overlap(edge_a, edge_b)
    else:
        edge_a = _simple_edges(a)
        edge_b = _simple_edges(b)
        edge_corr = _normalized_corr(edge_a, edge_b)
    mae = float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32)))) / 255.0
    pixel_score = max(0.0, 1.0 - mae)
    aspect_score = max(0.0, 1.0 - (aspect_ratio - 1.0) / 0.28)
    return max(
        0.0,
        min(
            1.0,
            0.52 * corr
            + 0.22 * edge_corr
            + 0.16 * pixel_score
            + 0.10 * aspect_score,
        ),
    )


def _letterbox_gray(gray: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    target_w, target_h = size
    src_h, src_w = gray.shape[:2]
    scale = min(target_w / max(1, src_w), target_h / max(1, src_h))
    width = max(1, round(src_w * scale))
    height = max(1, round(src_h * scale))
    if cv2 is not None:
        resized = cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA)
    else:
        resized = np.asarray(
            Image.fromarray(gray).resize((width, height), Image.Resampling.LANCZOS),
            dtype=np.uint8,
        )
    canvas = np.full((target_h, target_w), 255, dtype=np.uint8)
    x = (target_w - width) // 2
    y = (target_h - height) // 2
    canvas[y:y + height, x:x + width] = resized
    return canvas


def _normalized_corr(first: np.ndarray, second: np.ndarray) -> float:
    a = first.astype(np.float32).ravel()
    b = second.astype(np.float32).ravel()
    a -= float(a.mean())
    b -= float(b.mean())
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-6:
        return 1.0 if np.allclose(first, second, atol=3) else 0.0
    return max(0.0, min(1.0, float(np.dot(a, b) / denom)))


def _simple_edges(gray: np.ndarray) -> np.ndarray:
    gx = np.zeros_like(gray, dtype=np.int16)
    gy = np.zeros_like(gray, dtype=np.int16)
    gx[:, 1:] = np.diff(gray.astype(np.int16), axis=1)
    gy[1:, :] = np.diff(gray.astype(np.int16), axis=0)
    mag = np.clip(np.abs(gx) + np.abs(gy), 0, 255)
    return mag.astype(np.uint8)


def _patch_similarity(
    patch_rgb: np.ndarray,
    template_gray: np.ndarray,
    alpha: np.ndarray,
    template_rgb: np.ndarray,
) -> float:
    if cv2 is None:
        return 0.0
    patch_gray = cv2.cvtColor(patch_rgb, cv2.COLOR_RGB2GRAY)
    mask = alpha > 24
    if np.count_nonzero(mask) < max(8, mask.size * 0.01):
        mask = np.ones_like(alpha, dtype=bool)

    if np.count_nonzero(mask) < 8:
        return 0.0

    corr = _masked_corr(patch_gray, template_gray, mask)
    corr = max(
        corr,
        _masked_corr(
            cv2.GaussianBlur(patch_gray, (5, 5), 0),
            cv2.GaussianBlur(template_gray, (5, 5), 0),
            mask,
        ),
    )

    patch_edges = cv2.Canny(patch_gray, 50, 150)
    template_edges = cv2.Canny(template_gray, 50, 150)
    edge_score = _edge_overlap(patch_edges, template_edges, mask)

    patch_color = patch_rgb[mask].astype(np.float32)
    template_color = template_rgb[mask].astype(np.float32)
    color_mae = float(np.mean(np.abs(patch_color - template_color))) / 255.0
    color_score = max(0.0, 1.0 - color_mae)
    return max(0.0, min(1.0, 0.74 * corr + 0.17 * edge_score + 0.09 * color_score))


def _masked_corr(first: np.ndarray, second: np.ndarray, mask: np.ndarray) -> float:
    a = first[mask].astype(np.float32)
    b = second[mask].astype(np.float32)
    if a.size < 8:
        return 0.0
    a -= float(a.mean())
    b -= float(b.mean())
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-6:
        return 1.0 if np.allclose(a, b, atol=3) else 0.0
    return max(0.0, min(1.0, float(np.dot(a, b) / denom)))


def _edge_overlap(
    first: np.ndarray,
    second: np.ndarray,
    mask: np.ndarray | None = None,
) -> float:
    if cv2 is None:
        return _normalized_corr(first, second)
    a = first > 0
    b = second > 0
    if mask is not None:
        a &= mask
        b &= mask
    if np.count_nonzero(a) < 4 or np.count_nonzero(b) < 4:
        return 0.0
    kernel = np.ones((3, 3), dtype=np.uint8)
    dilated_a = cv2.dilate(a.astype(np.uint8), kernel) > 0
    dilated_b = cv2.dilate(b.astype(np.uint8), kernel) > 0
    recall_a = np.count_nonzero(a & dilated_b) / max(1, np.count_nonzero(a))
    recall_b = np.count_nonzero(b & dilated_a) / max(1, np.count_nonzero(b))
    return float((recall_a + recall_b) / 2.0)


def _template_score_map(
    page_gray: np.ndarray,
    page_edges: np.ndarray,
    template_gray: np.ndarray,
) -> np.ndarray:
    gray_scores = cv2.matchTemplate(page_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    template_edges = cv2.Canny(template_gray, 50, 150)
    if np.count_nonzero(template_edges) < max(6, template_edges.size * 0.002):
        return gray_scores
    edge_scores = cv2.matchTemplate(page_edges, template_edges, cv2.TM_CCOEFF_NORMED)
    return gray_scores * 0.80 + edge_scores * 0.20


def _top_local_maxima(
    score_map: np.ndarray,
    threshold: float,
    *,
    limit: int,
) -> list[tuple[int, int, float]]:
    if cv2 is None or score_map.size == 0:
        return []
    kernel = np.ones((5, 5), dtype=np.uint8)
    local_max = score_map >= cv2.dilate(score_map, kernel)
    ys, xs = np.where(local_max & (score_map >= threshold))
    if not len(xs):
        return []
    scores = score_map[ys, xs]
    order = np.argsort(scores)[::-1][:limit]
    return [(int(xs[i]), int(ys[i]), float(scores[i])) for i in order]


def _nms_pixel_candidates(
    candidates: Sequence[tuple[float, int, int, int, int]],
    *,
    limit: int,
) -> list[tuple[float, int, int, int, int]]:
    kept: list[tuple[float, int, int, int, int]] = []
    for candidate in sorted(candidates, key=lambda item: item[0], reverse=True):
        _, x, y, width, height = candidate
        rect = fitz.Rect(x, y, x + width, y + height)
        if any(
            _rect_iou(
                rect,
                fitz.Rect(other_x, other_y, other_x + other_w, other_y + other_h),
            )
            >= 0.36
            for _, other_x, other_y, other_w, other_h in kept
        ):
            continue
        kept.append(candidate)
        if len(kept) >= max(1, limit):
            break
    return kept


def _geometric_widths(min_width: int, max_width: int, count: int) -> list[int]:
    min_width = max(8, int(min_width))
    max_width = max(min_width, int(max_width))
    if min_width == max_width:
        return [min_width]
    values = np.geomspace(min_width, max_width, max(2, count))
    return sorted({max(8, int(round(value))) for value in values})


def _bounded_dpi(page: fitz.Page, requested: int, max_side: int) -> float:
    page_long = max(1.0, page.rect.width, page.rect.height)
    limit = max_side * 72.0 / page_long
    return max(72.0, min(float(requested), limit))


def _hybrid_container_rect(
    page: fitz.Page,
    embedded_matches: Sequence[LogoMatch],
) -> fitz.Rect | None:
    """Return the union of large images that may contain extra rasterized logos."""
    if not embedded_matches:
        return None
    base_width = max(match.rect.width for match in embedded_matches)
    base_height = max(match.rect.height for match in embedded_matches)
    base_area = max(match.rect.get_area() for match in embedded_matches)
    regions: list[fitz.Rect] = []
    seen_xrefs: set[int] = set()
    for info in page.get_images(full=True):
        xref = int(info[0])
        if xref <= 0 or xref in seen_xrefs:
            continue
        seen_xrefs.add(xref)
        try:
            rects = page.get_image_rects(xref, transform=False)
        except Exception:
            continue
        for raw_rect in rects:
            rect = _native_rect_to_display(page, fitz.Rect(raw_rect)) & page.rect
            if rect.width < 2.0 or rect.height < 2.0:
                continue
            if any(_rect_iou(rect, match.rect) >= 0.38 for match in embedded_matches):
                continue
            is_container = (
                rect.get_area() >= base_area * 3.0
                or rect.width >= base_width * 2.0
                or rect.height >= base_height * 2.0
            )
            if is_container:
                regions.append(rect)
    if not regions:
        return None
    union = fitz.Rect(regions[0])
    for rect in regions[1:]:
        union.include_rect(rect)
    union += (-2.0, -2.0, 2.0, 2.0)
    return union & page.rect


def _group_matches(matches: Sequence[LogoMatch]) -> dict[int, list[LogoMatch]]:
    grouped: dict[int, list[LogoMatch]] = {}
    for match in matches:
        grouped.setdefault(match.page_index, []).append(match)
    return grouped


def _deduplicate_matches(matches: Sequence[LogoMatch]) -> list[LogoMatch]:
    ordered = sorted(
        matches,
        key=lambda item: (
            item.method == "embedded",
            item.confidence,
            item.rect.get_area(),
        ),
        reverse=True,
    )
    kept: list[LogoMatch] = []
    for candidate in ordered:
        if any(
            existing.page_index == candidate.page_index
            and _rect_iou(existing.rect, candidate.rect) >= 0.42
            for existing in kept
        ):
            continue
        kept.append(candidate)
    return kept


def _rect_iou(first: fitz.Rect, second: fitz.Rect) -> float:
    intersection = first & second
    if intersection.is_empty:
        return 0.0
    union = first.get_area() + second.get_area() - intersection.get_area()
    return intersection.get_area() / max(1e-6, union)


def _display_rect_for_page(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    if not int(page.rotation) % 360:
        return rect
    matrix = page.derotation_matrix
    points = [
        fitz.Point(rect.x0, rect.y0) * matrix,
        fitz.Point(rect.x1, rect.y0) * matrix,
        fitz.Point(rect.x0, rect.y1) * matrix,
        fitz.Point(rect.x1, rect.y1) * matrix,
    ]
    return fitz.Rect(
        min(point.x for point in points),
        min(point.y for point in points),
        max(point.x for point in points),
        max(point.y for point in points),
    )


def _native_rect_to_display(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    if not int(page.rotation) % 360:
        return rect
    matrix = page.rotation_matrix
    points = [
        fitz.Point(rect.x0, rect.y0) * matrix,
        fitz.Point(rect.x1, rect.y0) * matrix,
        fitz.Point(rect.x0, rect.y1) * matrix,
        fitz.Point(rect.x1, rect.y1) * matrix,
    ]
    return fitz.Rect(
        min(point.x for point in points),
        min(point.y for point in points),
        max(point.x for point in points),
        max(point.y for point in points),
    )


class _CancelledError(Exception):
    pass
