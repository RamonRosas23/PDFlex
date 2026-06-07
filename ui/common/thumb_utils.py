"""Generación de thumbnails de PDFs para listas de documentos."""
from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QBrush


def make_pdf_thumb(pdf_path: str, width: int = 72) -> Optional[QImage]:
    """Renderiza la primera página del PDF como thumbnail.

    Retorna None si el archivo no se puede abrir o no es un PDF válido.
    Retorna QImage (seguro en cualquier hilo) — convertir a QPixmap en el GUI thread.
    """
    doc = None
    try:
        import fitz

        doc = fitz.open(pdf_path)
        if doc.page_count <= 0:
            return None
        if doc.is_encrypted and not doc.authenticate(""):
            return None

        page = doc[0]
        page_width = max(1.0, float(page.rect.width))
        scale = max(0.05, width / page_width)
        mat = fitz.Matrix(scale, scale)

        # Render en RGB con alpha para capturar correctamente PDFs con fondos
        # transparentes; luego se compone sobre blanco para evitar miniaturas
        # negras sobre el tema oscuro de la app.
        pm = page.get_pixmap(
            matrix=mat,
            colorspace=fitz.csRGB,
            alpha=True,
            annots=True,
        )
        if pm.width <= 0 or pm.height <= 0:
            return None

        qimg = QImage(
            pm.samples,
            pm.width,
            pm.height,
            pm.stride,
            QImage.Format.Format_RGBA8888,
        )
        if qimg.isNull():
            return None

        rendered = qimg.copy()
        canvas = QImage(
            rendered.width(),
            rendered.height(),
            QImage.Format.Format_RGB888,
        )
        canvas.fill(QColor("#FFFFFF"))

        painter = QPainter(canvas)
        painter.drawImage(0, 0, rendered)
        pen = QPen(QColor("#D5DAE5"))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRect(0, 0, canvas.width() - 1, canvas.height() - 1)
        painter.end()
        return canvas
    except Exception:
        return None
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def make_placeholder_pixmap(width: int, height: int) -> QPixmap:
    """Crea una hoja clara mientras se genera el thumbnail real."""
    pix = QPixmap(width, height)
    pix.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    margin = 3
    page_rect = pix.rect().adjusted(margin, margin, -margin, -margin)
    painter.setBrush(QBrush(QColor("#F8FAFC")))
    pen = QPen(QColor("#D5DAE5"))
    pen.setWidth(1)
    painter.setPen(pen)
    painter.drawRoundedRect(page_rect, 4, 4)

    fold = max(8, min(width, height) // 6)
    painter.setBrush(QBrush(QColor("#E9EDF5")))
    painter.setPen(QPen(QColor("#D5DAE5"), 1))
    painter.drawLine(
        page_rect.right() - fold,
        page_rect.top(),
        page_rect.right(),
        page_rect.top() + fold,
    )
    painter.drawLine(
        page_rect.right() - fold,
        page_rect.top(),
        page_rect.right() - fold,
        page_rect.top() + fold,
    )
    painter.drawLine(
        page_rect.right() - fold,
        page_rect.top() + fold,
        page_rect.right(),
        page_rect.top() + fold,
    )

    painter.setPen(QPen(QColor("#BAC3D3"), 2))
    line_left = page_rect.left() + 10
    line_right = page_rect.right() - 10
    line_top = page_rect.top() + max(20, height // 3)
    for offset, shrink in ((0, 0), (9, 6), (18, 14)):
        painter.drawLine(line_left, line_top + offset, line_right - shrink, line_top + offset)
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
