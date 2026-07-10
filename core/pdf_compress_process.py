"""Isolated PDF compression worker process.

This module runs outside the Qt process and communicates through temporary
JSON files. Keeping PyMuPDF / image work out of the UI process prevents native
code or long GIL holds from freezing progress updates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback
from typing import Any, Optional

def _write_json_atomic(path: Path, payload: dict) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _append_event(path: Path, event_type: str, **payload: Any) -> None:
    event = {"type": event_type, **payload}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()


def run_request(
    request_path: Path,
    response_path: Path,
    events_path: Path,
    cancel_path: Path,
) -> int:
    """Processes a compression request and persists progress/results."""

    try:
        from core.pdf_compress_engine import (
            PdfCompressEngine,
            compress_job_from_dict,
            compress_result_to_dict,
        )

        _append_event(events_path, "started")
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        jobs = [compress_job_from_dict(job_data) for job_data in payload["jobs"]]
        total = len(jobs)
        total_units = max(1, total) * 100
        results = []
        engine = PdfCompressEngine()

        for index, job in enumerate(jobs):
            if cancel_path.exists():
                break
            _append_event(
                events_path,
                "progress",
                current=index * 100,
                total=total_units,
                message=f"Preparando {Path(job.pdf_path).name}...",
            )

            def _stage(stage_pct: int, message: str, *, _index: int = index) -> None:
                if cancel_path.exists():
                    raise RuntimeError("Operacion cancelada.")
                pct = max(0, min(99, int(stage_pct)))
                _append_event(
                    events_path,
                    "progress",
                    current=_index * 100 + pct,
                    total=total_units,
                    message=message,
                )

            result = engine.run_job(job, status=_stage)
            results.append(result)
            _append_event(
                events_path,
                "result",
                result=compress_result_to_dict(result),
            )
            _append_event(
                events_path,
                "progress",
                current=(index + 1) * 100,
                total=total_units,
                message=f"{index + 1}/{total} PDFs procesados",
            )

        cancelled = cancel_path.exists()
        _write_json_atomic(
            response_path,
            {
                "status": "cancelled" if cancelled else "ok",
                "results": [compress_result_to_dict(result) for result in results],
            },
        )
        return 0
    except Exception as exc:
        error = str(exc) or exc.__class__.__name__
        _append_event(events_path, "error", message=error)
        _write_json_atomic(
            response_path,
            {
                "status": "error",
                "error": error,
                "traceback": traceback.format_exc(),
            },
        )
        return 1


def page_rewrite_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="PDFlex single-page compression worker")
    parser.add_argument("--page-source", required=True)
    parser.add_argument("--page-output", required=True)
    parser.add_argument("--page-index", required=True, type=int)
    parser.add_argument("--dpi-threshold", required=True, type=int)
    parser.add_argument("--dpi-target", required=True, type=int)
    parser.add_argument("--quality", required=True, type=int)
    parser.add_argument("--lossy", default="1")
    parser.add_argument("--lossless", default="1")
    parser.add_argument("--set-to-gray", default="0")
    args = parser.parse_args(argv)

    try:
        from core.pdf_compress_engine import (
            CompressProfile,
            _write_single_page_image_candidate,
        )

        profile = CompressProfile(
            id="page-worker",
            label="Page worker",
            description="",
            dpi_threshold=int(args.dpi_threshold),
            dpi_target=int(args.dpi_target),
            quality=int(args.quality),
            set_to_gray=str(args.set_to_gray).strip() == "1",
            rewrite_lossy=str(args.lossy).strip() != "0",
            rewrite_lossless=str(args.lossless).strip() != "0",
        )
        _write_single_page_image_candidate(
            Path(args.page_source),
            Path(args.page_output),
            int(args.page_index),
            profile,
        )
        return 0
    except Exception:
        traceback.print_exc()
        return 1


def doc_rewrite_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="PDFlex whole-document compression worker")
    parser.add_argument("--doc-source", required=True)
    parser.add_argument("--doc-output", required=True)
    parser.add_argument("--dpi-threshold", required=True, type=int)
    parser.add_argument("--dpi-target", required=True, type=int)
    parser.add_argument("--quality", required=True, type=int)
    parser.add_argument("--lossy", default="1")
    parser.add_argument("--lossless", default="1")
    parser.add_argument("--set-to-gray", default="0")
    args = parser.parse_args(argv)

    try:
        from core.pdf_compress_engine import (
            CompressProfile,
            _write_image_candidate,
        )

        profile = CompressProfile(
            id="doc-worker",
            label="Doc worker",
            description="",
            dpi_threshold=int(args.dpi_threshold),
            dpi_target=int(args.dpi_target),
            quality=int(args.quality),
            set_to_gray=str(args.set_to_gray).strip() == "1",
            rewrite_lossy=str(args.lossy).strip() != "0",
            rewrite_lossless=str(args.lossless).strip() != "0",
        )
        _write_image_candidate(
            Path(args.doc_source),
            Path(args.doc_output),
            profile,
        )
        return 0
    except Exception:
        traceback.print_exc()
        return 1


def main(argv: Optional[list[str]] = None) -> int:
    raw_args = list(argv) if argv is not None else None
    if raw_args is None:
        import sys
        raw_args = sys.argv[1:]
    if raw_args and raw_args[0] == "--page-rewrite":
        return page_rewrite_main(raw_args[1:])
    if raw_args and raw_args[0] == "--doc-rewrite":
        return doc_rewrite_main(raw_args[1:])

    parser = argparse.ArgumentParser(description="PDFlex PDF compression worker")
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--cancel", required=True)
    args = parser.parse_args(raw_args)
    return run_request(
        Path(args.request),
        Path(args.response),
        Path(args.events),
        Path(args.cancel),
    )


if __name__ == "__main__":
    raise SystemExit(main())
