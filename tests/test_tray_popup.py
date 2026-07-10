import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel


_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or _QAPP or QApplication([])
    return _QAPP


def _touch(path, content=b"data"):
    path.write_bytes(content)
    return str(path)


def test_tray_popup_groups_by_origin_and_emits_compatible_selection(tmp_path):
    _app()
    from shell.tray import PdfTray, TrayPopup

    first = _touch(tmp_path / "firmado-a.pdf")
    second = _touch(tmp_path / "firmado-b.pdf")
    word = _touch(tmp_path / "texto.docx")
    tray = PdfTray()
    tray.add_items(
        [first, second],
        "Firmador",
        source_tool_title="Firmador masivo",
        batch_id="firma-1",
    )
    tray.add_items([word], "PDF a Word", batch_id="word-1")
    popup = TrayPopup(
        tray,
        active_tool_title="Unir",
        active_extensions=(".pdf",),
    )
    try:
        headers = [
            label.text() for label in popup._container.findChildren(QLabel)
            if "· Resultado ·" in label.text()
        ]
        assert "Firmador masivo · Resultado · 2 archivos" in headers
        assert "PDF a Word · Resultado · 1 archivo" in headers

        selected = []
        popup.use_in_active_tool_requested.connect(selected.append)
        popup._item_checks[first].setChecked(True)
        popup._use_active_btn.click()

        assert selected == [[first]]
        assert not popup._item_checks[word].isEnabled()
    finally:
        popup.deleteLater()
        _app().processEvents()


def test_tray_popup_mass_actions_remove_matching_files(tmp_path):
    _app()
    from shell.tray import PdfTray, TrayPopup

    output = _touch(tmp_path / "resultado.pdf")
    converted = _touch(tmp_path / "convertido.pdf")
    original = _touch(tmp_path / "original.pdf")
    manual = _touch(tmp_path / "manual.pdf")
    missing = _touch(tmp_path / "faltante.pdf")
    tray = PdfTray()
    tray.add_items([output], "Compresor", kind="output")
    tray.add_items([converted], "Word a PDF", kind="converted")
    tray.add_items([original], "Importado", kind="original")
    tray.add_items([manual], "Usuario", kind="manual")
    tray.add_items([missing], "Importado", kind="original")
    (tmp_path / "faltante.pdf").unlink()
    popup = TrayPopup(tray)
    try:
        popup._clear_results_btn.click()
        assert tray.paths() == [original, manual, missing]

        popup._remove_missing_btn.click()
        assert tray.paths() == [original, manual]

        popup._clear_originals_btn.click()
        assert tray.paths() == []
    finally:
        popup.deleteLater()
        _app().processEvents()


def test_shell_delivers_only_compatible_tray_files_to_active_tool(tmp_path):
    from types import SimpleNamespace

    from shell.shell_window import ShellWindow
    from shell.tray import PdfTray

    pdf = _touch(tmp_path / "compatible.pdf")
    image = _touch(tmp_path / "incompatible.png")
    tray = PdfTray()
    tray.add_items([pdf, image], "Resultados")
    delivered = []

    class _Popup:
        def close(self):
            return None

    class _Harness:
        _active_tool_id = "unir"
        _tool_widgets = {"unir": object()}
        _tray = tray
        _tray_popup = _Popup()

        def _deliver_tool_inputs(self, widget, paths):
            delivered.append((widget, paths))

    tool = SimpleNamespace(input_extensions=(".pdf",))
    harness = _Harness()
    with patch("shell.shell_window.get_tool", return_value=tool):
        ShellWindow._use_selected_tray_items(harness, [pdf, image])

    assert delivered == [(harness._tool_widgets["unir"], [pdf])]
    assert [item.status for item in tray.items] == ["in_work", "available"]
    assert harness._tray_popup is None


def test_shell_tray_tooltip_summarizes_each_origin(tmp_path):
    from shell.shell_window import ShellWindow
    from shell.tray import PdfTray

    first = _touch(tmp_path / "first.pdf")
    second = _touch(tmp_path / "second.pdf")
    tray = PdfTray()
    tray.add_items([first], "Compresor")
    tray.add_items([second], "Firmador")
    harness = type("Harness", (), {"_tray": tray})()

    assert ShellWindow._tray_tooltip(harness) == (
        "Bandeja: 2 archivos\nCompresor: 1\nFirmador: 1"
    )


def test_tray_popup_keeps_groups_with_a_large_tray(tmp_path):
    _app()
    from shell.tray import PdfTray, TrayPopup

    tray = PdfTray()
    for group in range(4):
        paths = [
            _touch(tmp_path / f"grupo-{group}-{index}.pdf")
            for index in range(25)
        ]
        tray.add_items(paths, f"Herramienta {group}", batch_id=f"batch-{group}")

    popup = TrayPopup(tray)
    try:
        headers = [
            label for label in popup._container.findChildren(QLabel)
            if "· Resultado ·" in label.text()
        ]
        assert tray.count() == 100
        assert len(headers) == 4
        assert popup._count_lbl.text() == "100 archivos"
    finally:
        popup.deleteLater()
        _app().processEvents()
