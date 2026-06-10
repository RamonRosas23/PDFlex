"""Validación al abrir: cifrado, daño reparado, firmas digitales, resumen de páginas."""
import fitz
import pytest

from core.editor.validation import OpenReport, inspect_pdf


def test_clean_pdf_report(make_pdf):
    path = make_pdf(rotations=[0, 90], with_text=True)
    rep = inspect_pdf(path)
    assert rep.ok and not rep.needs_password
    assert rep.page_count == 2
    assert rep.rotated_pages == [2]            # 1-based
    assert rep.scanned_pages == []             # tiene texto nativo
    assert not rep.has_signatures
    assert not rep.mixed_sizes


def test_scanned_pages_detected(make_pdf):
    path = make_pdf(rotations=[0])             # sin texto
    rep = inspect_pdf(path)
    assert rep.scanned_pages == [1]


def test_mixed_sizes_detected(make_pdf):
    path = make_pdf(sizes=[(595, 842), (612, 1008)])
    rep = inspect_pdf(path)
    assert rep.mixed_sizes


def test_encrypted_pdf_needs_password(make_pdf, tmp_path):
    src = make_pdf()
    enc = tmp_path / "enc.pdf"
    with fitz.open(src) as doc:
        doc.save(str(enc), encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw="own", user_pw="usr")
    rep = inspect_pdf(enc)
    assert rep.needs_password and not rep.ok
    rep2 = inspect_pdf(enc, password="usr")
    assert rep2.ok and not rep2.needs_password


def test_signature_fields_detected(make_pdf):
    src = make_pdf()
    with fitz.open(src) as doc:
        page = doc[0]
        w = fitz.Widget()
        w.field_name = "firma1"
        w.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE
        w.rect = fitz.Rect(50, 50, 200, 100)
        page.add_widget(w)
        out = src.with_name("signed.pdf")
        doc.save(str(out))
    rep = inspect_pdf(out)
    assert rep.has_signatures


def test_missing_file_reports_error(tmp_path):
    rep = inspect_pdf(tmp_path / "no_existe.pdf")
    assert not rep.ok and rep.error
