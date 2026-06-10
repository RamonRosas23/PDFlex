"""Respaldo del archivo destino antes de sobrescribir (spec §15)."""
from __future__ import annotations
import shutil
from datetime import datetime
from pathlib import Path


def backup_existing(target: Path) -> Path | None:
    """Si target existe, lo copia a <dir>/respaldo/<stem>_<timestamp>.pdf."""
    if not target.exists():
        return None
    backup_dir = target.parent / "respaldo"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"{target.stem}_{stamp}{target.suffix}"
    shutil.copy2(target, dest)
    return dest
