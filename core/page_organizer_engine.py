"""Page organizer engine for rebuilding PDFs from visual page references."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

from core.pdf_backend import (
    PdfCancelledError,
    SourcePage,
    assemble_pages,
)


@dataclass(frozen=True)
class PageRef:
    """Reference to one source PDF page plus an extra rotation delta."""

    source_path: str
    page_index: int
    rotation_deg: int = 0
    page_id: str = ""


@dataclass
class OrganizerJob:
    pages: List[PageRef]
    output_path: str


@dataclass
class OrganizerResult:
    job: OrganizerJob
    output_path: str = ""
    success: bool = False
    error: str = ""
    total_pages: int = 0
    source_count: int = 0


@dataclass
class MultiOrganizerJob:
    """N lanes → N PDFs independientes o 1 PDF fusionado."""
    lanes: List[OrganizerJob]
    merge_all: bool = False


@dataclass
class MultiOrganizerResult:
    results: List[OrganizerResult]
    merged_output_path: str = ""
    success: bool = False
    error: str = ""


class PageOrganizerEngine:
    """Builds a new PDF from ordered page references."""

    def run_job(
        self,
        job: OrganizerJob,
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> OrganizerResult:
        if not job.pages:
            return OrganizerResult(
                job=job,
                success=False,
                error="No hay paginas para organizar.",
            )

        output_path = Path(job.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        total = len(job.pages)
        source_pages = [
            SourcePage(
                path=page.source_path,
                index=page.page_index,
                rotation=_normalize_rotation(page.rotation_deg),
            )
            for page in job.pages
        ]

        try:
            def on_page_copied(index: int, _total: int, page_ref: SourcePage) -> None:
                if progress:
                    progress(
                        index,
                        total,
                        f"Copiando pagina {page_ref.index + 1} de {Path(page_ref.path).name}...",
                    )

            report = assemble_pages(
                source_pages,
                output_path,
                progress=on_page_copied,
                should_cancel=should_cancel,
            )

            if progress:
                progress(total, total, "Guardando PDF organizado...")
            return OrganizerResult(
                job=job,
                output_path=str(output_path),
                success=True,
                total_pages=report.page_count,
                source_count=report.source_count,
            )
        except PdfCancelledError:
            return OrganizerResult(
                job=job,
                success=False,
                error="Operacion cancelada.",
            )
        except Exception as exc:
            return OrganizerResult(job=job, success=False, error=str(exc))

    def run_multi_job(
        self,
        job: MultiOrganizerJob,
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> MultiOrganizerResult:
        if not job.lanes:
            return MultiOrganizerResult(results=[], success=False, error="No hay lanes.")

        if job.merge_all:
            all_pages: List[PageRef] = []
            for lane_job in job.lanes:
                all_pages.extend(lane_job.pages)
            # Use the output_path of the first lane as the merged output
            merged_out = job.lanes[0].output_path
            merged_job = OrganizerJob(pages=all_pages, output_path=merged_out)
            result = self.run_job(merged_job, progress=progress, should_cancel=should_cancel)
            return MultiOrganizerResult(
                results=[result],
                merged_output_path=result.output_path,
                success=result.success,
                error=result.error,
            )

        results: List[OrganizerResult] = []
        total_lanes = len(job.lanes)
        for idx, lane_job in enumerate(job.lanes):
            if should_cancel and should_cancel():
                return MultiOrganizerResult(results=results, success=False, error="Operación cancelada.")

            def _prog(c, t, m, _i=idx, _n=total_lanes):
                if progress:
                    overall = int((_i + c / max(1, t)) / _n * 100)
                    progress(overall, 100, m)

            result = self.run_job(lane_job, progress=_prog, should_cancel=should_cancel)
            results.append(result)

        all_ok = all(r.success for r in results)
        return MultiOrganizerResult(
            results=results,
            success=all_ok,
            error="" if all_ok else "; ".join(r.error for r in results if r.error),
        )


def _normalize_rotation(value: int) -> int:
    """Return a clockwise rotation in 90-degree steps."""
    return (int(round(value / 90.0)) * 90) % 360
