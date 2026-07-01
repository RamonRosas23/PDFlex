"""SubrayadorWindow - realistic manual highlighter for PDFs."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import fitz
from PIL import Image
from PyQt6.QtCore import QObject, QPointF, QRectF, QSize, QThread, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QWidget,
    QAbstractScrollArea,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QButtonGroup,
    QPushButton,
    QLabel,
    QComboBox,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QSpinBox,
)

from core.highlight_engine import (
    COLOR_CHOICES,
    HIGHLIGHT_PROFILES,
    HighlightEngine,
    HighlightJob,
    HighlightMark,
    HighlightOptions,
    HighlightResult,
    render_highlight_texture,
)
from core.output_naming import unique_output_path_for_source
from core.output_paths import make_run_dir
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.document_workspace import DocumentWorkspace as DocumentsCard
from ui.common.icons import set_button_icon, set_compact_icon_button
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.process_step import ProcessStep
from ui.common.send_to_tool import SendToToolButton
from ui.common.tool_scaffold import PipelineWindow, RunnerThread


class HighlightWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[HighlightJob]) -> None:
        super().__init__()
        self.jobs = jobs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = HighlightEngine().run_batch(
                self.jobs,
                progress=lambda c, t, m: self.progress.emit(c, t, m),
                should_cancel=lambda: self._cancel,
            )
            if self._cancel:
                self.error.emit("Operacion cancelada.")
            else:
                self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


class PageRenderWorker(QObject):
    """Renderiza una pagina PDF en hilo secundario y emite QImage."""

    ready = pyqtSignal(object, int)

    def __init__(self, path: str, page_index: int, guard: int) -> None:
        super().__init__()
        self._path = path
        self._page_index = page_index
        self._guard = guard

    def run(self) -> None:
        try:
            doc = fitz.open(self._path)
            try:
                if self._page_index >= doc.page_count:
                    self.ready.emit(None, self._guard)
                    return
                page = doc[self._page_index]
                page_long = max(1.0, page.rect.width, page.rect.height)
                dpi = max(36.0, min(140.0, 1400.0 * 72.0 / page_long))
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0),
                    alpha=False,
                )
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
                data = image.tobytes("raw", "RGBA")
                qimage = QImage(data, image.width, image.height, QImage.Format.Format_RGBA8888)
                self.ready.emit(qimage.copy(), self._guard)
            finally:
                doc.close()
        except Exception:
            self.ready.emit(None, self._guard)


class HighlightCanvas(QWidget):
    changed = pyqtSignal()
    pageChanged = pyqtSignal(int, int)
    viewChanged = pyqtSignal(float, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._doc: fitz.Document | None = None
        self._path = ""
        self._page_index = 0
        self._base_pixmap = QPixmap()
        self._pixmap = QPixmap()
        self._marks: dict[int, list[QRectF]] = {}
        self._drag_start: QPointF | None = None
        self._drag_current: QPointF | None = None
        self._interaction_mode = "highlight"
        self._fit_mode = "page"
        self._zoom = 1.0
        self._scroll_area: QScrollArea | None = None
        self._pan_start = None
        self._pan_h_start = 0
        self._pan_v_start = 0
        self._options = HighlightOptions.from_profile("oficina_real")
        self._preview_cache: dict[tuple, QPixmap] = {}
        self._render_guard = 0
        self._render_thread: Optional[QThread] = None
        self.setMinimumSize(360, 420)
        self.setMouseTracking(True)
        self.setStyleSheet("background:#0D0D10;")
        self.setCursor(Qt.CursorShape.CrossCursor)

    @property
    def path(self) -> str:
        return self._path

    def set_options(self, options: HighlightOptions) -> None:
        self._options = options.clamped()
        self._preview_cache.clear()
        self.update()

    def set_scroll_area(self, scroll_area: QScrollArea) -> None:
        self._scroll_area = scroll_area

    def set_interaction_mode(self, mode: str) -> None:
        self._interaction_mode = "pan" if mode == "pan" else "highlight"
        self._drag_start = None
        self._drag_current = None
        self._pan_start = None
        self.setCursor(
            Qt.CursorShape.OpenHandCursor
            if self._interaction_mode == "pan"
            else Qt.CursorShape.CrossCursor
        )
        self.update()

    def interaction_mode(self) -> str:
        return self._interaction_mode

    def fit_page(self) -> None:
        self._fit_mode = "page"
        self._apply_view_transform()

    def fit_width(self) -> None:
        self._fit_mode = "width"
        self._apply_view_transform()

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.20)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.20)

    def set_zoom(self, zoom: float) -> None:
        self._fit_mode = "manual"
        self._zoom = max(0.12, min(3.5, float(zoom)))
        self._apply_view_transform()

    def refit_to_viewport(self) -> None:
        if self._fit_mode in {"page", "width"}:
            self._apply_view_transform()

    def zoom_percent(self) -> int:
        return int(round(self._zoom * 100))

    def fit_mode(self) -> str:
        return self._fit_mode

    def load_pdf(self, path: str) -> None:
        self.close_doc()
        self._path = path
        self._doc = fitz.open(path)
        self._page_index = 0
        self._marks = {}
        self._render_current()
        self.changed.emit()
        self.pageChanged.emit(self._page_index, self.page_count())

    def close_doc(self) -> None:
        self._render_guard += 1
        thread = self._render_thread
        if thread is not None and thread.isRunning():
            thread.wait(2000)
        self._render_thread = None
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
        self._doc = None
        self._path = ""
        self._page_index = 0
        self._base_pixmap = QPixmap()
        self._pixmap = QPixmap()
        self._marks = {}
        self._drag_start = None
        self._drag_current = None
        self._pan_start = None
        self._preview_cache.clear()
        self.update()

    def page_count(self) -> int:
        return self._doc.page_count if self._doc is not None else 0

    def current_page(self) -> int:
        return self._page_index

    def set_page(self, index: int) -> None:
        if self._doc is None:
            return
        index = max(0, min(self._doc.page_count - 1, index))
        if index == self._page_index:
            return
        self._page_index = index
        self._drag_start = None
        self._drag_current = None
        self._render_current()
        self.pageChanged.emit(self._page_index, self.page_count())

    def next_page(self) -> None:
        self.set_page(self._page_index + 1)

    def previous_page(self) -> None:
        self.set_page(self._page_index - 1)

    def add_highlight_norm(
        self,
        page_index: int,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> None:
        rect = QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized()
        if rect.width() <= 0.001 or rect.height() <= 0.001:
            return
        self._marks.setdefault(page_index, []).append(rect)
        self._preview_cache.clear()
        self.changed.emit()
        self.update()

    def undo_current_page(self) -> None:
        marks = self._marks.get(self._page_index, [])
        if marks:
            marks.pop()
            if not marks:
                self._marks.pop(self._page_index, None)
            self._preview_cache.clear()
            self.changed.emit()
            self.update()

    def clear_current_page(self) -> None:
        if self._marks.pop(self._page_index, None) is not None:
            self._preview_cache.clear()
            self.changed.emit()
            self.update()

    def clear_all(self) -> None:
        if self._marks:
            self._marks.clear()
            self._preview_cache.clear()
            self.changed.emit()
            self.update()

    def total_highlights(self) -> int:
        return sum(len(marks) for marks in self._marks.values())

    def current_page_highlights(self) -> int:
        return len(self._marks.get(self._page_index, []))

    def pages_with_highlights(self) -> int:
        return sum(1 for marks in self._marks.values() if marks)

    def highlight_marks(self) -> List[HighlightMark]:
        out: List[HighlightMark] = []
        for page_index, marks in sorted(self._marks.items()):
            for rect in marks:
                out.append(
                    HighlightMark(
                        page_index=page_index,
                        x0_norm=rect.left(),
                        y0_norm=rect.top(),
                        x1_norm=rect.right(),
                        y1_norm=rect.bottom(),
                    )
                )
        return out

    def _render_current(self) -> None:
        if self._doc is None or self._doc.page_count <= 0:
            self._base_pixmap = QPixmap()
            self._pixmap = QPixmap()
            self.setFixedSize(420, 520)
            self.update()
            return
        self._render_guard += 1
        guard = self._render_guard
        if self._pixmap.isNull():
            self.setFixedSize(520, 640)
        worker = PageRenderWorker(self._path, self._page_index, guard)
        thread = RunnerThread(worker.run, self)
        worker.ready.connect(self._on_render_ready)
        worker.ready.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._cleanup_render_thread(t))
        self._render_thread = thread
        thread.start()

    def _cleanup_render_thread(self, thread: QThread) -> None:
        if self._render_thread is thread:
            self._render_thread = None

    def _on_render_ready(self, qimage, guard: int) -> None:
        if guard != self._render_guard:
            return
        if qimage is None:
            self._base_pixmap = QPixmap()
            self._pixmap = QPixmap()
            self.setFixedSize(420, 520)
        else:
            self._base_pixmap = QPixmap.fromImage(qimage)
            self._apply_view_transform()
            return
        self._preview_cache.clear()
        self.update()

    def _apply_view_transform(self) -> None:
        if self._base_pixmap.isNull():
            return
        viewport = self._viewport_size()
        pad = 24
        available_w = max(80, viewport.width() - pad)
        available_h = max(80, viewport.height() - pad)
        base_w = max(1, self._base_pixmap.width())
        base_h = max(1, self._base_pixmap.height())
        if self._fit_mode == "page":
            scale = min(available_w / base_w, available_h / base_h)
        elif self._fit_mode == "width":
            scale = available_w / base_w
        else:
            scale = self._zoom
        self._zoom = max(0.08, min(3.5, float(scale)))
        target_w = max(24, int(round(base_w * self._zoom)))
        target_h = max(24, int(round(base_h * self._zoom)))
        self._pixmap = self._base_pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setFixedSize(self._pixmap.size())
        self._preview_cache.clear()
        self.viewChanged.emit(self._zoom, self._fit_mode)
        self.update()

    def _viewport_size(self) -> QSize:
        if self._scroll_area is not None:
            size = self._scroll_area.viewport().size()
            if size.width() > 0 and size.height() > 0:
                return size
        parent = self.parentWidget()
        if parent is not None:
            return parent.size()
        return QSize(800, 600)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0D0D10"))
        if not self._pixmap.isNull():
            painter.drawPixmap(0, 0, self._pixmap)
            self._draw_marks(painter)
        else:
            painter.setPen(QColor("#9094A0"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Carga un PDF para subrayar.")
        painter.end()
        super().paintEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._should_start_pan(event):
            self._start_pan(event)
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._interaction_mode == "highlight"
            and not self._pixmap.isNull()
        ):
            self._drag_start = self._clamp_point(event.position())
            self._drag_current = self._drag_start
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pan_start is not None:
            self._update_pan(event)
            return
        if self._drag_start is not None:
            self._drag_current = self._clamp_point(event.position())
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pan_start is not None:
            self._finish_pan()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            end = self._clamp_point(event.position())
            rect_px = QRectF(self._drag_start, end).normalized()
            self._drag_start = None
            self._drag_current = None
            if rect_px.width() >= 8 and rect_px.height() >= 3:
                self.add_highlight_norm(
                    self._page_index,
                    rect_px.left() / max(1, self._pixmap.width()),
                    rect_px.top() / max(1, self._pixmap.height()),
                    rect_px.right() / max(1, self._pixmap.width()),
                    rect_px.bottom() / max(1, self._pixmap.height()),
                )
            self.update()
        super().mouseReleaseEvent(event)

    def _should_start_pan(self, event: QMouseEvent) -> bool:
        if self._pixmap.isNull() or self._scroll_area is None:
            return False
        if event.button() in {Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton}:
            return True
        return event.button() == Qt.MouseButton.LeftButton and self._interaction_mode == "pan"

    def _start_pan(self, event: QMouseEvent) -> None:
        assert self._scroll_area is not None
        self._pan_start = event.globalPosition().toPoint()
        self._pan_h_start = self._scroll_area.horizontalScrollBar().value()
        self._pan_v_start = self._scroll_area.verticalScrollBar().value()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def _update_pan(self, event: QMouseEvent) -> None:
        if self._scroll_area is None or self._pan_start is None:
            return
        current = event.globalPosition().toPoint()
        delta = current - self._pan_start
        self._scroll_area.horizontalScrollBar().setValue(self._pan_h_start - delta.x())
        self._scroll_area.verticalScrollBar().setValue(self._pan_v_start - delta.y())
        event.accept()

    def _finish_pan(self) -> None:
        self._pan_start = None
        self.setCursor(
            Qt.CursorShape.OpenHandCursor
            if self._interaction_mode == "pan"
            else Qt.CursorShape.CrossCursor
        )

    def _draw_marks(self, painter: QPainter) -> None:
        for idx, rect in enumerate(self._marks.get(self._page_index, [])):
            rect_px = self._norm_to_px(rect)
            self._draw_texture(painter, rect_px, idx)

        if self._drag_start is not None and self._drag_current is not None:
            preview = QRectF(self._drag_start, self._drag_current).normalized()
            if preview.width() >= 2 and preview.height() >= 2:
                self._draw_texture(painter, preview, -1)
            pen = QPen(QColor("#FACC15"))
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QBrush(Qt.GlobalColor.transparent))
            painter.drawRect(preview)

    def _draw_texture(self, painter: QPainter, rect_px: QRectF, index: int) -> None:
        expanded = self._expanded_preview_rect(rect_px)
        if expanded.width() < 2 or expanded.height() < 2:
            return
        pix = self._texture_pixmap(expanded, index)
        painter.drawPixmap(expanded, pix, QRectF(0, 0, pix.width(), pix.height()))

    def _texture_pixmap(self, rect_px: QRectF, index: int) -> QPixmap:
        key = (
            round(rect_px.width()),
            round(rect_px.height()),
            self._page_index,
            index,
            self._options.profile_id,
            tuple(round(c, 4) for c in self._options.color),
            round(self._options.opacity, 3),
            round(self._options.roughness, 3),
            round(self._options.pressure, 3),
            round(self._options.streakiness, 3),
            round(self._options.bleed, 3),
            round(self._options.overshoot, 3),
            self._options.passes,
            round(self._options.slant_deg, 2),
            self._options.seed,
        )
        cached = self._preview_cache.get(key)
        if cached is not None:
            return cached
        image = render_highlight_texture(
            max(4, int(round(rect_px.width()))),
            max(4, int(round(rect_px.height()))),
            self._options,
            seed=f"preview|{self._page_index}|{index}|{rect_px.x():.2f}|{rect_px.y():.2f}",
        )
        data = image.tobytes("raw", "RGBA")
        qimage = QImage(data, image.width, image.height, QImage.Format.Format_RGBA8888)
        pix = QPixmap.fromImage(qimage.copy())
        self._preview_cache[key] = pix
        return pix

    def _expanded_preview_rect(self, rect: QRectF) -> QRectF:
        x_pad = min(36.0, rect.height() * (0.25 + self._options.overshoot * 1.25))
        y_pad = min(16.0, rect.height() * (self._options.bleed * 0.34 + self._options.roughness * 0.08))
        expanded = QRectF(rect.left() - x_pad, rect.top() - y_pad, rect.width() + x_pad * 2.0, rect.height() + y_pad * 2.0)
        return expanded.intersected(QRectF(0, 0, self._pixmap.width(), self._pixmap.height()))

    def _norm_to_px(self, rect: QRectF) -> QRectF:
        return QRectF(
            rect.left() * self._pixmap.width(),
            rect.top() * self._pixmap.height(),
            rect.width() * self._pixmap.width(),
            rect.height() * self._pixmap.height(),
        )

    def _clamp_point(self, point: QPointF) -> QPointF:
        return QPointF(
            max(0.0, min(float(self._pixmap.width()), point.x())),
            max(0.0, min(float(self._pixmap.height()), point.y())),
        )


class SubrayadorWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documento", "Carga un PDF"),
        ("02", "Subrayar", "Dibuja trazos realistas"),
        ("03", "Procesar", "Aplica marcatexto"),
        ("04", "Resultados", "Revisa el PDF subrayado"),
    ]
    BRAND = "Subrayador realista"
    TAGLINE = "Marcatexto natural para PDFs"
    ACCENT_COLOR = "#FACC15"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[HighlightResult] = []
        self._worker: Optional[HighlightWorker] = None
        self._worker_thread: Optional[QThread] = None
        self._loading_profile = False

        self._build_pages()
        self._relax_stacked_page_size_hints()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_highlight_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documento a subrayar",
            "Carga un PDF para marcarlo con trazos manuales de marcatexto.",
        ))

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=False,
            show_thumbnails=True,
            thumb_size=(64, 82),
            file_filter="PDF (*.pdf)",
        )
        self._docs_card.files_changed.connect(self._on_docs_changed)
        self._docs_card.setMinimumSize(0, 0)
        self._docs_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        outer.addWidget(self._docs_card, 1)

        self._docs_summary_lbl = QLabel("Sin documento cargado.")
        self._docs_summary_lbl.setProperty("class", "CardHint")
        self._docs_summary_lbl.setWordWrap(True)
        outer.addWidget(self._docs_summary_lbl)

        return page

    def _build_highlight_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(18)

        outer.addLayout(make_page_header(
            "Subrayar con marcatexto",
            "Configura el comportamiento fisico del marcador y dibuja sobre la pagina.",
        ))

        body = QHBoxLayout()
        body.setSpacing(16)

        controls_shell = make_card("Marcador")
        controls_shell.setFixedWidth(362)
        controls_shell.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        shell_layout = card_layout(controls_shell)

        self._controls_scroll = QScrollArea()
        controls_scroll = self._controls_scroll
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QFrame.Shape.NoFrame)
        controls_scroll.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        controls_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        controls_scroll.setMinimumHeight(220)
        controls_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        controls_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        controls_scroll.viewport().setStyleSheet("background: transparent;")

        controls = QWidget()
        controls.setStyleSheet("background: transparent;")
        controls.setMinimumWidth(304)
        cl = QVBoxLayout(controls)
        cl.setContentsMargins(0, 0, 8, 0)
        cl.setSpacing(10)

        self._page_lbl = QLabel("Pagina -/-")
        self._page_lbl.setProperty("class", "CardTitle")
        cl.addWidget(self._page_lbl)

        nav_row = QHBoxLayout()
        self._prev_page_btn = QPushButton()
        set_compact_icon_button(self._prev_page_btn, "chevron-left", "Página anterior")
        self._prev_page_btn.clicked.connect(self._previous_page)
        nav_row.addWidget(self._prev_page_btn)
        self._next_page_btn = QPushButton()
        set_compact_icon_button(self._next_page_btn, "chevron-right", "Página siguiente")
        self._next_page_btn.clicked.connect(self._next_page)
        nav_row.addWidget(self._next_page_btn)
        nav_row.addStretch(1)
        cl.addLayout(nav_row)

        self._mark_count_lbl = QLabel("0 trazos")
        self._mark_count_lbl.setProperty("class", "CardHint")
        cl.addWidget(self._mark_count_lbl)

        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(250)
        for profile in HIGHLIGHT_PROFILES.values():
            self._profile_combo.addItem(profile.label, profile.id)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        cl.addWidget(self._profile_combo)

        self._color_combo = QComboBox()
        self._color_combo.setMinimumWidth(250)
        for color_id, (label, _rgb) in COLOR_CHOICES.items():
            self._color_combo.addItem(label, color_id)
        self._color_combo.currentIndexChanged.connect(lambda _idx: self._on_options_changed())
        cl.addWidget(self._color_combo)

        self._opacity_slider, self._opacity_value = self._add_slider(cl, "Opacidad", 5, 95, 48, "%")
        self._roughness_slider, self._roughness_value = self._add_slider(cl, "Rugosidad", 0, 100, 46, "%")
        self._pressure_slider, self._pressure_value = self._add_slider(cl, "Presion", 0, 100, 58, "%")
        self._streak_slider, self._streak_value = self._add_slider(cl, "Vetas", 0, 100, 34, "%")
        self._bleed_slider, self._bleed_value = self._add_slider(cl, "Sangrado", 0, 100, 34, "%")
        self._overshoot_slider, self._overshoot_value = self._add_slider(cl, "Rebase", 0, 100, 42, "%")

        pass_row = QHBoxLayout()
        pass_lbl = QLabel("Pasadas")
        pass_lbl.setProperty("class", "CardHint")
        pass_row.addWidget(pass_lbl, 1)
        self._passes_spin = QSpinBox()
        self._passes_spin.setRange(1, 4)
        self._passes_spin.setValue(2)
        self._passes_spin.setMinimumWidth(76)
        self._passes_spin.valueChanged.connect(lambda _value: self._on_options_changed())
        pass_row.addWidget(self._passes_spin)
        cl.addLayout(pass_row)

        slant_row = QHBoxLayout()
        slant_lbl = QLabel("Inclinacion")
        slant_lbl.setProperty("class", "CardHint")
        slant_row.addWidget(slant_lbl, 1)
        self._slant_spin = QSpinBox()
        self._slant_spin.setRange(-8, 8)
        self._slant_spin.setValue(0)
        self._slant_spin.setSuffix(" deg")
        self._slant_spin.setMinimumWidth(92)
        self._slant_spin.valueChanged.connect(lambda _value: self._on_options_changed())
        slant_row.addWidget(self._slant_spin)
        cl.addLayout(slant_row)

        seed_row = QHBoxLayout()
        seed_lbl = QLabel("Semilla")
        seed_lbl.setProperty("class", "CardHint")
        seed_row.addWidget(seed_lbl, 1)
        self._seed_spin = QSpinBox()
        self._seed_spin.setRange(0, 999999)
        self._seed_spin.setValue(1947)
        self._seed_spin.setMinimumWidth(104)
        self._seed_spin.valueChanged.connect(lambda _value: self._on_options_changed())
        seed_row.addWidget(self._seed_spin)
        cl.addLayout(seed_row)

        self._undo_btn = QPushButton("Deshacer")
        self._undo_btn.setProperty("class", "Ghost")
        set_button_icon(self._undo_btn, "arrow-left")
        self._undo_btn.clicked.connect(self._undo_page)
        cl.addWidget(self._undo_btn)
        self._clear_page_btn = QPushButton("Limpiar página")
        self._clear_page_btn.setProperty("class", "Ghost")
        set_button_icon(self._clear_page_btn, "eraser")
        self._clear_page_btn.clicked.connect(self._clear_page)
        cl.addWidget(self._clear_page_btn)

        self._clear_all_btn = QPushButton("Limpiar todo")
        self._clear_all_btn.setProperty("class", "Danger")
        set_button_icon(self._clear_all_btn, "trash-2", color="#E5484D")
        self._clear_all_btn.clicked.connect(self._clear_all)
        cl.addWidget(self._clear_all_btn)
        cl.addStretch(1)
        controls_scroll.setWidget(controls)
        shell_layout.addWidget(controls_scroll, 1)
        body.addWidget(controls_shell)

        viewer = make_card("Vista de pagina")
        vl = card_layout(viewer)

        view_bar = QHBoxLayout()
        view_bar.setSpacing(8)
        self._draw_mode_btn = QPushButton("Subrayar")
        self._draw_mode_btn.setCheckable(True)
        self._draw_mode_btn.setProperty("class", "Ghost")
        set_button_icon(self._draw_mode_btn, "tool-subrayador")
        self._draw_mode_btn.setMinimumWidth(164)
        self._pan_mode_btn = QPushButton("Mover")
        self._pan_mode_btn.setCheckable(True)
        self._pan_mode_btn.setProperty("class", "Ghost")
        set_button_icon(self._pan_mode_btn, "arrow-up-down")
        self._pan_mode_btn.setMinimumWidth(124)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self._draw_mode_btn)
        self._mode_group.addButton(self._pan_mode_btn)
        self._draw_mode_btn.setChecked(True)
        self._draw_mode_btn.clicked.connect(lambda: self._set_canvas_mode("highlight"))
        self._pan_mode_btn.clicked.connect(lambda: self._set_canvas_mode("pan"))
        view_bar.addWidget(self._draw_mode_btn)
        view_bar.addWidget(self._pan_mode_btn)

        self._fit_page_btn = QPushButton()
        self._fit_page_btn.setProperty("class", "IconBtn")
        self._fit_page_btn.setToolTip("Ajustar pagina completa")
        set_button_icon(self._fit_page_btn, "file-text", size=14, icon_only=True)
        self._fit_page_btn.clicked.connect(self._fit_page)
        view_bar.addWidget(self._fit_page_btn)

        self._fit_width_btn = QPushButton()
        self._fit_width_btn.setProperty("class", "IconBtn")
        self._fit_width_btn.setToolTip("Ajustar al ancho")
        set_button_icon(self._fit_width_btn, "maximize", size=14, icon_only=True)
        self._fit_width_btn.clicked.connect(self._fit_width)
        view_bar.addWidget(self._fit_width_btn)

        self._zoom_out_btn = QPushButton()
        self._zoom_out_btn.setProperty("class", "IconBtn")
        self._zoom_out_btn.setToolTip("Reducir zoom")
        set_button_icon(self._zoom_out_btn, "minus", size=14, icon_only=True)
        self._zoom_out_btn.clicked.connect(self._zoom_out)
        view_bar.addWidget(self._zoom_out_btn)

        self._zoom_lbl = QLabel("100%")
        self._zoom_lbl.setProperty("class", "CardHint")
        self._zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_lbl.setMinimumWidth(48)
        view_bar.addWidget(self._zoom_lbl)

        self._zoom_in_btn = QPushButton()
        self._zoom_in_btn.setProperty("class", "IconBtn")
        self._zoom_in_btn.setToolTip("Aumentar zoom")
        set_button_icon(self._zoom_in_btn, "plus", size=14, icon_only=True)
        self._zoom_in_btn.clicked.connect(self._zoom_in)
        view_bar.addWidget(self._zoom_in_btn)
        view_bar.addStretch(1)
        vl.addLayout(view_bar)

        self._canvas = HighlightCanvas()
        self._canvas.changed.connect(self._sync_highlight_labels)
        self._canvas.pageChanged.connect(lambda *_: self._sync_highlight_labels())
        self._canvas.viewChanged.connect(lambda *_: self._sync_view_labels())
        self._canvas.set_options(self._build_options())
        scroll = QScrollArea()
        self._page_scroll = scroll
        scroll.setWidgetResizable(False)
        scroll.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        scroll.setMinimumSize(360, 300)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(self._canvas)
        self._canvas.set_scroll_area(scroll)
        vl.addWidget(scroll, 1)
        body.addWidget(viewer, 1)

        outer.addLayout(body, 1)

        self._on_profile_changed()
        self._sync_highlight_labels()
        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar subrayado",
            "PDFlex aplanara los trazos realistas sobre una copia temporal.",
        ))

        self._proc_step = ProcessStep(
            run_label="Aplicar subrayado",
            show_output_dir=False,
        )
        self._proc_step.set_run_enabled(False)
        outer.addWidget(self._proc_step, 1)

        return page

    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultados",
            "Revisa el PDF subrayado antes de guardarlo o enviarlo a otra herramienta.",
        ))

        self._result_viewer = GenericPdfViewer("PDF subrayado")
        self._result_viewer.setMinimumSize(0, 0)
        self._result_viewer.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        return page

    def _relax_stacked_page_size_hints(self) -> None:
        for index in range(self.stack.count()):
            page = self.stack.widget(index)
            if page is not None:
                page.setMinimumSize(0, 0)
                page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def _build_action_buttons(self) -> None:
        self._run_btn = QPushButton("Aplicar subrayado")
        self._run_btn.setProperty("class", "Primary")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setMinimumWidth(170)
        set_button_icon(self._run_btn, "play")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        self._cancel_btn.setFixedHeight(36)
        set_button_icon(self._cancel_btn, "square", color="#E5484D")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._restart_btn = QPushButton("Nueva sesion")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "subrayador")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _add_slider(
        self,
        layout: QVBoxLayout,
        label: str,
        minimum: int,
        maximum: int,
        value: int,
        suffix: str,
    ) -> tuple[QSlider, QLabel]:
        row = QHBoxLayout()
        title = QLabel(label)
        title.setProperty("class", "CardHint")
        row.addWidget(title, 1)
        value_lbl = QLabel(f"{value}{suffix}")
        value_lbl.setProperty("class", "CardHint")
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value_lbl.setMinimumWidth(44)
        row.addWidget(value_lbl)
        layout.addLayout(row)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.valueChanged.connect(lambda new_value, lbl=value_lbl, s=suffix: self._on_slider_changed(lbl, new_value, s))
        layout.addWidget(slider)
        return slider, value_lbl

    def _on_slider_changed(self, label: QLabel, value: int, suffix: str) -> None:
        label.setText(f"{value}{suffix}")
        self._on_options_changed()

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()

    def _on_section_activated(self, idx: int) -> None:
        if idx == 1:
            self._load_canvas_if_ready()
            QTimer.singleShot(0, self._refit_canvas_view)
        if idx == 2:
            self._refresh_summary()

    def set_inputs(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def _on_docs_changed(self, paths: List[str]) -> None:
        count = len(paths)
        if count == 0:
            self._docs_summary_lbl.setText("Sin documento cargado.")
            self._canvas.close_doc()
        elif count == 1:
            self._docs_summary_lbl.setText("1 documento listo para subrayar.")
            self._load_canvas_if_ready()
        else:
            self._docs_summary_lbl.setText("Carga un solo PDF por sesion para subrayado manual.")
            self._canvas.close_doc()
        self._sync_highlight_labels()

    def _load_canvas_if_ready(self) -> None:
        paths = self._docs_card.paths()
        if len(paths) != 1:
            return
        path = paths[0]
        if self._canvas.path == path:
            return
        try:
            self._canvas.load_pdf(path)
        except Exception as exc:
            show_error(self, "No se pudo abrir el PDF", str(exc))

    def _previous_page(self) -> None:
        self._canvas.previous_page()
        QTimer.singleShot(0, self._refit_canvas_view)

    def _next_page(self) -> None:
        self._canvas.next_page()
        QTimer.singleShot(0, self._refit_canvas_view)

    def _set_canvas_mode(self, mode: str) -> None:
        self._canvas.set_interaction_mode(mode)
        self._draw_mode_btn.setChecked(mode != "pan")
        self._pan_mode_btn.setChecked(mode == "pan")

    def _fit_page(self) -> None:
        self._canvas.fit_page()
        self._sync_view_labels()

    def _fit_width(self) -> None:
        self._canvas.fit_width()
        self._sync_view_labels()

    def _zoom_in(self) -> None:
        self._canvas.zoom_in()
        self._sync_view_labels()

    def _zoom_out(self) -> None:
        self._canvas.zoom_out()
        self._sync_view_labels()

    def _refit_canvas_view(self) -> None:
        if hasattr(self, "_canvas"):
            self._canvas.refit_to_viewport()
            self._sync_view_labels()

    def _sync_view_labels(self) -> None:
        if not hasattr(self, "_zoom_lbl"):
            return
        mode = self._canvas.fit_mode()
        label = {
            "page": "Pagina",
            "width": "Ancho",
            "manual": f"{self._canvas.zoom_percent()}%",
        }.get(mode, f"{self._canvas.zoom_percent()}%")
        self._zoom_lbl.setText(label)

    def _undo_page(self) -> None:
        self._canvas.undo_current_page()

    def _clear_page(self) -> None:
        self._canvas.clear_current_page()

    def _clear_all(self) -> None:
        self._canvas.clear_all()

    def _on_profile_changed(self) -> None:
        if not hasattr(self, "_profile_combo"):
            return
        profile_id = str(self._profile_combo.currentData() or "oficina_real")
        profile = HIGHLIGHT_PROFILES.get(profile_id, HIGHLIGHT_PROFILES["oficina_real"])
        self._loading_profile = True
        try:
            self._set_color_by_rgb(profile.color)
            self._opacity_slider.setValue(round(profile.opacity * 100))
            self._roughness_slider.setValue(round(profile.roughness * 100))
            self._pressure_slider.setValue(round(profile.pressure * 100))
            self._streak_slider.setValue(round(profile.streakiness * 100))
            self._bleed_slider.setValue(round(profile.bleed * 100))
            self._overshoot_slider.setValue(round(profile.overshoot * 100))
            self._passes_spin.setValue(profile.passes)
            self._slant_spin.setValue(round(profile.slant_deg))
        finally:
            self._loading_profile = False
        self._on_options_changed()

    def _on_options_changed(self) -> None:
        if self._loading_profile:
            return
        if hasattr(self, "_canvas"):
            self._canvas.set_options(self._build_options())
        if hasattr(self, "_proc_step") and self.stack.currentIndex() == 2:
            self._refresh_summary()

    def _build_options(self) -> HighlightOptions:
        profile_id = str(self._profile_combo.currentData() or "oficina_real") if hasattr(self, "_profile_combo") else "oficina_real"
        return HighlightOptions(
            profile_id=profile_id,
            color=self._color(),
            opacity=self._opacity_slider.value() / 100.0,
            roughness=self._roughness_slider.value() / 100.0,
            pressure=self._pressure_slider.value() / 100.0,
            streakiness=self._streak_slider.value() / 100.0,
            bleed=self._bleed_slider.value() / 100.0,
            overshoot=self._overshoot_slider.value() / 100.0,
            passes=int(self._passes_spin.value()),
            slant_deg=float(self._slant_spin.value()),
            seed=int(self._seed_spin.value()),
        )

    def _color(self) -> tuple[float, float, float]:
        color_id = str(self._color_combo.currentData() or "amarillo")
        return COLOR_CHOICES.get(color_id, COLOR_CHOICES["amarillo"])[1]

    def _set_color_by_rgb(self, rgb: tuple[float, float, float]) -> None:
        best_index = 0
        best_delta = 999.0
        for index in range(self._color_combo.count()):
            color_id = str(self._color_combo.itemData(index))
            candidate = COLOR_CHOICES.get(color_id, COLOR_CHOICES["amarillo"])[1]
            delta = sum(abs(candidate[i] - rgb[i]) for i in range(3))
            if delta < best_delta:
                best_delta = delta
                best_index = index
        self._color_combo.setCurrentIndex(best_index)

    def _sync_highlight_labels(self) -> None:
        total = self._canvas.page_count()
        current_index = self._canvas.current_page()
        current = current_index + 1 if total else 0
        current_marks = self._canvas.current_page_highlights()
        total_marks = self._canvas.total_highlights()
        self._page_lbl.setText(f"Pagina {current}/{total}" if total else "Pagina -/-")
        self._mark_count_lbl.setText(
            f"{current_marks} en esta pagina · "
            f"{total_marks} total"
        )
        self._prev_page_btn.setEnabled(total > 0 and current_index > 0)
        self._next_page_btn.setEnabled(total > 0 and current_index < total - 1)
        self._undo_btn.setEnabled(current_marks > 0)
        self._clear_page_btn.setEnabled(current_marks > 0)
        self._clear_all_btn.setEnabled(total_marks > 0)
        if hasattr(self, "_proc_step"):
            self._proc_step.set_run_enabled(
                len(self._docs_card.paths()) == 1 and total_marks > 0
            )

    def _validate_ready(self) -> Optional[str]:
        paths = self._docs_card.paths()
        if len(paths) != 1:
            return "Carga exactamente un PDF."
        if self._canvas.path != paths[0]:
            self._load_canvas_if_ready()
        if self._canvas.total_highlights() <= 0:
            return "Dibuja al menos un trazo de marcatexto."
        return None

    def _refresh_summary(self) -> None:
        paths = self._docs_card.paths()
        name = Path(paths[0]).name if len(paths) == 1 else "Sin documento"
        options = self._build_options()
        profile = HIGHLIGHT_PROFILES.get(options.profile_id, HIGHLIGHT_PROFILES["oficina_real"])
        rows = [
            f"<b>Documento:</b>&nbsp;&nbsp;{name}",
            f"<b>Perfil:</b>&nbsp;&nbsp;{profile.label}",
            f"<b>Paginas con trazos:</b>&nbsp;&nbsp;{self._canvas.pages_with_highlights()}",
            f"<b>Trazos totales:</b>&nbsp;&nbsp;{self._canvas.total_highlights()}",
            f"<b>Opacidad:</b>&nbsp;&nbsp;{round(options.opacity * 100)} %",
            f"<b>Textura:</b>&nbsp;&nbsp;{round(options.roughness * 100)} % rugosidad · {round(options.streakiness * 100)} % vetas",
            "<b>Salida:</b>&nbsp;&nbsp;PDF temporal con marcatexto aplanado",
        ]
        error = self._validate_ready()
        if error:
            rows.insert(0, f"<span style='color:#E5484D;'>Atencion: {error}</span>")
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )

    def _build_jobs(self) -> List[HighlightJob]:
        out_dir = make_run_dir("Subrayador")
        add_suffix = add_tool_suffix_enabled()
        source = self._docs_card.paths()[0]
        out_path = unique_output_path_for_source(
            out_dir,
            source,
            extension=".pdf",
            tool_suffix="subrayado",
            add_tool_suffix=add_suffix,
            fallback="documento",
        )
        return [
            HighlightJob(
                pdf_path=source,
                output_path=str(out_path),
                marks=self._canvas.highlight_marks(),
                options=self._build_options(),
            )
        ]

    def _on_run(self) -> None:
        self._stop_active_worker()
        error = self._validate_ready()
        if error:
            show_warning(self, "Falta informacion", error)
            return
        if self._worker_thread is not None:
            return

        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []

        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Preparando subrayado...")

        self._worker = HighlightWorker(self._build_jobs())
        self._worker_thread = RunnerThread(self._worker.run, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._proc_step.set_progress(self._current_progress(), "Cancelando...")

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        self._proc_step.set_progress(int(current / max(1, total) * 100), msg)

    def _on_finished(self, results: list) -> None:
        self._cleanup_thread()
        self.last_results = list(results)
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Subrayado completado")

        output_paths = [
            result.output_path
            for result in self.last_results
            if result.success and result.output_path
        ]
        self.ctx.tray.add_items(output_paths, "Subrayador realista")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        self._result_viewer.set_results(self.last_results)
        self._result_viewer.set_source_dirs([
            str(Path(result.job.pdf_path).parent)
            for result in self.last_results
        ])

        ok = sum(1 for result in self.last_results if result.success)
        failed = len(self.last_results) - ok
        marks = sum(result.mark_count for result in self.last_results if result.success)
        msg = f"Se genero {ok} PDF subrayado.\nTrazos aplicados: {marks}"
        if failed:
            msg += f"\nCon error: {failed}"
            show_warning(self, "Subrayado completado con avisos", msg)
        else:
            show_success(self, "Subrayado completo", msg)
        self._switch_section(3)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al subrayar PDF", msg)

    def _cleanup_thread(self) -> None:
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
            self._worker_thread = None
        self._worker = None

    def _current_progress(self) -> int:
        bar = getattr(self._proc_step, "_prog_bar", None)
        return int(bar.value()) if bar is not None else 0

    def _open_in_explorer(self, path: str) -> None:
        from ui.common.open_utils import open_folder
        open_folder(self, path, title="Abrir carpeta")

    def _reset_session(self) -> None:
        self.last_results = []
        self._docs_card.clear()
        self._canvas.close_doc()
        self._docs_summary_lbl.setText("Sin documento cargado.")
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._proc_step.reset()
        self._switch_section(0)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        from ui.common.file_ordering import paths_from_mime_data

        self.handle_drop(paths_from_mime_data(event.mimeData()))
        event.acceptProposedAction()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "stack") and self.stack.currentIndex() == 1:
            QTimer.singleShot(0, self._refit_canvas_view)

    def closeEvent(self, event) -> None:
        self._canvas.close_doc()
        super().closeEvent(event)
