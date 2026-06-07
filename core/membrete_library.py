"""Biblioteca local de hojas membretadas."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import fitz


MEMBRETE_LIBRARY_ENV = "PDFLEX_MEMBRETE_LIBRARY_DIR"
MEMBRETE_LIBRARY_FILE = "library.json"


@dataclass(frozen=True)
class SavedLetterhead:
    id: str
    label: str
    path: str
    source_name: str
    added_at: float
    page_count: int = 0
    page_width_pt: float = 0.0
    page_height_pt: float = 0.0


def membrete_library_root() -> Path:
    override = os.environ.get(MEMBRETE_LIBRARY_ENV)
    if override:
        return Path(override).expanduser().resolve()

    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base).resolve() / "PDFlex" / "membretado" / "membretes"
    return Path.home().resolve() / ".pdflex" / "membretado" / "membretes"


def load_letterhead_library(root: Path | None = None) -> list[SavedLetterhead]:
    library_root = root or membrete_library_root()
    library_file = library_root / MEMBRETE_LIBRARY_FILE
    if not library_file.exists():
        return []
    try:
        payload = json.loads(library_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    entries: list[SavedLetterhead] = []
    for raw in payload.get("letterheads", []):
        try:
            entry = SavedLetterhead(
                id=str(raw["id"]),
                label=str(raw.get("label") or raw.get("source_name") or "Membrete"),
                path=str(raw["path"]),
                source_name=str(raw.get("source_name") or Path(str(raw["path"])).name),
                added_at=float(raw.get("added_at") or 0.0),
                page_count=int(raw.get("page_count") or 0),
                page_width_pt=float(raw.get("page_width_pt") or 0.0),
                page_height_pt=float(raw.get("page_height_pt") or 0.0),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if Path(entry.path).exists():
            entries.append(entry)
    return sorted(entries, key=lambda item: item.added_at, reverse=True)


def add_letterhead_to_library(
    pdf_path: str | Path,
    *,
    label: str = "",
    root: Path | None = None,
) -> SavedLetterhead:
    source = Path(pdf_path).resolve()
    if not source.exists():
        raise FileNotFoundError("El membrete no existe.")
    if source.suffix.lower() != ".pdf":
        raise ValueError("La biblioteca solo guarda membretes PDF.")

    page_count, width, height = _pdf_metadata(source)
    digest = _file_digest(source)
    library_root = root or membrete_library_root()
    files_dir = library_root / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    stored_path = files_dir / f"{digest[:16]}.pdf"
    if not stored_path.exists():
        shutil.copy2(source, stored_path)

    entry = SavedLetterhead(
        id=digest,
        label=_friendly_label(label or source.stem),
        path=str(stored_path),
        source_name=source.name,
        added_at=time.time(),
        page_count=page_count,
        page_width_pt=width,
        page_height_pt=height,
    )

    entries = [item for item in load_letterhead_library(library_root) if item.id != entry.id]
    entries.insert(0, entry)
    _save_letterhead_library(entries, library_root)
    return entry


def remove_letterhead_from_library(letterhead_id: str, root: Path | None = None) -> bool:
    library_root = root or membrete_library_root()
    entries = load_letterhead_library(library_root)
    kept = [item for item in entries if item.id != letterhead_id]
    removed = len(kept) != len(entries)
    if removed:
        _save_letterhead_library(kept, library_root)
    return removed


def _save_letterhead_library(entries: list[SavedLetterhead], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "letterheads": [asdict(item) for item in entries]}
    tmp = root / f"{MEMBRETE_LIBRARY_FILE}.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(root / MEMBRETE_LIBRARY_FILE)


def _pdf_metadata(path: Path) -> tuple[int, float, float]:
    doc = fitz.open(str(path))
    try:
        if doc.is_encrypted:
            raise RuntimeError("El PDF esta protegido o cifrado.")
        if doc.page_count <= 0:
            raise RuntimeError("El PDF no tiene paginas.")
        page = doc[0]
        return int(doc.page_count), float(page.rect.width), float(page.rect.height)
    finally:
        doc.close()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _friendly_label(text: str) -> str:
    label = Path(text).stem.strip().replace("_", " ").replace("-", " ")
    label = " ".join(label.split())
    return (label or "Membrete guardado")[:48]
