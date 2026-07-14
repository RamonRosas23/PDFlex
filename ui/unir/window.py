"""UnirWindow — pipeline para combinar múltiples PDFs en uno solo.

Pipeline:
    01 Documentos  →  02 Opciones  →  03 Procesar  →  04 Resultados
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QFrame, QLineEdit, QCheckBox,
)
from core.pdf_backend import pdf_page_count

from shell.context import ShellContext
from core.pdf_merge_engine import PdfMergeEngine, PdfMergeOptions, PdfMergeResult
from core.output_paths import filename_with_suffix, make_run_dir, unique_output_path
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.tool_scaffold import PipelineWindow, RunnerThread
from ui.common.document_workspace import DocumentWorkspace as DocumentsCard
from ui.common.process_step import ProcessStep
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.send_to_tool import SendToToolButton
from ui.common.dialogs import show_error, show_warning
from ui.common.icons import set_button_icon
from ui.styles import COLORS


# ====================================================================== #
#  Worker
# ====================================================================== #

class MergeWorker(QObject):
    progress = Signal(int, int, str)    # current, total, message
    finished = Signal(object)           # MergeResult
    error = Signal(str)

    def __init__(
        self,
        pdf_paths: List[str],
        output_path: str,
        blank_between: bool,
        add_bookmarks: bool,
    ) -> None:
        super().__init__()
        self.pdf_paths = pdf_paths
        self.output_path = output_path
        self.blank_between = blank_between
        self.add_bookmarks = add_bookmarks
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            result = PdfMergeEngine().run(
                self.pdf_paths,
                self.output_path,
                PdfMergeOptions(
                    blank_between=self.blank_between,
                    add_bookmarks=self.add_bookmarks,
                    validate_visual=True,
                ),
                progress=self.progress.emit,
                should_cancel=lambda: self._cancel,
            )
            if result.success:
                self.finished.emit(result)
            else:
                self.error.emit(result.error or "No se pudo unir los PDFs.")
        except Exception as exc:
            self.error.emit(str(exc))


# ====================================================================== #
#  Ventana principal
# ====================================================================== #

class UnirWindow(PipelineWindow):

    SECTIONS = [
        ("01", "Documentos", "Agrega los PDFs a unir"),
        ("02", "Opciones",   "Nombre de salida y ajustes"),
        ("03", "Procesar",   "Ejecuta la unión"),
        ("04", "Resultados", "Revisa el PDF combinado"),
    ]
    BRAND = "Unir PDFs"
    TAGLINE = "Combina múltiples documentos en uno solo"
    ACCENT_COLOR = "#FF9B3E"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)

        self._pdf_paths: List[str] = []
        self._last_result: Optional[MergeResult] = None
        self._worker: Optional[MergeWorker] = None
        self._worker_thread: Optional[QThread] = None
        self._page_cache: dict[str, int] = {}

        self._build_pages()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_options_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_action_buttons(self) -> None:
        from ui.common.icons import set_button_icon
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Unir PDFs")
        self._run_btn.setProperty("class", "Primary")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setMinimumWidth(160)
        set_button_icon(self._run_btn, "play")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        self._cancel_btn.setFixedHeight(36)
        set_button_icon(self._cancel_btn, "square", color="#E5484D")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._restart_btn = QPushButton("Nueva sesión")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()

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
            "Documentos a unir",
            "Agrega los PDFs en el orden en que deben aparecer en el resultado. "
            "Puedes reordenarlos arrastrando filas.",
        ))

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=True,
            show_thumbnails=True,
        )
        self._docs_card.files_changed.connect(self._on_files_changed)
        outer.addWidget(self._docs_card, 1)

        # Card de estado: resumen rápido
        self._docs_summary_card = make_card("Resumen")
        self._docs_summary_lbl = QLabel("Sin documentos cargados.")
        self._docs_summary_lbl.setProperty("class", "CardHint")
        self._docs_summary_lbl.setWordWrap(True)
        card_layout(self._docs_summary_card).addWidget(self._docs_summary_lbl)
        outer.addWidget(self._docs_summary_card)

        return page

    # ------------------------------------------------------------------ #
    # Paso 02: Opciones
    # ------------------------------------------------------------------ #

    def _build_options_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Opciones de unión",
            "Configura cómo se combinarán los documentos.",
        ))

        # ── Card unificada de configuración ──────────────────────────
        cfg_card = make_card("Configuración")
        cl = card_layout(cfg_card)
        cl.setSpacing(18)

        # Nombre del archivo
        name_col = QVBoxLayout()
        name_col.setSpacing(6)
        name_lbl = QLabel("Nombre del archivo resultante")
        name_lbl.setProperty("class", "CardTitle")
        name_hint = QLabel("Sin extensión — se guardará como .pdf")
        name_hint.setProperty("class", "CardHint")
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self._out_name_edit = QLineEdit("documentos_unidos")
        self._out_name_edit.setPlaceholderText("ej: contrato_completo")
        self._out_name_edit.setMaximumWidth(340)
        pdf_suffix = QLabel(".pdf")
        pdf_suffix.setStyleSheet("color: #6B6F7A; background: transparent;")
        name_row.addWidget(self._out_name_edit)
        name_row.addWidget(pdf_suffix)
        name_row.addStretch()
        name_col.addWidget(name_lbl)
        name_col.addWidget(name_hint)
        name_col.addLayout(name_row)
        cl.addLayout(name_col)

        # Divisor
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {COLORS['border']}; border: none;")
        cl.addWidget(div)

        # Opciones de check
        self._blank_between_chk = QCheckBox("Insertar página en blanco entre documentos")
        self._blank_between_chk.setToolTip(
            "Facilita la impresión o la separación visual entre documentos."
        )
        self._blank_between_chk.setChecked(False)
        cl.addWidget(self._blank_between_chk)

        self._bookmarks_chk = QCheckBox("Agregar marcadores de navegación por documento")
        self._bookmarks_chk.setToolTip(
            "Cada documento tendrá un marcador con su nombre de archivo.\n"
            "Facilita la navegación en visores PDF."
        )
        self._bookmarks_chk.setChecked(False)
        cl.addWidget(self._bookmarks_chk)

        outer.addWidget(cfg_card)
        outer.addStretch(1)

        return page

    # ------------------------------------------------------------------ #
    # Paso 03: Procesar
    # ------------------------------------------------------------------ #

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Genera el PDF en temporal; usa \"Guardar como\" para conservarlo.",
        ))

        self._proc_step = ProcessStep(
            run_label="Unir PDFs",
            show_output_dir=False,
        )
        self._proc_step.set_run_enabled(False)
        outer.addWidget(self._proc_step, 1)

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
            "Resultado",
            "El PDF combinado está listo.",
        ))

        self._result_viewer = GenericPdfViewer("Documento unido")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        self._send_btn = SendToToolButton(self.ctx, "unir")
        # _send_btn is exposed via _get_step_actions for the navbar; no inline row needed.

        return page

    # ------------------------------------------------------------------ #
    # Hooks de navegación
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

    # ------------------------------------------------------------------ #
    # Actualizar estado al cambiar archivos
    # ------------------------------------------------------------------ #

    def _on_files_changed(self, paths: List[str]) -> None:
        self._pdf_paths = paths
        for cached in list(self._page_cache):
            if cached not in paths:
                self._page_cache.pop(cached, None)

        n = len(paths)
        if n == 0:
            self._docs_summary_lbl.setText("Sin documentos cargados.")
        elif n == 1:
            self._docs_summary_lbl.setText(
                "1 documento cargado. Agrega al menos uno más para unir."
            )
        else:
            for p in paths:
                if p not in self._page_cache or self._page_cache.get(p, 0) <= 0:
                    try:
                        self._page_cache[p] = pdf_page_count(p)
                    except Exception:
                        self._page_cache[p] = 0
            total = sum(self._page_cache.get(p, 0) for p in paths)
            invalid = [Path(p).name for p in paths if self._page_cache.get(p, 0) <= 0]
            if invalid:
                shown = ", ".join(invalid[:3])
                extra = "..." if len(invalid) > 3 else ""
                self._docs_summary_lbl.setText(
                    f"{n} documentos · {total} páginas legibles · "
                    f"revisa: {shown}{extra}"
                )
            else:
                self._docs_summary_lbl.setText(
                    f"{n} documentos · {total} páginas en total"
                )
        self._sync_run_enabled()

    # ------------------------------------------------------------------ #
    # Resumen para el paso Procesar
    # ------------------------------------------------------------------ #

    def _refresh_summary(self) -> None:
        n = len(self._pdf_paths)
        out_name = filename_with_suffix(
            self._out_name_edit.text(),
            ".pdf",
            fallback="documentos_unidos",
        )
        blank = "Sí" if self._blank_between_chk.isChecked() else "No"
        bm = "Sí" if self._bookmarks_chk.isChecked() else "No"

        rows = [
            f"<b>Documentos a unir:</b>&nbsp;&nbsp;{n}",
            f"<b>Nombre de salida:</b>&nbsp;&nbsp;{out_name}",
            f"<b>Página en blanco entre docs:</b>&nbsp;&nbsp;{blank}",
            f"<b>Marcadores de navegación:</b>&nbsp;&nbsp;{bm}",
        ]
        if n >= 2:
            expected = sum(self._page_cache.get(p, 0) for p in self._pdf_paths)
            if self._blank_between_chk.isChecked():
                expected += max(0, n - 1)
            rows.append(f"<b>Páginas esperadas:</b>&nbsp;&nbsp;{expected}")
        if n == 0:
            rows.insert(0, "<span style='color:#E5484D;'>Atención: no hay documentos cargados.</span>")
        elif n == 1:
            rows.insert(0, "<span style='color:#F5A623;'>Atención: solo hay 1 documento — agrega más para unir.</span>")
        elif not self._inputs_are_readable():
            rows.insert(0, "<span style='color:#E5484D;'>Atención: hay PDFs que no se pudieron leer correctamente.</span>")

        self._proc_step.set_summary_html("<br>".join(rows))
        self._sync_run_enabled()

    def _sync_run_enabled(self) -> None:
        if hasattr(self, "_proc_step"):
            self._proc_step.set_run_enabled(
                len(self._pdf_paths) >= 2 and self._inputs_are_readable()
            )

    def _inputs_are_readable(self) -> bool:
        if len(self._pdf_paths) < 2:
            return False
        return all(self._page_cache.get(p, 0) > 0 for p in self._pdf_paths)

    # ------------------------------------------------------------------ #
    # Ejecutar
    # ------------------------------------------------------------------ #

    def _on_run(self) -> None:
        self._stop_active_worker()
        if len(self._pdf_paths) < 2:
            show_warning(
                self, "Sin documentos",
                "Agrega al menos 2 archivos PDF para unir.",
            )
            return
        if self._worker_thread is not None:
            return

        out_dir = make_run_dir("Unir")
        out_name = filename_with_suffix(
            self._out_name_edit.text(),
            ".pdf",
            fallback="documentos_unidos",
        )
        out_path = str(unique_output_path(out_dir, out_name))

        self._worker = MergeWorker(
            pdf_paths=list(self._pdf_paths),
            output_path=out_path,
            blank_between=self._blank_between_chk.isChecked(),
            add_bookmarks=self._bookmarks_chk.isChecked(),
        )
        self._worker_thread = RunnerThread(self._worker.run, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)

        self._proc_step.set_running(True)
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._worker_thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._proc_step.set_progress(self._proc_step._prog_bar.value(), "Cancelando…")

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        pct = int(current / total * 100) if total > 0 else 0
        self._proc_step.set_progress(pct, msg)

    def _on_finished(self, result: PdfMergeResult) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "¡Listo!")
        self._last_result = result

        # Mostrar en visor
        self._result_viewer.set_results([result])
        if self._pdf_paths:
            self._result_viewer.set_source_dirs([str(Path(self._pdf_paths[0]).parent)])
        output_paths = [result.output_path] if result.success and result.output_path else []
        self.ctx.tray.add_items(output_paths, "Unir")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)
        self._switch_section(3)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al unir PDFs", msg)

    def _cleanup_thread(self) -> None:
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(3000)
            self._worker_thread = None
        self._worker = None

    # ------------------------------------------------------------------ #
    # Resultados / navegación
    # ------------------------------------------------------------------ #

    def _open_in_explorer(self, path: str) -> None:
        from ui.common.open_utils import open_folder
        open_folder(self, path, title="Abrir carpeta")

    # ------------------------------------------------------------------ #
    # Resetear sesión
    # ------------------------------------------------------------------ #

    def _reset_session(self) -> None:
        self._docs_card.clear()
        self._pdf_paths.clear()
        self._last_result = None
        self._docs_summary_lbl.setText("Sin documentos cargados.")
        self._out_name_edit.setText("documentos_unidos")
        self._blank_between_chk.setChecked(False)
        self._bookmarks_chk.setChecked(False)
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._proc_step.reset()
        self._switch_section(0)

    # ------------------------------------------------------------------ #
    # Drag & drop
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        from ui.common.file_ordering import paths_from_mime_data

        self.handle_drop(paths_from_mime_data(event.mimeData()))
