from __future__ import annotations

from pathlib import Path

from ui.common import open_utils


def test_open_file_reports_missing_path_without_opening(tmp_path, monkeypatch):
    messages: list[str] = []
    opened: list[str] = []

    monkeypatch.setattr(
        open_utils,
        "show_info",
        lambda _parent, _title, message: messages.append(message),
    )
    monkeypatch.setattr(
        open_utils.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    assert not open_utils.open_file(None, tmp_path / "missing.pdf")
    assert messages
    assert not opened


def test_open_folder_opens_parent_for_file_path(tmp_path, monkeypatch):
    source = tmp_path / "resultado.pdf"
    source.write_bytes(b"pdf")
    opened: list[str] = []

    monkeypatch.setattr(
        open_utils.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    assert open_utils.open_folder(None, source)
    assert len(opened) == 1
    assert Path(opened[0]) == tmp_path


def test_open_file_reports_desktop_service_rejection(tmp_path, monkeypatch):
    source = tmp_path / "resultado.pdf"
    source.write_bytes(b"pdf")
    warnings: list[tuple[str, str]] = []

    monkeypatch.setattr(open_utils.QDesktopServices, "openUrl", lambda _url: False)
    monkeypatch.setattr(
        open_utils,
        "show_warning",
        lambda _parent, title, message, **_kwargs: warnings.append((title, message)),
    )

    assert not open_utils.open_file(None, source, title="Abrir PDF")
    assert warnings
    assert warnings[0][0] == "Abrir PDF"
    assert "No pudo abrir" in warnings[0][1] or "no pudo abrir" in warnings[0][1]


def test_open_file_reports_desktop_service_exception(tmp_path, monkeypatch):
    source = tmp_path / "resultado.pdf"
    source.write_bytes(b"pdf")
    warnings: list[tuple[str, str]] = []

    def raise_open(_url):
        raise RuntimeError("sin asociacion")

    monkeypatch.setattr(open_utils.QDesktopServices, "openUrl", raise_open)
    monkeypatch.setattr(
        open_utils,
        "show_warning",
        lambda _parent, title, message, **_kwargs: warnings.append((title, message)),
    )

    assert not open_utils.open_file(None, Path(source), title="Abrir PDF")
    assert warnings
    assert warnings[0][0] == "Abrir PDF"
