"""Preview panel for PDF splitting ranges."""
from __future__ import annotations

from typing import Optional

import fitz
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from core.split_ranges import SplitRange
from ui.common.icons import icon, set_button_icon
from ui.styles import COLORS


ZOOM_LEVELS = [0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 2.50, 3.00]
_FIT_ZOOM_IDX = 2
_CANVAS_MAX_PX = 2200
_THUMB_TARGET_PX = 150


class SplitPreviewPanel(QFrame):
    """Live PDF preview with page coverage awareness."""

    addVisiblePageRequested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "Card")
        self.setMinimumWidth(320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._pdf_path = ""
        self._doc: Optional[fitz.Document] = None
        self._total_pages = 0
        self._current_page = 0  # 0-based
        self._ranges: list[SplitRange] = []
        self._selected_range_idx: Optional[int] = None
        self._zoom_index = _FIT_ZOOM_IDX
        self._fit_mode = "page"
        self._thumb_generation = 0
        self._thumb_queue: list[int] = []
        self._build()
        self.clear_document()

    @property
    def current_page_number(self) -> int:
        return self._current_page + 1

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Previsualización")
        title.setProperty("class", "CardTitle")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        self._coverage_lbl = QLabel("Sin documento")
        self._coverage_lbl.setProperty("class", "CardHint")
        self._coverage_lbl.setWordWrap(True)
        layout.addWidget(self._coverage_lbl)

        controls = QVBoxLayout()
        controls.setSpacing(6)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)

        self._prev_btn = QPushButton()
        self._prev_btn.setProperty("class", "IconBtn")
        self._prev_btn.setFixedSize(28, 28)
        self._prev_btn.setToolTip("Página anterior")
        set_button_icon(self._prev_btn, "chevron-left", size=14, icon_only=True)
        self._prev_btn.clicked.connect(self._prev_page)
        nav_row.addWidget(self._prev_btn)

        self._page_spin = QSpinBox()
        self._page_spin.setRange(1, 1)
        self._page_spin.setFixedWidth(56)
        self._page_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._page_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_spin.editingFinished.connect(self._on_page_jump)
        nav_row.addWidget(self._page_spin)

        self._total_lbl = QLabel("/ -")
        self._total_lbl.setFixedWidth(54)
        self._total_lbl.setStyleSheet("color:#9094A0; font-size:12px;")
        nav_row.addWidget(self._total_lbl)

        self._next_btn = QPushButton()
        self._next_btn.setProperty("class", "IconBtn")
        self._next_btn.setFixedSize(28, 28)
        self._next_btn.setToolTip("Página siguiente")
        set_button_icon(self._next_btn, "chevron-right", size=14, icon_only=True)
        self._next_btn.clicked.connect(self._next_page)
        nav_row.addWidget(self._next_btn)

        nav_row.addStretch()
        self._add_visible_btn = QPushButton()
        self._add_visible_btn.setProperty("class", "Ghost")
        self._add_visible_btn.setFixedSize(34, 28)
        self._add_visible_btn.setToolTip("Agrega la página visible como tramo de una página")
        set_button_icon(self._add_visible_btn, "plus", size=14, icon_only=True)
        self._add_visible_btn.clicked.connect(
            lambda: self.addVisiblePageRequested.emit(self.current_page_number)
        )
        nav_row.addWidget(self._add_visible_btn)
        controls.addLayout(nav_row)

        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(6)
        self._zoom_out_btn = QPushButton()
        self._zoom_out_btn.setProperty("class", "IconBtn")
        self._zoom_out_btn.setFixedSize(28, 28)
        self._zoom_out_btn.setToolTip("Reducir zoom")
        set_button_icon(self._zoom_out_btn, "minus", size=14, icon_only=True)
        self._zoom_out_btn.clicked.connect(self._zoom_out)
        zoom_row.addWidget(self._zoom_out_btn)

        self._zoom_lbl = QLabel("100%")
        self._zoom_lbl.setFixedWidth(42)
        self._zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_lbl.setStyleSheet("color:#9094A0; font-size:12px;")
        zoom_row.addWidget(self._zoom_lbl)

        self._zoom_in_btn = QPushButton()
        self._zoom_in_btn.setProperty("class", "IconBtn")
        self._zoom_in_btn.setFixedSize(28, 28)
        self._zoom_in_btn.setToolTip("Aumentar zoom")
        set_button_icon(self._zoom_in_btn, "plus", size=14, icon_only=True)
        self._zoom_in_btn.clicked.connect(self._zoom_in)
        zoom_row.addWidget(self._zoom_in_btn)

        self._fit_width_btn = QPushButton()
        self._fit_width_btn.setProperty("class", "IconBtn")
        self._fit_width_btn.setFixedSize(28, 28)
        self._fit_width_btn.setToolTip("Ajustar al ancho")
        set_button_icon(self._fit_width_btn, "maximize", size=14, icon_only=True)
        self._fit_width_btn.clicked.connect(self._fit_width)
        zoom_row.addWidget(self._fit_width_btn)

        self._fit_page_btn = QPushButton()
        self._fit_page_btn.setProperty("class", "IconBtn")
        self._fit_page_btn.setFixedSize(28, 28)
        self._fit_page_btn.setToolTip("Ajustar página completa")
        set_button_icon(self._fit_page_btn, "file-text", size=14, icon_only=True)
        self._fit_page_btn.clicked.connect(self._fit_page)
        zoom_row.addWidget(self._fit_page_btn)
        zoom_row.addStretch()
        controls.addLayout(zoom_row)

        layout.addLayout(controls)

        body = QHBoxLayout()
        body.setSpacing(8)

        self._page_list = QListWidget()
        self._page_list.setObjectName("SplitPreviewPageList")
        self._page_list.setFixedWidth(112)
        self._page_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._page_list.setIconSize(self._thumb_size())
        self._page_list.setGridSize(self._grid_size())
        self._page_list.setFlow(QListWidget.Flow.TopToBottom)
        self._page_list.setWrapping(False)
        self._page_list.setResizeMode(QListWidget.ResizeMode.Fixed)
        self._page_list.setSpacing(4)
        self._page_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._page_list.itemSelectionChanged.connect(self._on_thumb_selected)
        body.addWidget(self._page_list)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("SplitPreviewCanvas")
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setMinimumSize(160, 180)
        self._scroll.setSizeAdjustPolicy(QScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self._scroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._scroll.setStyleSheet(
            f"QScrollArea#SplitPreviewCanvas {{ background:{COLORS['bg']}; border:none; }}"
        )

        self._canvas = QLabel()
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas.setStyleSheet("background: transparent;")
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._scroll.setWidget(self._canvas)
        body.addWidget(self._scroll, 1)
        layout.addLayout(body, 1)

        self._page_status_lbl = QLabel("")
        self._page_status_lbl.setProperty("class", "CardHint")
        self._page_status_lbl.setWordWrap(True)
        layout.addWidget(self._page_status_lbl)

    def _thumb_size(self):
        return QSize(72, 94)

    def _grid_size(self):
        return QSize(92, 124)

    def set_document(self, pdf_path: str, total_pages: int) -> None:
        self.clear_document(close_doc=True)
        self._pdf_path = pdf_path
        self._total_pages = max(0, int(total_pages))
        try:
            self._doc = fitz.open(pdf_path)
        except Exception as exc:
            self._canvas.setText(f"No se pudo previsualizar: {exc}")
            self._sync_controls()
            return
        self._current_page = 0
        self._populate_pages()
        if self._total_pages > 0:
            self._page_list.setCurrentRow(0)
            self._render_current()
            self._start_thumb_rendering()
        self._sync_controls()

    def clear_document(self, close_doc: bool = True) -> None:
        self._thumb_generation += 1
        self._thumb_queue = []
        if close_doc and self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
        self._doc = None
        self._pdf_path = ""
        self._total_pages = 0
        self._current_page = 0
        self._ranges = []
        self._selected_range_idx = None
        self._page_list.blockSignals(True)
        try:
            self._page_list.clear()
        finally:
            self._page_list.blockSignals(False)
        self._canvas.clear()
        self._canvas.setText("Carga un PDF para ver sus páginas.")
        self._canvas.setStyleSheet("color:#6B6F7A; font-size:12px; background:transparent;")
        self._canvas.setFixedSize(420, 120)
        self._coverage_lbl.setText("Sin documento")
        self._page_status_lbl.setText("")
        self._sync_controls()

    def set_ranges(
        self,
        ranges: list[SplitRange],
        selected_range_idx: Optional[int] = None,
    ) -> None:
        self._ranges = list(ranges)
        self._selected_range_idx = selected_range_idx
        self._refresh_page_styles()
        self._refresh_coverage_label()
        self._refresh_page_status()

    def preview_range(self, idx: int, rng: SplitRange) -> None:
        self._selected_range_idx = idx
        self.set_page(rng.start)
        self._refresh_page_styles()

    def set_page(self, page_number: int) -> None:
        if self._total_pages <= 0:
            return
        target = max(1, min(page_number, self._total_pages)) - 1
        if target == self._current_page:
            self._render_current()
            return
        self._page_list.setCurrentRow(target)

    def _populate_pages(self) -> None:
        self._thumb_generation += 1
        placeholder = icon("file-text", COLORS["text_muted"], 16)
        self._page_list.blockSignals(True)
        try:
            self._page_list.clear()
            for index in range(self._total_pages):
                item = QListWidgetItem(placeholder, str(index + 1))
                item.setToolTip(f"Página {index + 1}")
                self._page_list.addItem(item)
        finally:
            self._page_list.blockSignals(False)
        self._refresh_page_styles()

    def _coverage_for_page(self, page_number: int) -> list[int]:
        return [
            idx for idx, rng in enumerate(self._ranges)
            if rng.start <= page_number <= rng.end
        ]

    def _refresh_page_styles(self) -> None:
        for row in range(self._page_list.count()):
            item = self._page_list.item(row)
            page_number = row + 1
            covered_by = self._coverage_for_page(page_number)
            if len(covered_by) > 1:
                color = QColor(229, 72, 77, 70)
                item.setToolTip(f"Página {page_number} · solapada en {len(covered_by)} tramos")
            elif covered_by:
                is_selected = covered_by[0] == self._selected_range_idx
                color = QColor(245, 166, 35, 95 if is_selected else 42)
                item.setToolTip(f"Página {page_number} · tramo #{covered_by[0] + 1}")
            else:
                color = QColor(255, 255, 255, 0)
                item.setToolTip(f"Página {page_number} · sin tramo")
            item.setBackground(QBrush(color))

    def _refresh_coverage_label(self) -> None:
        if self._total_pages <= 0:
            self._coverage_lbl.setText("Sin documento")
            return
        covered = set()
        overlaps = set()
        seen = set()
        for rng in self._ranges:
            for page in range(max(1, rng.start), min(self._total_pages, rng.end) + 1):
                if page in seen:
                    overlaps.add(page)
                seen.add(page)
                covered.add(page)
        missing = self._total_pages - len(covered)
        bits = [f"{len(covered)}/{self._total_pages} cubiertas"]
        if missing:
            bits.append(f"{missing} sin tramo")
        if overlaps:
            bits.append(f"{len(overlaps)} solapadas")
        self._coverage_lbl.setText(" · ".join(bits))

    def _refresh_page_status(self) -> None:
        if self._total_pages <= 0:
            self._page_status_lbl.setText("")
            return
        page_number = self._current_page + 1
        covered_by = self._coverage_for_page(page_number)
        if len(covered_by) > 1:
            labels = ", ".join(f"#{idx + 1}" for idx in covered_by)
            text = f"Página {page_number}: solapada en tramos {labels}."
            color = "#E5484D"
        elif covered_by:
            idx = covered_by[0]
            rng = self._ranges[idx]
            text = (
                f"Página {page_number}: tramo #{idx + 1} · "
                f"{rng.start}-{rng.end} · {rng.name or 'sin nombre'}"
            )
            color = "#F5A623"
        else:
            text = f"Página {page_number}: sin tramo, no saldrá en ningún archivo."
            color = "#9094A0"
        self._page_status_lbl.setText(text)
        self._page_status_lbl.setStyleSheet(f"color:{color}; font-size:12px;")

    def _start_thumb_rendering(self) -> None:
        if self._doc is None:
            return
        generation = self._thumb_generation
        pages = list(range(self._total_pages))
        if self._current_page in pages:
            pages.remove(self._current_page)
            pages.insert(0, self._current_page)
        self._thumb_queue = pages
        QTimer.singleShot(0, lambda gen=generation: self._render_next_thumb(gen))

    def _render_next_thumb(self, generation: int) -> None:
        if generation != self._thumb_generation or self._doc is None:
            return
        if not self._thumb_queue:
            return
        page_index = self._thumb_queue.pop(0)
        if 0 <= page_index < self._page_list.count():
            try:
                pix = self._render_page(page_index, self._thumb_dpi_for_page(page_index))
                item = self._page_list.item(page_index)
                if item is not None:
                    item.setIcon(QIcon(pix))
            except Exception:
                pass
        if self._thumb_queue:
            QTimer.singleShot(0, lambda gen=generation: self._render_next_thumb(gen))

    def _thumb_dpi_for_page(self, page_idx: int) -> float:
        if self._doc is None:
            return 12.0
        page = self._doc[page_idx]
        long_side = max(1.0, page.rect.width, page.rect.height)
        return max(3.0, min(_THUMB_TARGET_PX * 72.0 / long_side, 30.0))

    def _compute_dpi(self) -> float:
        if self._doc is None:
            return 96.0
        page = self._doc[self._current_page]
        vp_w = max(220, self._scroll.viewport().width() - 24)
        vp_h = max(220, self._scroll.viewport().height() - 24)
        page_w = max(1.0, page.rect.width)
        page_h = max(1.0, page.rect.height)
        dpi_w = vp_w / page_w * 72.0
        dpi_h = vp_h / page_h * 72.0
        base = dpi_w if self._fit_mode == "width" else min(dpi_w, dpi_h)
        max_dpi = min(320.0, _CANVAS_MAX_PX / max(page_w, page_h) * 72.0)
        return max(4.0, min(base * ZOOM_LEVELS[self._zoom_index], max_dpi))

    def _render_current(self) -> None:
        if self._doc is None or self._total_pages <= 0:
            return
        pix = self._render_page(self._current_page, self._compute_dpi())
        self._canvas.setStyleSheet("background: transparent;")
        self._canvas.clear()
        self._canvas.setPixmap(pix)
        self._canvas.setFixedSize(pix.size())
        self._sync_controls()
        self._refresh_page_status()

    def _render_page(self, page_index: int, dpi: float) -> QPixmap:
        page = self._doc[page_index]
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        qimg = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        )
        return QPixmap.fromImage(qimg.copy())

    def _on_thumb_selected(self) -> None:
        row = self._page_list.currentRow()
        if row < 0 or row >= self._total_pages:
            return
        self._current_page = row
        self._render_current()

    def _on_page_jump(self) -> None:
        self.set_page(self._page_spin.value())

    def _prev_page(self) -> None:
        self.set_page(self.current_page_number - 1)

    def _next_page(self) -> None:
        self.set_page(self.current_page_number + 1)

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
        self._zoom_index = _FIT_ZOOM_IDX
        self._render_current()

    def _fit_page(self) -> None:
        self._fit_mode = "page"
        self._zoom_index = _FIT_ZOOM_IDX
        self._render_current()

    def _sync_controls(self) -> None:
        has_doc = self._doc is not None and self._total_pages > 0
        self._page_spin.blockSignals(True)
        self._page_spin.setRange(1, max(1, self._total_pages))
        self._page_spin.setValue(self.current_page_number if has_doc else 1)
        self._page_spin.blockSignals(False)
        self._page_spin.setEnabled(has_doc and self._total_pages > 1)
        self._total_lbl.setText(f"/ {self._total_pages}" if has_doc else "/ -")
        self._prev_btn.setEnabled(has_doc and self._current_page > 0)
        self._next_btn.setEnabled(has_doc and self._current_page < self._total_pages - 1)
        self._zoom_out_btn.setEnabled(has_doc and self._zoom_index > 0)
        self._zoom_in_btn.setEnabled(has_doc and self._zoom_index < len(ZOOM_LEVELS) - 1)
        self._fit_width_btn.setEnabled(has_doc)
        self._fit_page_btn.setEnabled(has_doc)
        self._add_visible_btn.setEnabled(has_doc)
        self._zoom_lbl.setText(f"{int(ZOOM_LEVELS[self._zoom_index] * 100)}%")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._doc is not None and self._fit_mode != "manual":
            self._render_current()

    def close_document(self) -> None:
        self.clear_document(close_doc=True)

    def deleteLater(self) -> None:  # type: ignore[override]
        self.close_document()
        super().deleteLater()
