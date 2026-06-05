"""QuitarFondoWindow — herramienta dedicada para remover fondos de imágenes."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QGridLayout,
)

from core.background_removal_engine import (
    BackgroundRemovalEngine,
    BackgroundRemovalJob,
    BackgroundRemovalResult,
)
from core.output_paths import make_run_dir
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.dialogs import show_error, show_success, show_warning
from ui.common.image_results_viewer import ImageResultsViewer
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.process_step import ProcessStep
from ui.common.send_to_tool import SendToToolButton
from ui.common.slider import SliderWithValue
from ui.common.tool_scaffold import PipelineWindow
from ui.common.icons import set_button_icon
from ui.imgs_a_pdf.window import IMAGE_EXTS, ImageListCard


class RemoveBackgroundWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[BackgroundRemovalJob]) -> None:
        super().__init__()
        self.jobs = jobs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = BackgroundRemovalEngine().run_batch(
                self.jobs,
                progress=lambda c, t, m: self.progress.emit(c, t, m),
                should_cancel=lambda: self._cancel,
            )
            if self._cancel:
                self.error.emit("Operación cancelada.")
            else:
                self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


class QuitarFondoWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Imágenes", "Carga las imágenes a limpiar"),
        ("02", "Ajustes", "Controla la fuerza de limpieza"),
        ("03", "Procesar", "Genera PNGs transparentes"),
        ("04", "Resultados", "Revisa las imágenes generadas"),
    ]
    BRAND = "Quitar fondo"
    TAGLINE = "Convierte fondos uniformes en transparencia"
    ACCENT_COLOR = "#00B894"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[BackgroundRemovalResult] = []
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[RemoveBackgroundWorker] = None

        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_images_section())
        self.stack.addWidget(self._build_options_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_images_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Imágenes",
            "Carga imágenes con fondo blanco o uniforme. La salida será PNG con transparencia.",
        ))

        self._img_card = ImageListCard()
        self._img_card.files_changed.connect(self._on_files_changed)
        outer.addWidget(self._img_card, 1)

        self._imgs_summary_lbl = QLabel("Sin imágenes cargadas.")
        self._imgs_summary_lbl.setProperty("class", "CardHint")
        outer.addWidget(self._imgs_summary_lbl)

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

    def _build_options_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Ajustes de limpieza",
            "Ajusta qué tan variable puede ser el fondo antes de convertirlo en transparencia.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        strength_card = make_card(
            "Fuerza de limpieza",
            "Valor alto elimina fondos más variables; valor bajo conserva más bordes claros.",
        )
        self._tolerance_slider = SliderWithValue(
            5.0,
            80.0,
            30.0,
            step=1.0,
            suffix="",
            decimals=0,
        )
        card_layout(strength_card).addWidget(self._tolerance_slider)
        grid.addWidget(strength_card, 0, 0, 1, 2)

        format_card = make_card(
            "Formato de salida",
            "La transparencia requiere PNG. Los nombres se generan en temporal y se pueden conservar con Guardar como.",
        )
        out_lbl = QLabel("PNG transparente")
        out_lbl.setProperty("class", "Mono")
        card_layout(format_card).addWidget(out_lbl)
        grid.addWidget(format_card, 1, 0)

        use_card = make_card(
            "Uso recomendado",
            "Funciona mejor con fotografías de documentos, firmas, sellos o logos sobre fondo blanco o liso.",
        )
        note = QLabel("Para fondos complejos, usa una fuerza moderada y revisa los bordes.")
        note.setProperty("class", "CardHint")
        note.setWordWrap(True)
        card_layout(use_card).addWidget(note)
        grid.addWidget(use_card, 1, 1)

        outer.addLayout(grid)
        outer.addStretch(1)

        nav = QHBoxLayout()
        back = QPushButton("Imágenes")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(0))
        nav.addWidget(back)
        nav.addStretch()
        next_btn = QPushButton("Continuar")
        next_btn.setProperty("class", "Primary")
        next_btn.setMinimumWidth(160)
        set_button_icon(next_btn, "arrow-right")
        next_btn.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(next_btn)
        outer.addLayout(nav)
        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Genera PNGs transparentes en temporal; usa Guardar como para conservarlos.",
        ))

        self._proc_step = ProcessStep(
            run_label="Quitar fondo",
            show_output_dir=False,
        )
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        self._proc_step.watch_documents(self._img_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Ajustes")
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
            "Revisa las imágenes con fondo transparente.",
        ))

        self._img_viewer = ImageResultsViewer("Imágenes sin fondo")
        self._img_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._img_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        nav.addStretch()

        self._send_btn = SendToToolButton(self.ctx, "quitar_fondo")
        nav.addWidget(self._send_btn)

        restart = QPushButton("Nueva sesión")
        restart.setProperty("class", "Primary")
        restart.setMinimumWidth(180)
        set_button_icon(restart, "refresh-cw")
        restart.clicked.connect(self._reset_session)
        nav.addWidget(restart)
        outer.addLayout(nav)
        return page

    def _on_section_activated(self, idx: int) -> None:
        if idx == 2:
            self._refresh_summary()

    def set_inputs(self, paths: List[str]) -> None:
        self._img_card.add_paths(self._image_paths(paths))
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._img_card.add_paths(self._image_paths(paths))
        self._switch_section(0)

    def _on_files_changed(self, paths: List[str]) -> None:
        count = len(paths)
        if count == 0:
            self._imgs_summary_lbl.setText("Sin imágenes cargadas.")
        else:
            self._imgs_summary_lbl.setText(
                f"{count} imagen{'es' if count != 1 else ''} · salida PNG transparente"
            )

    def _refresh_summary(self) -> None:
        count = self._img_card.count()
        rows = [
            f"<b>Imágenes:</b>&nbsp;&nbsp;{count}",
            f"<b>Fuerza de limpieza:</b>&nbsp;&nbsp;{self._tolerance_slider.value():.0f}",
            "<b>Salida:</b>&nbsp;&nbsp;PNG con transparencia",
        ]
        if count == 0:
            rows.insert(0, "<span style='color:#E5484D;'>Atención: no hay imágenes cargadas.</span>")
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )

    def _validate_ready(self) -> Optional[str]:
        if self._img_card.count() == 0:
            return "Agrega al menos una imagen."
        return None

    def _build_jobs(self) -> List[BackgroundRemovalJob]:
        out_dir = make_run_dir("QuitarFondo")
        tolerance = float(self._tolerance_slider.value())
        add_suffix = add_tool_suffix_enabled()
        return [
            BackgroundRemovalJob(
                image_path=path,
                output_dir=str(out_dir),
                tolerance=tolerance,
                add_tool_suffix=add_suffix,
            )
            for path in self._img_card.paths()
        ]

    def _on_run(self) -> None:
        error = self._validate_ready()
        if error:
            show_warning(self, "Falta información", error)
            return
        if self._worker_thread is not None:
            return

        self._img_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []

        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Preparando imágenes...")

        self._worker_thread = QThread(self)
        self._worker = RemoveBackgroundWorker(self._build_jobs())
        self._worker.moveToThread(self._worker_thread)

        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._proc_step.set_progress(self._current_progress(), "Cancelando...")

    def _on_progress(self, current: int, total: int, message: str) -> None:
        self._proc_step.set_progress(int(current / max(1, total) * 100), message)

    def _on_finished(self, results: list) -> None:
        self.last_results = list(results)
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Limpieza completada")
        self._worker_thread = None
        self._worker = None

        output_paths = [
            result.output_path
            for result in self.last_results
            if result.success and result.output_path
        ]
        errors = [result for result in self.last_results if not result.success]
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        self._img_viewer.set_results(self.last_results)
        self._img_viewer.set_source_dirs([
            str(Path(result.job.image_path).parent)
            for result in self.last_results
        ])

        msg = (
            f"Se generaron {len(output_paths)} imagen"
            + ("es" if len(output_paths) != 1 else "")
            + " sin fondo."
        )
        if errors:
            msg += f"\nCon error: {len(errors)}"
        if errors:
            show_warning(self, "Limpieza completada con avisos", msg)
        else:
            show_success(self, "Limpieza completa", msg)
        self._switch_section(3)

    def _on_worker_error(self, message: str) -> None:
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, "Proceso detenido")
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
            self._worker_thread.deleteLater()
            self._worker_thread = None
            self._worker = None
        show_error(self, "Error al quitar fondo", message)

    def _current_progress(self) -> int:
        bar = getattr(self._proc_step, "_prog_bar", None)
        return int(bar.value()) if bar is not None else 0

    def _open_in_explorer(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _reset_session(self) -> None:
        self.last_results = []
        self._img_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._img_card.clear()
        self._imgs_summary_lbl.setText("Sin imágenes cargadas.")
        self._proc_step.reset()
        self._switch_section(0)

    @staticmethod
    def _image_paths(paths: List[str]) -> List[str]:
        return [path for path in paths if Path(path).suffix.lower() in IMAGE_EXTS]

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.handle_drop([url.toLocalFile() for url in event.mimeData().urls()])
        event.acceptProposedAction()
