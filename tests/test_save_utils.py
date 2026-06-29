from __future__ import annotations

from pathlib import Path

from ui.common import save_utils


def test_save_file_as_handles_locked_destination_without_raising(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    dest = tmp_path / "dest.pdf"
    source.write_bytes(b"nuevo")
    dest.write_bytes(b"anterior")
    warnings: list[tuple[str, str]] = []

    def fake_replace(src: str, dst: str) -> None:
        raise PermissionError("archivo en uso")

    monkeypatch.setattr(save_utils, "get_save_file_name", lambda *args, **kwargs: (str(dest), ""))
    monkeypatch.setattr(save_utils.os, "replace", fake_replace)
    monkeypatch.setattr(
        save_utils,
        "show_warning",
        lambda _parent, title, message, **_kwargs: warnings.append((title, message)),
    )

    assert not save_utils.save_file_as(None, source, title="Guardar como")
    assert dest.read_bytes() == b"anterior"
    assert warnings
    assert "No se pudo guardar" in warnings[0][1]
    assert not list(tmp_path.glob("*.pdflex-*.tmp"))


def test_save_file_as_replaces_through_temp_file(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    dest = tmp_path / "dest.pdf"
    source.write_bytes(b"nuevo")
    dest.write_bytes(b"anterior")

    monkeypatch.setattr(save_utils, "get_save_file_name", lambda *args, **kwargs: (str(dest), ""))

    assert save_utils.save_file_as(None, source, title="Guardar como")
    assert dest.read_bytes() == b"nuevo"
    assert source.read_bytes() == b"nuevo"
    assert not list(tmp_path.glob("*.pdflex-*.tmp"))


def test_save_files_as_batch_reports_locked_files_and_continues(tmp_path, monkeypatch):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"uno")
    second.write_bytes(b"dos")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "first.pdf").write_bytes(b"viejo")
    warnings: list[str] = []

    real_replace = save_utils.os.replace

    def fake_replace(src: str, dst: str) -> None:
        if Path(dst).name == "first.pdf":
            raise PermissionError("archivo en uso")
        real_replace(src, dst)

    monkeypatch.setattr(save_utils, "get_existing_directory", lambda *args, **kwargs: str(out_dir))
    monkeypatch.setattr(save_utils, "_ask_conflict_strategy", lambda *args, **kwargs: "replace")
    monkeypatch.setattr(save_utils.os, "replace", fake_replace)
    monkeypatch.setattr(save_utils, "show_warning", lambda _parent, _title, msg: warnings.append(msg))
    monkeypatch.setattr(save_utils, "show_success", lambda *args, **kwargs: None)

    save_utils.save_files_as_batch(None, [first, second])

    assert (out_dir / "first.pdf").read_bytes() == b"viejo"
    assert (out_dir / "second.pdf").read_bytes() == b"dos"
    assert warnings
    assert "Se guardaron 1 archivo" in warnings[0]
    assert "first.pdf" in warnings[0]
