"""
Vista previa interactiva del PDF con soporte multi-firma.

Cambios v3:
  - Múltiples SignatureItem simultáneos, cada uno con color propio.
  - set_page() no destruye los items del canvas (solo actualiza el pixmap).
  - load_pdf() limpia todo el canvas (incluyendo firmas).
  - API backward-compat: set_signature/clear_signature/has_signature/
    restore_signature_placement/signature_center_* siguen funcionando
    exactamente igual (usados por foleador y main_window legacy).
  - Nueva API multi-sig: add_sig / remove_sig / clear_all_sigs /
    set_active_uid / restore_placement / placement_of.
  - Señales: placementChanged() ← backward compat (sin uid);
             sig_placement_changed(str uid) ← nueva;
             item_activated(str uid) ← click del usuario sobre un item.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import math

import fitz
from PIL import Image
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QColor, QBrush, QCursor,
)
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsPixmapItem, QGraphicsObject, QGraphicsDropShadowEffect,
)

from core.safe_zone import Placement, fit_placement_inside_page


PREVIEW_DPI = 144

# Máximo de píxeles en el lado largo del canvas de preview.
# Para páginas inusualmente grandes (scans a alta resolución) el DPI se reduce
# para mantenerse dentro de este límite y evitar imágenes de cientos de MB.
_PREVIEW_MAX_LONG_PX = 2000


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


# ====================================================================== #
#  Item de firma con handles, color propio y estado activo/inactivo
# ====================================================================== #

class SignatureItem(QGraphicsObject):
    # Handles circulares: radio en px (espacio local)
    HANDLE_RADIUS = 7
    # Distancia del handle de rotación por encima del borde superior
    ROTATE_HANDLE_OFFSET = 36

    geometryChanged = pyqtSignal()
    activated  = pyqtSignal()   # click sobre item inactivo → activarlo
    dragStarted  = pyqtSignal()   # inicio de move o resize
    dragFinished = pyqtSignal()   # fin de move o resize (mouse release)

    def __init__(self, uid: str, pixmap: QPixmap, color: QColor, parent=None):
        super().__init__(parent)
        self._uid = uid
        self._pixmap = pixmap
        self._color = color
        self._active: bool = False

        # Tamaño inicial provisional; PdfPreviewView.add_sig() ajusta al PDF real
        target_w = 220
        ratio = pixmap.height() / max(1, pixmap.width())
        self._w = float(target_w)
        self._h = float(target_w * ratio)

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(5)

        self._action: Optional[str] = None
        self._start_pos = QPointF()
        self._start_w = self._w
        self._start_h = self._h
        self._start_angle = 0.0
        # Pivot para resize: esquina opuesta en espacio local y de escena
        self._pivot_local = QPointF()
        self._resize_pivot_scene = QPointF()

        self.setTransformOriginPoint(self._w / 2, self._h / 2)

    # ------------------------------------------------------------------ #
    # Estado
    # ------------------------------------------------------------------ #

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self.setZValue(10 if active else 5)
        self.update()

    def set_pixmap(self, pixmap) -> None:
        """Actualiza la imagen de la firma sin mover ni redimensionar el ítem."""
        self._pixmap = pixmap
        self.update()

    def uid(self) -> str:
        return self._uid

    # ------------------------------------------------------------------ #
    # Geometría
    # ------------------------------------------------------------------ #

    def boundingRect(self) -> QRectF:
        m = self.HANDLE_RADIUS + self.ROTATE_HANDLE_OFFSET + 10
        return QRectF(-m, -m, self._w + 2 * m, self._h + 2 * m)

    def signatureRect(self) -> QRectF:
        return QRectF(0, 0, self._w, self._h)

    def width(self) -> float:
        return self._w

    def height(self) -> float:
        return self._h

    def setSize(self, w: float, h: float) -> None:
        self.prepareGeometryChange()
        # El mínimo interactivo se aplica en _do_resize(). Aquí permitimos
        # tamaños menores para poder encajar firmas en páginas inusualmente
        # pequeñas durante una restauración o un cambio de página.
        self._w = max(1e-3, w)
        self._h = max(1e-3, h)
        self.setTransformOriginPoint(self._w / 2, self._h / 2)
        self.update()

    # ------------------------------------------------------------------ #
    # Posiciones de handles (en espacio local)
    # ------------------------------------------------------------------ #

    def _corner_centers(self) -> dict:
        """Centros de los 4 handles de esquina."""
        return {
            "resize-tl": QPointF(0.0,       0.0),
            "resize-tr": QPointF(self._w,    0.0),
            "resize-bl": QPointF(0.0,        self._h),
            "resize-br": QPointF(self._w,    self._h),
        }

    def _rotate_center(self) -> QPointF:
        return QPointF(self._w / 2, -self.ROTATE_HANDLE_OFFSET)

    # ------------------------------------------------------------------ #
    # Pintura
    # ------------------------------------------------------------------ #

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        target = self.signatureRect()
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))

        if self._active:
            pen = QPen(self._color, 2.0)
            pen.setStyle(Qt.PenStyle.SolidLine)
        else:
            faded = QColor(self._color.red(), self._color.green(),
                           self._color.blue(), 70)
            pen = QPen(faded, 1.0)
            pen.setStyle(Qt.PenStyle.DashLine)

        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(target)

        if self._active:
            self._draw_handles(painter)

    def _draw_handles(self, painter: QPainter) -> None:
        R = self.HANDLE_RADIUS
        c = self._color
        white = QColor(248, 248, 252)

        # ── Línea punteada al handle de rotación ──────────────────────
        rot_c = self._rotate_center()
        painter.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 160), 1.0,
                            Qt.PenStyle.DotLine))
        painter.drawLine(QPointF(self._w / 2, 0), rot_c)

        # ── Handle de rotación (círculo con arco ↻) ───────────────────
        # Sombra
        shadow_c = QColor(0, 0, 0, 55)
        painter.setPen(QPen(shadow_c, 2.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rot_c, R + 1.5, R + 1.5)
        # Relleno oscuro
        painter.setPen(QPen(c, 1.5))
        painter.setBrush(QBrush(QColor(22, 22, 30, 230)))
        painter.drawEllipse(rot_c, R, R)
        # Arco ↻ interior
        arc_r = R * 0.58
        arc_rect = QRectF(rot_c.x() - arc_r, rot_c.y() - arc_r, arc_r * 2, arc_r * 2)
        painter.setPen(QPen(c, 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(arc_rect, 20 * 16, 290 * 16)
        # Punta de flecha (triángulo pequeño)
        tip_angle = math.radians(20 - 10)
        tx = rot_c.x() + arc_r * math.cos(tip_angle)
        ty = rot_c.y() - arc_r * math.sin(tip_angle)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(c))
        tip_size = arc_r * 0.55
        painter.drawPolygon([
            QPointF(tx, ty),
            QPointF(tx - tip_size, ty - tip_size * 0.5),
            QPointF(tx - tip_size * 0.5, ty + tip_size),
        ])

        # ── Handles de esquina (círculos premium) ─────────────────────
        for center in self._corner_centers().values():
            # Sombra exterior
            painter.setPen(QPen(QColor(0, 0, 0, 50), 2.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, R + 1.5, R + 1.5)
            # Círculo blanco
            painter.setPen(QPen(c, 1.5))
            painter.setBrush(QBrush(white))
            painter.drawEllipse(center, R, R)
            # Punto interior del color de la firma
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(c))
            painter.drawEllipse(center, R * 0.38, R * 0.38)

    # ------------------------------------------------------------------ #
    # Detección de handle
    # ------------------------------------------------------------------ #

    def _handle_at(self, pos: QPointF) -> Optional[str]:
        R = self.HANDLE_RADIUS + 5   # zona de hit generosa
        rc = self._rotate_center()
        dx, dy = pos.x() - rc.x(), pos.y() - rc.y()
        if dx * dx + dy * dy <= R * R * 1.6:
            return "rotate"
        for name, center in self._corner_centers().items():
            dx, dy = pos.x() - center.x(), pos.y() - center.y()
            if dx * dx + dy * dy <= R * R * 1.6:
                return name
        return None

    # ------------------------------------------------------------------ #
    # Hover
    # ------------------------------------------------------------------ #

    def hoverMoveEvent(self, event) -> None:
        if not self._active:
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            super().hoverMoveEvent(event)
            return
        handle = self._handle_at(event.pos())
        if handle == "rotate":
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        elif handle in ("resize-tl", "resize-br"):
            self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
        elif handle in ("resize-tr", "resize-bl"):
            self.setCursor(QCursor(Qt.CursorShape.SizeBDiagCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    # ------------------------------------------------------------------ #
    # Mouse
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._active:
                self.activated.emit()
                super().mousePressEvent(event)
                return
            handle = self._handle_at(event.pos())
            if handle:
                self._action = handle
                self._start_pos = event.scenePos()
                self._start_w = self._w
                self._start_h = self._h
                self._start_angle = self.rotation()

                if handle in ("resize-tl", "resize-tr", "resize-bl", "resize-br"):
                    _pivot_map = {
                        "resize-tl": QPointF(self._w,  self._h),   # br
                        "resize-tr": QPointF(0.0,       self._h),   # bl
                        "resize-bl": QPointF(self._w,  0.0),        # tr
                        "resize-br": QPointF(0.0,       0.0),       # tl
                    }
                    self._pivot_local = _pivot_map[handle]
                    self._resize_pivot_scene = self.mapToScene(self._pivot_local)

                self.dragStarted.emit()
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
            self.dragFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self.geometryChanged.emit()

    # ------------------------------------------------------------------ #
    # Resize con esquina opuesta fija
    # ------------------------------------------------------------------ #

    def _do_resize(self, scene_pos: QPointF) -> None:
        """Redimensiona manteniendo la esquina opuesta (pivot) anclada en escena.

        Algoritmo de proyección diagonal
        ---------------------------------
        El bug clásico de los resize "trabados" viene de elegir el eje dominante
        (X o Y) mediante una condición `if dx/w >= dy/h`.  Cuando el cursor cruza
        esa frontera, el eje cambia de golpe y el tamaño da un salto brusco.

        Solución: proyectar el vector cursor→pivot sobre la diagonal del item
        (la línea que une las dos esquinas opuestas en espacio local).  Eso da
        un factor de escala continuo y diferenciable — sin axis-switching, sin
        saltos.

        Invariante geométrico
        ---------------------
        Tras el resize, la esquina opuesta al handle (pivot) debe estar exactamente
        en la misma posición de escena que tenía al iniciar el drag.  Se corrige la
        posición del item después de setSize() para mantener ese invariante.
        """
        if self._start_w <= 0 or self._start_h <= 0:
            return

        # Cursor en coordenadas LOCALES del item (mapFromScene ya aplica rotación)
        local = self.mapFromScene(scene_pos)
        pivot = self._pivot_local

        # Esquina que se está arrastrando en el momento del press (espacio local)
        _start_handle_map = {
            "resize-tl": QPointF(0.0,           0.0),
            "resize-tr": QPointF(self._start_w,  0.0),
            "resize-bl": QPointF(0.0,            self._start_h),
            "resize-br": QPointF(self._start_w,  self._start_h),
        }
        start_handle = _start_handle_map[self._action]

        # Vector diagonal: del pivot hacia la esquina del handle (al inicio)
        dir_x = start_handle.x() - pivot.x()
        dir_y = start_handle.y() - pivot.y()
        diag_sq = dir_x * dir_x + dir_y * dir_y
        if diag_sq < 1.0:
            return
        diag_len = math.sqrt(diag_sq)   # == sqrt(w²+h²) en todos los casos

        # Proyección escalar del cursor (relativo al pivot) sobre la diagonal.
        # Esto da cuánto "avanzó" el cursor en la dirección del resize.
        cur_x = local.x() - pivot.x()
        cur_y = local.y() - pivot.y()
        proj = (cur_x * dir_x + cur_y * dir_y) / diag_len

        # No permitir inversión (cursor cruzó el pivot): proj mínimo = 0
        proj = max(0.0, proj)

        # Factor de escala: cuánto avanzó el cursor respecto a la posición inicial
        scale = proj / diag_len   # == 1.0 cuando el cursor está en la esquina inicial

        # Tamaño mínimo: al menos MIN_W × MIN_H px en el canvas
        MIN_W, MIN_H = 16.0, 6.0
        min_scale = max(MIN_W / self._start_w, MIN_H / self._start_h)
        scale = max(scale, min_scale)

        new_w = self._start_w * scale
        new_h = self._start_h * scale

        self.setSize(new_w, new_h)

        # ── Reanclar el pivot ──────────────────────────────────────────────
        # Después de setSize(), el transform-origin cambió al nuevo centro.
        # Calculamos dónde quedó el pivot en escena y corregimos la posición
        # del item para devolverlo a _resize_pivot_scene.
        _new_pivot_map = {
            "resize-tl": QPointF(self._w,  self._h),
            "resize-tr": QPointF(0.0,       self._h),
            "resize-bl": QPointF(self._w,  0.0),
            "resize-br": QPointF(0.0,       0.0),
        }
        new_pivot_scene = self.mapToScene(_new_pivot_map[self._action])
        delta = self._resize_pivot_scene - new_pivot_scene
        self.setPos(self.pos() + delta)
        self.geometryChanged.emit()

    # ------------------------------------------------------------------ #
    # Rotación
    # ------------------------------------------------------------------ #

    def _do_rotate(self, scene_pos: QPointF) -> None:
        center = self.mapToScene(QPointF(self._w / 2, self._h / 2))
        dx = scene_pos.x() - center.x()
        dy = scene_pos.y() - center.y()
        angle = math.degrees(math.atan2(dy, dx)) + 90

        # Snap magnético a 0°, 90°, 180°, 270° con zona de ±3°
        # (facilita alinear la firma exactamente horizontal o vertical)
        SNAP_TARGETS = (0.0, 90.0, 180.0, 270.0, 360.0, -90.0, -180.0, -270.0)
        SNAP_ZONE = 3.0
        for t in SNAP_TARGETS:
            if abs(angle - t) < SNAP_ZONE:
                angle = 0.0 if t in (0.0, 360.0, -360.0) else t % 360
                break
        else:
            angle = round(angle, 1)

        self.setRotation(angle)
        self.geometryChanged.emit()


# ====================================================================== #
#  Vista previa
# ====================================================================== #

class PdfPreviewView(QGraphicsView):

    # ── Señales ──────────────────────────────────────────────────────── #
    # Backward compat: emitida para cualquier cambio (sin uid)
    placementChanged = pyqtSignal()
    # Nueva: emitida con el uid de la firma que cambió
    sig_placement_changed = pyqtSignal(str)
    # Emitida cuando el usuario hace click sobre una firma (para sincronizar lista)
    item_activated = pyqtSignal(str)
    # Emitidas al inicio y fin de un drag (mover o redimensionar).
    # Permiten a herramientas como el foleador diferir cálculos costosos
    # hasta que el usuario suelte el ratón, evitando lag durante el arrastre.
    drag_started = pyqtSignal()
    drag_finished = pyqtSignal()
    # Cambio de página
    pageChanged = pyqtSignal(int, int)   # current, total

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

        # Multi-sig state
        self._sig_items: Dict[str, SignatureItem] = {}
        self._configured_placements: Dict[
            str, Tuple[float, float, float, float, float]
        ] = {}
        self._active_uid: Optional[str] = None
        self._restoring: bool = False   # bloquea emision de señales durante restore

        self._scene_to_pdf: float = 72.0 / PREVIEW_DPI
        self._page_w_pt: float = 0.0
        self._page_h_pt: float = 0.0
        self._has_fit_once: bool = False

    # ==================================================================== #
    # API de carga de documentos
    # ==================================================================== #

    def load_pdf(self, path: str) -> None:
        """Carga un nuevo PDF. Limpia TODOS los items del canvas (página + firmas)."""
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass

        # Limpiar firmas sin emitir señales
        self._sig_items.clear()
        self._configured_placements.clear()
        self._active_uid = None

        self._doc = fitz.open(path)
        self._pdf_path = path
        self._page_index = 0
        self._has_fit_once = False

        self._scene.clear()
        self._page_pixmap_item = None

        self._render_page()

    def set_page(self, idx: int) -> None:
        """Cambia a otra página SIN destruir los items de firma en el canvas."""
        if not self._doc:
            return
        idx = max(0, min(idx, self._doc.page_count - 1))
        if idx == self._page_index:
            return
        placements = {
            uid: self.configured_placement_of(uid)
            for uid in self._sig_items
        }
        self._page_index = idx
        self._update_page_pixmap()
        for uid, placement in placements.items():
            if placement is not None:
                self._apply_placement(uid, *placement, update_configured=False)
        self.pageChanged.emit(self._page_index, self.page_count())

    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    def current_page(self) -> int:
        return self._page_index

    def page_size_pt(self) -> Tuple[float, float]:
        return self._page_w_pt, self._page_h_pt

    # ==================================================================== #
    # API multi-firma (nueva)
    # ==================================================================== #

    def add_sig(self, uid: str, pixmap: QPixmap, color: QColor) -> None:
        """Agrega una firma al canvas en posición por defecto (zona inferior).

        El tamaño inicial es proporcional al ancho del PDF activo (~22 %),
        de modo que sea consistente entre documentos de distintos formatos.
        """
        if uid in self._sig_items:
            self.remove_sig(uid)

        item = SignatureItem(uid, pixmap, color)
        item.geometryChanged.connect(lambda _uid=uid: self._on_item_geometry_changed(_uid))
        item.activated.connect(lambda _uid=uid: self._on_item_activated(_uid))
        # Propagar drag_started / drag_finished para que herramientas externas
        # puedan diferir cálculos costosos hasta que el usuario suelte el ratón.
        item.dragStarted.connect(self.drag_started)
        item.dragFinished.connect(self.drag_finished)

        # ── Tamaño inicial proporcional al PDF ─────────────────────────
        if self._page_w_pt > 0:
            # ~22 % del ancho del PDF en puntos, convertido a pixels del canvas
            target_w_pt = max(60.0, self._page_w_pt * 0.22)
            target_w_sc = target_w_pt / self._scene_to_pdf
            ratio = pixmap.height() / max(1, pixmap.width())
            item.setSize(target_w_sc, target_w_sc * ratio)

        if self._page_pixmap_item is not None:
            pr = self._page_pixmap_item.boundingRect()
            item.setPos(
                pr.width() * 0.5 - item.width() / 2,
                pr.height() * 0.82 - item.height() / 2,
            )

        self._scene.addItem(item)
        self._sig_items[uid] = item
        self._constrain_item_to_page(uid)
        placement = self.placement_of(uid)
        if placement is not None:
            self._configured_placements[uid] = placement

        if len(self._sig_items) == 1:
            self.set_active_uid(uid)

    def remove_sig(self, uid: str) -> None:
        """Elimina una firma del canvas."""
        item = self._sig_items.pop(uid, None)
        if item is not None and item.scene() == self._scene:
            self._scene.removeItem(item)
        self._configured_placements.pop(uid, None)
        if self._active_uid == uid:
            self._active_uid = None

    def update_sig_pixmap(self, uid: str, pixmap) -> None:
        """Actualiza la imagen de una firma existente en el canvas (mantiene posición y tamaño)."""
        item = self._sig_items.get(uid)
        if item is not None:
            item.set_pixmap(pixmap)

    def clear_all_sigs(self) -> None:
        """Elimina todas las firmas del canvas."""
        for uid in list(self._sig_items.keys()):
            self.remove_sig(uid)
        self._active_uid = None

    def clear_page(self) -> None:
        """Limpia la escena completamente: página y todas las firmas."""
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None
        self._pdf_path = None
        self._page_index = 0
        self._page_pixmap_item = None
        self._sig_items.clear()
        self._configured_placements.clear()
        self._active_uid = None
        self._page_w_pt = 0.0
        self._page_h_pt = 0.0
        self._has_fit_once = False
        self._scene.clear()

    def set_active_uid(self, uid: Optional[str]) -> None:
        """Selecciona la firma activa (borde sólido + handles visibles)."""
        self._active_uid = uid
        for u, item in self._sig_items.items():
            item.set_active(u == uid)

    def restore_placement(
        self,
        uid: str,
        cx_norm: float,
        cy_norm: float,
        w_pt: float,
        h_pt: float,
        angle: float,
    ) -> None:
        """Posiciona programáticamente una firma; NO emite señales de cambio."""
        self._apply_placement(
            uid, cx_norm, cy_norm, w_pt, h_pt, angle, update_configured=True
        )

    def _apply_placement(
        self,
        uid: str,
        cx_norm: float,
        cy_norm: float,
        w_pt: float,
        h_pt: float,
        angle: float,
        update_configured: bool,
    ) -> None:
        item = self._sig_items.get(uid)
        if item is None or self._page_pixmap_item is None:
            return
        pix = self._page_pixmap_item.pixmap()
        if pix.width() == 0 or pix.height() == 0:
            return

        was_restoring = self._restoring
        self._restoring = True
        try:
            w_sc = w_pt / self._scene_to_pdf
            h_sc = h_pt / self._scene_to_pdf
            item.setSize(w_sc, h_sc)
            cx_sc = cx_norm * pix.width()
            cy_sc = cy_norm * pix.height()
            item.setPos(cx_sc - w_sc / 2, cy_sc - h_sc / 2)
            item.setRotation(-angle)
            self._constrain_item_to_page(uid)
            if update_configured:
                placement = self.placement_of(uid)
                if placement is not None:
                    self._configured_placements[uid] = placement
        finally:
            self._restoring = was_restoring

    def placement_of(
        self, uid: str
    ) -> Optional[Tuple[float, float, float, float, float]]:
        """Devuelve (cx_norm, cy_norm, w_pt, h_pt, angle) de una firma, o None."""
        item = self._sig_items.get(uid)
        if item is None or self._page_pixmap_item is None:
            return None
        pix = self._page_pixmap_item.pixmap()
        if pix.width() == 0 or pix.height() == 0:
            return None

        center_local = QPointF(item.width() / 2, item.height() / 2)
        center_scene = item.mapToScene(center_local)
        cx_n = center_scene.x() / pix.width()
        cy_n = center_scene.y() / pix.height()
        w_pt = item.width() * self._scene_to_pdf
        h_pt = item.height() * self._scene_to_pdf
        angle = -item.rotation()
        return (cx_n, cy_n, w_pt, h_pt, angle)

    def configured_placement_of(
        self, uid: str
    ) -> Optional[Tuple[float, float, float, float, float]]:
        """Devuelve la preferencia estable, sin ajustes temporales por página."""
        return self._configured_placements.get(uid) or self.placement_of(uid)

    def sig_uids(self) -> List[str]:
        return list(self._sig_items.keys())

    def has_sigs(self) -> bool:
        return bool(self._sig_items)

    def placement_fits_page(self, uid: str) -> bool:
        """Indica si el bbox rotado de una firma está dentro de la página."""
        p = self.placement_of(uid)
        if p is None or self._page_w_pt <= 0 or self._page_h_pt <= 0:
            return False
        cx_n, cy_n, w_pt, h_pt, angle = p
        placement = Placement(
            x=cx_n * self._page_w_pt,
            y=cy_n * self._page_h_pt,
            width=w_pt,
            height=h_pt,
            angle=angle,
        )
        bbox = placement.rotated_bbox
        tolerance = 1e-6
        return (
            bbox.x0 >= -tolerance
            and bbox.y0 >= -tolerance
            and bbox.x1 <= self._page_w_pt + tolerance
            and bbox.y1 <= self._page_h_pt + tolerance
        )

    # ==================================================================== #
    # API backward-compat (foleador, main_window legacy)
    # ==================================================================== #

    def set_signature(self, pixmap: QPixmap) -> None:
        """Backward-compat: gestiona una sola firma con uid '_single'."""
        self.remove_sig("_single")
        if not pixmap.isNull():
            self.add_sig("_single", pixmap, QColor(94, 106, 210))
            self.set_active_uid("_single")
        self.placementChanged.emit()

    def clear_signature(self) -> None:
        self.remove_sig("_single")
        self.placementChanged.emit()

    def has_signature(self) -> bool:
        return "_single" in self._sig_items

    def restore_signature_placement(
        self,
        cx_norm: float,
        cy_norm: float,
        w_pt: float,
        h_pt: float,
        angle: float,
    ) -> None:
        if "_single" in self._sig_items:
            self.restore_placement("_single", cx_norm, cy_norm, w_pt, h_pt, angle)

    def signature_center_pdf(self) -> Tuple[float, float]:
        p = self.placement_of("_single")
        if not p:
            return (0.0, 0.0)
        cx_n, cy_n, _, _, _ = p
        return cx_n * self._page_w_pt, cy_n * self._page_h_pt

    def signature_size_pdf(self) -> Tuple[float, float]:
        p = self.placement_of("_single")
        if not p:
            return (0.0, 0.0)
        return p[2], p[3]

    def signature_angle(self) -> float:
        p = self.placement_of("_single")
        return p[4] if p else 0.0

    def signature_center_normalized(self) -> Tuple[float, float]:
        p = self.placement_of("_single")
        if not p:
            return (0.5, 0.5)
        return p[0], p[1]

    # ==================================================================== #
    # Zoom público
    # ==================================================================== #

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
        if not self._has_fit_once and self._page_pixmap_item is not None:
            self.fit_to_view()
            self._has_fit_once = True

    # ==================================================================== #
    # Internos
    # ==================================================================== #

    def _page_render_dpi(self, page: "fitz.Page") -> float:
        """DPI adaptativo para el canvas de posicionamiento.

        Usa PREVIEW_DPI (144) para páginas normales.  Para páginas muy grandes
        (scans o formatos inusuales) reduce el DPI para que el lado más largo
        no supere _PREVIEW_MAX_LONG_PX píxeles, evitando imágenes de cientos
        de MB que congelen la UI.

        IMPORTANTE: _scene_to_pdf debe actualizarse con 72 / dpi_usado cada
        vez que se renderiza, para que la conversión píxeles↔puntos PDF sea
        correcta y las firmas/folios aparezcan al tamaño proporcional correcto.
        """
        page_long = max(1.0, page.rect.width, page.rect.height)
        dpi = min(PREVIEW_DPI, _PREVIEW_MAX_LONG_PX * 72.0 / page_long)
        return max(36.0, dpi)

    def _render_page(self) -> None:
        """Renderiza la página actual y la agrega al canvas. No toca las firmas."""
        if not self._doc:
            return

        page = self._doc[self._page_index]
        dpi = self._page_render_dpi(page)
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pm = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples).convert("RGBA")
        pix = pil_to_qpixmap(img)

        # Actualizar la relación píxel/punto para este DPI específico.
        # Debe hacerse ANTES de que cualquier _apply_placement use el valor.
        self._scene_to_pdf = 72.0 / dpi

        self._page_pixmap_item = QGraphicsPixmapItem(pix)
        self._page_pixmap_item.setZValue(0)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 130))
        shadow.setOffset(0, 6)
        self._page_pixmap_item.setGraphicsEffect(shadow)
        self._scene.addItem(self._page_pixmap_item)

        self._page_w_pt = page.rect.width
        self._page_h_pt = page.rect.height

        self._update_scene_rect(pix)

        if not self._has_fit_once:
            self.fit_to_view()
            self._has_fit_once = True

        self.pageChanged.emit(self._page_index, self.page_count())

    def _update_page_pixmap(self) -> None:
        """Solo actualiza el pixmap de página; los items de firma se conservan."""
        if not self._doc or not self._page_pixmap_item:
            return
        page = self._doc[self._page_index]
        dpi = self._page_render_dpi(page)
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pm = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples).convert("RGBA")
        pix = pil_to_qpixmap(img)

        # Actualizar escala píxel/punto ANTES de que _apply_placement use el valor.
        self._scene_to_pdf = 72.0 / dpi

        self._page_pixmap_item.setPixmap(pix)
        self._page_w_pt = page.rect.width
        self._page_h_pt = page.rect.height
        self._update_scene_rect(pix)

    def _on_item_geometry_changed(self, uid: str) -> None:
        if self._restoring:
            return
        self._constrain_item_to_page(uid)
        placement = self.placement_of(uid)
        if placement is not None:
            self._configured_placements[uid] = placement
        self.sig_placement_changed.emit(uid)
        self.placementChanged.emit()   # backward compat

    def _on_item_activated(self, uid: str) -> None:
        self.set_active_uid(uid)
        self.item_activated.emit(uid)

    def _update_scene_rect(self, pixmap: QPixmap) -> None:
        margin = 40
        self._scene.setSceneRect(
            QRectF(
                -margin,
                -margin,
                pixmap.width() + 2 * margin,
                pixmap.height() + 2 * margin,
            )
        )

    def _constrain_item_to_page(self, uid: str) -> None:
        """Encaja una firma en el papel usando el mismo cálculo que el motor."""
        item = self._sig_items.get(uid)
        if (
            item is None
            or self._page_pixmap_item is None
            or self._page_w_pt <= 0
            or self._page_h_pt <= 0
        ):
            return
        pix = self._page_pixmap_item.pixmap()
        if pix.width() <= 0 or pix.height() <= 0:
            return

        p = self.placement_of(uid)
        if p is None:
            return
        cx_n, cy_n, w_pt, h_pt, angle = p
        desired = Placement(
            x=cx_n * self._page_w_pt,
            y=cy_n * self._page_h_pt,
            width=w_pt,
            height=h_pt,
            angle=angle,
        )
        bounded = fit_placement_inside_page(
            desired, self._page_w_pt, self._page_h_pt, margin=0.0
        )
        if not bounded.adjusted_to_page:
            return

        was_restoring = self._restoring
        self._restoring = True
        try:
            w_sc = bounded.width / self._scene_to_pdf
            h_sc = bounded.height / self._scene_to_pdf
            cx_sc = bounded.x / self._page_w_pt * pix.width()
            cy_sc = bounded.y / self._page_h_pt * pix.height()
            item.setSize(w_sc, h_sc)
            item.setPos(cx_sc - w_sc / 2, cy_sc - h_sc / 2)
            item.setRotation(-bounded.angle)
        finally:
            self._restoring = was_restoring
