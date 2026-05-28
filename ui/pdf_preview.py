"""
Vista previa interactiva del PDF con firma arrastrable.

Mejoras vs versión anterior:
  - El fitInView se hace una sola vez al cargar, no en cada resize.
  - Controles de zoom expuestos (zoomIn, zoomOut, fitToView, actualSize).
  - Manejo robusto del estado de selección y handles siempre visibles.
"""
from __future__ import annotations
from typing import Optional, Tuple
import math

import fitz
from PIL import Image
from PyQt6.QtCore import (
    Qt, QRectF, QPointF, pyqtSignal,
)
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QColor, QBrush, QCursor,
)
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsPixmapItem, QGraphicsObject, QGraphicsDropShadowEffect,
)


PREVIEW_DPI = 144


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


# ====================================================================== #
#  Item de firma con handles
# ====================================================================== #

class SignatureItem(QGraphicsObject):
    HANDLE_SIZE = 11
    ROTATE_HANDLE_OFFSET = 28

    geometryChanged = pyqtSignal()

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        target_w = 220
        ratio = pixmap.height() / max(1, pixmap.width())
        self._w = float(target_w)
        self._h = float(target_w * ratio)

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(10)

        self._action: Optional[str] = None
        self._start_pos = QPointF()
        self._start_w = self._w
        self._start_h = self._h
        self._start_angle = 0.0

        self.setTransformOriginPoint(self._w / 2, self._h / 2)

    def boundingRect(self) -> QRectF:
        m = self.HANDLE_SIZE + self.ROTATE_HANDLE_OFFSET + 6
        return QRectF(-m, -m, self._w + 2 * m, self._h + 2 * m)

    def signatureRect(self) -> QRectF:
        return QRectF(0, 0, self._w, self._h)

    def width(self) -> float:
        return self._w

    def height(self) -> float:
        return self._h

    def setSize(self, w: float, h: float) -> None:
        self.prepareGeometryChange()
        self._w = max(20.0, w)
        self._h = max(10.0, h)
        self.setTransformOriginPoint(self._w / 2, self._h / 2)
        self.geometryChanged.emit()
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        target = self.signatureRect()
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))

        # Borde fino con acento
        pen = QPen(QColor(94, 106, 210, 200), 1.4)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(target)

        self._draw_handles(painter)

    def _handle_rects(self) -> dict:
        s = self.HANDLE_SIZE
        half = s / 2
        r = self.signatureRect()
        return {
            "resize-tl": QRectF(r.left() - half, r.top() - half, s, s),
            "resize-tr": QRectF(r.right() - half, r.top() - half, s, s),
            "resize-bl": QRectF(r.left() - half, r.bottom() - half, s, s),
            "resize-br": QRectF(r.right() - half, r.bottom() - half, s, s),
            "rotate": QRectF(
                r.center().x() - half,
                r.top() - self.ROTATE_HANDLE_OFFSET - half,
                s, s,
            ),
        }

    def _draw_handles(self, painter: QPainter) -> None:
        accent = QColor(94, 106, 210)

        for name, rect in self._handle_rects().items():
            if name == "rotate":
                painter.setPen(QPen(accent, 1.2))
                painter.drawLine(
                    QPointF(rect.center().x(), rect.center().y() + self.HANDLE_SIZE / 2),
                    QPointF(rect.center().x(), self.signatureRect().top()),
                )
                painter.setPen(QPen(QColor(255, 255, 255), 1.5))
                painter.setBrush(QBrush(accent))
                painter.drawEllipse(rect)
            else:
                painter.setPen(QPen(accent, 1.5))
                painter.setBrush(QBrush(QColor(255, 255, 255)))
                painter.drawRect(rect)

    def hoverMoveEvent(self, event) -> None:
        handle = self._handle_at(event.pos())
        if handle == "rotate":
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        elif handle in ("resize-tl", "resize-br"):
            self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
        elif handle in ("resize-tr", "resize-bl"):
            self.setCursor(QCursor(Qt.CursorShape.SizeBDiagCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        super().hoverMoveEvent(event)

    def _handle_at(self, pos: QPointF) -> Optional[str]:
        for name, rect in self._handle_rects().items():
            if rect.contains(pos):
                return name
        return None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._handle_at(event.pos())
            if handle:
                self._action = handle
                self._start_pos = event.scenePos()
                self._start_w = self._w
                self._start_h = self._h
                self._start_angle = self.rotation()
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._action:
            if self._action == "rotate":
                self._do_rotate(event.scenePos())
            else:
                self._do_resize(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)
        self.geometryChanged.emit()

    def mouseReleaseEvent(self, event) -> None:
        if self._action:
            self._action = None
            self.geometryChanged.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self.geometryChanged.emit()

    def _do_resize(self, scene_pos: QPointF) -> None:
        local = self.mapFromScene(scene_pos)
        cx, cy = self._w / 2, self._h / 2
        dx = abs(local.x() - cx) * 2
        dy = abs(local.y() - cy) * 2
        ratio = self._start_h / max(1.0, self._start_w)
        if dx / max(1, self._start_w) > dy / max(1, self._start_h):
            new_w = max(40.0, dx)
            new_h = new_w * ratio
        else:
            new_h = max(20.0, dy)
            new_w = new_h / max(0.01, ratio)
        old_center = self.mapToScene(QPointF(self._w / 2, self._h / 2))
        self.setSize(new_w, new_h)
        new_center = self.mapToScene(QPointF(self._w / 2, self._h / 2))
        self.setPos(self.pos() + (old_center - new_center))

    def _do_rotate(self, scene_pos: QPointF) -> None:
        center = self.mapToScene(QPointF(self._w / 2, self._h / 2))
        dx = scene_pos.x() - center.x()
        dy = scene_pos.y() - center.y()
        angle = math.degrees(math.atan2(dy, dx)) + 90
        angle = round(angle, 1)
        if abs(angle) < 1.5:
            angle = 0.0
        self.setRotation(angle)
        self.geometryChanged.emit()


# ====================================================================== #
#  Vista previa
# ====================================================================== #

class PdfPreviewView(QGraphicsView):
    placementChanged = pyqtSignal()
    pageChanged = pyqtSignal(int, int)  # current, total

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.TextAntialiasing
        )
        self.setBackgroundBrush(QBrush(QColor("#111114")))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)

        self._doc: Optional[fitz.Document] = None
        self._pdf_path: Optional[str] = None
        self._page_index: int = 0
        self._page_pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._signature_item: Optional[SignatureItem] = None
        self._stored_signature_pix: Optional[QPixmap] = None

        self._scene_to_pdf: float = 72.0 / PREVIEW_DPI
        self._page_w_pt: float = 0.0
        self._page_h_pt: float = 0.0

        self._has_fit_once: bool = False

    # ---- Carga ----
    def load_pdf(self, path: str) -> None:
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
        self._doc = fitz.open(path)
        self._pdf_path = path
        self._page_index = 0
        self._has_fit_once = False
        self._render_page()

    def set_page(self, idx: int) -> None:
        if self._doc is None:
            return
        idx = max(0, min(idx, self._doc.page_count - 1))
        if idx == self._page_index:
            return
        self._page_index = idx
        self._render_page(preserve_signature=True)

    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    def current_page(self) -> int:
        return self._page_index

    def _render_page(self, preserve_signature: bool = False) -> None:
        if self._doc is None:
            return

        sig_state: Optional[Tuple[float, float, float, float, float]] = None
        if preserve_signature and self._signature_item is not None and self._page_w_pt > 0:
            cx_pt, cy_pt = self.signature_center_pdf()
            w_pt = self._signature_item.width() * self._scene_to_pdf
            h_pt = self._signature_item.height() * self._scene_to_pdf
            sig_state = (
                cx_pt / self._page_w_pt,
                cy_pt / self._page_h_pt,
                w_pt, h_pt,
                self._signature_item.rotation(),
            )

        self._scene.clear()
        self._page_pixmap_item = None
        self._signature_item = None

        page = self._doc[self._page_index]
        mat = fitz.Matrix(PREVIEW_DPI / 72.0, PREVIEW_DPI / 72.0)
        pm = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples).convert("RGBA")
        pix = pil_to_qpixmap(img)

        self._page_pixmap_item = QGraphicsPixmapItem(pix)
        self._page_pixmap_item.setZValue(0)
        # Sombra sutil
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 130))
        shadow.setOffset(0, 6)
        self._page_pixmap_item.setGraphicsEffect(shadow)
        self._scene.addItem(self._page_pixmap_item)

        self._page_w_pt = page.rect.width
        self._page_h_pt = page.rect.height
        # Margen alrededor de la página para que la sombra no se corte
        margin = 40
        self._scene.setSceneRect(
            QRectF(-margin, -margin, pix.width() + 2 * margin, pix.height() + 2 * margin)
        )

        if sig_state and self._stored_signature_pix is not None:
            nx, ny, w_pt, h_pt, rot = sig_state
            self.set_signature(self._stored_signature_pix)
            assert self._signature_item is not None
            w_sc = w_pt / self._scene_to_pdf
            h_sc = h_pt / self._scene_to_pdf
            self._signature_item.setSize(w_sc, h_sc)
            cx_sc = nx * pix.width()
            cy_sc = ny * pix.height()
            self._signature_item.setPos(cx_sc - w_sc / 2, cy_sc - h_sc / 2)
            self._signature_item.setRotation(rot)

        if not self._has_fit_once:
            self.fit_to_view()
            self._has_fit_once = True

        self.pageChanged.emit(self._page_index, self.page_count())

    # ---- Firma ----
    def set_signature(self, pixmap: QPixmap) -> None:
        if self._signature_item is not None:
            self._scene.removeItem(self._signature_item)
            self._signature_item = None

        if pixmap.isNull():
            return

        self._stored_signature_pix = pixmap
        item = SignatureItem(pixmap)
        self._scene.addItem(item)

        if self._page_pixmap_item is not None:
            page_rect = self._page_pixmap_item.boundingRect()
            init_x = page_rect.width() * 0.62
            init_y = page_rect.height() * 0.82
            item.setPos(init_x, init_y)

        item.geometryChanged.connect(self.placementChanged.emit)
        self._signature_item = item
        self.placementChanged.emit()

    def clear_signature(self) -> None:
        """Elimina la firma del canvas y borra la referencia almacenada."""
        if self._signature_item is not None:
            self._scene.removeItem(self._signature_item)
            self._signature_item = None
        self._stored_signature_pix = None
        self.placementChanged.emit()

    def has_signature(self) -> bool:
        return self._signature_item is not None

    # ---- Conversión ----
    def signature_center_pdf(self) -> Tuple[float, float]:
        if self._signature_item is None:
            return 0.0, 0.0
        item = self._signature_item
        center_local = QPointF(item.width() / 2, item.height() / 2)
        center_scene = item.mapToScene(center_local)
        return (
            center_scene.x() * self._scene_to_pdf,
            center_scene.y() * self._scene_to_pdf,
        )

    def signature_size_pdf(self) -> Tuple[float, float]:
        if self._signature_item is None:
            return 0.0, 0.0
        return (
            self._signature_item.width() * self._scene_to_pdf,
            self._signature_item.height() * self._scene_to_pdf,
        )

    def signature_angle(self) -> float:
        if self._signature_item is None:
            return 0.0
        return -self._signature_item.rotation()

    def signature_center_normalized(self) -> Tuple[float, float]:
        if self._page_w_pt <= 0 or self._page_h_pt <= 0:
            return 0.5, 0.5
        cx, cy = self.signature_center_pdf()
        return cx / self._page_w_pt, cy / self._page_h_pt

    def page_size_pt(self) -> Tuple[float, float]:
        return self._page_w_pt, self._page_h_pt

    # ---- Zoom público ----
    def fit_to_view(self) -> None:
        if self._page_pixmap_item is not None:
            self.fitInView(
                self._page_pixmap_item.sceneBoundingRect(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )

    def zoom_in(self) -> None:
        self.scale(1.2, 1.2)

    def zoom_out(self) -> None:
        self.scale(1 / 1.2, 1 / 1.2)

    def actual_size(self) -> None:
        self.resetTransform()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Primera vez visible: ajustar
        if not self._has_fit_once and self._page_pixmap_item is not None:
            self.fit_to_view()
            self._has_fit_once = True
