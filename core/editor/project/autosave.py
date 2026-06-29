"""Autosave: escritura periódica atómica en %APPDATA%/PDFlex/autosave (spec §15).

Sin Qt: quien lo usa (EditorWindow, plan Parte 2) llama maybe_autosave() desde
un QTimer. Aquí solo vive la política (intervalo, destino, limpieza)."""
from __future__ import annotations
import os
import time
from pathlib import Path

from .format import ProjectStore


def autosave_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home())) / "PDFlex" / "autosave"
    base.mkdir(parents=True, exist_ok=True)
    return base


class Autosaver:
    def __init__(self, interval_s: float = 90.0, directory: Path | None = None) -> None:
        self._interval = interval_s
        self._dir = directory or autosave_dir()
        self._last_save = 0.0
        self._dirty = False
        self.last_error = ""

    def mark_dirty(self) -> None:
        self._dirty = True

    def autosave_path(self, doc) -> Path:
        return self._dir / f"{doc.source_sha256[:16]}.flexproj"

    def maybe_autosave(self, doc) -> Path | None:
        """Guarda si hay cambios y pasó el intervalo. Retorna la ruta si guardó."""
        if not self._dirty or (time.monotonic() - self._last_save) < self._interval:
            return None
        path = self.autosave_path(doc)
        try:
            ProjectStore().save(doc, path)
        except Exception as exc:
            self.last_error = str(exc)
            self._last_save = time.monotonic()
            return None
        self.last_error = ""
        self._last_save = time.monotonic()
        self._dirty = False
        return path

    def discard(self, doc) -> None:
        """Al cerrar limpiamente se elimina el autosave (ya no hay nada que recuperar)."""
        p = self.autosave_path(doc)
        if p.exists():
            p.unlink()
        self._dirty = False

    def pending_recoveries(self) -> list[Path]:
        return sorted(self._dir.glob("*.flexproj"))
