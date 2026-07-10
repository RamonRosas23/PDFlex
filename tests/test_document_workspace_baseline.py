import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or _QAPP or QApplication([])
    return _QAPP


def _touch_pdf(path):
    path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return str(path)


def test_pdf_tray_keeps_existing_files_once_and_emits_on_changes(tmp_path):
    from shell.tray import PdfTray

    tray = PdfTray()
    emissions = []
    tray.changed.connect(lambda: emissions.append(tray.count()))

    first = _touch_pdf(tmp_path / "first.pdf")
    second = _touch_pdf(tmp_path / "second.pdf")
    missing = str(tmp_path / "missing.pdf")

    tray.add_items([first, missing, first, "", second], "Compresor")

    assert tray.paths() == [first, second]
    assert [item.source_tool for item in tray.items] == ["Compresor", "Compresor"]
    assert emissions == [2]

    tray.add_items([first], "Otra herramienta")
    assert tray.paths() == [first, second]
    assert emissions == [2]

    tray.remove(first)
    assert tray.paths() == [second]
    assert emissions == [2, 1]

    tray.clear()
    assert tray.paths() == []
    assert emissions == [2, 1, 0]


def test_documents_card_loads_tray_into_work_list_without_clearing_tray(tmp_path):
    _app()

    from shell.tray import PdfTray
    from ui.common.documents_step import DocumentsCard

    first = _touch_pdf(tmp_path / "a.pdf")
    second = _touch_pdf(tmp_path / "b.pdf")
    tray = PdfTray()
    tray.add_items([first, second], "Firmador")
    ctx = SimpleNamespace(
        tray=tray,
        word_converter=SimpleNamespace(is_available=lambda: False),
    )

    card = DocumentsCard(ctx, show_thumbnails=False)
    emissions = []
    card.files_changed.connect(lambda paths: emissions.append(list(paths)))

    card._on_load_from_tray()
    assert card.paths() == [first, second]
    assert tray.paths() == [first, second]
    assert emissions == [[first, second]]

    card._on_load_from_tray()
    assert card.paths() == [first, second]
    assert emissions == [[first, second]]

    card.deleteLater()


def test_send_to_tool_button_and_panel_send_tool_transfer_with_safe_defaults(tmp_path):
    _app()

    from shell.tool_registry import get_tool
    from shell.transfer import ToolTransfer
    from ui.common.send_to_tool import SendToToolButton, SendToToolPanel

    pdf_path = _touch_pdf(tmp_path / "resultado.pdf")
    calls = []
    ctx = SimpleNamespace(
        open_tool=lambda tool_id, inputs=None: calls.append((tool_id, inputs))
    )

    button = SendToToolButton(ctx, "compresor")
    assert not button.isVisible()

    button.set_output_paths([pdf_path])
    assert button.isVisible()

    panel = SendToToolPanel(ctx, "compresor", [pdf_path])
    compatible_ids = [tool.id for tool in panel._compatible_tools()]
    assert "firmador" in compatible_ids

    panel._send_to(get_tool("firmador"))
    assert calls[0][0] == "firmador"
    assert isinstance(calls[0][1], ToolTransfer)
    assert calls[0][1].paths == [pdf_path]
    assert calls[0][1].source_tool_id == "compresor"
    assert calls[0][1].source_tool_title == "Comprimir PDF"
    assert calls[0][1].mode == "replace"
    assert calls[0][1].tray_policy == "keep"

    panel.deleteLater()
    button.deleteLater()


def test_send_to_tool_panel_honors_selected_transfer_options(tmp_path):
    _app()

    from shell.tool_registry import get_tool
    from ui.common.send_to_tool import SendToToolPanel

    pdf_path = _touch_pdf(tmp_path / "resultado.pdf")
    calls = []
    ctx = SimpleNamespace(
        open_tool=lambda tool_id, inputs=None: calls.append((tool_id, inputs))
    )
    panel = SendToToolPanel(ctx, "compresor", [pdf_path])

    panel._mode_buttons["append"].click()
    panel._tray_buttons["clear"].click()
    panel._send_to(get_tool("firmador"))

    transfer = calls[0][1]
    assert transfer.mode == "append"
    assert transfer.tray_policy == "clear"

    panel.deleteLater()
