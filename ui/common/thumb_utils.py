"""Generación de thumbnails de PDFs para listas de documentos."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PyQt6.QtGui import QPixmap, QImage


def make_pdf_thumb(pdf_path: str, width: int = 72) -> Optional[QPixmap]:
    """Renderiza la primera página del PDF como thumbnail.

    Retorna None si el archivo no se puede abrir o no es un PDF válido.
    """
    try:
        import fitz
        from PIL import Image

        doc = fitz.open(pdf_path)
        page = doc[0]
        scale = width / max(1.0, page.rect.width)
        mat = fitz.Matrix(scale, scale)
        pm = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples).convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        doc.close()
        return QPixmap.fromImage(qimg.copy())
    except Exception:
        return None
