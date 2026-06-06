"""ProtectorWindow - password protection and PDF permissions."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QCheckBox, QGridLayout, QLineEdit,
)

from core.output_naming import unique_output_path_for_source
from core.output_paths import make_run_dir
from core.pdf_protect_engine import (
    PdfProtectEngine,
    ProtectJob,
    ProtectOptions,
    ProtectResult,
    permission_label,
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


class ProtectWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[ProtectJob]) -> None:
        super().__init__()
        self.jobs = jobs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = PdfProtectEngine().run_batch(
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


class ProtectorWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documentos", "Carga PDFs a proteger"),
        ("02", "Seguridad", "Configura password y permisos"),
        ("03", "Procesar", "Crea copias protegidas"),
        ("04", "Resultados", "Revisa PDFs protegidos"),
    ]
    BRAND = "Proteger PDF"
    TAGLINE = "Contraseñas y permisos AES-256"
    ACCENT_COLOR = "#0EA5E9"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[ProtectResult] = []
        self._worker: Optional[ProtectWorker] = None
        self._worker_thread: Optional[QThread] = None

        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_security_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documentos a proteger",
            "Carga PDFs y genera copias cifradas sin modificar los originales.",
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

        self._docs_summary_lbl = QLabel("Sin documentos cargados.")
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

    def _build_security_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Seguridad y permisos",
            "Define si el PDF pedira password al abrir y que acciones permitira.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        passwords = make_card("Contraseñas")
        self._require_open_chk = QCheckBox("Pedir contraseña para abrir")
        self._require_open_chk.setChecked(True)
        self._require_open_chk.toggled.connect(self._sync_open_password_enabled)
        card_layout(passwords).addWidget(self._require_open_chk)

        self._open_pw_edit = QLineEdit()
        self._open_pw_edit.setPlaceholderText("Contraseña de apertura")
        self._open_pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        card_layout(passwords).addWidget(self._open_pw_edit)

        self._owner_pw_edit = QLineEdit()
        self._owner_pw_edit.setPlaceholderText("Contraseña de propietario")
        self._owner_pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        card_layout(passwords).addWidget(self._owner_pw_edit)

        hint = QLabel("Si dejas propietario vacío, PDFlex usará la contraseña de apertura como propietario.")
        hint.setProperty("class", "CardHint")
        hint.setWordWrap(True)
        card_layout(passwords).addWidget(hint)
        grid.addWidget(passwords, 0, 0)

        permissions = make_card("Permisos")
        self._allow_print_chk = QCheckBox("Permitir imprimir")
        self._allow_print_chk.setChecked(True)
        permissions.layout().addWidget(self._allow_print_chk)

        self._allow_hq_print_chk = QCheckBox("Impresión en alta calidad")
        self._allow_hq_print_chk.setChecked(True)
        permissions.layout().addWidget(self._allow_hq_print_chk)

        self._allow_copy_chk = QCheckBox("Permitir copiar texto o imagenes")
        permissions.layout().addWidget(self._allow_copy_chk)

        self._allow_modify_chk = QCheckBox("Permitir editar contenido")
        permissions.layout().addWidget(self._allow_modify_chk)

        self._allow_annotate_chk = QCheckBox("Permitir comentarios/anotaciones")
        permissions.layout().addWidget(self._allow_annotate_chk)

        self._allow_forms_chk = QCheckBox("Permitir rellenar formularios")
        permissions.layout().addWidget(self._allow_forms_chk)

        self._allow_assemble_chk = QCheckBox("Permitir organizar paginas")
        permissions.layout().addWidget(self._allow_assemble_chk)

        self._allow_accessibility_chk = QCheckBox("Permitir accesibilidad")
        self._allow_accessibility_chk.setChecked(True)
        permissions.layout().addWidget(self._allow_accessibility_chk)
        grid.addWidget(permissions, 0, 1)

        note = make_card("Lectura rapida")
        note_lbl = QLabel(
            "AES-256 crea una copia protegida. Los permisos dependen del lector PDF, "
            "pero la contraseña de apertura sí bloquea el acceso al documento."
        )
        note_lbl.setProperty("class", "CardHint")
        note_lbl.setWordWrap(True)
        card_layout(note).addWidget(note_lbl)
        grid.addWidget(note, 1, 0, 1, 2)

        outer.addLayout(grid)
        outer.addStretch(1)

        nav = QHBoxLayout()
        back = QPushButton("Documentos")
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

        self._sync_open_password_enabled()
        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Genera PDFs protegidos en temporal; usa Guardar como para conservarlos.",
        ))

        self._proc_step = ProcessStep(
            run_label="Proteger PDFs",
            show_output_dir=False,
        )
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Seguridad")
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
            "Revisa los PDFs protegidos y guardalos o envialos a otra herramienta.",
        ))

        self._result_viewer = GenericPdfViewer("PDFs protegidos")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        nav.addStretch()

        self._send_btn = SendToToolButton(self.ctx, "protector")
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
            self._docs_summary_lbl.setText("Sin documentos cargados.")
            return
        self._docs_summary_lbl.setText(
            f"{count} documento{'s' if count != 1 else ''} listo{'s' if count != 1 else ''} para proteger."
        )

    def _sync_open_password_enabled(self) -> None:
        self._open_pw_edit.setEnabled(self._require_open_chk.isChecked())

    def _build_options(self) -> ProtectOptions:
        return ProtectOptions(
            open_password=self._open_pw_edit.text() if self._require_open_chk.isChecked() else "",
            owner_password=self._owner_pw_edit.text(),
            allow_print=self._allow_print_chk.isChecked(),
            allow_high_quality_print=self._allow_hq_print_chk.isChecked(),
            allow_copy=self._allow_copy_chk.isChecked(),
            allow_modify=self._allow_modify_chk.isChecked(),
            allow_annotate=self._allow_annotate_chk.isChecked(),
            allow_forms=self._allow_forms_chk.isChecked(),
            allow_assemble=self._allow_assemble_chk.isChecked(),
            allow_accessibility=self._allow_accessibility_chk.isChecked(),
        )

    def _validate_ready(self) -> Optional[str]:
        if self._docs_card.is_empty():
            return "Agrega al menos un PDF."
        options = self._build_options()
        if self._require_open_chk.isChecked() and not options.open_password.strip():
            return "Escribe la contraseña de apertura."
        if not options.open_password.strip() and not options.owner_password.strip():
            return "Escribe una contraseña de propietario o activa contraseña de apertura."
        if options.open_password.strip() and len(options.open_password.strip()) < 4:
            return "La contraseña de apertura debe tener al menos 4 caracteres."
        if options.owner_password.strip() and len(options.owner_password.strip()) < 4:
            return "La contraseña de propietario debe tener al menos 4 caracteres."
        return None

    def _refresh_summary(self) -> None:
        paths = self._docs_card.paths()
        options = self._build_options()
        mode = "requiere contraseña al abrir" if options.open_password.strip() else "abre sin contraseña"
        rows = [
            f"<b>Documentos:</b>&nbsp;&nbsp;{len(paths)}",
            "<b>Cifrado:</b>&nbsp;&nbsp;AES-256",
            f"<b>Apertura:</b>&nbsp;&nbsp;{mode}",
            f"<b>Permisos:</b>&nbsp;&nbsp;{permission_label(options)}",
            "<b>Salida:</b>&nbsp;&nbsp;PDF temporal por documento",
        ]
        error = self._validate_ready()
        if error:
            rows.insert(0, f"<span style='color:#E5484D;'>Atencion: {error}</span>")
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )

    def _build_jobs(self) -> List[ProtectJob]:
        out_dir = make_run_dir("ProtegerPDF")
        reserved: set[str] = set()
        add_suffix = add_tool_suffix_enabled()
        options = self._build_options()
        jobs: List[ProtectJob] = []
        for path in self._docs_card.paths():
            out_path = unique_output_path_for_source(
                out_dir,
                path,
                extension=".pdf",
                tool_suffix="protegido",
                add_tool_suffix=add_suffix,
                reserved=reserved,
                fallback="documento",
            )
            jobs.append(ProtectJob(pdf_path=path, output_path=str(out_path), options=options))
        return jobs

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
        self._proc_step.set_progress(0, "Preparando proteccion...")

        self._worker = ProtectWorker(self._build_jobs())
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
        self._proc_step.set_progress(100, "Proteccion completada")

        output_paths = [
            result.output_path
            for result in self.last_results
            if result.success and result.output_path
        ]
        sendable_paths = [
            result.output_path
            for result in self.last_results
            if result.success and result.output_path and not result.user_password
        ]
        self.ctx.tray.add_items(output_paths, "Proteger PDF")
        self._send_btn.set_output_paths(sendable_paths)
        self.outputs_ready.emit(output_paths)

        self._result_viewer.set_results(self.last_results)
        self._result_viewer.set_source_dirs([
            str(Path(result.job.pdf_path).parent)
            for result in self.last_results
        ])

        ok = sum(1 for result in self.last_results if result.success)
        failed = len(self.last_results) - ok
        msg = f"Se protegieron {ok} PDF{'s' if ok != 1 else ''}."
        if failed:
            msg += f"\nCon error: {failed}"
            show_warning(self, "Proteccion completada con avisos", msg)
        else:
            show_success(self, "Proteccion completa", msg)
        self._switch_section(3)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al proteger PDFs", msg)

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
        self._docs_summary_lbl.setText("Sin documentos cargados.")
        self._require_open_chk.setChecked(True)
        self._open_pw_edit.clear()
        self._owner_pw_edit.clear()
        self._allow_print_chk.setChecked(True)
        self._allow_hq_print_chk.setChecked(True)
        self._allow_copy_chk.setChecked(False)
        self._allow_modify_chk.setChecked(False)
        self._allow_annotate_chk.setChecked(False)
        self._allow_forms_chk.setChecked(False)
        self._allow_assemble_chk.setChecked(False)
        self._allow_accessibility_chk.setChecked(True)
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
