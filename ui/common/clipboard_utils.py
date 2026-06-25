"""Clipboard helpers shared by PDFlex widgets."""
from __future__ import annotations

from pathlib import Path
import os
import struct
from typing import Iterable

from PyQt6.QtCore import QByteArray, QMimeData, QUrl
from PyQt6.QtGui import QClipboard
from PyQt6.QtWidgets import QApplication


def existing_file_paths(paths: Iterable[str]) -> list[str]:
    """Return existing local files without duplicates, preserving order."""
    result: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        if not raw:
            continue
        try:
            path = str(Path(raw).resolve())
        except OSError:
            continue
        if path in seen or not Path(path).is_file():
            continue
        seen.add(path)
        result.append(path)
    return result


def copy_files_to_clipboard(paths: Iterable[str]) -> bool:
    """Place local files on the OS clipboard as file URLs."""
    files = existing_file_paths(paths)
    if not files:
        return False

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path) for path in files])
    mime.setText("\n".join(files))
    if os.name == "nt":
        # Windows Explorer reads this DWORD to know that pasting should copy.
        mime.setData(
            'application/x-qt-windows-mime;value="Preferred DropEffect"',
            QByteArray(struct.pack("<I", 1)),
        )

    clipboard = QApplication.clipboard()
    clipboard.setMimeData(mime, QClipboard.Mode.Clipboard)
    return clipboard.mimeData(QClipboard.Mode.Clipboard).hasUrls()


def clipboard_file_paths(
    *,
    suffixes: Iterable[str] | None = None,
) -> list[str]:
    """Read local file paths from the clipboard, optionally filtering by suffix."""
    clipboard = QApplication.clipboard()
    mime = clipboard.mimeData(QClipboard.Mode.Clipboard)
    if not mime or not mime.hasUrls():
        return []

    normalized_suffixes = None
    if suffixes is not None:
        normalized_suffixes = {
            value.lower() if value.startswith(".") else f".{value.lower()}"
            for value in suffixes
        }

    paths: list[str] = []
    seen: set[str] = set()
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if not path:
            continue
        suffix = Path(path).suffix.lower()
        if normalized_suffixes is not None and suffix not in normalized_suffixes:
            continue
        if path in seen or not Path(path).is_file():
            continue
        seen.add(path)
        paths.append(path)
    return paths
