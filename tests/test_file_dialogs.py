from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication, QSettings
from PyQt6.QtWidgets import QApplication, QFileDialog


def _reset_settings_scope() -> None:
    QApplication.instance() or QApplication([])
    QCoreApplication.setOrganizationName("PDFlexTests")
    QCoreApplication.setApplicationName(f"FileDialogs-{uuid4().hex}")
    QSettings().clear()


def test_file_dialogs_remember_last_open_location(monkeypatch, tmp_path) -> None:
    _reset_settings_scope()
    first_dir = tmp_path / "primera"
    first_dir.mkdir()
    seen_dirs: list[str] = []

    def first_open(parent, title, directory, file_filter):
        seen_dirs.append(directory)
        return str(first_dir / "entrada.pdf"), file_filter

    monkeypatch.setattr(QFileDialog, "getOpenFileName", first_open)

    from ui.common.file_dialogs import get_open_file_name

    path, _ = get_open_file_name(None, "Abrir", "", "PDF (*.pdf)")
    assert Path(path).parent == first_dir

    def second_open(parent, title, directory, file_filter):
        seen_dirs.append(directory)
        return "", file_filter

    monkeypatch.setattr(QFileDialog, "getOpenFileName", second_open)

    get_open_file_name(None, "Abrir", "", "PDF (*.pdf)")

    assert Path(seen_dirs[-1]) == first_dir


def test_save_dialog_uses_last_location_and_preserves_suggested_name(
    monkeypatch,
    tmp_path,
) -> None:
    _reset_settings_scope()
    last_dir = tmp_path / "destino"
    source_dir = tmp_path / "origen"
    last_dir.mkdir()
    source_dir.mkdir()
    captured_dirs: list[str] = []

    from ui.common.file_dialogs import _store_working_location, get_save_file_name

    _store_working_location(last_dir)

    def fake_save(parent, title, directory, file_filter):
        captured_dirs.append(directory)
        return str(last_dir / "salida.pdf"), file_filter

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save)

    get_save_file_name(
        None,
        "Guardar como",
        str(source_dir / "salida.pdf"),
        "PDF (*.pdf)",
    )

    assert Path(captured_dirs[0]) == last_dir / "salida.pdf"
