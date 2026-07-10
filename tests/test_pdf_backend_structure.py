"""Cross-engine contracts for QPDF-backed structural operations."""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from core.pdf_backend import (
    PdfRenderDocument,
    SourcePage,
    assemble_pages,
    extract_pages,
    merge_documents,
    normalize_pdf,
    raster_merge_documents,
)


def _make_pdf(path: Path, labels: list[str], *, with_form: bool = False) -> Path:
    canvas = Canvas(str(path), pagesize=(300, 200), pageCompression=1)
    for index, label in enumerate(labels):
        canvas.drawString(36, 150, label)
        if with_form and index == 0:
            canvas.acroForm.textfield(
                name="cliente",
                value="PDFlex",
                x=36,
                y=90,
                width=140,
                height=24,
            )
        canvas.showPage()
    canvas.save()
    return path


def test_assemble_pages_preserves_order_duplicates_rotation_and_forms(tmp_path: Path):
    first = _make_pdf(tmp_path / "a.pdf", ["A1", "A2"], with_form=True)
    second = _make_pdf(tmp_path / "b.pdf", ["B1"])
    output = tmp_path / "assembled.pdf"

    report = assemble_pages(
        [
            SourcePage(str(second), 0),
            SourcePage(str(first), 0, 90),
            SourcePage(str(first), 0),
        ],
        output,
    )

    assert report.page_count == 3
    assert report.source_count == 2
    with PdfRenderDocument(output) as document:
        assert "B1" in document.extract_text(0)
        assert "A1" in document.extract_text(1)
        assert "A1" in document.extract_text(2)
        assert document.page_info(1).rotation == 90
        assert document.page_info(2).rotation == 0
    fields = PdfReader(output).get_fields()
    assert fields and any(name.startswith("cliente") for name in fields)


def test_extract_pages_preserves_selected_form_page(tmp_path: Path):
    source = _make_pdf(tmp_path / "source.pdf", ["Uno", "Dos"], with_form=True)
    output = tmp_path / "part.pdf"

    report = extract_pages(source, [0], output)

    assert report.page_count == 1
    assert "cliente" in (PdfReader(output).get_fields() or {})
    with PdfRenderDocument(output) as document:
        assert "Uno" in document.extract_text(0)


def test_normalize_repairs_broken_startxref_and_removes_metadata(tmp_path: Path):
    source = _make_pdf(tmp_path / "source.pdf", ["Reparable"])
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(source.read_bytes().replace(b"startxref", b"startxxxxx"))
    output = tmp_path / "normalized.pdf"

    report = normalize_pdf(broken, output, preserve_metadata=False)

    assert report.page_count == 1
    assert report.repaired_on_open
    with PdfRenderDocument(output) as document:
        assert "Reparable" in document.extract_text(0)
    assert not (PdfReader(output).metadata or {})


def test_structure_backend_rejects_source_overwrite(tmp_path: Path):
    source = _make_pdf(tmp_path / "source.pdf", ["Uno"])
    try:
        assemble_pages([SourcePage(str(source), 0)], source)
    except ValueError as exc:
        assert "sobrescribir" in str(exc)
    else:
        raise AssertionError("assemble_pages allowed overwriting a source")


def test_merge_documents_preserves_forms_blanks_and_bookmarks(tmp_path: Path):
    first = _make_pdf(tmp_path / "first.pdf", ["A1", "A2"], with_form=True)
    second = _make_pdf(tmp_path / "second.pdf", ["B1"])
    output = tmp_path / "merged.pdf"

    report = merge_documents(
        [first, second],
        output,
        blank_between=True,
        add_bookmarks=True,
    )

    assert report.page_count == 4
    assert report.blank_pages == 1
    assert [item.start_page for item in report.sources] == [1, 4]
    reader = PdfReader(output)
    assert len(reader.pages) == 4
    assert "cliente" in (reader.get_fields() or {})
    assert [item.title for item in reader.outline] == ["first", "second"]
    with PdfRenderDocument(output) as document:
        assert "A1" in document.extract_text(0)
        assert not document.extract_text(2).strip()
        assert "B1" in document.extract_text(3)


def test_raster_merge_is_renderable_last_resort(tmp_path: Path):
    first = _make_pdf(tmp_path / "first.pdf", ["A1"])
    second = _make_pdf(tmp_path / "second.pdf", ["B1", "B2"])
    output = tmp_path / "raster.pdf"

    report = raster_merge_documents([first, second], output, dpi=96)

    assert report.page_count == 3
    with PdfRenderDocument(output) as document:
        assert document.page_count == 3
        assert not document.extract_text(0).strip()
        assert document.render_page(2, scale=0.5).width > 0
