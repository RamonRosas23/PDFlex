from __future__ import annotations

from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

from core.margin_detector import detect_margins


def test_detect_margins_uses_text_vector_and_image_object_bounds(tmp_path: Path):
    source = tmp_path / "letterhead.pdf"
    canvas = Canvas(str(source), pagesize=(612, 792))
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(36, 752, "PDFLEX EMPRESA")
    canvas.setLineWidth(2)
    canvas.line(30, 742, 582, 742)
    canvas.setFont("Helvetica", 9)
    canvas.drawString(36, 28, "Dirección y teléfono")
    canvas.showPage()
    canvas.save()

    margins = detect_margins(str(source))

    assert 45 <= margins.top_pt <= 70
    assert 35 <= margins.bottom_pt <= 60
    assert margins.left_pt == 18
    assert margins.right_pt == 18


def test_detect_margins_falls_back_for_invalid_pdf(tmp_path: Path):
    margins = detect_margins(str(tmp_path / "missing.pdf"))

    assert margins.top_pt == 72
    assert margins.bottom_pt == 54
