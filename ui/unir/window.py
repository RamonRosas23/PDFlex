"""UnirWindow — pipeline para combinar múltiples PDFs en uno solo.

Pipeline:
    01 Documentos  →  02 Opciones  →  03 Procesar  →  04 Resultados
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import fitz
from PyQt6.QtCore import QObject, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QFrame, QLineEdit, QCheckBox,
)

from shell.context import ShellContext
from core.output_paths import filename_with_suffix, make_run_dir, unique_output_path
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.tool_scaffold import PipelineWindow
from ui.common.documents_step import DocumentsCard
from ui.common.process_step import ProcessStep
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.send_to_tool import SendToToolButton
from ui.common.dialogs import show_error, show_warning
from ui.common.icons import set_button_icon


# ====================================================================== #
#  Resultado
# ====================================================================== #

@dataclass
class MergeResult:
    output_path: str
    success: bool
    error: str = ""
    total_pages: int = 0
    source_count: int = 0


# ====================================================================== #
#  Worker
# ====================================================================== #

class MergeWorker(QObject):
    progress = pyqtSignal(int, int, str)    # current, total, message
    finished = pyqtSignal(object)           # MergeResult
    error = pyqtSignal(str)

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
        out_doc = None
        try:
            out_doc = fitz.open()
            total = len(self.pdf_paths)
            toc_entries: list = []
            current_page = 0

            for i, path in enumerate(self.pdf_paths):
                if self._cancel:
                    out_doc.close()
                    self.error.emit("Operación cancelada.")
                    return

                stem = Path(path).stem
                self.progress.emit(i + 1, total, f"Uniendo {stem}…")

                # Insertar página en blanco de separación (excepto antes del primero)
                if self.blank_between and i > 0:
                    # Mismas dimensiones que la última página insertada
                    ref_rect = out_doc[-1].rect if out_doc.page_count > 0 \
                        else fitz.Rect(0, 0, 595, 842)
                    out_doc.new_page(width=ref_rect.width, height=ref_rect.height)
                    current_page += 1

                src = None
                try:
                    src = fitz.open(path)
                    if self.add_bookmarks:
                        # Guardar marcador al inicio del documento fuente
                        toc_entries.append([1, stem, current_page + 1])

                    out_doc.insert_pdf(src)
                    current_page += src.page_count
                finally:
                    if src is not None:
                        src.close()

            if self.add_bookmarks and toc_entries:
                out_doc.set_toc(toc_entries)

            self.progress.emit(total, total, "Guardando…")
            Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
            out_doc.save(self.output_path, garbage=4, deflate=True)
            total_pages = out_doc.page_count
            out_doc.close()

            self.finished.emit(MergeResult(
                output_path=self.output_path,
                success=True,
                total_pages=total_pages,
                source_count=len(self.pdf_paths),
            ))
        except Exception as exc:
            if out_doc is not None:
                try:
                    out_doc.close()
                except Exception:
                    pass
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

        self._build_pages()
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
        div.setStyleSheet("background: #1E1E24; border: none;")
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
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Opciones")
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
            "Resultado",
            "El PDF combinado está listo.",
        ))

        self._result_viewer = GenericPdfViewer("Documento unido")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        nav.addStretch()

        self._send_btn = SendToToolButton(self.ctx, "unir")
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
        n = len(paths)
        if n == 0:
            self._docs_summary_lbl.setText("Sin documentos cargados.")
        elif n == 1:
            self._docs_summary_lbl.setText(
                "1 documento cargado. Agrega al menos uno más para unir."
            )
        else:
            # Contar páginas totales
            total_pages = 0
            for p in paths:
                try:
                    d = fitz.open(p)
                    total_pages += d.page_count
                    d.close()
                except Exception:
                    pass
            self._docs_summary_lbl.setText(
                f"{n} documentos · {total_pages} páginas en total"
            )

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
        if n == 0:
            rows.insert(0, "<span style='color:#E5484D;'>Atención: no hay documentos cargados.</span>")
        elif n == 1:
            rows.insert(0, "<span style='color:#F5A623;'>Atención: solo hay 1 documento — agrega más para unir.</span>")

        self._proc_step.set_summary_html("<br>".join(rows))

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
        self._worker_thread = QThread(self)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

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

    def _on_finished(self, result: MergeResult) -> None:
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
            self._worker_thread.wait()
            self._worker_thread = None
        self._worker = None

    # ------------------------------------------------------------------ #
    # Resultados / navegación
    # ------------------------------------------------------------------ #

    def _open_in_explorer(self, path: str) -> None:
        folder = str(Path(path).parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

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
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        self._docs_card.add_paths(paths)
