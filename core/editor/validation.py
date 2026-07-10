"""Inspección al abrir un PDF en el Studio (spec §15).

Produce un OpenReport con todo lo que la UI necesita para avisar al usuario:
contraseña, daño reparado al vuelo, firmas digitales (se invalidarían al
editar), páginas rotadas y páginas sin texto nativo (candidatas a OCR).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf

from core.pdf_backend import PdfRenderDocument


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
        with pikepdf.Pdf.open(path, password=password or "") as structure:
            rep.was_repaired = bool(structure.get_warnings())
            rep.page_count = len(structure.pages)
            rep.has_signatures = _has_signature_fields(structure)
    except pikepdf.PasswordError:
        rep.needs_password = True
        rep.error = "El PDF está protegido con contraseña"
        return rep
    except Exception as exc:  # noqa: BLE001 — se reporta
        rep.error = f"No se pudo abrir el PDF: {exc}"
        return rep

    try:
        sizes: set[tuple[int, ...]] = set()
        with PdfRenderDocument(path, password=password) as document:
            for index in range(document.page_count):
                info = document.page_info(index)
                page_number = index + 1
                if info.rotation % 360 != 0:
                    rep.rotated_pages.append(page_number)
                # /Rotate transpone el display, pero el papel físico es el mismo.
                sizes.add(tuple(sorted((round(info.width_pt), round(info.height_pt)))))
                if not document.extract_text(index).strip():
                    rep.scanned_pages.append(page_number)
        rep.mixed_sizes = len(sizes) > 1
        rep.ok = True
        return rep
    except Exception as exc:  # noqa: BLE001 — se reporta
        rep.error = f"No se pudo inspeccionar el PDF: {exc}"
        return rep


def _has_signature_fields(document: pikepdf.Pdf) -> bool:
    acro_form = document.Root.get("/AcroForm")
    if not acro_form:
        return False

    def visit(field, inherited_type=None) -> bool:
        field_type = field.get("/FT", inherited_type)
        if str(field_type) == "/Sig":
            return True
        return any(visit(kid, field_type) for kid in field.get("/Kids", []))

    return any(visit(field) for field in acro_form.get("/Fields", []))
