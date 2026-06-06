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

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core.output_paths import make_run_dir, unique_output_path
from core.page_organizer_engine import (
    MultiOrganizerJob,
    MultiOrganizerResult,
    OrganizerJob,
    PageOrganizerEngine,
)
from shell.context import ShellContext
from ui.common.cards import make_page_header
from ui.common.dialogs import show_error, show_warning
from ui.common.icons import set_button_icon
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.process_step import ProcessStep
from ui.common.send_to_tool import SendToToolButton
from ui.common.tool_scaffold import PipelineWindow
from ui.organizador.lane_container import LaneContainer


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
        self._build_pages()
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

        self._lane_container = LaneContainer()
        self._lane_container.layout_changed.connect(self._on_layout_changed)
        outer.addWidget(self._lane_container, 1)

        self._summary_lbl = QLabel("Sin paginas cargadas.")
        self._summary_lbl.setProperty("class", "CardHint")
        outer.addWidget(self._summary_lbl)

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
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Paginas")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(0))
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
            "Resultado",
            "Los PDFs organizados estan listos.",
        ))

        self._result_viewer = GenericPdfViewer("PDF organizado")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(back)
        nav.addStretch()
        self._send_btn = SendToToolButton(self.ctx, "organizador")
        nav.addWidget(self._send_btn)
        restart_btn = QPushButton("Nueva sesion")
        restart_btn.setProperty("class", "Primary")
        restart_btn.setMinimumWidth(180)
        set_button_icon(restart_btn, "refresh-cw")
        restart_btn.clicked.connect(self._reset_session)
        nav.addWidget(restart_btn)
        outer.addLayout(nav)
        return page

    # ── PipelineWindow hooks ───────────────────────────────────────────────

    def _on_section_activated(self, idx: int) -> None:
        if idx == 1:
            self._refresh_output_table()
            self._refresh_proc_summary()
            # Enable the run button whenever there are pages loaded
            has_pages = self._lane_container.total_pages() > 0
            self._proc_step.set_run_enabled(has_pages)

    def set_inputs(self, paths: List[str]) -> None:
        self._lane_container.add_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._lane_container.add_paths(paths)
        self._switch_section(0)

    # ── Slots ──────────────────────────────────────────────────────────────

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

        if output_paths and result.results:
            first = result.results[0]
            self._result_viewer.set_results([first])
            if first.job.pages:
                self._result_viewer.set_source_dirs(
                    [str(Path(first.job.pages[0].source_path).parent)]
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
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

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
