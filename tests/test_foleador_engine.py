from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from core.foleador_engine import FoleadorEngine, FolioJob, FolioStyle
from core.folio_format import FolioConfig
from core.pdf_backend import PdfRenderDocument


def _make_pdf(path: Path, pages: int = 3) -> Path:
    canvas = Canvas(str(path), pagesize=(360, 260))
    for index in range(pages):
        canvas.drawString(36, 190, f"ORIGINAL {index + 1}")
        canvas.showPage()
    canvas.save()
    return path


def _job(source: Path, output: Path) -> FolioJob:
    return FolioJob(
        str(source), str(output),
        x_norm=0.82, y_norm=0.90,
        width_norm=0.22, height_norm=0.08,
        smart_position=True,
    )


def test_foleador_preserves_original_text_and_selected_page_scope(tmp_path: Path):
    source = _make_pdf(tmp_path / "source.pdf")
    output = tmp_path / "folio.pdf"

    result = FoleadorEngine().run_batch(
        [_job(source, output)],
        FolioConfig(pattern="F-{n:03}", start=7, step=2, only_pages=[1, 3]),
        FolioStyle(fontsize=14, bold=True, bg_color=(1, 1, 1)),
    )[0]

    assert result.success, result.error
    assert [page.folio_text for page in result.page_results] == ["F-007", "F-009"]
    with PdfRenderDocument(output) as document:
        assert "ORIGINAL 1" in document.extract_text(0)
        assert "F-007" in document.extract_text(0)
        assert "F-" not in document.extract_text(1)
        assert "F-009" in document.extract_text(2)


def test_foleador_continues_counter_between_documents(tmp_path: Path):
    first = _make_pdf(tmp_path / "a.pdf", 2)
    second = _make_pdf(tmp_path / "b.pdf", 1)
    first_out, second_out = tmp_path / "a-out.pdf", tmp_path / "b-out.pdf"

    results = FoleadorEngine().run_batch(
        [_job(first, first_out), _job(second, second_out)],
        FolioConfig(pattern="{n}", start=10, scope="continuous"),
        FolioStyle(),
    )

    assert all(result.success for result in results)
    assert [item.folio_text for item in results[0].page_results] == ["10", "11"]
    assert [item.folio_text for item in results[1].page_results] == ["12"]


def test_foleador_uses_display_coordinates_on_rotated_page(tmp_path: Path):
    source = _make_pdf(tmp_path / "rotated.pdf", 1)
    writer = PdfWriter(clone_from=PdfReader(source))
    writer.pages[0].rotate(90)
    temporary = tmp_path / ".rotated.pdf"
    writer.write(temporary)
    temporary.replace(source)
    output = tmp_path / "output.pdf"

    result = FoleadorEngine().run_batch(
        [_job(source, output)], FolioConfig(pattern="ROT-{n}"), FolioStyle(fontsize=16)
    )[0]

    assert result.success, result.error
    with PdfRenderDocument(output) as document:
        assert document.page_info(0).rotation == 90
        assert "ROT-1" in document.extract_text(0)
