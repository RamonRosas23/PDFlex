"""RedactorWindow - secure manual PDF redaction."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import fitz
from PIL import Image
from PyQt6.QtCore import QObject, QPointF, QRectF, QThread, QUrl, Qt, pyqtSignal
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
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QComboBox, QScrollArea,
)

from core.output_naming import unique_output_path_for_source
from core.output_paths import make_run_dir
from core.redaction_engine import (
    RedactionEngine,
    RedactionJob,
    RedactionOptions,
    RedactionRect,
    RedactionResult,
)
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.documents_step import DocumentsCard
from ui.common.icons import set_button_icon
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.process_step import ProcessStep
from ui.common.send_to_tool import SendToToolButton
from ui.common.tool_scaffold import PipelineWindow


class RedactionWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[RedactionJob]) -> None:
        super().__init__()
        self.jobs = jobs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = RedactionEngine().run_batch(
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


class RedactionCanvas(QWidget):
    changed = pyqtSignal()
    pageChanged = pyqtSignal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._doc: fitz.Document | None = None
        self._path = ""
        self._page_index = 0
        self._pixmap = QPixmap()
        self._rects: dict[int, list[QRectF]] = {}
        self._drag_start: QPointF | None = None
        self._drag_current: QPointF | None = None
        self.setMinimumSize(520, 640)
        self.setMouseTracking(True)
        self.setStyleSheet("background:#0D0D10;")

    @property
    def path(self) -> str:
        return self._path

    def load_pdf(self, path: str) -> None:
        self.close_doc()
        self._path = path
        self._doc = fitz.open(path)
        self._page_index = 0
        self._rects = {}
        self._render_current()
        self.changed.emit()
        self.pageChanged.emit(self._page_index, self.page_count())

    def close_doc(self) -> None:
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
        self._doc = None
        self._path = ""
        self._page_index = 0
        self._pixmap = QPixmap()
        self._rects = {}
        self._drag_start = None
        self._drag_current = None
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

    def add_redaction_norm(
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
        self._rects.setdefault(page_index, []).append(rect)
        self.changed.emit()
        self.update()

    def undo_current_page(self) -> None:
        rects = self._rects.get(self._page_index, [])
        if rects:
            rects.pop()
            if not rects:
                self._rects.pop(self._page_index, None)
            self.changed.emit()
            self.update()

    def clear_current_page(self) -> None:
        if self._rects.pop(self._page_index, None) is not None:
            self.changed.emit()
            self.update()

    def clear_all(self) -> None:
        if self._rects:
            self._rects.clear()
            self.changed.emit()
            self.update()

    def total_redactions(self) -> int:
        return sum(len(rects) for rects in self._rects.values())

    def current_page_redactions(self) -> int:
        return len(self._rects.get(self._page_index, []))

    def pages_with_redactions(self) -> int:
        return sum(1 for rects in self._rects.values() if rects)

    def redaction_rects(self) -> List[RedactionRect]:
        out: List[RedactionRect] = []
        for page_index, rects in sorted(self._rects.items()):
            for rect in rects:
                out.append(
                    RedactionRect(
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
            self._pixmap = QPixmap()
            self.setFixedSize(520, 640)
            self.update()
            return
        page = self._doc[self._page_index]
        page_long = max(1.0, page.rect.width, page.rect.height)
        dpi = max(36.0, min(140.0, 1400.0 * 72.0 / page_long))
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
        data = image.tobytes("raw", "RGBA")
        qimage = QImage(data, image.width, image.height, QImage.Format.Format_RGBA8888)
        self._pixmap = QPixmap.fromImage(qimage.copy())
        self.setFixedSize(self._pixmap.size())
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0D0D10"))
        if not self._pixmap.isNull():
            painter.drawPixmap(0, 0, self._pixmap)
            self._draw_rects(painter)
        else:
            painter.setPen(QColor("#9094A0"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Carga un PDF para redactar.")
        painter.end()
        super().paintEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._pixmap.isNull():
            self._drag_start = self._clamp_point(event.position())
            self._drag_current = self._drag_start
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start is not None:
            self._drag_current = self._clamp_point(event.position())
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            end = self._clamp_point(event.position())
            rect_px = QRectF(self._drag_start, end).normalized()
            self._drag_start = None
            self._drag_current = None
            if rect_px.width() >= 6 and rect_px.height() >= 6:
                self.add_redaction_norm(
                    self._page_index,
                    rect_px.left() / max(1, self._pixmap.width()),
                    rect_px.top() / max(1, self._pixmap.height()),
                    rect_px.right() / max(1, self._pixmap.width()),
                    rect_px.bottom() / max(1, self._pixmap.height()),
                )
            self.update()
        super().mouseReleaseEvent(event)

    def _draw_rects(self, painter: QPainter) -> None:
        fill = QBrush(QColor(0, 0, 0, 150))
        pen = QPen(QColor("#EF4444"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(fill)
        for rect in self._rects.get(self._page_index, []):
            painter.drawRect(self._norm_to_px(rect))

        if self._drag_start is not None and self._drag_current is not None:
            preview_pen = QPen(QColor("#F97316"))
            preview_pen.setWidth(2)
            preview_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(preview_pen)
            painter.setBrush(QBrush(QColor(249, 115, 22, 90)))
            painter.drawRect(QRectF(self._drag_start, self._drag_current).normalized())

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


class RedactorWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documento", "Carga un PDF"),
        ("02", "Redactar", "Dibuja zonas seguras"),
        ("03", "Procesar", "Elimina contenido sensible"),
        ("04", "Resultados", "Revisa el PDF redactado"),
    ]
    BRAND = "Redaccion segura"
    TAGLINE = "Elimina informacion de forma real"
    ACCENT_COLOR = "#EF4444"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[RedactionResult] = []
        self._worker: Optional[RedactionWorker] = None
        self._worker_thread: Optional[QThread] = None

        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_redaction_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documento a redactar",
            "Carga un solo PDF por sesion para dibujar zonas manuales con precision.",
        ))

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=False,
            show_thumbnails=True,
            thumb_size=(64, 82),
            file_filter="PDF (*.pdf)",
        )
        self._docs_card.files_changed.connect(self._on_docs_changed)
        outer.addWidget(self._docs_card, 1)

        self._docs_summary_lbl = QLabel("Sin documento cargado.")
        self._docs_summary_lbl.setProperty("class", "CardHint")
        self._docs_summary_lbl.setWordWrap(True)
        outer.addWidget(self._docs_summary_lbl)

        nav = QHBoxLayout()
        nav.addStretch()
        next_btn = QPushButton("Continuar")
        next_btn.setProperty("class", "Primary")
        next_btn.setMinimumWidth(160)
        set_button_icon(next_btn, "arrow-right")
        next_btn.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(next_btn)
        outer.addLayout(nav)
        return page

    def _build_redaction_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(18)

        outer.addLayout(make_page_header(
            "Redactar zonas sensibles",
            "Dibuja rectangulos sobre datos sensibles. Al procesar, el contenido se elimina del PDF.",
        ))

        body = QHBoxLayout()
        body.setSpacing(16)

        controls = make_card("Controles")
        controls.setFixedWidth(280)
        cl = card_layout(controls)

        self._page_lbl = QLabel("Pagina -/-")
        self._page_lbl.setProperty("class", "CardTitle")
        cl.addWidget(self._page_lbl)

        nav_row = QHBoxLayout()
        prev_btn = QPushButton("Anterior")
        prev_btn.setProperty("class", "Ghost")
        set_button_icon(prev_btn, "chevron-left")
        prev_btn.clicked.connect(self._previous_page)
        nav_row.addWidget(prev_btn)
        next_btn = QPushButton("Siguiente")
        next_btn.setProperty("class", "Ghost")
        set_button_icon(next_btn, "chevron-right")
        next_btn.clicked.connect(self._next_page)
        nav_row.addWidget(next_btn)
        cl.addLayout(nav_row)

        self._rect_count_lbl = QLabel("0 zonas")
        self._rect_count_lbl.setProperty("class", "CardHint")
        cl.addWidget(self._rect_count_lbl)

        undo_btn = QPushButton("Deshacer zona")
        undo_btn.setProperty("class", "Ghost")
        set_button_icon(undo_btn, "arrow-left")
        undo_btn.clicked.connect(self._undo_page)
        cl.addWidget(undo_btn)

        clear_page_btn = QPushButton("Limpiar pagina")
        clear_page_btn.setProperty("class", "Ghost")
        set_button_icon(clear_page_btn, "eraser")
        clear_page_btn.clicked.connect(self._clear_page)
        cl.addWidget(clear_page_btn)

        clear_all_btn = QPushButton("Limpiar todo")
        clear_all_btn.setProperty("class", "Danger")
        set_button_icon(clear_all_btn, "trash-2", color="#E5484D")
        clear_all_btn.clicked.connect(self._clear_all)
        cl.addWidget(clear_all_btn)

        self._fill_combo = QComboBox()
        self._fill_combo.addItem("Relleno negro", "black")
        self._fill_combo.addItem("Relleno blanco", "white")
        cl.addWidget(self._fill_combo)
        cl.addStretch(1)
        body.addWidget(controls)

        viewer = make_card("Vista de pagina")
        vl = card_layout(viewer)
        self._canvas = RedactionCanvas()
        self._canvas.changed.connect(self._sync_redaction_labels)
        self._canvas.pageChanged.connect(lambda *_: self._sync_redaction_labels())
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(self._canvas)
        vl.addWidget(scroll, 1)
        body.addWidget(viewer, 1)

        outer.addLayout(body, 1)

        nav = QHBoxLayout()
        back = QPushButton("Documento")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(0))
        nav.addWidget(back)
        nav.addStretch()
        next_step = QPushButton("Continuar")
        next_step.setProperty("class", "Primary")
        next_step.setMinimumWidth(160)
        set_button_icon(next_step, "arrow-right")
        next_step.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(next_step)
        outer.addLayout(nav)
        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar redaccion",
            "PDFlex aplicara redacciones reales y guardara un PDF temporal seguro.",
        ))

        self._proc_step = ProcessStep(
            run_label="Redactar PDF",
            show_output_dir=False,
        )
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Redactar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(back)
        outer.addLayout(nav)
        return page

    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultados",
            "Revisa el PDF redactado antes de guardarlo o enviarlo a otra herramienta.",
        ))

        self._result_viewer = GenericPdfViewer("PDF redactado")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        nav.addStretch()

        self._send_btn = SendToToolButton(self.ctx, "redactor")
        nav.addWidget(self._send_btn)

        restart = QPushButton("Nueva sesion")
        restart.setProperty("class", "Primary")
        restart.setMinimumWidth(180)
        set_button_icon(restart, "refresh-cw")
        restart.clicked.connect(self._reset_session)
        nav.addWidget(restart)
        outer.addLayout(nav)
        return page

    def _on_section_activated(self, idx: int) -> None:
        if idx == 1:
            self._load_canvas_if_ready()
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
            self._docs_summary_lbl.setText("1 documento listo para redactar.")
            self._load_canvas_if_ready()
        else:
            self._docs_summary_lbl.setText("Carga un solo PDF por sesion para redaccion manual.")
            self._canvas.close_doc()
        self._sync_redaction_labels()

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

    def _next_page(self) -> None:
        self._canvas.next_page()

    def _undo_page(self) -> None:
        self._canvas.undo_current_page()

    def _clear_page(self) -> None:
        self._canvas.clear_current_page()

    def _clear_all(self) -> None:
        self._canvas.clear_all()

    def _sync_redaction_labels(self) -> None:
        current = self._canvas.current_page() + 1 if self._canvas.page_count() else 0
        total = self._canvas.page_count()
        self._page_lbl.setText(f"Pagina {current}/{total}" if total else "Pagina -/-")
        self._rect_count_lbl.setText(
            f"{self._canvas.current_page_redactions()} en esta pagina · "
            f"{self._canvas.total_redactions()} total"
        )

    def _fill_color(self) -> tuple[float, float, float]:
        return (1.0, 1.0, 1.0) if self._fill_combo.currentData() == "white" else (0.0, 0.0, 0.0)

    def _validate_ready(self) -> Optional[str]:
        paths = self._docs_card.paths()
        if len(paths) != 1:
            return "Carga exactamente un PDF."
        if self._canvas.path != paths[0]:
            self._load_canvas_if_ready()
        if self._canvas.total_redactions() <= 0:
            return "Dibuja al menos una zona de redaccion."
        return None

    def _refresh_summary(self) -> None:
        paths = self._docs_card.paths()
        name = Path(paths[0]).name if len(paths) == 1 else "Sin documento"
        rows = [
            f"<b>Documento:</b>&nbsp;&nbsp;{name}",
            f"<b>Paginas con zonas:</b>&nbsp;&nbsp;{self._canvas.pages_with_redactions()}",
            f"<b>Zonas totales:</b>&nbsp;&nbsp;{self._canvas.total_redactions()}",
            f"<b>Relleno:</b>&nbsp;&nbsp;{'blanco' if self._fill_combo.currentData() == 'white' else 'negro'}",
            "<b>Seguridad:</b>&nbsp;&nbsp;redaccion real de texto, imagenes y graficos tocados",
            "<b>Salida:</b>&nbsp;&nbsp;PDF temporal",
        ]
        error = self._validate_ready()
        if error:
            rows.insert(0, f"<span style='color:#E5484D;'>Atencion: {error}</span>")
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )

    def _build_jobs(self) -> List[RedactionJob]:
        out_dir = make_run_dir("RedaccionSegura")
        add_suffix = add_tool_suffix_enabled()
        source = self._docs_card.paths()[0]
        out_path = unique_output_path_for_source(
            out_dir,
            source,
            extension=".pdf",
            tool_suffix="redactado",
            add_tool_suffix=add_suffix,
            fallback="documento",
        )
        return [
            RedactionJob(
                pdf_path=source,
                output_path=str(out_path),
                rects=self._canvas.redaction_rects(),
                options=RedactionOptions(fill_color=self._fill_color()),
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
        self._proc_step.set_progress(0, "Preparando redaccion...")

        self._worker = RedactionWorker(self._build_jobs())
        self._worker_thread = QThread(self)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
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
        self._proc_step.set_progress(100, "Redaccion completada")

        output_paths = [
            result.output_path
            for result in self.last_results
            if result.success and result.output_path
        ]
        self.ctx.tray.add_items(output_paths, "Redaccion segura")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        self._result_viewer.set_results(self.last_results)
        self._result_viewer.set_source_dirs([
            str(Path(result.job.pdf_path).parent)
            for result in self.last_results
        ])

        ok = sum(1 for result in self.last_results if result.success)
        failed = len(self.last_results) - ok
        redactions = sum(result.redaction_count for result in self.last_results if result.success)
        msg = f"Se genero {ok} PDF redactado.\nRedacciones aplicadas: {redactions}"
        if failed:
            msg += f"\nCon error: {failed}"
            show_warning(self, "Redaccion completada con avisos", msg)
        else:
            show_success(self, "Redaccion completa", msg)
        self._switch_section(3)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al redactar PDF", msg)

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
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

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
        self.handle_drop([url.toLocalFile() for url in event.mimeData().urls()])
        event.acceptProposedAction()

    def closeEvent(self, event) -> None:
        self._canvas.close_doc()
        super().closeEvent(event)
