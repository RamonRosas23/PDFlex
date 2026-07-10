from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PIL import Image
from PySide6.QtWidgets import QApplication

from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from ui.word_a_pdf.window import WordAPdfWindow


_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or _QAPP or QApplication([])
    return _QAPP


def test_word_to_pdf_accepts_images_without_office(tmp_path):
    _app()

    image_path = tmp_path / "scan.png"
    Image.new("RGB", (70, 35), "white").save(image_path)
    ctx = ShellContext(
        tray=PdfTray(),
        word_converter=SimpleNamespace(is_available=lambda: False),
        open_tool=lambda *_: None,
    )
    window = WordAPdfWindow(ctx)
    try:
        window.set_inputs([str(image_path)])

        with patch("ui.word_a_pdf.window.show_success"):
            window._on_run()

        assert len(window.last_results) == 1
        result = window.last_results[0]
        assert result.success
        assert Path(result.output_path).suffix.lower() == ".pdf"
        doc = fitz.open(result.output_path)
        try:
            assert round(doc[0].rect.width) == 70
            assert round(doc[0].rect.height) == 35
        finally:
            doc.close()
    finally:
        window.deleteLater()
        _app().processEvents()


def test_tool_registry_exposes_word_to_pdf_for_images():
    tool = get_tool("word_a_pdf")

    assert tool is not None
    assert ".docx" in tool.input_extensions
    assert ".png" in tool.input_extensions
