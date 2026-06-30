from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from core.safe_zone import Placement
from core.signature_engine import (
    SigPlacement,
    SignJob,
    SignatureEngine,
    _process_image_size,
)
from core.variation import VariationConfig


def test_run_job_with_progress_succeeds(tmp_path: Path) -> None:
    pdf_path = _make_pdf(tmp_path / "source.pdf", pages=1)
    sig_path = _make_signature(tmp_path / "firma.png")
    out_path = tmp_path / "source_firmado.pdf"
    progress: list[tuple[int, int, str]] = []

    result = SignatureEngine(_exact_variation()).run_job(
        SignJob(
            pdf_path=str(pdf_path),
            output_path=str(out_path),
            signatures=[
                SigPlacement(
                    signature_path=str(sig_path),
                    base_x_norm=0.5,
                    base_y_norm=0.72,
                    base_width_pt=110,
                    base_height_pt=38,
                )
            ],
            smart_placement=False,
        ),
        progress=lambda cur, total, msg: progress.append((cur, total, msg)),
    )

    assert result.success, result.error
    assert out_path.exists()
    assert progress[-1] == (1, 1, "Guardado")


def test_exact_signature_reuses_image_xref_across_pages(tmp_path: Path) -> None:
    pdf_path = _make_pdf(tmp_path / "source.pdf", pages=4)
    sig_path = _make_signature(tmp_path / "firma.png")
    out_path = tmp_path / "source_firmado.pdf"

    result = SignatureEngine(_exact_variation()).run_job(
        SignJob(
            pdf_path=str(pdf_path),
            output_path=str(out_path),
            signatures=[
                SigPlacement(
                    signature_path=str(sig_path),
                    base_x_norm=0.5,
                    base_y_norm=0.72,
                    base_width_pt=110,
                    base_height_pt=38,
                )
            ],
            smart_placement=False,
        )
    )

    assert result.success, result.error
    with fitz.open(out_path) as doc:
        image_xrefs = {
            image[0]
            for page in doc
            for image in page.get_images(full=True)
        }
    assert len(image_xrefs) == 1


def test_signature_processing_size_downscales_only_when_oversized() -> None:
    placement = Placement(x=100, y=100, width=144, height=48, angle=0)

    assert _process_image_size((300, 100), placement) == (300, 100)
    assert _process_image_size((2400, 800), placement) == (720, 240)


def _exact_variation() -> VariationConfig:
    return VariationConfig(
        angle_deg=0,
        scale_pct=0,
        offset_x=0,
        offset_y=0,
        opacity_min=1,
        opacity_max=1,
        enable_pressure_jitter=False,
        stroke_mode="exacta",
        stroke_strength=0,
    )


def _make_pdf(path: Path, *, pages: int) -> Path:
    doc = fitz.open()
    try:
        for page_index in range(pages):
            page = doc.new_page(width=300, height=420)
            page.insert_text((40, 80), f"Contrato base {page_index + 1}")
    finally:
        doc.save(path)
        doc.close()
    return path


def _make_signature(path: Path) -> Path:
    img = Image.new("RGBA", (900, 260), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.line((50, 165, 830, 95), fill=(20, 45, 170, 230), width=8)
    draw.arc((130, 70, 360, 220), 200, 350, fill=(20, 45, 170, 220), width=7)
    img.save(path)
    return path
