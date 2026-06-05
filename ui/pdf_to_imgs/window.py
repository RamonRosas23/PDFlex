"""PdfToImgsWindow — pipeline de conversión de PDFs a imágenes.

Pipeline:
    01 Documentos  →  02 Formato  →  03 Procesar  →  04 Resultados
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QComboBox, QCheckBox, QGridLayout,
)

from ui.common.documents_step import DocumentsCard
from ui.common.process_step import ProcessStep

from core.pdf_to_images_engine import (
    PdfToImagesConfig, PdfToImagesJob, PdfToImagesEngine,
    PdfToImagesJobResult, ImageResult,
)
from core.output_paths import make_run_dir, unique_name
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.image_results_viewer import ImageResultsViewer
from ui.common.slider import SliderWithValue
from ui.common.tool_scaffold import PipelineWindow
from ui.common.send_to_tool import SendToToolButton
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.icons import set_button_icon


# ====================================================================== #
#  Worker
# ====================================================================== #

class PdfToImgsWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[PdfToImagesJob], config: PdfToImagesConfig) -> None:
        super().__init__()
        self.jobs = jobs
        self.config = config
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            engine = PdfToImagesEngine()
            results = engine.run_batch(
                self.jobs,
                self.config,
                progress=lambda c, t, m: self.progress.emit(c, t, m),
                should_cancel=lambda: self._cancel,
            )
            if self._cancel:
                self.error.emit("Operación cancelada.")
            else:
                self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


# ====================================================================== #
#  Ventana PDF a Imágenes
# ====================================================================== #

class PdfToImgsWindow(PipelineWindow):

    SECTIONS = [
        ("01", "Documentos", "Carga los PDFs a convertir"),
        ("02", "Formato",    "DPI, formato y modo"),
        ("03", "Procesar",   "Ejecuta la conversión"),
        ("04", "Resultados", "Revisa las imágenes generadas"),
    ]
    BRAND = "PDF a Imágenes"
    TAGLINE = "Exporta páginas PDF como PNG, JPG o WebP"
    ACCENT_COLOR = "#4CC9F0"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)

        self.last_results: List[PdfToImagesJobResult] = []
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[PdfToImgsWorker] = None

        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_format_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    # ------------------------------------------------------------------ #
    # Paso 01: Documentos
    # ------------------------------------------------------------------ #

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documentos a convertir",
            "Carga los PDFs cuyas páginas exportarás como imágenes.",
        ))

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=True,
            show_thumbnails=True,
            thumb_size=(64, 82),
            file_filter="PDF (*.pdf)",
        )
        outer.addWidget(self._docs_card, 1)

        nav = QHBoxLayout()
        nav.addStretch()
        nxt = QPushButton("Continuar")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        set_button_icon(nxt, "arrow-right")
        nxt.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(nxt)
        outer.addLayout(nav)

        return page

    # ------------------------------------------------------------------ #
    # Paso 02: Formato
    # ------------------------------------------------------------------ #

    def _build_format_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Formato de exportación",
            "Configura la resolución y el formato de las imágenes generadas.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Formato
        c_fmt = make_card("Formato de imagen")
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItems(["PNG (sin pérdida)", "JPG (comprimido)", "WebP (eficiente)"])
        self._fmt_combo.currentIndexChanged.connect(self._on_fmt_changed)
        card_layout(c_fmt).addWidget(self._fmt_combo)
        grid.addWidget(c_fmt, 0, 0)

        # DPI
        c_dpi = make_card("Resolución (DPI)",
                          "Mayor DPI = mayor calidad y tamaño de archivo")
        self._dpi_slider = SliderWithValue(72.0, 600.0, 150.0, step=1.0, suffix=" DPI", decimals=0)
        card_layout(c_dpi).addWidget(self._dpi_slider)
        grid.addWidget(c_dpi, 0, 1)

        # Modo
        c_mode = make_card("Modo de exportación")
        mode_l = card_layout(c_mode)
        self._panoramic_chk = QCheckBox(
            "Imagen panorámica vertical (todas las páginas en una sola imagen)"
        )
        mode_l.addWidget(self._panoramic_chk)
        mode_hint = QLabel(
            "Por defecto exporta una imagen por página con el nombre {doc}_p001.png"
        )
        mode_hint.setProperty("class", "CardHint")
        mode_hint.setWordWrap(True)
        mode_l.addWidget(mode_hint)
        grid.addWidget(c_mode, 1, 0, 1, 2)

        # Calidad JPG/WebP
        c_q = make_card("Calidad JPG / WebP", "Aplica solo para JPG y WebP (1 = mínima, 100 = máxima)")
        self._quality_slider = SliderWithValue(1.0, 100.0, 90.0, step=1.0, decimals=0)
        self._quality_slider.setEnabled(False)
        card_layout(c_q).addWidget(self._quality_slider)
        grid.addWidget(c_q, 2, 0, 1, 2)

        outer.addLayout(grid)
        outer.addStretch(1)

        nav = QHBoxLayout()
        back = QPushButton("Documentos")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(0))
        nav.addWidget(back)
        nav.addStretch()
        nxt = QPushButton("Continuar")
        nxt.setProperty("class", "Primary")
        nxt.setMinimumWidth(160)
        set_button_icon(nxt, "arrow-right")
        nxt.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(nxt)
        outer.addLayout(nav)

        return page

    # ------------------------------------------------------------------ #
    # Paso 03: Procesar (via ProcessStep compartido)
    # ------------------------------------------------------------------ #

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Genera las imágenes en temporal; usa \"Guardar como\" para conservarlas.",
        ))

        self._proc_step = ProcessStep(
            run_label="Convertir a imágenes",
            show_output_dir=False,
        )
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Formato")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(back)
        outer.addLayout(nav)

        return page

    # ------------------------------------------------------------------ #
    # Paso 04: Resultados
    # ------------------------------------------------------------------ #

    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultados",
            "Revisa las imágenes exportadas.",
        ))

        self._img_viewer = ImageResultsViewer()
        self._img_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._img_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        nav.addStretch()

        # Las imágenes generadas sólo se ofrecerán a herramientas compatibles.
        self._send_btn = SendToToolButton(self.ctx, "pdf_to_imgs")
        nav.addWidget(self._send_btn)

        restart_btn = QPushButton("Nueva sesión")
        restart_btn.setProperty("class", "Primary")
        restart_btn.setMinimumWidth(180)
        set_button_icon(restart_btn, "refresh-cw")
        restart_btn.clicked.connect(self._reset_session)
        nav.addWidget(restart_btn)
        outer.addLayout(nav)

        return page

    # ------------------------------------------------------------------ #
    # Hooks
    # ------------------------------------------------------------------ #

    def _on_section_activated(self, idx: int) -> None:
        if idx == 2:
            self._refresh_summary()

    # ------------------------------------------------------------------ #
    # API PipelineWindow
    # ------------------------------------------------------------------ #

    def set_inputs(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    # ------------------------------------------------------------------ #
    # Formato
    # ------------------------------------------------------------------ #

    def _on_fmt_changed(self, idx: int) -> None:
        # Habilitar calidad solo para JPG/WebP
        self._quality_slider.setEnabled(idx in (1, 2))

    def _read_config(self) -> PdfToImagesConfig:
        fmt_map = {0: "png", 1: "jpg", 2: "webp"}
        return PdfToImagesConfig(
            format=fmt_map.get(self._fmt_combo.currentIndex(), "png"),
            dpi=int(self._dpi_slider.value()),
            panoramic=self._panoramic_chk.isChecked(),
            jpg_quality=int(self._quality_slider.value()),
        )

    # ------------------------------------------------------------------ #
    # Procesar
    # ------------------------------------------------------------------ #

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._proc_step.set_progress(self._proc_step._prog_bar.value(), "Cancelando…")

    def _refresh_summary(self) -> None:
        cfg = self._read_config()
        n = self._docs_card.count()
        fmt_names = {"png": "PNG", "jpg": "JPG", "webp": "WebP"}
        mode_txt = "una imagen panorámica por PDF" if cfg.panoramic else "una imagen por página"
        rows = [
            f"<b>Documentos:</b> &nbsp; {n}",
            f"<b>Formato:</b> &nbsp; {fmt_names.get(cfg.format, cfg.format)}",
            f"<b>Resolución:</b> &nbsp; {cfg.dpi} DPI",
            f"<b>Modo:</b> &nbsp; {mode_txt}",
        ]
        if cfg.format in ("jpg", "webp"):
            rows.append(f"<b>Calidad:</b> &nbsp; {cfg.jpg_quality} %")
        html = "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        self._proc_step.set_summary_html(html)

    def _validate_ready(self) -> Optional[str]:
        if self._docs_card.is_empty():
            return "Agrega al menos un documento."
        return None

    def _build_jobs(self, cfg: PdfToImagesConfig) -> List[PdfToImagesJob]:
        base_dir = make_run_dir("PDFaImagenes")
        jobs = []
        reserved: set[str] = set()
        add_suffix = add_tool_suffix_enabled()
        for p in self._docs_card.paths():
            stem = unique_name(
                Path(p).stem,
                reserved=reserved,
                directory=base_dir,
                fallback="documento",
            )
            task_dir = base_dir / stem
            task_dir.mkdir(parents=True, exist_ok=True)
            jobs.append(PdfToImagesJob(
                pdf_path=p,
                output_dir=str(task_dir),
                base_name=stem,
                tool_suffix="imagenes",
                add_tool_suffix=add_suffix,
            ))
        return jobs

    def _on_run(self) -> None:
        err = self._validate_ready()
        if err:
            show_warning(self, "Falta información", err)
            return
        if self._worker_thread is not None:
            return

        self._img_viewer.clear_results()
        self._send_btn.set_output_paths([])
        cfg = self._read_config()
        jobs = self._build_jobs(cfg)

        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Iniciando…")

        self._worker_thread = QThread(self)
        self._worker = PdfToImgsWorker(jobs, cfg)
        self._worker.moveToThread(self._worker_thread)

        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)

        self._worker_thread.start()

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        self._proc_step.set_progress(int(current / max(1, total) * 100), msg)

    def _on_finished(self, results: list) -> None:
        self.last_results = list(results)
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Completado")
        self._worker_thread = None
        self._worker = None

        all_img_results: List[ImageResult] = []
        ok_files = 0
        for job_result in results:
            all_img_results.extend(job_result.image_results)
            ok_files += sum(1 for r in job_result.image_results if r.success)

        output_paths = [r.output_path for r in all_img_results if r.success and r.output_path]
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        show_success(
            self, "Conversión completa",
            f"Se generaron {ok_files} imagen{'es' if ok_files != 1 else ''}.",
        )
        self._img_viewer.set_results(all_img_results)
        src_dirs = [
            str(Path(jr.job.pdf_path).parent)
            for jr in results
            for _ in jr.image_results
        ]
        self._img_viewer.set_source_dirs(src_dirs)
        self._switch_section(3)

    def _on_worker_error(self, msg: str) -> None:
        show_error(self, "Error", msg)
        self._proc_step.set_running(False)
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
            self._worker_thread.deleteLater()
            self._worker_thread = None
            self._worker = None

    def _open_in_explorer(self, path: str) -> None:
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    # ------------------------------------------------------------------ #
    # Reset
    # ------------------------------------------------------------------ #

    def _reset_session(self) -> None:
        self._img_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []
        self._docs_card.clear()
        self._proc_step.reset()
        self._switch_section(0)

    # ------------------------------------------------------------------ #
    # Drag & drop
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        self._docs_card.add_paths(paths)
        self._switch_section(0)
