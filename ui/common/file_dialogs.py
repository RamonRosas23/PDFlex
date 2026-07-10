"""Native Windows file dialog wrappers for PDFlex."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QWidget

from ui.common.file_ordering import import_paths


_LAST_LOCATION_KEY = "fileDialogs/lastLocation"


def _remembered_directory() -> Path | None:
    raw = QSettings().value(_LAST_LOCATION_KEY, "", str)
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_dir() else None


def _store_working_location(path: str | Path) -> None:
    if not path:
        return
    candidate = Path(path).expanduser()
    folder = candidate if candidate.is_dir() else candidate.parent
    if folder.is_dir():
        settings = QSettings()
        settings.setValue(_LAST_LOCATION_KEY, str(folder))
        settings.sync()


def _looks_like_file_path(path: Path) -> bool:
    return bool(path.name and path.suffix)


def _dialog_start(directory: str, *, preserve_filename: bool = False) -> str:
    explicit = Path(directory).expanduser() if directory else None
    remembered = _remembered_directory()

    if preserve_filename and explicit and _looks_like_file_path(explicit):
        if remembered:
            return str(remembered / explicit.name)
        return str(explicit)

    if remembered:
        return str(remembered)

    if explicit:
        if explicit.is_file():
            return str(explicit.parent)
        return str(explicit)
    return str(Path.home())


def get_open_file_name(
    parent: QWidget | None,
    title: str,
    directory: str = "",
    file_filter: str = "Todos los archivos (*)",
) -> tuple[str, str]:
    path, selected = QFileDialog.getOpenFileName(
        parent, title, _dialog_start(directory), file_filter
    )
    if path:
        _store_working_location(path)
        return str(Path(path)), selected
    return "", selected


def get_open_file_names(
    parent: QWidget | None,
    title: str,
    directory: str = "",
    file_filter: str = "Todos los archivos (*)",
) -> tuple[list[str], str]:
    paths, selected = QFileDialog.getOpenFileNames(
        parent, title, _dialog_start(directory), file_filter
    )
    if paths:
        _store_working_location(paths[0])
    return import_paths(str(Path(p)) for p in paths), selected


def get_save_file_name(
    parent: QWidget | None,
    title: str,
    directory: str = "",
    file_filter: str = "Todos los archivos (*)",
) -> tuple[str, str]:
    path, selected = QFileDialog.getSaveFileName(
        parent, title, _dialog_start(directory, preserve_filename=True), file_filter
    )
    if path:
        _store_working_location(path)
        return str(Path(path)), selected
    return "", selected


def get_existing_directory(
    parent: QWidget | None,
    title: str,
    directory: str = "",
) -> str:
    path = QFileDialog.getExistingDirectory(parent, title, _dialog_start(directory))
    if path:
        _store_working_location(path)
        return str(Path(path))
    return ""
