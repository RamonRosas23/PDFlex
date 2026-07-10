"""PDF composition helpers built on ReportLab and verified with PDFium."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
from typing import Iterable
import uuid

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from .errors import PdfBackendError
from .rendering import PdfRenderDocument


@dataclass(frozen=True, slots=True)
class ImagePdfPage:
    """One image placement using top-left PDFlex coordinates, in points."""

    image: Image.Image | bytes
    page_width_pt: float
    page_height_pt: float
    left_pt: float = 0.0
    top_pt: float = 0.0
    width_pt: float | None = None
    height_pt: float | None = None


def create_image_pdf(
    pages: Iterable[ImagePdfPage],
    output_path: str | Path,
) -> int:
    """Write image-backed PDF pages atomically and return the page count."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    canvas: Canvas | None = None
    page_count = 0

    try:
        for spec in pages:
            page_width = float(spec.page_width_pt)
            page_height = float(spec.page_height_pt)
            draw_width = float(spec.width_pt if spec.width_pt is not None else page_width)
            draw_height = float(spec.height_pt if spec.height_pt is not None else page_height)
            if min(page_width, page_height, draw_width, draw_height) <= 0:
                raise ValueError("Las dimensiones de página e imagen deben ser positivas.")

            if canvas is None:
                canvas = Canvas(
                    str(temporary),
                    pagesize=(page_width, page_height),
                    pageCompression=1,
                )
            canvas.setPageSize((page_width, page_height))
            # ReportLab uses a bottom-left origin; PDFlex placement uses the
            # top-left convention shared by the UI and rendering APIs.
            draw_y = page_height - float(spec.top_pt) - draw_height
            image_source = BytesIO(spec.image) if isinstance(spec.image, bytes) else spec.image
            canvas.drawImage(
                ImageReader(image_source),
                float(spec.left_pt),
                draw_y,
                width=draw_width,
                height=draw_height,
                preserveAspectRatio=False,
                mask="auto",
            )
            canvas.showPage()
            page_count += 1

        if canvas is None or page_count == 0:
            raise ValueError("Agrega al menos una imagen para crear el PDF.")
        canvas.save()
        os.replace(temporary, output)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    try:
        with PdfRenderDocument(output) as document:
            if document.page_count != page_count:
                raise PdfBackendError(
                    f"El PDF contiene {document.page_count} páginas; se esperaban {page_count}."
                )
            for index in _sample_page_indexes(page_count):
                document.render_page(index, scale=0.2)
    except Exception:
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return page_count


def _sample_page_indexes(page_count: int) -> list[int]:
    if page_count <= 6:
        return list(range(page_count))
    return sorted({0, page_count // 2, page_count - 1})
