"""ReportLab drawing primitives for display-sized editor overlays."""
from __future__ import annotations

from io import BytesIO

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from core.editor.geometry import PageGeometry, display_rect
from core.pdf_backend import Rect

RGB = tuple[float, float, float]

_FONT_MAP = {
    "helv": "Helvetica",
    "hebo": "Helvetica-Bold",
    "heit": "Helvetica-Oblique",
    "hebi": "Helvetica-BoldOblique",
    "tiro": "Times-Roman",
    "tibo": "Times-Bold",
    "tiit": "Times-Italic",
    "tibi": "Times-BoldItalic",
    "cour": "Courier",
    "cobo": "Courier-Bold",
    "coit": "Courier-Oblique",
    "cobi": "Courier-BoldOblique",
}


def stamp_rect(
    canvas: Canvas,
    geo: PageGeometry,
    rect_display: object,
    *,
    fill: RGB,
    opacity: float = 1.0,
) -> None:
    """Draw a filled rectangle in display coordinates."""
    rect = display_rect(rect_display)
    canvas.saveState()
    canvas.setFillColorRGB(*fill)
    canvas.setFillAlpha(_clamp_opacity(opacity))
    canvas.rect(
        rect.x0,
        geo.height_pt - rect.y1,
        rect.width,
        rect.height,
        stroke=0,
        fill=1,
    )
    canvas.restoreState()


def stamp_text(
    canvas: Canvas,
    geo: PageGeometry,
    rect_display: object,
    text: str,
    *,
    fontsize: float = 12.0,
    fontname: str = "helv",
    color: RGB = (0, 0, 0),
    opacity: float = 1.0,
    align: int = 0,
    angle_deg: float = 0.0,
) -> float:
    """Draw extractable text in a display-space box.

    The return value mirrors the old exporter contract: negative means
    some text did not fit vertically.
    """
    rect = display_rect(rect_display)
    font = _FONT_MAP.get(fontname, "Helvetica")
    size = max(1.0, float(fontsize))
    line_height = size * 1.2
    lines = _wrap_lines(text, font, size, max(1.0, rect.width))
    max_lines = max(1, int(rect.height // line_height))
    visible = lines[:max_lines]

    canvas.saveState()
    canvas.setFillColorRGB(*color)
    canvas.setFillAlpha(_clamp_opacity(opacity))
    canvas.setFont(font, size)
    canvas.translate((rect.x0 + rect.x1) / 2.0, geo.height_pt - (rect.y0 + rect.y1) / 2.0)
    if abs(angle_deg) > 0.001:
        canvas.rotate(-float(angle_deg))

    for index, line in enumerate(visible):
        line_width = stringWidth(line, font, size)
        x = _aligned_x(rect.width, line_width, align)
        y = rect.height / 2.0 - size * 1.22 - index * line_height
        canvas.drawString(x, y, line)
    canvas.restoreState()

    if len(lines) > max_lines:
        return -(len(lines) - max_lines) * line_height
    return rect.height - len(lines) * line_height


def stamp_image(
    canvas: Canvas,
    geo: PageGeometry,
    rect_display: object,
    image_bytes: bytes,
) -> None:
    """Draw an image in a display-space box."""
    rect = display_rect(rect_display)
    _draw_image(canvas, geo, rect, image_bytes)


def stamp_image_rotated(
    canvas: Canvas,
    geo: PageGeometry,
    rect_display: object,
    image_bytes: bytes,
    *,
    angle_deg: float,
) -> None:
    """Draw an image rotated around the center of its frame.

    Product convention is Qt-like: positive degrees rotate clockwise on screen.
    """
    rect = display_rect(rect_display)
    image = Image.open(BytesIO(image_bytes)).convert("RGBA")
    rotated = image.rotate(
        -float(angle_deg),
        resample=Image.Resampling.BICUBIC,
        expand=True,
        fillcolor=(0, 0, 0, 0),
    )
    out = BytesIO()
    rotated.save(out, format="PNG")

    scale_x = rect.width / max(1, image.width)
    scale_y = rect.height / max(1, image.height)
    new_w = rotated.width * scale_x
    new_h = rotated.height * scale_y
    cx = (rect.x0 + rect.x1) / 2.0
    cy = (rect.y0 + rect.y1) / 2.0
    grown = Rect(cx - new_w / 2.0, cy - new_h / 2.0, cx + new_w / 2.0, cy + new_h / 2.0)
    _draw_image(canvas, geo, grown, out.getvalue())


def _draw_image(canvas: Canvas, geo: PageGeometry, rect: Rect, image_bytes: bytes) -> None:
    canvas.drawImage(
        ImageReader(BytesIO(image_bytes)),
        rect.x0,
        geo.height_pt - rect.y1,
        width=rect.width,
        height=rect.height,
        preserveAspectRatio=False,
        mask="auto",
    )


def _wrap_lines(text: str, font: str, size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    for raw_line in str(text).splitlines() or [""]:
        words = raw_line.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if current and stringWidth(candidate, font, size) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def _aligned_x(width: float, line_width: float, align: int) -> float:
    left = -width / 2.0
    if align == 1:
        return -line_width / 2.0
    if align == 2:
        return width / 2.0 - line_width
    return left


def _clamp_opacity(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
