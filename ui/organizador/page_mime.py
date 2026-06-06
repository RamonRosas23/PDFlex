"""MIME serialization for cross-lane page drag & drop."""
from __future__ import annotations

import json
from typing import List, Optional, Tuple

from PyQt6.QtCore import QMimeData

from core.page_organizer_engine import PageRef

MIME_TYPE = "application/x-pdflex-pageref"


def encode_drag(lane_id: str, refs: List[PageRef]) -> QMimeData:
    payload = {
        "source_lane_id": lane_id,
        "refs": [
            {
                "source_path": r.source_path,
                "page_index": r.page_index,
                "rotation_deg": r.rotation_deg,
                "page_id": r.page_id,
            }
            for r in refs
        ],
    }
    mime = QMimeData()
    mime.setData(MIME_TYPE, json.dumps(payload).encode("utf-8"))
    return mime


def decode_drag(mime: QMimeData) -> Optional[Tuple[str, List[PageRef]]]:
    """Returns (source_lane_id, refs) or None if not our MIME."""
    if not mime.hasFormat(MIME_TYPE):
        return None
    try:
        payload = json.loads(bytes(mime.data(MIME_TYPE)).decode("utf-8"))
        lane_id = str(payload["source_lane_id"])
        refs = [
            PageRef(
                source_path=str(r["source_path"]),
                page_index=int(r["page_index"]),
                rotation_deg=int(r.get("rotation_deg", 0)),
                page_id=str(r.get("page_id", "")),
            )
            for r in payload["refs"]
        ]
        return lane_id, refs
    except (KeyError, ValueError, json.JSONDecodeError):
        return None
