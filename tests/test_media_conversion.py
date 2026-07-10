from __future__ import annotations

from pathlib import Path

from PIL import Image
from reportlab.pdfgen.canvas import Canvas

from core.pdf_backend import PdfRenderDocument
from core.media_conversion import (
    images_to_pdf_exact,
    pdfs_to_images_exact,
)


def test_images_to_pdf_exact_creates_marginless_image_sized_page(tmp_path):
    image_path = tmp_path / "source.png"
    Image.new("RGB", (123, 57), (20, 140, 210)).save(image_path)

    output = images_to_pdf_exact([str(image_path)], out_dir=tmp_path)

    assert Path(output).exists()
    with PdfRenderDocument(output) as document:
        assert document.page_count == 1
        info = document.page_info(0)
        assert round(info.width_pt, 2) == 123
        assert round(info.height_pt, 2) == 57
        rendered = document.render_page(0, scale=1).to_pil()
        assert rendered.size == (123, 57)
        assert rendered.getpixel((0, 0)) == (20, 140, 210)


def test_pdfs_to_images_exact_renders_each_page_without_extra_canvas(tmp_path):
    source = tmp_path / "source.pdf"
    canvas = Canvas(str(source), pagesize=(72, 36))
    canvas.showPage()
    canvas.save()

    outputs = pdfs_to_images_exact([str(source)], out_dir=tmp_path, dpi=144)

    assert len(outputs) == 1
    with Image.open(outputs[0]) as image:
        assert image.size == (144, 72)
