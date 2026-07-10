from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.ocr_engine import OcrJob, OcrJobResult, OcrPageResult
from ui.ocr.window import TextResultsViewer


def test_text_results_viewer_rows_include_outputs_and_sizes(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "entrada.pdf"
    source.write_bytes(b"%PDF-1.7")
    docx = tmp_path / "entrada.docx"
    docx.write_bytes(b"x" * 1024)
    txt = tmp_path / "entrada.txt"
    txt.write_text("texto final", encoding="utf-8")

    viewer = TextResultsViewer()
    try:
        viewer.set_results([
            OcrJobResult(
                job=OcrJob(str(source), str(tmp_path)),
                docx_path=str(docx),
                txt_path=str(txt),
                page_results=[
                    OcrPageResult(
                        page_index=0,
                        text="texto final",
                        quality_score=0.92,
                        method="ocr",
                    )
                ],
                success=True,
            )
        ])
        app.processEvents()

        text = viewer._doc_list.item(0).text()
        assert "entrada.pdf" in text
        assert "Listo" in text
        assert "DOCX 1.0 KB" in text
        assert "TXT" in text
    finally:
        viewer.deleteLater()
        app.processEvents()


def test_text_results_viewer_rows_show_errors(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "roto.pdf"
    source.write_bytes(b"%PDF-1.7")

    viewer = TextResultsViewer()
    try:
        viewer.set_results([
            OcrJobResult(
                job=OcrJob(str(source), str(tmp_path)),
                success=False,
                error="fallo controlado",
            )
        ])
        app.processEvents()

        text = viewer._doc_list.item(0).text()
        assert "Error" in text
        assert "fallo controlado" in text
    finally:
        viewer.deleteLater()
        app.processEvents()
