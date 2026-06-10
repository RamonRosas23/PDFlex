"""Verificación post-exportación: el PDF debe reabrirse y renderizar (spec §15)."""
from __future__ import annotations
from pathlib import Path

import fitz


def verify_pdf(path: Path, expected_pages: int) -> tuple[bool, str]:
    try:
        if path.stat().st_size == 0:
            return False, "El archivo exportado está vacío"
        with fitz.open(str(path)) as doc:
            if doc.page_count != expected_pages:
                return False, (f"Páginas esperadas {expected_pages}, "
                               f"obtenidas {doc.page_count}")
            # Render de muestra: primera, última y una del medio
            for idx in sorted({0, doc.page_count // 2, doc.page_count - 1}):
                doc[idx].get_pixmap(matrix=fitz.Matrix(0.4, 0.4))
        return True, ""
    except Exception as exc:                      # noqa: BLE001 — se reporta
        return False, f"El PDF exportado no es válido: {exc}"
