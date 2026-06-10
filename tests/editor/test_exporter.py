"""Exportador end-to-end: documento+reglas → PDF nuevo verificado, original intacto."""
import hashlib

import fitz
import pytest

from core.editor.export.exporter import ExportOptions, Exporter
from core.editor.geometry import PageGeometry
from core.editor.model.document_state import EditorDocument
from core.editor.model.elements import ImageElement, TextElement
from core.editor.model.layers import Layer
from core.editor.model.page_target import PageTarget
from core.editor.model.placement import Anchor, Frame, Placement
from core.editor.model.rules import PageRule


def _build_doc(pdf_path) -> EditorDocument:
    with fitz.open(pdf_path) as d:
        geos = [PageGeometry.from_page(i, d[i]) for i in range(d.page_count)]
    sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    return EditorDocument(source_path=str(pdf_path), source_sha256=sha,
                          page_geometries=geos)


def test_export_concrete_text_and_rule_on_odd_pages(make_pdf, tmp_path):
    src = make_pdf(rotations=[0, 90, 0, 270])
    doc = _build_doc(src)
    doc.add_element(2, TextElement(text="SOLO PAG 2", font_size=18,
                                   frame=Frame(80, 100, 250, 40)))
    doc.add_rule(PageRule(
        element=TextElement(text="Pág. {pagina} de {total}", variables_enabled=True,
                            frame=Frame(0, 0, 140, 26), font_size=9,
                            placement=Placement(mode="anchor",
                                                anchor=Anchor.BOTTOM_CENTER, dy_pt=-12)),
        target=PageTarget(mode="odd")))
    out = tmp_path / "salida.pdf"
    src_bytes = src.read_bytes()

    result = Exporter().export(doc, out, ExportOptions())

    assert result.success, result.error
    assert src.read_bytes() == src_bytes          # original INTACTO byte a byte
    with fitz.open(out) as d:
        assert d.page_count == 4
        assert "SOLO PAG 2" in d[1].get_text()
        assert "Pág. 1 de 4" in d[0].get_text()
        assert "Pág. 3 de 4" in d[2].get_text()   # página /Rotate=0
        assert "SOLO PAG 2" not in d[0].get_text()
        assert "Pág. 2" not in d[1].get_text()    # la regla es solo impares


def test_export_image_element_visually_verified(make_pdf, probe_png, tmp_path):
    src = make_pdf(rotations=[90])
    doc = _build_doc(src)
    doc.assets["img1"] = probe_png
    doc.add_element(1, ImageElement(asset_id="img1", frame=Frame(100, 120, 80, 80)))
    out = tmp_path / "img.pdf"
    result = Exporter().export(doc, out, ExportOptions())
    assert result.success, result.error
    import numpy as np
    with fitz.open(out) as d:
        pix = d[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        ys, xs = np.nonzero((arr < 250).any(axis=2))
        bbox = (xs.min() / 2, ys.min() / 2, (xs.max() + 1) / 2, (ys.max() + 1) / 2)
        for g, w in zip(bbox, (100, 120, 180, 200)):
            assert g == pytest.approx(w, abs=0.6), f"{bbox}"


def test_hidden_layer_not_exported(make_pdf, tmp_path):
    src = make_pdf()
    doc = _build_doc(src)
    doc.layers.add(Layer(id="oculta", name="Oculta", z=1, visible=False))
    doc.add_element(1, TextElement(text="NO DEBE SALIR", layer_id="oculta",
                                   frame=Frame(50, 50, 200, 30)))
    out = tmp_path / "capas.pdf"
    assert Exporter().export(doc, out, ExportOptions()).success
    with fitz.open(out) as d:
        assert "NO DEBE SALIR" not in d[0].get_text()


def test_text_overflow_produces_warning(make_pdf, tmp_path):
    src = make_pdf()
    doc = _build_doc(src)
    doc.add_element(1, TextElement(text="palabra " * 200, font_size=14,
                                   frame=Frame(50, 50, 120, 40)))   # caja chica
    out = tmp_path / "overflow.pdf"
    result = Exporter().export(doc, out, ExportOptions())
    assert result.success
    assert result.warnings and "no cupo" in result.warnings[0]


def test_backup_created_when_overwriting(make_pdf, tmp_path):
    src = make_pdf()
    doc = _build_doc(src)
    doc.add_element(1, TextElement(text="v2", frame=Frame(50, 50, 100, 30)))
    out = tmp_path / "salida.pdf"
    out.write_bytes(b"%PDF-1.4 contenido previo")
    result = Exporter().export(doc, out, ExportOptions())
    assert result.success, result.error
    backups = list((tmp_path / "respaldo").glob("salida*.pdf"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"%PDF-1.4 contenido previo"
    assert out.read_bytes() != b"%PDF-1.4 contenido previo"


def test_progress_and_cancel(make_pdf, tmp_path):
    src = make_pdf(rotations=[0] * 6)
    doc = _build_doc(src)
    calls = []
    result = Exporter().export(doc, tmp_path / "c.pdf", ExportOptions(),
                               progress=lambda c, t, m: calls.append((c, t)),
                               should_cancel=lambda: len(calls) >= 3)
    assert not result.success and "cancel" in result.error.lower()
    assert not (tmp_path / "c.pdf").exists()      # cancelado → no deja basura
    assert not list(tmp_path.glob("*.tmp*"))


def test_verifier_rejects_corrupt_output(tmp_path):
    from core.editor.export.verifier import verify_pdf
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"garbage")
    ok, msg = verify_pdf(bad, expected_pages=1)
    assert not ok and msg
