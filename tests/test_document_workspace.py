import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PIL import Image


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


def test_document_workspace_sends_work_items_back_to_tray(tmp_path):
    _app()

    from shell.tray import PdfTray
    from ui.common.document_workspace import DocumentWorkspace

    tray = PdfTray()
    pdf = _touch_pdf(tmp_path / "work.pdf")
    workspace = DocumentWorkspace(_ctx(tray), show_thumbnails=False)
    try:
        workspace.add_paths([pdf])
        workspace.list_widget.item(0).setSelected(True)

        assert workspace._work_card.send_selected_to_tray()
        assert tray.paths() == [pdf]
        assert tray.items[0].status == "in_work"
        assert tray.items[0].kind == "manual"
    finally:
        workspace.deleteLater()
        _app().processEvents()


def test_documents_card_pastes_files_from_windows_clipboard(tmp_path):
    app = _app()

    from shell.tray import PdfTray
    from ui.common.clipboard_utils import copy_files_to_clipboard
    from ui.common.documents_step import DocumentsCard

    pdf = _touch_pdf(tmp_path / "pasted.pdf")
    card = DocumentsCard(_ctx(PdfTray()), show_thumbnails=False)
    try:
        app.clipboard().clear()
        assert copy_files_to_clipboard([pdf])

        assert card.paste_from_clipboard()
        assert [Path(path).resolve() for path in card.paths()] == [Path(pdf).resolve()]
    finally:
        card.deleteLater()
        app.processEvents()


def test_documents_card_copies_selected_files_to_clipboard(tmp_path):
    app = _app()

    from shell.tray import PdfTray
    from ui.common.documents_step import DocumentsCard

    pdf = _touch_pdf(tmp_path / "copy_me.pdf")
    card = DocumentsCard(_ctx(PdfTray()), show_thumbnails=False)
    try:
        card.add_paths([pdf])
        card.list_widget.item(0).setSelected(True)

        assert card.copy_selected_to_clipboard()
        mime = app.clipboard().mimeData()
        assert mime.hasUrls()
        assert Path(mime.urls()[0].toLocalFile()).resolve() == Path(pdf).resolve()
    finally:
        card.deleteLater()
        app.processEvents()


def test_documents_card_converts_images_to_marginless_pdf(tmp_path):
    _app()

    import fitz
    from shell.tray import PdfTray
    from ui.common.documents_step import DocumentsCard

    image_path = tmp_path / "photo.png"
    Image.new("RGB", (80, 40), "navy").save(image_path)
    card = DocumentsCard(_ctx(PdfTray()), show_thumbnails=False)
    try:
        card.add_paths([str(image_path)])

        assert card.count() == 1
        output = Path(card.paths()[0])
        assert output.suffix.lower() == ".pdf"
        doc = fitz.open(str(output))
        try:
            assert doc.page_count == 1
            assert round(doc[0].rect.width) == 80
            assert round(doc[0].rect.height) == 40
        finally:
            doc.close()
    finally:
        card.deleteLater()
        _app().processEvents()


def test_documents_card_converts_each_image_to_its_own_pdf(tmp_path):
    _app()

    import fitz
    from shell.tray import PdfTray
    from ui.common.documents_step import DocumentsCard

    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (80, 40), "navy").save(first)
    Image.new("RGB", (60, 30), "white").save(second)
    card = DocumentsCard(_ctx(PdfTray()), show_thumbnails=False)
    try:
        card.add_paths([str(first), str(second)])

        outputs = [Path(path) for path in card.paths()]
        assert len(outputs) == 2
        assert [path.stem for path in outputs] == ["first", "second"]
        for output, size in zip(outputs, [(80, 40), (60, 30)]):
            doc = fitz.open(str(output))
            try:
                assert doc.page_count == 1
                assert (round(doc[0].rect.width), round(doc[0].rect.height)) == size
            finally:
                doc.close()
    finally:
        card.deleteLater()
        _app().processEvents()


def test_documents_card_preserves_input_order_across_image_conversion(tmp_path):
    _app()

    from shell.tray import PdfTray
    from ui.common.documents_step import DocumentsCard

    first_pdf = _touch_pdf(tmp_path / "10-original.pdf")
    image_path = tmp_path / "02-scan.png"
    Image.new("RGB", (80, 40), "navy").save(image_path)
    last_pdf = _touch_pdf(tmp_path / "01-final.pdf")

    card = DocumentsCard(_ctx(PdfTray()), show_thumbnails=False)
    try:
        card.add_paths([first_pdf, str(image_path), last_pdf])

        paths = card.paths()
        assert paths[0] == first_pdf
        assert Path(paths[1]).stem == image_path.stem
        assert paths[2] == last_pdf
    finally:
        card.deleteLater()
        _app().processEvents()


def test_document_workspace_uses_preview_panel(tmp_path):
    _app()

    from shell.tray import PdfTray
    from ui.common.document_workspace import DocumentWorkspace

    workspace = DocumentWorkspace(_ctx(PdfTray()), show_thumbnails=False)
    try:
        assert hasattr(workspace._work_card, "_preview_canvas")
        assert workspace._work_card._preview_name_lbl.text() == "Selecciona un documento"
    finally:
        workspace.deleteLater()
        _app().processEvents()
