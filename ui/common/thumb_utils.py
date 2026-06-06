"""Generación de thumbnails de PDFs para listas de documentos."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen


def make_pdf_thumb(pdf_path: str, width: int = 72) -> Optional[QImage]:
    """Renderiza la primera página del PDF como thumbnail.

    Retorna None si el archivo no se puede abrir o no es un PDF válido.
    Retorna QImage (seguro en cualquier hilo) — convertir a QPixmap en el GUI thread.
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
        return qimg.copy()   # QImage — seguro en cualquier hilo
    except Exception:
        return None


def make_placeholder_pixmap(width: int, height: int) -> QPixmap:
    """Crea un QPixmap placeholder gris para usar mientras se genera el thumbnail.

    Fondo #2A2A33 con borde #444454.
    """
    pix = QPixmap(width, height)
    pix.fill(QColor("#2A2A33"))
    painter = QPainter(pix)
    pen = QPen(QColor("#444454"))
    pen.setWidth(1)
    painter.setPen(pen)
    painter.drawRect(0, 0, width - 1, height - 1)
    painter.end()
    return pix


class ThumbnailLoader(QObject):
    """Cargador asíncrono de thumbnails PDF.

    Signals:
        ready(str, QImage | None): Emitida con (path, image) cuando termina.
            image es None si el archivo no se pudo procesar.
            Convertir a QPixmap en el slot receptor (GUI thread).
    """

    ready = pyqtSignal(str, object)  # (path, QImage | None)

    def __init__(self, pdf_path: str, width: int = 72) -> None:
        super().__init__()
        self._pdf_path = pdf_path
        self._width = width

    def run(self) -> None:
        pix = make_pdf_thumb(self._pdf_path, self._width)
        self.ready.emit(self._pdf_path, pix)
