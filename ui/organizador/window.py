"""OrganizadorWindow — organizador visual multi-lane de paginas PDF.

v2 — Rediseno completo:
  - Un DocLane por PDF (filas separadas, no cuadricula mezclada).
  - Drag & drop entre filas: mover (default) o copiar (Ctrl).
  - Exportacion flexible: N PDFs independientes o uno fusionado.
  - ThumbnailWorker en background: UI no se bloquea al cargar PDFs grandes.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core.output_paths import make_run_dir, unique_output_path
from core.media_conversion import (
    DOCUMENT_IMPORT_EXTENSIONS,
    image_paths,
    images_to_pdf_exact,
    pdf_paths,
    word_paths,
)
from core.page_organizer_engine import (
    MultiOrganizerJob,
    MultiOrganizerResult,
    OrganizerJob,
    PageOrganizerEngine,
)
from shell.context import ShellContext
from shell.transfer import ToolTransfer
from ui.common.cards import make_page_header
from ui.common.dialogs import show_error, show_info, show_warning
from ui.common.icons import set_button_icon
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.process_step import ProcessStep
from ui.common.tray_input_panel import TrayInputPanel
from ui.common.tool_scaffold import PipelineWindow, RunnerThread
from ui.organizador.lane_container import LaneContainer
from ui.organizador.page_preview_dialog import OrganizerPagePreviewDialog

_ACCEPTED_IMPORT_EXTS = set(DOCUMENT_IMPORT_EXTENSIONS)


class _MultiWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, job: MultiOrganizerJob) -> None:
        super().__init__()
        self.job = job
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        result = PageOrganizerEngine().run_multi_job(
            self.job,
            progress=lambda c, t, m: self.progress.emit(c, t, m),
            should_cancel=lambda: self._cancel,
        )
        if result.success:
            self.finished.emit(result)
        else:
            self.error.emit(result.error or "No se pudo organizar el PDF.")


class OrganizadorWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Paginas",    "Carga, reordena y edita"),
        ("02", "Procesar",   "Configura la salida"),
        ("03", "Resultados", "Revisa los documentos"),
    ]
    BRAND = "Organizador"
    TAGLINE = "Reordena, rota, duplica y extrae paginas"
    ACCENT_COLOR = "#14B8A6"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self._last_result: Optional[MultiOrganizerResult] = None
        self._worker: Optional[_MultiWorker] = None
        self._worker_thread: Optional[QThread] = None
        self._conv_thread: Optional[QThread] = None
        self._conv_worker = None
        self._conv_dlg = None
        self._pending_import: Optional[dict] = None
        self._build_pages()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)

    # ── Build ─────────────────────────────────────────────────────────────

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_pages_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_pages_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(16)

        outer.addLayout(make_page_header(
            "Organizador visual de paginas",
            "Cada PDF carga en su propia fila. "
            "Arrastra paginas entre filas para moverlas (Ctrl = copiar).",
        ))

        body = QHBoxLayout()
        body.setSpacing(12)

        self._tray_panel = TrayInputPanel(self.ctx, _ACCEPTED_IMPORT_EXTS)
        self._tray_panel.add_requested.connect(self._add_tray_paths)
        self._tray_panel.replace_requested.connect(self._replace_with_tray_paths)
        body.addWidget(self._tray_panel)

        self._lane_container = LaneContainer()
        self._lane_container.layout_changed.connect(self._on_layout_changed)
        self._lane_container.page_preview_requested.connect(self._open_page_preview)
        self._lane_container.files_add_requested.connect(self._on_files_add_requested)
        body.addWidget(self._lane_container, 1)
        outer.addLayout(body, 1)

        self._summary_lbl = QLabel("Sin paginas cargadas.")
        self._summary_lbl.setProperty("class", "CardHint")
        outer.addWidget(self._summary_lbl)

        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Configura el nombre de cada documento de salida o fusiónalo todo en uno.",
        ))

        self._output_table = QTableWidget(0, 3)
        self._output_table.setHorizontalHeaderLabels(["Documento", "Paginas", "Nombre de salida"])
        self._output_table.horizontalHeader().setStretchLastSection(True)
        self._output_table.verticalHeader().setVisible(False)
        self._output_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._output_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._output_table.setMaximumHeight(220)
        outer.addWidget(self._output_table)

        merge_row = QHBoxLayout()
        self._merge_chk = QCheckBox("Fusionar todo en un solo PDF:")
        self._merge_chk.toggled.connect(self._on_merge_toggled)
        merge_row.addWidget(self._merge_chk)
        self._merge_name_edit = QLineEdit("organizado_merged")
        self._merge_name_edit.setMaximumWidth(240)
        self._merge_name_edit.setEnabled(False)
        merge_row.addWidget(self._merge_name_edit)
        merge_row.addStretch()
        outer.addLayout(merge_row)

        self._proc_step = ProcessStep(run_label="Generar PDFs", show_output_dir=False)
        outer.addWidget(self._proc_step, 1)

        return page

    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultado",
            "Los PDFs organizados estan listos.",
        ))

        self._result_viewer = GenericPdfViewer("PDF organizado")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        return page

    # ── Action buttons (navbar footer) ────────────────────────────────────

    def _build_action_buttons(self) -> None:
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Generar PDFs")
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

        self._restart_btn = QPushButton("Nueva sesion")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "organizador")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()

    # ── PipelineWindow hooks ───────────────────────────────────────────────

    def _on_section_activated(self, idx: int) -> None:
        if idx == 1:
            self._refresh_output_table()
            self._refresh_proc_summary()
            # Enable the run button whenever there are pages loaded
            has_pages = self._lane_container.total_pages() > 0
            self._proc_step.set_run_enabled(has_pages)

    def set_inputs(self, paths: List[str]) -> None:
        self._add_input_paths(paths)
        self._switch_section(0)

    def set_transfer(self, transfer: ToolTransfer) -> None:
        self._add_input_paths(transfer.paths, replace=transfer.mode == "replace")
        self.ctx.tray.mark_in_work(transfer.paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._add_input_paths(paths)
        self._switch_section(0)

    # ── Slots ──────────────────────────────────────────────────────────────

    def _add_tray_paths(self, paths: List[str]) -> None:
        self._add_input_paths(paths)

    def _replace_with_tray_paths(self, paths: List[str]) -> None:
        self._add_input_paths(paths, replace=True)

    def _on_files_add_requested(
        self,
        paths: List[str],
        target_lane_id,
        at_row: int,
    ) -> None:
        lane_id = str(target_lane_id) if target_lane_id else None
        self._add_input_paths(paths, target_lane_id=lane_id, at_row=at_row)

    def _add_input_paths(
        self,
        paths: List[str],
        *,
        target_lane_id: str | None = None,
        at_row: int = -1,
        replace: bool = False,
    ) -> None:
        accepted = [
            p for p in paths
            if Path(p).suffix.lower() in _ACCEPTED_IMPORT_EXTS and Path(p).is_file()
        ]
        if not accepted:
            return

        pdfs = pdf_paths(accepted)
        images = image_paths(accepted)
        words = word_paths(accepted)
        if images:
            try:
                converted = images_to_pdf_exact(images)
            except Exception as exc:
                show_error(self, "No se pudieron convertir las imágenes", str(exc))
                converted = ""
            if converted:
                pdfs.append(converted)
        if words:
            self._convert_words_then_add(
                words,
                initial_pdfs=pdfs,
                target_lane_id=target_lane_id,
                at_row=at_row,
                replace=replace,
            )
            return
        self._add_pdfs_to_lanes(
            pdfs,
            target_lane_id=target_lane_id,
            at_row=at_row,
            replace=replace,
        )

    def _add_pdfs_to_lanes(
        self,
        pdfs: List[str],
        *,
        target_lane_id: str | None = None,
        at_row: int = -1,
        replace: bool = False,
    ) -> None:
        if replace:
            self._lane_container.clear()
            target_lane_id = None
            at_row = -1
        if not pdfs:
            return
        if target_lane_id:
            self._lane_container.add_paths_to_lane(
                target_lane_id,
                pdfs,
                at_row=at_row,
            )
        else:
            self._lane_container.add_paths(pdfs)

    def _convert_words_then_add(
        self,
        words: List[str],
        *,
        initial_pdfs: List[str],
        target_lane_id: str | None,
        at_row: int,
        replace: bool,
    ) -> None:
        if not self.ctx.word_converter.is_available():
            show_info(
                self,
                "Microsoft Office requerido",
                "Para convertir archivos Word a PDF se necesita Microsoft Office.\n"
                "Los archivos .doc/.docx han sido omitidos.",
            )
            self._add_pdfs_to_lanes(
                initial_pdfs,
                target_lane_id=target_lane_id,
                at_row=at_row,
                replace=replace,
            )
            return

        from shell.word_to_pdf import WordConvertWorker
        from ui.common.word_convert_dialog import WordConvertDialog

        self._pending_import = {
            "initial_pdfs": list(initial_pdfs),
            "target_lane_id": target_lane_id,
            "at_row": at_row,
            "replace": replace,
        }
        self._conv_dlg = WordConvertDialog(self, words)
        worker = WordConvertWorker(
            self.ctx.word_converter,
            words,
            make_run_dir("converted"),
        )
        self._conv_thread = RunnerThread(worker.run, self)
        self._conv_worker = worker
        worker.progress.connect(self._conv_dlg.on_progress)
        worker.finished.connect(self._on_word_done)
        worker.finished.connect(self._conv_dlg.on_finished)
        worker.error.connect(self._on_word_error)
        worker.error.connect(self._conv_dlg.on_error)
        worker.finished.connect(self._conv_thread.quit)
        worker.error.connect(self._conv_thread.quit)
        self._conv_thread.finished.connect(worker.deleteLater)
        self._conv_thread.finished.connect(self._conv_thread.deleteLater)
        self._conv_dlg.cancel_requested.connect(worker.cancel)
        QTimer.singleShot(0, self._conv_thread.start)
        self._conv_dlg.exec()

    def _consume_pending_import(self) -> dict:
        context = self._pending_import or {}
        self._pending_import = None
        return context

    def _on_word_done(self, converted_paths: List[str]) -> None:
        self._conv_thread = None
        self._conv_worker = None
        context = self._consume_pending_import()
        pdfs = list(context.get("initial_pdfs") or []) + list(converted_paths)
        self._add_pdfs_to_lanes(
            pdfs,
            target_lane_id=context.get("target_lane_id"),
            at_row=int(context.get("at_row", -1)),
            replace=bool(context.get("replace", False)),
        )

    def _on_word_error(self, msg: str) -> None:
        self._conv_thread = None
        self._conv_worker = None
        context = self._consume_pending_import()
        initial_pdfs = list(context.get("initial_pdfs") or [])
        if initial_pdfs:
            self._add_pdfs_to_lanes(
                initial_pdfs,
                target_lane_id=context.get("target_lane_id"),
                at_row=int(context.get("at_row", -1)),
                replace=bool(context.get("replace", False)),
            )

    def _on_layout_changed(self) -> None:
        total = self._lane_container.total_pages()
        lanes = self._lane_container.total_lanes()
        if total == 0:
            self._summary_lbl.setText("Sin paginas cargadas.")
        else:
            self._summary_lbl.setText(
                f"{total} pagina{'s' if total != 1 else ''}"
                f" · {lanes} fila{'s' if lanes != 1 else ''}"
            )

    def _open_page_preview(self, ref) -> None:
        refs = self._lane_container.ordered_page_refs()
        if not refs:
            return
        current = 0
        for idx, candidate in enumerate(refs):
            if candidate.page_id == getattr(ref, "page_id", ""):
                current = idx
                break
        dlg = OrganizerPagePreviewDialog(
            self,
            refs,
            current_index=current,
            accent_color=self.ACCENT_COLOR,
        )
        dlg.page_action_requested.connect(
            lambda action, page_id, d=dlg: self._on_preview_action(d, action, page_id)
        )
        dlg.exec()

    def _on_preview_action(
        self,
        dialog: OrganizerPagePreviewDialog,
        action: str,
        page_id: str,
    ) -> None:
        next_id = self._lane_container.apply_page_action(page_id, action)
        refs = self._lane_container.ordered_page_refs()
        if not refs:
            dialog.accept()
            return
        dialog.replace_refs(refs, current_page_id=next_id or page_id)
        self._on_layout_changed()

    def _on_merge_toggled(self, checked: bool) -> None:
        self._merge_name_edit.setEnabled(checked)
        for row in range(self._output_table.rowCount()):
            w = self._output_table.cellWidget(row, 2)
            if w:
                w.setEnabled(not checked)

    # ── Output table ──────────────────────────────────────────────────────

    def _refresh_output_table(self) -> None:
        states = self._lane_container.all_lane_states()
        self._output_table.setRowCount(len(states))
        for row, (lane_id, name, refs) in enumerate(states):
            self._output_table.setItem(row, 0, QTableWidgetItem(name))
            self._output_table.setItem(row, 1, QTableWidgetItem(str(len(refs))))
            stem = Path(name).stem if "." in name else name
            edit = QLineEdit(f"{stem}_org")
            edit.setProperty("lane_id", lane_id)
            self._output_table.setCellWidget(row, 2, edit)
        self._output_table.resizeColumnsToContents()
        self._output_table.horizontalHeader().setStretchLastSection(True)

    def _output_name_for_row(self, row: int) -> str:
        w = self._output_table.cellWidget(row, 2)
        if isinstance(w, QLineEdit):
            text = w.text().strip()
            if text:
                return text if text.endswith(".pdf") else text + ".pdf"
        return f"doc_{row + 1}_org.pdf"

    # ── Job building ──────────────────────────────────────────────────────

    def _build_multi_job(self) -> MultiOrganizerJob:
        out_dir = make_run_dir("Organizador")
        states = self._lane_container.all_lane_states()
        merge = self._merge_chk.isChecked()

        if merge:
            merged_stem = self._merge_name_edit.text().strip() or "organizado_merged"
            merged_out = str(unique_output_path(out_dir, merged_stem + ".pdf"))
            lanes = [
                OrganizerJob(pages=refs, output_path=merged_out)
                for (_, _, refs) in states
                if refs
            ]
        else:
            lanes = []
            for row, (_, _, refs) in enumerate(states):
                if not refs:
                    continue
                out_name = (
                    self._output_name_for_row(row)
                    if row < self._output_table.rowCount()
                    else f"doc_{row + 1}_org.pdf"
                )
                out_path = str(unique_output_path(out_dir, out_name))
                lanes.append(OrganizerJob(pages=refs, output_path=out_path))

        return MultiOrganizerJob(lanes=lanes, merge_all=merge)

    # ── Process ───────────────────────────────────────────────────────────

    def _refresh_proc_summary(self) -> None:
        states = self._lane_container.all_lane_states()
        total_pages = sum(len(refs) for _, _, refs in states)
        merge = self._merge_chk.isChecked()
        mode_txt = "Fusionar en un solo PDF" if merge else "PDFs separados por fila"
        rows = [
            f"<b>Filas:</b>&nbsp;&nbsp;{len(states)}",
            f"<b>Paginas totales:</b>&nbsp;&nbsp;{total_pages}",
            f"<b>Modo de salida:</b>&nbsp;&nbsp;{mode_txt}",
        ]
        if total_pages == 0:
            rows.insert(0, "<span style='color:#E5484D'>Sin paginas cargadas.</span>")
        self._proc_step.set_summary_html("<br>".join(rows))

    def _validate_ready(self) -> Optional[str]:
        if self._lane_container.total_pages() == 0:
            return "Agrega al menos un PDF con paginas."
        if not any(s[2] for s in self._lane_container.all_lane_states()):
            return "Todas las filas estan vacias."
        return None

    def _on_run(self) -> None:
        self._stop_active_worker()
        err = self._validate_ready()
        if err:
            show_warning(self, "Falta informacion", err)
            return
        if self._worker_thread is not None:
            return

        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Preparando...")

        self._worker = _MultiWorker(self._build_multi_job())
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

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        pct = int(current / max(1, total) * 100)
        self._proc_step.set_progress(pct, msg)

    def _on_finished(self, result: MultiOrganizerResult) -> None:
        self._cleanup_thread()
        self._last_result = result
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Listo")

        output_paths = [r.output_path for r in result.results if r.success and r.output_path]
        self.ctx.tray.add_items(output_paths, "Organizador")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        if result.results:
            self._result_viewer.set_results(result.results)
            self._result_viewer.set_source_dirs(
                [
                    str(Path(r.job.pages[0].source_path).parent)
                    if r.job.pages else str(Path.home())
                    for r in result.results
                ]
            )

        self._switch_section(2)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al organizar paginas", msg)

    def _cleanup_thread(self) -> None:
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
            self._worker_thread = None
        self._worker = None

    def _open_in_explorer(self, path: str) -> None:
        from ui.common.open_utils import open_folder
        open_folder(self, path, title="Abrir carpeta")

    def _reset_session(self) -> None:
        self._lane_container.clear()
        self._last_result = None
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._proc_step.reset()
        self._switch_section(0)

    # ── Drag & drop (window-level) ────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self.handle_drop(paths)
        event.acceptProposedAction()

    def deleteLater(self) -> None:  # type: ignore[override]
        try:
            self._stop_active_worker()
        except Exception:
            pass
        try:
            if self._conv_worker is not None:
                cancel = getattr(self._conv_worker, "cancel", None)
                if callable(cancel):
                    cancel()
            if self._conv_thread is not None:
                self._conv_thread.quit()
                self._conv_thread.wait(2000)
        except Exception:
            pass
        try:
            self._lane_container.deleteLater()
        except Exception:
            pass
        super().deleteLater()
