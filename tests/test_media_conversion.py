from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image

from core.media_conversion import (
    images_to_pdf_exact,
    pdfs_to_images_exact,
)


def test_images_to_pdf_exact_creates_marginless_image_sized_page(tmp_path):
    image_path = tmp_path / "source.png"
    Image.new("RGB", (123, 57), (20, 140, 210)).save(image_path)

    output = images_to_pdf_exact([str(image_path)], out_dir=tmp_path)

    assert Path(output).exists()
    doc = fitz.open(output)
    try:
        assert doc.page_count == 1
        page = doc[0]
        assert round(page.rect.width, 2) == 123
        assert round(page.rect.height, 2) == 57
        image_info = page.get_image_info(hashes=False)
        assert len(image_info) == 1
        assert tuple(round(value, 2) for value in image_info[0]["bbox"]) == (
            0,
            0,
            123,
            57,
        )
    finally:
        doc.close()


def test_pdfs_to_images_exact_renders_each_page_without_extra_canvas(tmp_path):
    source = tmp_path / "source.pdf"
    doc = fitz.open()
    doc.new_page(width=72, height=36)
    doc.save(source)
    doc.close()

    outputs = pdfs_to_images_exact([str(source)], out_dir=tmp_path, dpi=144)

    assert len(outputs) == 1
    with Image.open(outputs[0]) as image:
        assert image.size == (144, 72)
