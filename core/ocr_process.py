"""Ejecutor aislado del motor OCR.

Este modulo corre en un proceso separado de la interfaz. La comunicacion usa
archivos JSON temporales para mantener la aplicacion estable incluso si una
dependencia nativa del OCR termina inesperadamente.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback
from typing import Any, Optional

from core.ocr_engine import (
    OcrConfig,
    OcrEngine,
    OcrJob,
    ocr_job_result_to_dict,
)


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
    """Procesa una solicitud OCR y persiste progreso, checkpoints y respuesta."""

    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        jobs = [OcrJob(**job_data) for job_data in payload["jobs"]]
        config = OcrConfig(**payload["config"])

        _append_event(events_path, "started")
        results = OcrEngine().run_batch(
            jobs,
            config,
            progress=lambda current, total, message: _append_event(
                events_path,
                "progress",
                current=current,
                total=total,
                message=message,
            ),
            should_cancel=cancel_path.exists,
            result_ready=lambda result: _append_event(
                events_path,
                "result",
                result=ocr_job_result_to_dict(result),
            ),
        )
        cancelled = cancel_path.exists() or any(result.cancelled for result in results)
        _write_json_atomic(
            response_path,
            {
                "status": "cancelled" if cancelled else "ok",
                "results": [ocr_job_result_to_dict(result) for result in results],
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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="PDFlex OCR isolated worker")
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--cancel", required=True)
    args = parser.parse_args(argv)
    return run_request(
        Path(args.request),
        Path(args.response),
        Path(args.events),
        Path(args.cancel),
    )


if __name__ == "__main__":
    raise SystemExit(main())

