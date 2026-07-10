"""Verificación post-exportación: el PDF debe reabrirse y renderizar (spec §15)."""
from __future__ import annotations
from pathlib import Path

from core.pdf_backend import PdfRenderDocument


def verify_pdf(path: Path, expected_pages: int) -> tuple[bool, str]:
    try:
        if path.stat().st_size == 0:
            return False, "El archivo exportado está vacío"
        with PdfRenderDocument(path) as document:
            if document.page_count != expected_pages:
                return False, (f"Páginas esperadas {expected_pages}, "
                               f"obtenidas {document.page_count}")
            # Render de muestra: primera, última y una del medio
            for idx in sorted({0, document.page_count // 2, document.page_count - 1}):
                document.render_page(idx, scale=0.4)
        return True, ""
    except Exception as exc:                      # noqa: BLE001 — se reporta
        return False, f"El PDF exportado no es válido: {exc}"
