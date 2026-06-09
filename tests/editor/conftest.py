"""Fixtures compartidos del editor: fábrica de PDFs sintéticos con rotación/tamaños."""
from __future__ import annotations
from pathlib import Path

import fitz
import pytest


@pytest.fixture
def make_pdf(tmp_path):
    """Fábrica: crea un PDF en tmp con páginas controladas.

    make_pdf(rotations=[0, 90])            → 2 páginas A4 con /Rotate 0 y 90
    make_pdf(sizes=[(595,842),(612,1008)]) → 2 páginas de esos tamaños, /Rotate 0
    make_pdf(rotations=[90], with_text=True) → página con texto nativo de referencia
    """
    counter = {"n": 0}

    def _make(rotations=None, sizes=None, with_text=False) -> Path:
        rotations = rotations if rotations is not None else [0]
        sizes = sizes if sizes is not None else [(595.0, 842.0)] * len(rotations)
        if len(rotations) == 1 and len(sizes) > 1:
            rotations = rotations * len(sizes)
        counter["n"] += 1
        path = tmp_path / f"fixture_{counter['n']}.pdf"
        doc = fitz.open()
        for rot, (w, h) in zip(rotations, sizes):
            page = doc.new_page(width=w, height=h)
            if with_text:
                page.insert_text(fitz.Point(72, 72), "texto nativo de referencia",
                                 fontsize=11, fontname="helv")
            page.set_rotation(rot)
        doc.save(str(path))
        doc.close()
        return path

    return _make
