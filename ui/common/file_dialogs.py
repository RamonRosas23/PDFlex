"""Native Windows file dialog wrappers for PDFlex."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QWidget


def get_open_file_name(
    parent: QWidget | None,
    title: str,
    directory: str = "",
    file_filter: str = "Todos los archivos (*)",
) -> tuple[str, str]:
    path, selected = QFileDialog.getOpenFileName(
        parent, title, directory, file_filter
    )
    return str(Path(path)) if path else "", selected


def get_open_file_names(
    parent: QWidget | None,
    title: str,
    directory: str = "",
    file_filter: str = "Todos los archivos (*)",
) -> tuple[list[str], str]:
    paths, selected = QFileDialog.getOpenFileNames(
        parent, title, directory, file_filter
    )
    return [str(Path(p)) for p in paths], selected


def get_save_file_name(
    parent: QWidget | None,
    title: str,
    directory: str = "",
    file_filter: str = "Todos los archivos (*)",
) -> tuple[str, str]:
    path, selected = QFileDialog.getSaveFileName(
        parent, title, directory, file_filter
    )
    return str(Path(path)) if path else "", selected


def get_existing_directory(
    parent: QWidget | None,
    title: str,
    directory: str = "",
) -> str:
    path = QFileDialog.getExistingDirectory(parent, title, directory)
    return str(Path(path)) if path else ""
