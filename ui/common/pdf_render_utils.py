"""Qt conversions for rasters returned by the internal PDF backend."""
from __future__ import annotations

from PySide6.QtGui import QImage, QPixmap

from core.pdf_backend import RenderedPage


def rendered_page_to_qimage(rendered: RenderedPage) -> QImage:
    """Return a QImage that owns its pixel memory."""
    image_format = (
        QImage.Format.Format_RGBA8888
        if rendered.mode == "RGBA"
        else QImage.Format.Format_RGB888
    )
    image = QImage(
        rendered.data,
        rendered.width,
        rendered.height,
        rendered.stride,
        image_format,
    )
    return image.copy()


def rendered_page_to_qpixmap(rendered: RenderedPage) -> QPixmap:
    """Convert an owned backend raster to a GUI-thread QPixmap."""
    return QPixmap.fromImage(rendered_page_to_qimage(rendered))
