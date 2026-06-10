"""Inspección al abrir un PDF en el Studio (spec §15).

Produce un OpenReport con todo lo que la UI necesita para avisar al usuario:
contraseña, daño reparado al vuelo, firmas digitales (se invalidarían al
editar), páginas rotadas y páginas sin texto nativo (candidatas a OCR).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

import fitz


@dataclass
class OpenReport:
    ok: bool = False
    error: str = ""
    needs_password: bool = False
    was_repaired: bool = False
    has_signatures: bool = False
    page_count: int = 0
    rotated_pages: list[int] = field(default_factory=list)    # 1-based
    scanned_pages: list[int] = field(default_factory=list)    # 1-based, sin texto
    mixed_sizes: bool = False


def inspect_pdf(path: Path, password: str | None = None) -> OpenReport:
    rep = OpenReport()
    try:
        doc = fitz.open(str(path))
    except Exception as exc:                      # noqa: BLE001 — se reporta
        rep.error = f"No se pudo abrir el PDF: {exc}"
        return rep
    try:
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                rep.needs_password = True
                rep.error = "El PDF está protegido con contraseña"
                return rep
        rep.was_repaired = bool(getattr(doc, "is_repaired", False))
        rep.page_count = doc.page_count

        sizes: set[tuple[int, ...]] = set()
        for i, page in enumerate(doc, start=1):
            if page.rotation % 360 != 0:
                rep.rotated_pages.append(i)
            # Par ordenado: el /Rotate transpone el display, pero el papel físico
            # es el mismo (carta rotada sigue siendo carta)
            sizes.add(tuple(sorted((round(page.rect.width), round(page.rect.height)))))
            if not page.get_text("words"):
                rep.scanned_pages.append(i)
        rep.mixed_sizes = len(sizes) > 1

        # Firmas digitales: campos widget de tipo firma en cualquier página
        for page in doc:
            for w in page.widgets() or []:
                if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    rep.has_signatures = True
                    break
            if rep.has_signatures:
                break

        rep.ok = True
        return rep
    finally:
        doc.close()
