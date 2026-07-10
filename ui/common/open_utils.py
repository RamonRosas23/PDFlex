"""Helpers for opening generated files and folders from the UI."""
from __future__ import annotations

from pathlib import Path
from typing import Union

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget

from ui.common.dialogs import show_info, show_warning

PathLike = Union[str, Path]


def open_file(parent: QWidget | None, path: PathLike | None, *, title: str = "Abrir archivo") -> bool:
    if not path:
        show_info(parent, title, "No hay archivo disponible para abrir.")
        return False

    target = Path(path)
    if not target.exists() or not target.is_file():
        show_info(
            parent,
            title,
            "El archivo ya no esta disponible. Vuelve a generar el resultado "
            "o elige otro archivo.",
        )
        return False

    return _open_local_path(
        parent,
        target,
        title=title,
        failure_message="El sistema no pudo abrir este archivo.",
    )


def open_folder(parent: QWidget | None, path: PathLike | None, *, title: str = "Abrir carpeta") -> bool:
    if not path:
        show_info(parent, title, "No hay carpeta disponible para abrir.")
        return False

    target = Path(path)
    folder = target if target.is_dir() else target.parent
    if not folder.exists() or not folder.is_dir():
        show_info(
            parent,
            title,
            "La carpeta ya no esta disponible. Vuelve a generar el resultado "
            "o elige otra ubicacion.",
        )
        return False

    return _open_local_path(
        parent,
        folder,
        title=title,
        failure_message="El sistema no pudo abrir esta carpeta.",
    )


def _open_local_path(
    parent: QWidget | None,
    target: Path,
    *,
    title: str,
    failure_message: str,
) -> bool:
    try:
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
    except Exception as exc:
        show_warning(
            parent,
            title,
            f"{failure_message}\n\nRuta:\n{target}",
            details=str(exc),
        )
        return False

    if not opened:
        show_warning(parent, title, f"{failure_message}\n\nRuta:\n{target}")
        return False

    return True
