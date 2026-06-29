from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
import pytest
from PIL import Image, ImageDraw
from PyQt6.QtWidgets import QApplication, QScrollArea, QWidget

from shell.context import ShellContext
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from core.signature_engine import JobResult, SignJob
from ui.firmador.window import FirmadorWindow, _signature_fingerprint


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication(sys.argv)
    yield instance


@pytest.fixture
def ctx():
    return ShellContext(
        tray=PdfTray(),
        word_converter=WordToPdfConverter(),
        open_tool=lambda tool_id, inputs=None: None,
    )


def test_documents_without_active_signatures_are_excluded_from_jobs(
    app,
    ctx,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PDFLEX_SIGNATURE_LIBRARY_DIR", str(tmp_path / "siglib"))
    pdf_a = _make_pdf(tmp_path / "a.pdf")
    pdf_b = _make_pdf(tmp_path / "b.pdf")
    sig_path, sig_img = _make_signature(tmp_path / "firma.png")

    window = FirmadorWindow(ctx)
    try:
        window.set_inputs([str(pdf_a), str(pdf_b)])
        app.processEvents()
        entry = window._add_sig_entry_from_image(
            str(sig_path),
            sig_img,
            _signature_fingerprint(sig_img),
            source_name=sig_path.name,
        )
        window._placements[entry.uid] = {None: (0.5, 0.5, 0.2, 0.1, 0.0)}
        window._sig_disabled[entry.uid].add(str(pdf_b))

        assert window._validate_ready() is None

        jobs = window._build_jobs()
        assert [job.pdf_path for job in jobs] == [str(pdf_a)]
        assert jobs[0].signatures
    finally:
        window.deleteLater()
        app.processEvents()


def test_validation_blocks_when_every_document_is_excluded(
    app,
    ctx,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PDFLEX_SIGNATURE_LIBRARY_DIR", str(tmp_path / "siglib"))
    pdf_a = _make_pdf(tmp_path / "a.pdf")
    pdf_b = _make_pdf(tmp_path / "b.pdf")
    sig_path, sig_img = _make_signature(tmp_path / "firma.png")

    window = FirmadorWindow(ctx)
    try:
        window.set_inputs([str(pdf_a), str(pdf_b)])
        app.processEvents()
        entry = window._add_sig_entry_from_image(
            str(sig_path),
            sig_img,
            _signature_fingerprint(sig_img),
            source_name=sig_path.name,
        )
        window._placements[entry.uid] = {None: (0.5, 0.5, 0.2, 0.1, 0.0)}
        window._sig_disabled[entry.uid].update({str(pdf_a), str(pdf_b)})

        error = window._validate_ready()
        assert error is not None
        assert "Todos los documentos quedaron excluidos" in error
    finally:
        window.deleteLater()
        app.processEvents()


def test_review_stage_can_be_disabled_from_process_step(app, ctx) -> None:
    window = FirmadorWindow(ctx)
    try:
        assert window._review_enabled_chk.isChecked()
        assert "Activada" in window._review_mode_summary()

        window._review_enabled_chk.setChecked(False)

        assert "Desactivada" in window._review_mode_summary()
        assert "publicar directo" in window._proc_step._summary_lbl.text()
    finally:
        window.deleteLater()
        app.processEvents()


def test_disabled_review_publishes_processed_outputs_directly(
    app,
    ctx,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("ui.firmador.window.show_success", lambda *args, **kwargs: None)
    source_pdf = _make_pdf(tmp_path / "source.pdf")
    output_pdf = tmp_path / "source_firmado.pdf"
    output_pdf.write_bytes(source_pdf.read_bytes())

    job = SignJob(
        pdf_path=str(source_pdf),
        output_path=str(output_pdf),
        signatures=[],
    )
    result = JobResult(job=job, output_path=str(output_pdf), success=True)

    window = FirmadorWindow(ctx)
    try:
        window._review_enabled_chk.setChecked(False)
        window._on_all_finished([result])

        assert window.last_results == [result]
        assert window._review_documents == []
        assert window.stack.currentIndex() == 6
        assert ctx.tray.paths() == [str(output_pdf)]
    finally:
        window.deleteLater()
        app.processEvents()


def test_signature_position_left_panel_stays_accessible_in_narrow_window(
    app,
    ctx,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PDFLEX_SIGNATURE_LIBRARY_DIR", str(tmp_path / "siglib"))
    pdf_path = _make_pdf(
        tmp_path / "documento_con_nombre_muy_largo_para_panel_izquierdo.pdf"
    )
    sig_path, sig_img = _make_signature(
        tmp_path / "firma_con_nombre_extremadamente_largo_para_layout.png"
    )

    window = FirmadorWindow(ctx)
    try:
        window.resize(1000, 620)
        window.show()
        window.set_inputs([str(pdf_path)])
        window._switch_section(1)
        entry = window._add_sig_entry_from_image(
            str(sig_path),
            sig_img,
            _signature_fingerprint(sig_img),
            source_name=sig_path.name,
        )
        window.sigs_list.setCurrentRow(0)
        app.processEvents()

        assert entry is not None
        assert window.width() <= 1020

        left_scroll = next(
            scroll
            for scroll in window.findChildren(QScrollArea)
            if scroll.objectName() == "LeftPanelScroll"
        )
        assert left_scroll.horizontalScrollBar().maximum() == 0
        assert left_scroll.verticalScrollBar().maximum() > 0
        assert left_scroll.widget().width() <= left_scroll.viewport().width()

        for child in left_scroll.widget().findChildren(QWidget):
            if not child.isVisible():
                continue
            geometry = child.geometry()
            assert geometry.x() + geometry.width() <= left_scroll.widget().width() + 1
    finally:
        window.deleteLater()
        app.processEvents()


def test_pdf_signature_input_is_rendered_to_image(
    app,
    ctx,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PDFLEX_SIGNATURE_LIBRARY_DIR", str(tmp_path / "siglib"))
    pdf_sig = _make_pdf(tmp_path / "firma.pdf")

    window = FirmadorWindow(ctx)
    try:
        entry = window._add_sig_from_path(str(pdf_sig))

        assert entry is not None
        assert entry.source_name == "firma.pdf"
        assert entry.original_img.width > 0
        assert entry.original_img.height > 0
        assert Path(entry.path).suffix.lower() == ".png"
    finally:
        window.deleteLater()
        app.processEvents()


def _make_pdf(path) -> object:
    doc = fitz.open()
    page = doc.new_page(width=300, height=420)
    page.insert_text((40, 80), path.stem)
    doc.save(path)
    doc.close()
    return path


def _make_signature(path) -> tuple[object, Image.Image]:
    img = Image.new("RGBA", (240, 90), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.line((15, 55, 220, 35), fill=(20, 45, 170, 255), width=5)
    img.save(path)
    return path, img
