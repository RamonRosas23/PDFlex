"""Contract tests for the license-friendly PDFium rendering backend."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas

from core.pdf_backend import (
    PdfClosedError,
    PdfPasswordError,
    PdfRenderDocument,
)


@pytest.fixture()
def backend_pdf(tmp_path: Path) -> Path:
    source = tmp_path / "backend.pdf"
    canvas = Canvas(str(source), pagesize=letter, pageCompression=1)
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(72, 720, "PDFlex PDFium")
    canvas.setFont("Helvetica", 11)
    canvas.drawString(72, 690, "Texto vectorial de prueba 12345")
    canvas.acroForm.textfield(
        name="cliente",
        value="Visible",
        x=72,
        y=620,
        width=180,
        height=26,
    )
    canvas.showPage()
    canvas.drawString(72, 720, "Página rotada")
    canvas.save()

    reader = PdfReader(source)
    writer = PdfWriter(clone_from=reader)
    writer.pages[1].rotate(90)
    rotated = tmp_path / "backend-rotated.pdf"
    writer.write(rotated)
    rotated.replace(source)
    return source


def test_pdfium_backend_renders_text_forms_and_rotation(backend_pdf: Path):
    with PdfRenderDocument(backend_pdf) as document:
        assert document.page_count == 2
        first = document.page_info(0)
        second = document.page_info(1)

        assert (first.width_pt, first.height_pt, first.rotation) == (612.0, 792.0, 0)
        assert (second.width_pt, second.height_pt, second.rotation) == (792.0, 612.0, 90)
        assert "PDFlex PDFium" in document.extract_text(0)

        rendered = document.render_page(0, scale=2.0)
        assert (rendered.width, rendered.height, rendered.stride) == (1224, 1584, 3672)
        assert len(rendered.data) == rendered.height * rendered.stride
        image = rendered.to_pil()
        assert image.mode == "RGB"
        assert image.getbbox() == (0, 0, 1224, 1584)

        additionally_rotated = document.render_page(0, scale=0.5, rotation=90)
        assert (additionally_rotated.width, additionally_rotated.height) == (396, 306)

        transparent = document.render_page(0, scale=0.25, transparent_background=True)
        assert transparent.mode == "RGBA"
        assert transparent.stride == transparent.width * 4


def test_pdfium_object_bounds_are_recursive_and_rotation_aware(backend_pdf: Path):
    with PdfRenderDocument(backend_pdf) as document:
        first_text = document.object_bounds(0, kinds=("text",))
        rotated_text = document.object_bounds(1, kinds=("text",))
        text_blocks = document.text_blocks(0)

    assert len(first_text) >= 2
    assert all(item.kind == "text" for item in first_text)
    assert min(item.top for item in first_text) < 90
    assert rotated_text
    # Text originally near the physical top becomes a vertical strip at the
    # right after clockwise /Rotate=90, while its display Y starts near x=72.
    assert min(item.left for item in rotated_text) > 680
    assert min(item.top for item in rotated_text) == pytest.approx(72, abs=2)
    assert any("PDFlex PDFium" in block.text for block in text_blocks)


def test_pdfium_backend_rejects_invalid_scale_and_page(backend_pdf: Path):
    with PdfRenderDocument(backend_pdf) as document:
        with pytest.raises(ValueError):
            document.render_page(0, scale=0)
        with pytest.raises(ValueError):
            document.render_page(0, rotation=45)
        with pytest.raises(IndexError):
            document.render_page(2)


def test_pdfium_backend_close_is_idempotent(backend_pdf: Path):
    document = PdfRenderDocument(backend_pdf)
    document.close()
    document.close()
    assert document.closed
    with pytest.raises(PdfClosedError):
        _ = document.page_count


def test_pdfium_backend_maps_password_errors(backend_pdf: Path, tmp_path: Path):
    encrypted = tmp_path / "encrypted.pdf"
    writer = PdfWriter(clone_from=PdfReader(backend_pdf))
    writer.encrypt("correcta", algorithm="AES-256")
    writer.write(encrypted)

    with pytest.raises(PdfPasswordError):
        PdfRenderDocument(encrypted, password="incorrecta")

    with PdfRenderDocument(encrypted, password="correcta") as document:
        assert document.page_count == 2
        assert document.render_page(0, scale=0.25).width == 153


def test_pdfium_calls_are_safe_when_requested_from_multiple_threads(backend_pdf: Path):
    with PdfRenderDocument(backend_pdf) as document:
        def render(index: int) -> tuple[int, int]:
            page = document.render_page(index % 2, scale=0.5)
            return page.width, page.height

        with ThreadPoolExecutor(max_workers=4) as pool:
            sizes = list(pool.map(render, range(12)))

    assert sizes.count((306, 396)) == 6
    assert sizes.count((396, 306)) == 6
