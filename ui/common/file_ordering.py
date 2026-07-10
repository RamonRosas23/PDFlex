"""Helpers for stable external file import ordering."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

from PySide6.QtCore import QSettings


_NATURAL_RE = re.compile(r"\d+|\D+")
ORG_NAME = "GRUPO OCMX"
APP_NAME = "PDFlex"
NATURAL_IMPORT_SORT_KEY = "imports/natural_sort"
DEFAULT_NATURAL_IMPORT_SORT = False


def _natural_text_key(text: str) -> tuple[tuple[int, object, int], ...]:
    parts: list[tuple[int, object, int]] = []
    for part in _NATURAL_RE.findall(text.casefold()):
        if part.isdigit():
            parts.append((1, int(part), len(part)))
        else:
            parts.append((0, part, 0))
    return tuple(parts)


def natural_path_key(path: str | Path) -> tuple[str, tuple[tuple[int, object, int], ...], str]:
    candidate = Path(path)
    return (
        str(candidate.parent).casefold(),
        _natural_text_key(candidate.name),
        str(candidate).casefold(),
    )


def natural_import_sort_enabled() -> bool:
    settings = QSettings(ORG_NAME, APP_NAME)
    return _as_bool(
        settings.value(NATURAL_IMPORT_SORT_KEY, DEFAULT_NATURAL_IMPORT_SORT),
        DEFAULT_NATURAL_IMPORT_SORT,
    )


def set_natural_import_sort_enabled(enabled: bool) -> None:
    settings = QSettings(ORG_NAME, APP_NAME)
    settings.setValue(NATURAL_IMPORT_SORT_KEY, bool(enabled))


def import_paths(paths: Iterable[str], *, natural_sort: bool | None = None) -> list[str]:
    """Return non-empty local paths without duplicates.

    The default preserves the order provided by Qt/Windows. Natural filename
    sorting is an optional global preference, disabled by default.
    """
    unique: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        if not raw:
            continue
        value = str(Path(raw))
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    if natural_sort is None:
        natural_sort = natural_import_sort_enabled()
    return sorted(unique, key=natural_path_key) if natural_sort else unique


def paths_from_mime_data(mime_data) -> list[str]:
    """Extract local file paths from Qt MIME data using the import preference."""
    if mime_data is None or not mime_data.hasUrls():
        return []
    return import_paths(
        url.toLocalFile()
        for url in mime_data.urls()
        if url.isLocalFile()
    )


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "si", "sí", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default
