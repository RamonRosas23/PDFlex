from __future__ import annotations

from pathlib import Path

from PIL import Image

from core.pdf_backend import ImagePdfPage, PdfRenderDocument, create_image_pdf


def test_create_image_pdf_places_images_and_writes_multiple_pages(tmp_path: Path):
    output = tmp_path / "images.pdf"
    red = Image.new("RGB", (20, 20), (220, 20, 30))
    blue = Image.new("RGB", (20, 20), (20, 60, 220))

    page_count = create_image_pdf(
        [
            ImagePdfPage(red, 100, 100, 25, 25, 50, 50),
            ImagePdfPage(blue, 80, 40),
        ],
        output,
    )

    assert page_count == 2
    with PdfRenderDocument(output) as document:
        first = document.render_page(0, scale=1).to_pil()
        second = document.render_page(1, scale=1).to_pil()
        assert first.size == (100, 100)
        assert first.getpixel((5, 5)) == (255, 255, 255)
        assert first.getpixel((50, 50))[0] > 180
        assert second.size == (80, 40)
        assert second.getpixel((40, 20))[2] > 180


def test_create_image_pdf_keeps_existing_output_when_input_is_empty(tmp_path: Path):
    output = tmp_path / "existing.pdf"
    output.write_bytes(b"keep-me")

    try:
        create_image_pdf([], output)
    except ValueError as exc:
        assert "imagen" in str(exc)
    else:
        raise AssertionError("create_image_pdf accepted an empty page list")

    assert output.read_bytes() == b"keep-me"
