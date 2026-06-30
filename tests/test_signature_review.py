from __future__ import annotations

import fitz
from PIL import Image, ImageDraw

from core.safe_zone import Placement
from core.signature_engine import JobResult, SigPlacement, SignJob, SignatureEngine
from core.signature_review import (
    ReviewDocument,
    ReviewSignatureInstance,
    build_review_documents,
    export_review_documents,
    validate_review_document,
    validate_review_page,
)
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


def test_review_plan_does_not_write_draft_until_export(tmp_path) -> None:
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

    result = SignatureEngine(variation).plan_job(job)

    assert result.success
    assert result.output_path == str(out_path)
    assert not out_path.exists()
    review_docs = build_review_documents([result])

    final_results = export_review_documents(review_docs, variation)

    assert len(final_results) == 1
    assert final_results[0].success
    assert out_path.exists()
    assert _image_count(out_path) == 1


def test_validate_review_page_only_updates_target_page(tmp_path) -> None:
    pdf_path = _make_two_page_pdf(tmp_path / "source.pdf")
    job = SignJob(pdf_path=str(pdf_path), output_path=str(pdf_path), signatures=[])
    source_result = JobResult(job=job, output_path=str(pdf_path), success=True)
    review = ReviewDocument(
        source_path=str(pdf_path),
        draft_path=str(pdf_path),
        final_path=str(pdf_path),
        source_result=source_result,
        instances=[
            ReviewSignatureInstance.from_page_result(
                signature_path="firma-a.png",
                signature_uid="sig-a",
                signature_label="Firma A",
                page_index=0,
                placement=Placement(x=70, y=80, width=90, height=30, angle=0),
                order=0,
            ),
            ReviewSignatureInstance.from_page_result(
                signature_path="firma-b.png",
                signature_uid="sig-b",
                signature_label="Firma B",
                page_index=1,
                placement=Placement(x=70, y=80, width=90, height=30, angle=0),
                order=0,
            ),
        ],
    )

    validate_review_page(review, 0)

    assert "revisar texto" in review.instances[0].warnings
    assert review.instances[1].warnings == ()

    validate_review_document(review)

    assert "revisar texto" in review.instances[1].warnings


def _make_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=300, height=420)
    page.insert_text((40, 80), "Contrato base")
    doc.save(path)
    doc.close()
    return path


def _make_two_page_pdf(path):
    doc = fitz.open()
    for index in range(2):
        page = doc.new_page(width=300, height=420)
        page.insert_text((40, 80), f"Texto ocupado {index + 1}")
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
