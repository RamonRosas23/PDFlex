from __future__ import annotations

import fitz
from PIL import Image, ImageDraw

from core.signature_engine import SigPlacement, SignJob, SignatureEngine
from core.signature_review import build_review_documents, export_review_documents
from core.variation import VariationConfig


def test_review_export_can_remove_generated_signature(tmp_path) -> None:
    pdf_path = _make_pdf(tmp_path / "source.pdf")
    sig_path = _make_signature(tmp_path / "firma.png")
    out_path = tmp_path / "source_firmado.pdf"
    variation = VariationConfig(
        angle_deg=0,
        scale_pct=0,
        offset_x=0,
        offset_y=0,
        opacity_min=1,
        opacity_max=1,
        enable_pressure_jitter=False,
        stroke_mode="exacta",
    )

    job = SignJob(
        pdf_path=str(pdf_path),
        output_path=str(out_path),
        signatures=[
            SigPlacement(
                signature_path=str(sig_path),
                base_x_norm=0.5,
                base_y_norm=0.65,
                base_width_pt=120,
                base_height_pt=45,
                signature_uid="sig-a",
                signature_label="Firma A",
            )
        ],
        smart_placement=False,
    )
    result = SignatureEngine(variation).run_job(job)
    assert result.success
    assert _image_count(out_path) == 1

    review_docs = build_review_documents([result])
    assert len(review_docs) == 1
    assert review_docs[0].instances[0].signature_uid == "sig-a"
    assert review_docs[0].instances[0].signature_label == "Firma A"

    review_docs[0].instances[0].deleted = True
    final_results = export_review_documents(review_docs, variation)

    assert len(final_results) == 1
    assert final_results[0].success
    assert final_results[0].page_results == []
    assert _image_count(out_path) == 0


def _make_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=300, height=420)
    page.insert_text((40, 80), "Contrato base")
    doc.save(path)
    doc.close()
    return path


def _make_signature(path):
    img = Image.new("RGBA", (240, 90), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.line((15, 55, 220, 35), fill=(20, 45, 170, 255), width=5)
    img.save(path)
    return path


def _image_count(path) -> int:
    with fitz.open(path) as doc:
        return len(doc[0].get_images(full=True))
