from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.pdfgen.canvas import Canvas

from core.pdf_analyzer import PdfAnalyzer
from core.pdf_backend import Rect


def test_pdf_analyzer_detects_text_collision_margins_and_signature_line(tmp_path: Path):
    source = tmp_path / "analysis.pdf"
    canvas = Canvas(str(source), pagesize=(300, 400))
    canvas.setFont("Helvetica", 12)
    canvas.drawString(40, 300, "Texto que debe evitar la firma")
    canvas.setLineWidth(1)
    canvas.line(80, 100, 220, 100)
    canvas.showPage()
    canvas.save()

    analysis = PdfAnalyzer().analyze_document(str(source))[0]

    assert (analysis.width, analysis.height) == (300, 400)
    assert any("Texto que debe" in block.text for block in analysis.text_blocks)
    assert analysis.intersects_text(Rect(35, 85, 245, 120), padding=0)
    assert not analysis.intersects_text(Rect(20, 200, 60, 240), padding=0)
    assert analysis.signature_lines
    x0, y0, x1, y1 = analysis.signature_lines[0]
    assert x0 == pytest.approx(80, abs=1)
    assert x1 == pytest.approx(220, abs=1)
    assert 299 <= y0 <= 301
    assert y1 - y0 <= 2


def test_pdf_analyzer_understands_text_signature_rule(tmp_path: Path):
    source = tmp_path / "underscores.pdf"
    canvas = Canvas(str(source), pagesize=(300, 200))
    canvas.drawString(60, 60, "____________________")
    canvas.showPage()
    canvas.save()

    analysis = PdfAnalyzer().analyze_document(str(source))[0]

    assert analysis.signature_lines
    anchor_x, anchor_y = PdfAnalyzer.suggest_signature_anchor(analysis)
    assert 100 < anchor_x < 200
    assert anchor_y < analysis.signature_lines[-1][1]
