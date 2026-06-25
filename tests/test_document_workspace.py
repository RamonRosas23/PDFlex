import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication


_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or _QAPP or QApplication([])
    return _QAPP


def _touch_pdf(path):
    path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return str(path)


def _ctx(tray):
    return SimpleNamespace(
        tray=tray,
        word_converter=SimpleNamespace(is_available=lambda: False),
    )


def test_document_workspace_adds_selected_tray_items_to_work(tmp_path):
    _app()

    from shell.tray import PdfTray
    from ui.common.document_workspace import DocumentWorkspace

    tray = PdfTray()
    first = _touch_pdf(tmp_path / "first.pdf")
    second = _touch_pdf(tmp_path / "second.pdf")
    tray.add_items([first, second], "Compresor")

    workspace = DocumentWorkspace(_ctx(tray), show_thumbnails=False)
    try:
        workspace._tray_list.item(0).setSelected(True)
        workspace._add_selected_to_work()

        assert workspace.paths() == [first]
        assert tray.items[0].status == "in_work"
        assert tray.items[1].status == "available"
        assert workspace.list_widget is workspace._work_card.list_widget
        assert not workspace._work_card._tray_btn.isVisible()
    finally:
        workspace.deleteLater()
        _app().processEvents()


def test_document_workspace_replaces_work_with_selected_tray_items(tmp_path):
    _app()

    from shell.tray import PdfTray
    from ui.common.document_workspace import DocumentWorkspace

    tray = PdfTray()
    current = _touch_pdf(tmp_path / "current.pdf")
    replacement = _touch_pdf(tmp_path / "replacement.pdf")
    tray.add_items([replacement], "Membretado")

    workspace = DocumentWorkspace(_ctx(tray), show_thumbnails=False)
    try:
        workspace.add_paths([current])
        workspace._tray_list.item(0).setSelected(True)
        workspace._replace_work_with_selected()

        assert workspace.paths() == [replacement]
        assert workspace.count() == 1
        assert tray.items[0].status == "in_work"
    finally:
        workspace.deleteLater()
        _app().processEvents()


def test_document_workspace_set_transfer_supports_replace_and_append(tmp_path):
    _app()

    from shell.tray import PdfTray
    from shell.transfer import ToolTransfer
    from ui.common.document_workspace import DocumentWorkspace

    tray = PdfTray()
    first = _touch_pdf(tmp_path / "first.pdf")
    second = _touch_pdf(tmp_path / "second.pdf")
    third = _touch_pdf(tmp_path / "third.pdf")
    tray.add_items([first, second, third], "Firmador")

    workspace = DocumentWorkspace(_ctx(tray), show_thumbnails=False)
    try:
        workspace.add_paths([first])
        workspace.set_transfer(ToolTransfer([second], mode="replace"))
        assert workspace.paths() == [second]

        workspace.set_transfer(ToolTransfer([third], mode="append"))
        assert workspace.paths() == [second, third]
        assert [item.status for item in tray.items] == [
            "available",
            "in_work",
            "in_work",
        ]
    finally:
        workspace.deleteLater()
        _app().processEvents()


def test_document_workspace_removes_selected_items_from_tray(tmp_path):
    _app()

    from shell.tray import PdfTray
    from ui.common.document_workspace import DocumentWorkspace

    tray = PdfTray()
    first = _touch_pdf(tmp_path / "first.pdf")
    second = _touch_pdf(tmp_path / "second.pdf")
    tray.add_items([first, second], "Compresor")

    workspace = DocumentWorkspace(_ctx(tray), show_thumbnails=False)
    try:
        workspace._tray_list.item(0).setSelected(True)
        workspace._remove_selected_from_tray()

        assert tray.paths() == [second]
        assert workspace._tray_list.count() == 1
    finally:
        workspace.deleteLater()
        _app().processEvents()
