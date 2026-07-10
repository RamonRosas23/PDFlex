import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or _QAPP or QApplication([])
    return _QAPP


def test_file_workspace_filters_tray_and_adds_selected_word_file(tmp_path):
    _app()

    from shell.tray import PdfTray
    from ui.common.file_workspace import FileWorkspace
    from ui.word_a_pdf.window import WORD_EXTS, WordListCard

    word_path = tmp_path / "contrato.docx"
    word_path.write_bytes(b"placeholder")
    pdf_path = tmp_path / "ignorado.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    tray = PdfTray()
    tray.add_items([str(word_path), str(pdf_path)], "Membretado")
    ctx = SimpleNamespace(tray=tray)

    workspace = FileWorkspace(ctx, WordListCard(), WORD_EXTS, tray_title="Bandeja Word")
    try:
        assert workspace._tray_list.count() == 1
        workspace._tray_list.item(0).setSelected(True)
        workspace._add_selected_to_work()

        assert workspace.paths() == [str(word_path)]
        assert tray.items[0].status == "in_work"
        assert tray.items[1].status == "available"
    finally:
        workspace.deleteLater()
        _app().processEvents()
