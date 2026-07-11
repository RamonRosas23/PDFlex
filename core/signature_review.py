"""Editable post-processing model for visual signatures.

The firmador first creates an automatic draft.  This module turns that draft's
placement metadata into editable signature instances and can export a final PDF
from the original source plus the approved instances.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Callable, Iterable, Optional

from core.pdf_backend import PdfRenderDocument, Rect, pdf_page_count
from .pdf_analyzer import PdfAnalyzer
from .safe_zone import Placement, fit_placement_inside_page
from .signature_engine import (
    JobResult,
    PageResult,
    SignatureEngine,
    SignaturePageResult,
)
from .variation import VariationConfig


ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]


@dataclass
class ReviewSignatureInstance:
    instance_id: str
    signature_uid: str
    signature_label: str
    signature_path: str
    page_index: int
    x: float
    y: float
    width: float
    height: float
    angle: float
    opacity: float = 1.0
    original_x: float = 0.0
    original_y: float = 0.0
    original_width: float = 0.0
    original_height: float = 0.0
    original_angle: float = 0.0
    original_opacity: float = 1.0
    order: int = 0
    deleted: bool = False
    clean: bool = True
    snapped_to_line: bool = False
    adjusted_to_page: bool = False
    scaled_to_fit: bool = False
    moved_to_safe_zone: bool = False
    collides_with_text: bool = False
    overlaps_signature: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_page_result(
        cls,
        *,
        signature_path: str,
        signature_uid: str,
        signature_label: str,
        page_index: int,
        placement: Placement,
        order: int,
    ) -> "ReviewSignatureInstance":
        uid = signature_uid or Path(signature_path).stem or "firma"
        instance = cls(
            instance_id=f"{uid}:{page_index}:{order}",
            signature_uid=signature_uid or uid,
            signature_label=signature_label or Path(signature_path).stem or "Firma",
            signature_path=signature_path,
            page_index=page_index,
            x=placement.x,
            y=placement.y,
            width=placement.width,
            height=placement.height,
            angle=placement.angle,
            opacity=placement.opacity,
            original_x=placement.x,
            original_y=placement.y,
            original_width=placement.width,
            original_height=placement.height,
            original_angle=placement.angle,
            original_opacity=placement.opacity,
            order=order,
            clean=placement.clean,
            snapped_to_line=placement.snapped_to_line,
            adjusted_to_page=placement.adjusted_to_page,
            scaled_to_fit=placement.scaled_to_fit,
            moved_to_safe_zone=placement.moved_to_safe_zone,
            collides_with_text=placement.collides_with_text,
            overlaps_signature=placement.overlaps_signature,
        )
        instance.warnings = warnings_from_placement(instance.to_placement())
        return instance

    def to_placement(self) -> Placement:
        return Placement(
            x=self.x,
            y=self.y,
            width=self.width,
            height=self.height,
            angle=self.angle,
            opacity=self.opacity,
            clean=self.clean,
            snapped_to_line=self.snapped_to_line,
            adjusted_to_page=self.adjusted_to_page,
            scaled_to_fit=self.scaled_to_fit,
            moved_to_safe_zone=self.moved_to_safe_zone,
            collides_with_text=self.collides_with_text,
            overlaps_signature=self.overlaps_signature,
        )

    def reset_to_original(self) -> None:
        self.x = self.original_x
        self.y = self.original_y
        self.width = self.original_width
        self.height = self.original_height
        self.angle = self.original_angle
        self.opacity = self.original_opacity
        self.deleted = False

    def update_from_preview(
        self,
        *,
        cx_norm: float,
        cy_norm: float,
        width_pt: float,
        height_pt: float,
        angle: float,
        page_width: float,
        page_height: float,
    ) -> None:
        self.x = cx_norm * page_width
        self.y = cy_norm * page_height
        self.width = width_pt
        self.height = height_pt
        self.angle = angle
        self.deleted = False

    def preview_tuple(
        self,
        page_width: float,
        page_height: float,
    ) -> tuple[float, float, float, float, float]:
        cx = self.x / page_width if page_width > 0 else 0.5
        cy = self.y / page_height if page_height > 0 else 0.5
        return cx, cy, self.width, self.height, self.angle


@dataclass
class ReviewDocument:
    source_path: str
    draft_path: str
    final_path: str
    source_result: JobResult
    instances: list[ReviewSignatureInstance] = field(default_factory=list)
    _validated_page_keys: dict[int, tuple[tuple[object, ...], ...]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def page_instances(
        self,
        page_index: int,
        *,
        include_deleted: bool = False,
    ) -> list[ReviewSignatureInstance]:
        items = [
            inst for inst in self.instances
            if inst.page_index == page_index and (include_deleted or not inst.deleted)
        ]
        return sorted(items, key=lambda inst: inst.order)

    @property
    def live_count(self) -> int:
        return sum(1 for inst in self.instances if not inst.deleted)

    @property
    def warning_count(self) -> int:
        return sum(1 for inst in self.instances if not inst.deleted and inst.warnings)

    def validation_key(self, page_index: int) -> tuple[tuple[object, ...], ...]:
        return tuple(
            (
                inst.instance_id,
                bool(inst.deleted),
                round(float(inst.x), 4),
                round(float(inst.y), 4),
                round(float(inst.width), 4),
                round(float(inst.height), 4),
                round(float(inst.angle), 4),
                round(float(inst.opacity), 4),
                int(inst.order),
            )
            for inst in self.page_instances(page_index, include_deleted=True)
        )

    def is_page_validation_current(self, page_index: int) -> bool:
        return self._validated_page_keys.get(page_index) == self.validation_key(page_index)

    def mark_page_validated(self, page_index: int) -> None:
        self._validated_page_keys[page_index] = self.validation_key(page_index)


def build_review_documents(results: Iterable[JobResult]) -> list[ReviewDocument]:
    documents: list[ReviewDocument] = []
    for result in results:
        if not result.success or not result.output_path:
            continue
        job = result.job
        review = ReviewDocument(
            source_path=job.pdf_path,
            draft_path=result.output_path,
            final_path=result.output_path,
            source_result=result,
        )
        for page_result in result.page_results:
            signature_results = (
                page_result.signature_results
                if page_result.signature_results
                else [
                    SignaturePageResult(
                        signature_path=job.signatures[0].signature_path if job.signatures else "",
                        placement=page_result.placement,
                    )
                ]
            )
            for order, sig_result in enumerate(signature_results):
                if not sig_result.signature_path:
                    continue
                review.instances.append(
                    ReviewSignatureInstance.from_page_result(
                        signature_path=sig_result.signature_path,
                        signature_uid=sig_result.signature_uid,
                        signature_label=sig_result.signature_label,
                        page_index=page_result.page_index,
                        placement=sig_result.placement,
                        order=order,
                    )
                )
        for page_index in {inst.page_index for inst in review.instances}:
            review.mark_page_validated(page_index)
        documents.append(review)
    return documents


def export_review_documents(
    review_documents: list[ReviewDocument],
    variation: VariationConfig,
    progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCallback] = None,
    *,
    force_validation: bool = True,
) -> list[JobResult]:
    engine = SignatureEngine(variation)
    total_pages = _total_source_pages(review_documents)
    done_pages = 0
    results: list[JobResult] = []

    for review in review_documents:
        if should_cancel and should_cancel():
            results.append(_failed_result(review, "Exportacion cancelada por el usuario"))
            break

        validate_review_document(review, force=force_validation)
        out_path = Path(review.final_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_name(f"{out_path.stem}.review.tmp.pdf")

        try:
            instances_by_page = _instances_by_page(review)
            placements_by_page = {
                page_index: [
                    (inst.signature_path, inst.to_placement())
                    for inst in instances
                ]
                for page_index, instances in instances_by_page.items()
            }

            def _progress(current: int, _total: int, message: str) -> None:
                if progress:
                    progress(
                        done_pages + current,
                        max(1, total_pages),
                        message,
                    )

            page_count = engine.export_review_instances(
                review.source_path,
                str(tmp_path),
                placements_by_page,
                progress=_progress,
                should_cancel=should_cancel,
            )
            done_pages += page_count
            os.replace(tmp_path, out_path)
            if progress:
                progress(done_pages, max(1, total_pages), f"Finalizado: {out_path.name}")
            results.append(review_document_to_job_result(review, success=True))
        except Exception as exc:  # noqa: BLE001 - error surfaced to the UI
            results.append(_failed_result(review, str(exc)))
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    return results


def validate_review_document(
    review: ReviewDocument,
    *,
    force: bool = True,
) -> None:
    page_indices = sorted({inst.page_index for inst in review.instances})
    if not force:
        page_indices = [
            page_index for page_index in page_indices
            if not review.is_page_validation_current(page_index)
        ]
        if not page_indices:
            return

    analyzer = PdfAnalyzer()
    try:
        with PdfRenderDocument(review.source_path) as document:
            for page_index in page_indices:
                if page_index < 0 or page_index >= document.page_count:
                    continue
                _validate_review_page_with_doc(review, document, page_index, analyzer)
    except Exception:
        return


def validate_review_page(
    review: ReviewDocument,
    page_index: int,
    *,
    force: bool = True,
) -> None:
    if not force and review.is_page_validation_current(page_index):
        return
    try:
        with PdfRenderDocument(review.source_path) as document:
            if 0 <= page_index < document.page_count:
                _validate_review_page_with_doc(
                    review, document, page_index, PdfAnalyzer()
                )
    except Exception:
        return


def _validate_review_page_with_doc(
    review: ReviewDocument,
    document: PdfRenderDocument,
    page_index: int,
    analyzer: PdfAnalyzer,
) -> None:
    page = document.page_info(page_index)
    analysis = analyzer.analyze_page(document, page_index)
    occupied: list[Rect] = []
    for inst in review.page_instances(page_index):
        placement = fit_placement_inside_page(
            inst.to_placement(), page.width_pt, page.height_pt, margin=0.0
        )
        bbox = placement.rotated_bbox
        collides = analysis.intersects_text(bbox, padding=4.0)
        overlaps = _intersects_any(bbox, occupied, padding=4.0)
        inst.collides_with_text = collides
        inst.overlaps_signature = overlaps
        inst.clean = not collides and not overlaps
        inst.adjusted_to_page = inst.adjusted_to_page or placement.adjusted_to_page
        inst.scaled_to_fit = inst.scaled_to_fit or placement.scaled_to_fit
        inst.warnings = warnings_from_placement(inst.to_placement())
        occupied.append(bbox)
    review.mark_page_validated(page_index)


def review_document_to_job_result(
    review: ReviewDocument,
    *,
    success: bool,
    error: str = "",
) -> JobResult:
    page_results: list[PageResult] = []
    instances_by_page = _instances_by_page(review)
    for page_index in sorted(instances_by_page):
        signature_results: list[SignaturePageResult] = []
        for inst in instances_by_page[page_index]:
            signature_results.append(
                SignaturePageResult(
                    signature_path=inst.signature_path,
                    placement=inst.to_placement(),
                    signature_uid=inst.signature_uid,
                    signature_label=inst.signature_label,
                )
            )
        if not signature_results:
            continue
        placements = [sig.placement for sig in signature_results]
        page_results.append(
            PageResult(
                page_index=page_index,
                placement=placements[0],
                snapped_to_line=any(p.snapped_to_line for p in placements),
                clean=all(p.clean for p in placements),
                signature_results=signature_results,
            )
        )
    return JobResult(
        job=review.source_result.job,
        output_path=review.final_path if success else "",
        page_results=page_results,
        success=success,
        error=error,
    )


def warnings_from_placement(placement: Placement) -> tuple[str, ...]:
    warnings: list[str] = []
    if placement.snapped_to_line:
        warnings.append("ajustada a linea")
    if placement.moved_to_safe_zone and not placement.snapped_to_line:
        warnings.append("reubicada")
    if placement.adjusted_to_page:
        warnings.append("limitada al papel")
    if placement.scaled_to_fit:
        warnings.append("reducida")
    if placement.collides_with_text:
        warnings.append("revisar texto")
    if placement.overlaps_signature:
        warnings.append("revisar firmas")
    if not placement.clean and not any(item.startswith("revisar") for item in warnings):
        warnings.append("revisar margen")
    return tuple(warnings)


def _intersects_any(rect: Rect, others: Iterable[Rect], padding: float) -> bool:
    expanded = Rect(
        rect.x0 - padding,
        rect.y0 - padding,
        rect.x1 + padding,
        rect.y1 + padding,
    )
    return any(expanded.intersects(other) for other in others)


def _instances_by_page(
    review: ReviewDocument,
) -> dict[int, list[ReviewSignatureInstance]]:
    grouped: dict[int, list[ReviewSignatureInstance]] = {}
    for inst in review.instances:
        if inst.deleted:
            continue
        grouped.setdefault(inst.page_index, []).append(inst)
    for items in grouped.values():
        items.sort(key=lambda inst: inst.order)
    return grouped


def _total_source_pages(review_documents: list[ReviewDocument]) -> int:
    total = 0
    for review in review_documents:
        try:
            total += pdf_page_count(review.source_path)
        except Exception:
            total += 1
    return max(1, total)


def _failed_result(review: ReviewDocument, error: str) -> JobResult:
    return JobResult(
        job=review.source_result.job,
        output_path="",
        success=False,
        error=error,
    )
