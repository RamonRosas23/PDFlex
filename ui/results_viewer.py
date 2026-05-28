"""
Visor de resultados con renderizado adaptativo al viewport.

Fix principal vs versión anterior:
  - El PDF se renderiza al DPI que mejor ajusta al ancho del viewport,
    en lugar de a un DPI fijo que se cortaba.
  - Botones de zoom (–, +, Ajustar) en la barra superior.
  - QScrollArea con widget cuyo tamaño es exactamente el del pixmap.
"""
from __future__ import annotations
from typing import List, Optional
from pathlib import Path

import fitz
from PIL import Image
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QIcon, QColor, QBrush
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QFrame, QScrollArea, QSizePolicy,
)

from core.signature_engine import JobResult


def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


# Niveles de zoom (multiplicador sobre el DPI base "fit width")
ZOOM_LEVELS = [0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 2.50, 3.00]


class ResultsViewer(QWidget):
    openInExplorer = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: List[JobResult] = []
        self._current_doc: Optional[fitz.Document] = None
        self._current_result: Optional[JobResult] = None
        self._current_page: int = 0
        self._zoom_index: int = 2  # 1.00 = ajustado al ancho
        self._fit_mode: str = "width"  # "width" o "page" o "manual"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # =========================================================
        # Panel izquierdo: documentos
        # =========================================================
        left = QFrame()
        left.setProperty("class", "Card")
        left.setFixedWidth(240)
        left_v = QVBoxLayout(left)
        left_v.setContentsMargins(14, 14, 14, 14)
        left_v.setSpacing(10)

        lbl_docs = QLabel("Documentos firmados")
        lbl_docs.setProperty("class", "CardTitle")
        left_v.addWidget(lbl_docs)

        self.doc_list = QListWidget()
        self.doc_list.itemSelectionChanged.connect(self._on_doc_selected)
        left_v.addWidget(self.doc_list, 1)

        layout.addWidget(left)

        # =========================================================
        # Panel central: vista + páginas
        # =========================================================
        center = QFrame()
        center.setProperty("class", "Card")
        center_v = QVBoxLayout(center)
        center_v.setContentsMargins(14, 14, 14, 14)
        center_v.setSpacing(12)

        # Header: título + acciones
        header = QHBoxLayout()
        header.setSpacing(8)

        self.title_label = QLabel("Selecciona un documento")
        self.title_label.setProperty("class", "CardTitle")
        header.addWidget(self.title_label)
        header.addStretch()

        self.zoom_out_btn = QPushButton("−")
        self.zoom_out_btn.setProperty("class", "IconBtn")
        self.zoom_out_btn.setToolTip("Reducir")
        self.zoom_out_btn.clicked.connect(self._zoom_out)
        self.zoom_out_btn.setEnabled(False)
        header.addWidget(self.zoom_out_btn)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setStyleSheet("color: #9094A0; min-width: 40px;")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.zoom_label)

        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setProperty("class", "IconBtn")
        self.zoom_in_btn.setToolTip("Aumentar")
        self.zoom_in_btn.clicked.connect(self._zoom_in)
        self.zoom_in_btn.setEnabled(False)
        header.addWidget(self.zoom_in_btn)

        self.fit_width_btn = QPushButton("Ajustar ancho")
        self.fit_width_btn.setProperty("class", "IconBtn")
        self.fit_width_btn.clicked.connect(self._fit_width)
        self.fit_width_btn.setEnabled(False)
        header.addWidget(self.fit_width_btn)

        self.fit_page_btn = QPushButton("Ajustar página")
        self.fit_page_btn.setProperty("class", "IconBtn")
        self.fit_page_btn.clicked.connect(self._fit_page)
        self.fit_page_btn.setEnabled(False)
        header.addWidget(self.fit_page_btn)

        self.open_btn = QPushButton("Abrir carpeta")
        self.open_btn.setProperty("class", "Ghost")
        self.open_btn.clicked.connect(self._open_in_explorer)
        self.open_btn.setEnabled(False)
        header.addWidget(self.open_btn)

        center_v.addLayout(header)

        # Body: páginas + canvas
        inner = QHBoxLayout()
        inner.setSpacing(12)

        # Lista de páginas con thumbnails
        self.page_list = QListWidget()
        self.page_list.setFixedWidth(140)
        self.page_list.setIconSize(QSize(105, 135))
        self.page_list.setSpacing(2)
        self.page_list.itemSelectionChanged.connect(self._on_page_selected)
        inner.addWidget(self.page_list)

        # Canvas con scroll
        self.scroll = QScrollArea()
        self.scroll.setObjectName("ResultCanvas")
        self.scroll.setWidgetResizable(False)  # ← NO; queremos tamaño exacto del pixmap
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.canvas = QLabel()
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setStyleSheet("background: transparent;")
        self.scroll.setWidget(self.canvas)

        inner.addWidget(self.scroll, 1)

        center_v.addLayout(inner, 1)

        # Footer con metadata
        self.meta_label = QLabel("")
        self.meta_label.setProperty("class", "CardHint")
        self.meta_label.setWordWrap(True)
        center_v.addWidget(self.meta_label)

        layout.addWidget(center, 1)

    # ================================================================== #
    # API
    # ================================================================== #
    def set_results(self, results: List[JobResult]) -> None:
        self._results = results
        self.doc_list.clear()
        for r in results:
            if r.output_path:
                name = Path(r.output_path).name
            else:
                name = "(error)"
            item = QListWidgetItem(name)
            if not r.success:
                item.setForeground(QBrush(QColor("#E5484D")))
                item.setText(f"⚠  {name}")
            self.doc_list.addItem(item)

        if results:
            self.doc_list.setCurrentRow(0)
        else:
            self.title_label.setText("No hay resultados")
            self.meta_label.setText("")
            self.canvas.clear()
            self._set_actions_enabled(False)

    def clear_results(self) -> None:
        """Cierra documentos abiertos y limpia toda la vista (para reutilizar sin bloqueo)."""
        if self._current_doc is not None:
            try:
                self._current_doc.close()
            except Exception:
                pass
            self._current_doc = None
        self._results = []
        self._current_result = None
        self._current_page = 0
        self.doc_list.clear()
        self.page_list.clear()
        self.canvas.clear()
        self.title_label.setText("Selecciona un documento")
        self.meta_label.setText("")
        self._set_actions_enabled(False)

    # ================================================================== #
    # Estado de acciones
    # ================================================================== #
    def _set_actions_enabled(self, enabled: bool) -> None:
        self.open_btn.setEnabled(enabled)
        self.zoom_in_btn.setEnabled(enabled)
        self.zoom_out_btn.setEnabled(enabled)
        self.fit_width_btn.setEnabled(enabled)
        self.fit_page_btn.setEnabled(enabled)

    # ================================================================== #
    # Handlers
    # ================================================================== #
    def _on_doc_selected(self) -> None:
        row = self.doc_list.currentRow()
        if row < 0 or row >= len(self._results):
            return
        result = self._results[row]
        self._current_result = result

        if self._current_doc is not None:
            try:
                self._current_doc.close()
            except Exception:
                pass
            self._current_doc = None

        if not result.success or not result.output_path:
            self.title_label.setText("Error en este documento")
            self.meta_label.setText(result.error or "")
            self.page_list.clear()
            self.canvas.clear()
            self._set_actions_enabled(False)
            return

        self.title_label.setText(Path(result.output_path).name)
        self._set_actions_enabled(True)

        try:
            self._current_doc = fitz.open(result.output_path)
        except Exception as e:
            self.meta_label.setText(f"No se pudo abrir resultado: {e}")
            return

        # Thumbnails
        self.page_list.clear()
        for i in range(self._current_doc.page_count):
            thumb = self._render_page_pixmap(i, dpi=32)
            item = QListWidgetItem(QIcon(thumb), f"Página {i + 1}")
            pr = self._find_page_result(result, i)
            if pr is not None:
                marks = []
                if pr.snapped_to_line:
                    marks.append("línea")
                if not pr.clean:
                    marks.append("⚠ texto")
                if marks:
                    item.setText(f"Página {i + 1}\n{' · '.join(marks)}")
            self.page_list.addItem(item)

        if self._current_doc.page_count > 0:
            self.page_list.setCurrentRow(0)

        clean = sum(1 for pr in result.page_results if pr.clean)
        snapped = sum(1 for pr in result.page_results if pr.snapped_to_line)
        total = len(result.page_results)
        self.meta_label.setText(
            f"{total} páginas firmadas · {clean} sin tapar texto · "
            f"{snapped} ajustadas a línea de firma · {total - clean} con colisiones"
        )

    def _find_page_result(self, result: JobResult, page_index: int):
        for pr in result.page_results:
            if pr.page_index == page_index:
                return pr
        return None

    def _on_page_selected(self) -> None:
        if self._current_doc is None:
            return
        row = self.page_list.currentRow()
        if row < 0:
            return
        self._current_page = row
        self._render_current()

    # ================================================================== #
    # Render adaptativo
    # ================================================================== #
    def _compute_target_dpi(self) -> float:
        """Calcula el DPI según el modo de ajuste y zoom."""
        if self._current_doc is None or self._current_page < 0:
            return 96.0

        page = self._current_doc[self._current_page]
        pw_pt = max(1.0, page.rect.width)
        ph_pt = max(1.0, page.rect.height)

        # Viewport disponible (descontamos padding visual)
        vp_w = max(200, self.scroll.viewport().width() - 24)
        vp_h = max(200, self.scroll.viewport().height() - 24)

        # DPI base que ajusta exactamente al ancho/alto
        dpi_w = vp_w / pw_pt * 72.0
        dpi_h = vp_h / ph_pt * 72.0

        if self._fit_mode == "width":
            base_dpi = dpi_w
        elif self._fit_mode == "page":
            base_dpi = min(dpi_w, dpi_h)
        else:  # manual: usa "width" como referencia 1.0
            base_dpi = dpi_w

        zoom = ZOOM_LEVELS[self._zoom_index]
        dpi = base_dpi * zoom
        # Caps razonables
        dpi = max(36.0, min(dpi, 320.0))
        return dpi

    def _render_current(self) -> None:
        if self._current_doc is None or self._current_page < 0:
            return
        dpi = self._compute_target_dpi()
        pix = self._render_page_pixmap(self._current_page, dpi=dpi)
        self.canvas.setPixmap(pix)
        # Tamaño exacto del label = tamaño del pixmap (clave para no cortar)
        self.canvas.setFixedSize(pix.size())
        self._update_zoom_label()

    def _render_page_pixmap(self, page_index: int, dpi: float) -> QPixmap:
        page = self._current_doc[page_index]
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pm = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
        return _pil_to_qpixmap(img)

    def _update_zoom_label(self) -> None:
        zoom = ZOOM_LEVELS[self._zoom_index]
        self.zoom_label.setText(f"{int(zoom * 100)}%")

    # ================================================================== #
    # Zoom controls
    # ================================================================== #
    def _zoom_in(self) -> None:
        self._fit_mode = "manual"
        if self._zoom_index < len(ZOOM_LEVELS) - 1:
            self._zoom_index += 1
            self._render_current()

    def _zoom_out(self) -> None:
        self._fit_mode = "manual"
        if self._zoom_index > 0:
            self._zoom_index -= 1
            self._render_current()

    def _fit_width(self) -> None:
        self._fit_mode = "width"
        self._zoom_index = 2  # 1.00
        self._render_current()

    def _fit_page(self) -> None:
        self._fit_mode = "page"
        self._zoom_index = 2
        self._render_current()

    def _open_in_explorer(self) -> None:
        if self._current_result and self._current_result.output_path:
            self.openInExplorer.emit(self._current_result.output_path)

    # ================================================================== #
    # Resize
    # ================================================================== #
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Re-renderizar para que el ajuste al ancho/página siga válido
        if self._current_doc is not None and self._fit_mode != "manual":
            self._render_current()
