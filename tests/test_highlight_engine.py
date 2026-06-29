from __future__ import annotations

from pathlib import Path

import fitz
import numpy as np

from core.highlight_engine import (
    HighlightEngine,
    HighlightJob,
    HighlightMark,
    HighlightOptions,
    render_highlight_texture,
)


def test_render_highlight_texture_has_realistic_alpha_variation() -> None:
    options = HighlightOptions.from_profile("seco_textura", seed=123)

    image = render_highlight_texture(320, 44, options, seed="sample")
    alpha = np.asarray(image.getchannel("A"), dtype=np.uint8)

    assert image.mode == "RGBA"
    assert alpha.max() > 40
    assert alpha.std() > 7
    assert np.count_nonzero(alpha == 0) > 0


def test_highlight_engine_flattens_marker_texture_without_removing_text(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "input.pdf")
    output = tmp_path / "output.pdf"
    options = HighlightOptions.from_profile("oficina_real", seed=7)
    job = HighlightJob(
        pdf_path=str(source),
        output_path=str(output),
        marks=[HighlightMark(0, 0.10, 0.28, 0.84, 0.42)],
        options=options,
    )

    result = HighlightEngine().run_job(job)

    assert result.success, result.error
    assert result.mark_count == 1
    assert output.exists()

    doc = fitz.open(output)
    try:
        assert "Texto importante" in doc[0].get_text()
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        roi = arr[int(pix.height * 0.30): int(pix.height * 0.40), int(pix.width * 0.18): int(pix.width * 0.76)]
        assert roi[..., 0].mean() > 225
        assert roi[..., 1].mean() > 205
        assert roi[..., 2].mean() < 248
    finally:
        doc.close()


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=320, height=220)
    page.insert_text((42, 78), "Texto importante", fontsize=18)
    doc.save(path)
    doc.close()
    return path
