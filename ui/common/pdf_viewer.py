"""GenericPdfViewer — visor de resultados PDF reutilizable por todas las herramientas.

Acepta cualquier objeto que tenga los atributos:
    output_path: str
    success: bool
    error: str

No tiene metadatos específicos de ninguna herramienta (sin datos de firma,
sin page_results del Firmador, etc.).
"""
from __future__ import annotations
from pathlib import Path
from typing import List

import fitz
from PIL import Image
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QBrush, QColor, QIcon
from PyQt6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QPushButton,
    QScrollArea, QSizePolicy,
)


ZOOM_LEVELS = [0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 2.50, 3.00]


def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


class GenericPdfViewer(QWidget):
    """Visor genérico: lista de documentos resultado + render PDF interactivo."""

    openInExplorer = pyqtSignal(str)

    def __init__(self, doc_list_title: str = "Documentos procesados", parent=None) -> None:
        super().__init__(parent)
        self._doc_list_title = doc_list_title
        self._results: list = []
        self._current_doc: fitz.Document | None = None
        self._current_result = None
        self._current_page: int = 0
        self._zoom_index: int = 2
        self._fit_mode: str = "width"

        self._build()

    # ------------------------------------------------------------------ #
    # Construcción
    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Panel izquierdo — lista de documentos
        left = QFrame()
        left.setProperty("class", "Card")
        left.setFixedWidth(240)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 14, 14, 14)
        lv.setSpacing(10)

        title_lbl = QLabel(self._doc_list_title)
        title_lbl.setProperty("class", "CardTitle")
        lv.addWidget(title_lbl)

        self.doc_list = QListWidget()
        self.doc_list.itemSelectionChanged.connect(self._on_doc_selected)
        lv.addWidget(self.doc_list, 1)

        layout.addWidget(left)

        # Panel central — render + controles
        center = QFrame()
        center.setProperty("class", "Card")
        cv = QVBoxLayout(center)
        cv.setContentsMargins(14, 14, 14, 14)
        cv.setSpacing(12)

        # Header
        header = QHBoxLayout()
        header.setSpacing(8)

        self.title_label = QLabel("Selecciona un documento")
        self.title_label.setProperty("class", "CardTitle")
        header.addWidget(self.title_label, 1)

        # Controles zoom
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

        fit_btn = QPushButton("Ajustar")
        fit_btn.setProperty("class", "IconBtn")
        fit_btn.clicked.connect(self._fit_width)
        header.addWidget(fit_btn)

        self.open_file_btn = QPushButton("Abrir PDF")
        self.open_file_btn.setProperty("class", "Ghost")
        self.open_file_btn.clicked.connect(self._on_open_file)
        self.open_file_btn.setEnabled(False)
        header.addWidget(self.open_file_btn)

        self.open_btn = QPushButton("Abrir carpeta")
        self.open_btn.setProperty("class", "Ghost")
        self.open_btn.clicked.connect(self._on_open_in_explorer)
        self.open_btn.setEnabled(False)
        header.addWidget(self.open_btn)

        cv.addLayout(header)

        # Body: página miniatura + canvas
        body = QHBoxLayout()
        body.setSpacing(12)

        self.page_list = QListWidget()
        self.page_list.setFixedWidth(112)
        self.page_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.page_list.setIconSize(QSize(88, 112))
        self.page_list.setGridSize(QSize(100, 132))
        self.page_list.setFlow(QListWidget.Flow.TopToBottom)
        self.page_list.setWrapping(False)
        self.page_list.setResizeMode(QListWidget.ResizeMode.Fixed)
        self.page_list.setSpacing(2)
        self.page_list.itemSelectionChanged.connect(self._on_page_selected)
        body.addWidget(self.page_list)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("ResultCanvas")
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.canvas = QLabel()
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setStyleSheet("background: transparent;")
        self.scroll.setWidget(self.canvas)
        body.addWidget(self.scroll, 1)

        cv.addLayout(body, 1)

        self.meta_label = QLabel("")
        self.meta_label.setProperty("class", "CardHint")
        self.meta_label.setWordWrap(True)
        cv.addWidget(self.meta_label)

        layout.addWidget(center, 1)

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #

    def set_results(self, results: list) -> None:
        """Acepta cualquier lista de objetos con output_path, success, error."""
        self._results = results
        self.doc_list.clear()
        for r in results:
            out = getattr(r, "output_path", "") or ""
            name = Path(out).name if out else "(error)"
            item = QListWidgetItem(name)
            if not getattr(r, "success", False):
                item.setForeground(QBrush(QColor("#E5484D")))
                item.setText(f"⚠  {name}")
            self.doc_list.addItem(item)
        if results:
            self.doc_list.setCurrentRow(0)
        else:
            self._clear_view()

    def clear_results(self) -> None:
        self._close_doc()
        self._results = []
        self._current_result = None
        self.doc_list.clear()
        self._clear_view()

    # ------------------------------------------------------------------ #

    def _clear_view(self) -> None:
        self.page_list.clear()
        self.canvas.clear()
        self.title_label.setText("Selecciona un documento")
        self.meta_label.setText("")
        self._set_zoom_enabled(False)
        self.open_btn.setEnabled(False)
        self.open_file_btn.setEnabled(False)

    def _set_zoom_enabled(self, enabled: bool) -> None:
        self.zoom_in_btn.setEnabled(enabled)
        self.zoom_out_btn.setEnabled(enabled)
        self.open_btn.setEnabled(enabled)
        self.open_file_btn.setEnabled(enabled)

    def _close_doc(self) -> None:
        if self._current_doc is not None:
            try:
                self._current_doc.close()
            except Exception:
                pass
            self._current_doc = None

    # ------------------------------------------------------------------ #
    # Handlers
    # ------------------------------------------------------------------ #

    def _on_doc_selected(self) -> None:
        row = self.doc_list.currentRow()
        if row < 0 or row >= len(self._results):
            return
        result = self._results[row]
        self._current_result = result
        self._close_doc()

        out_path = getattr(result, "output_path", "") or ""
        if not getattr(result, "success", False) or not out_path:
            self.title_label.setText("Error en este documento")
            err = getattr(result, "error", "")
            self.meta_label.setText(err or "")
            self.page_list.clear()
            self.canvas.clear()
            self._set_zoom_enabled(False)
            return

        self.title_label.setText(Path(out_path).name)
        self._set_zoom_enabled(True)

        try:
            self._current_doc = fitz.open(out_path)
        except Exception as e:
            self.meta_label.setText(f"No se pudo abrir: {e}")
            return

        self._current_page = 0
        self.page_list.clear()
        for i in range(self._current_doc.page_count):
            thumb = self._render(i, dpi=30)
            item = QListWidgetItem(QIcon(thumb), str(i + 1))
            self.page_list.addItem(item)

        if self._current_doc.page_count > 0:
            self.page_list.setCurrentRow(0)

        self.meta_label.setText(
            f"{self._current_doc.page_count} páginas · {Path(out_path).name}"
        )

    def _on_page_selected(self) -> None:
        if self._current_doc is None:
            return
        row = self.page_list.currentRow()
        if row < 0:
            return
        self._current_page = row
        self._render_current()

    # ------------------------------------------------------------------ #
    # Render
    # ------------------------------------------------------------------ #

    def _compute_dpi(self) -> float:
        if self._current_doc is None:
            return 96.0
        page = self._current_doc[self._current_page]
        vp_w = max(200, self.scroll.viewport().width() - 24)
        vp_h = max(200, self.scroll.viewport().height() - 24)
        dpi_w = vp_w / max(1.0, page.rect.width) * 72.0
        dpi_h = vp_h / max(1.0, page.rect.height) * 72.0
        base = dpi_w if self._fit_mode == "width" else min(dpi_w, dpi_h)
        return max(36.0, min(base * ZOOM_LEVELS[self._zoom_index], 320.0))

    def _render_current(self) -> None:
        if self._current_doc is None:
            return
        dpi = self._compute_dpi()
        pix = self._render(self._current_page, dpi)
        self.canvas.setPixmap(pix)
        self.canvas.setFixedSize(pix.size())
        zoom = ZOOM_LEVELS[self._zoom_index]
        self.zoom_label.setText(f"{int(zoom * 100)}%")

    def _render(self, page_idx: int, dpi: float) -> QPixmap:
        page = self._current_doc[page_idx]
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pm = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
        return _pil_to_qpixmap(img)

    # ------------------------------------------------------------------ #
    # Zoom
    # ------------------------------------------------------------------ #

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
        self._zoom_index = 2
        self._render_current()

    def _on_open_file(self) -> None:
        if self._current_result:
            out = getattr(self._current_result, "output_path", "")
            if out and Path(out).exists():
                from PyQt6.QtCore import QUrl
                from PyQt6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def _on_open_in_explorer(self) -> None:
        if self._current_result:
            out = getattr(self._current_result, "output_path", "")
            if out:
                self.openInExplorer.emit(out)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._current_doc is not None and self._fit_mode != "manual":
            self._render_current()
