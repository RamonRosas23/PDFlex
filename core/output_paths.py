"""Shared helpers for transient PDFlex outputs.

Tools write generated files to per-run folders under the system temp
directory. The user keeps a result by using "Guardar como" from the viewer.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil
import tempfile
import uuid


_UNSAFE_CHARS = set('\\/:*?"<>|')


def pdflex_temp_root() -> Path:
    return Path(tempfile.gettempdir()).resolve() / "PDFlex"


def sanitize_filename(name: str, fallback: str = "salida") -> str:
    cleaned = "".join(
        "_" if char in _UNSAFE_CHARS or ord(char) < 32 else char
        for char in str(name)
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned or fallback


def cleanup_old_runs(tool_root: Path, *, days: int = 7) -> None:
    """Remove old run directories without touching current-session files."""
    if days <= 0 or not tool_root.exists():
        return
    cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
    for child in tool_root.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except Exception:
            pass


def make_run_dir(tool_name: str, *, cleanup_days: int = 7) -> Path:
    tool_root = pdflex_temp_root() / sanitize_filename(tool_name, "tool")
    tool_root.mkdir(parents=True, exist_ok=True)
    cleanup_old_runs(tool_root, days=cleanup_days)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for _ in range(20):
        run_dir = tool_root / f"{stamp}-{uuid.uuid4().hex[:8]}"
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            return run_dir
        except FileExistsError:
            continue
    raise RuntimeError(f"No se pudo crear carpeta temporal para {tool_name}.")


def unique_name(
    base: str,
    suffix: str = "",
    *,
    reserved: set[str] | None = None,
    directory: Path | None = None,
    fallback: str = "salida",
) -> str:
    safe_base = sanitize_filename(base, fallback)
    if suffix and not suffix.startswith("."):
        suffix = "." + suffix
    reserved = reserved if reserved is not None else set()

    index = 1
    while True:
        stem = safe_base if index == 1 else f"{safe_base}_{index}"
        candidate = f"{stem}{suffix}"
        key = candidate.casefold()
        exists = directory is not None and (directory / candidate).exists()
        if key not in reserved and not exists:
            reserved.add(key)
            return candidate
        index += 1


def unique_output_path(
    out_dir: Path,
    filename: str,
    *,
    reserved: set[str] | None = None,
    fallback: str = "salida",
) -> Path:
    raw = Path(str(filename)).name
    suffix = Path(raw).suffix
    stem = raw[: -len(suffix)] if suffix else raw
    return out_dir / unique_name(
        stem,
        suffix,
        reserved=reserved,
        directory=out_dir,
        fallback=fallback,
    )


def filename_with_suffix(name: str, suffix: str, *, fallback: str = "salida") -> str:
    if not suffix.startswith("."):
        suffix = "." + suffix
    raw = Path(str(name).strip()).name
    if raw.casefold().endswith(suffix.casefold()):
        raw = raw[: -len(suffix)]
    return f"{sanitize_filename(raw, fallback)}{suffix}"
