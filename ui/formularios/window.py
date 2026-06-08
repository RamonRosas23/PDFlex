"""FormulariosWindow - fill and flatten PDF forms."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import fitz
from PyQt6.QtCore import QObject, QThread, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QCheckBox, QComboBox, QGridLayout, QLineEdit, QPlainTextEdit,
    QScrollArea, QFrame,
)

from core.output_naming import unique_output_path_for_source
from core.output_paths import make_run_dir
from core.pdf_form_engine import (
    FormField,
    FormFillJob,
    FormFillOptions,
    FormFillResult,
    PdfFormEngine,
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
from ui.common.tool_scaffold import PipelineWindow, RunnerThread


class FormFillWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[FormFillJob]) -> None:
        super().__init__()
        self.jobs = jobs
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = PdfFormEngine().run_batch(
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


class FormulariosWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documento", "Carga un PDF con formulario"),
        ("02", "Campos", "Captura valores"),
        ("03", "Procesar", "Rellena y aplana"),
        ("04", "Resultados", "Revisa PDF final"),
    ]
    BRAND = "Formularios PDF"
    TAGLINE = "Rellena y aplana campos"
    ACCENT_COLOR = "#A855F7"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[FormFillResult] = []
        self._worker: Optional[FormFillWorker] = None
        self._worker_thread: Optional[QThread] = None
        self._fields: list[FormField] = []
        self._field_controls: dict[str, QWidget] = {}
        self._loaded_path = ""
        self._fields_are_ready = False

        self._build_pages()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_fields_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "PDF con formulario",
            "Carga un PDF con campos AcroForm. Esta herramienta trabaja un documento por sesion.",
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

        return page

    def _build_fields_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Campos del formulario",
            "Edita los valores detectados. Los campos no soportados se muestran bloqueados.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 1)

        fields_card = make_card(
            "Campos detectados",
            "Cada campo muestra su pagina, tipo y valor actual. Los campos requeridos se validan antes de procesar.",
        )
        self._fields_scroll = QScrollArea()
        self._fields_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._fields_scroll.setWidgetResizable(True)
        self._fields_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fields_inner = QWidget()
        self._fields_layout = QVBoxLayout(self._fields_inner)
        self._fields_layout.setContentsMargins(0, 0, 0, 0)
        self._fields_layout.setSpacing(10)
        self._fields_scroll.setWidget(self._fields_inner)
        card_layout(fields_card).addWidget(self._fields_scroll, 1)
        grid.addWidget(fields_card, 0, 0, 2, 1)

        options_card = make_card("Salida")
        self._flatten_chk = QCheckBox("Aplanar resultado")
        self._flatten_chk.setChecked(True)
        card_layout(options_card).addWidget(self._flatten_chk)

        self._skip_empty_chk = QCheckBox("No escribir valores vacios")
        self._skip_empty_chk.setChecked(False)
        card_layout(options_card).addWidget(self._skip_empty_chk)

        reload_btn = QPushButton("Recargar campos")
        reload_btn.setProperty("class", "Ghost")
        set_button_icon(reload_btn, "refresh-cw")
        reload_btn.clicked.connect(lambda: self._load_fields(force=True))
        card_layout(options_card).addWidget(reload_btn)

        info = QLabel(
            "Aplanar convierte los campos llenados en contenido fijo y elimina widgets editables."
        )
        info.setProperty("class", "CardHint")
        info.setWordWrap(True)
        card_layout(options_card).addWidget(info)
        grid.addWidget(options_card, 0, 1)

        status_card = make_card("Estado")
        self._fields_status_lbl = QLabel("Carga un PDF para detectar campos.")
        self._fields_status_lbl.setProperty("class", "CardHint")
        self._fields_status_lbl.setWordWrap(True)
        card_layout(status_card).addWidget(self._fields_status_lbl)
        grid.addWidget(status_card, 1, 1)

        outer.addLayout(grid, 1)

        self._clear_fields_ui("Carga un PDF para detectar sus campos.")
        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar formulario",
            "Genera una copia temporal rellenada; usa Guardar como para conservarla.",
        ))

        self._proc_step = ProcessStep(
            run_label="Rellenar formulario",
            show_output_dir=False,
        )
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Campos")
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
            "Revisa el PDF rellenado y guardalo o envialo a otra herramienta.",
        ))

        self._result_viewer = GenericPdfViewer("Formularios procesados")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(2))
        nav.addWidget(back)
        outer.addLayout(nav)
        return page

    def _build_action_buttons(self) -> None:
        from ui.common.icons import set_button_icon
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Rellenar formulario")
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

        self._send_btn = SendToToolButton(self.ctx, "formularios")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()

    def _on_section_activated(self, idx: int) -> None:
        if idx == 0 and hasattr(self, "_nav_next_btn"):
            count = len(self._docs_card.paths()) if hasattr(self, "_docs_card") else 0
            self._nav_next_btn.setEnabled(count == 1)
        elif idx == 1:
            self._load_fields()
            if hasattr(self, "_nav_next_btn"):
                self._nav_next_btn.setEnabled(getattr(self, "_fields_are_ready", False))
        elif hasattr(self, "_nav_next_btn"):
            self._nav_next_btn.setEnabled(True)
        if idx == 2:
            self._refresh_summary()

    def _on_nav_next(self) -> None:
        idx = self.stack.currentIndex()
        if idx == 0:
            self._go_to_fields()
        elif idx == 1:
            self._go_to_process()
        else:
            super()._on_nav_next()

    def set_inputs(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def _go_to_fields(self) -> None:
        if len(self._docs_card.paths()) != 1:
            show_warning(self, "Documento requerido", "Carga exactamente un PDF con formulario.")
            return
        self._switch_section(1)

    def _go_to_process(self) -> None:
        error = self._validate_ready()
        if error:
            show_warning(self, "Revisa los campos", error)
            return
        self._switch_section(2)

    def _on_docs_changed(self, paths: List[str]) -> None:
        self._loaded_path = ""
        self._fields = []
        self._field_controls = {}
        self._clear_fields_ui("Carga un PDF para detectar sus campos.")
        self._set_fields_ready(False)
        count = len(paths)
        if hasattr(self, "_nav_next_btn") and self.stack.currentIndex() == 0:
            self._nav_next_btn.setEnabled(count == 1)
        if count == 0:
            self._docs_summary_lbl.setText("Sin documento cargado.")
            return
        if count == 1:
            self._docs_summary_lbl.setText("1 documento listo para detectar campos.")
        else:
            self._docs_summary_lbl.setText("Carga exactamente un PDF para esta herramienta.")

    def _load_fields(self, *, force: bool = False) -> None:
        paths = self._docs_card.paths()
        if len(paths) != 1:
            self._fields_status_lbl.setText("Carga exactamente un PDF.")
            self._fields = []
            self._clear_fields_ui("Carga exactamente un PDF para detectar campos.")
            self._set_fields_ready(False)
            return
        path = paths[0]
        if not force and self._loaded_path == path and self._fields:
            return
        try:
            self._fields = PdfFormEngine().inspect_fields(path)
            self._loaded_path = path
            self._populate_fields_table()
        except Exception as exc:
            self._fields = []
            self._loaded_path = ""
            self._clear_fields_ui("No se pudieron detectar campos en este PDF.")
            self._set_fields_ready(False)
            self._fields_status_lbl.setText(f"No se pudieron detectar campos: {exc}")

    def _populate_fields_table(self) -> None:
        self._field_controls = {}
        if not self._fields:
            self._clear_fields_ui("Este PDF no contiene campos de formulario.")
            self._fields_status_lbl.setText("Este PDF no contiene campos de formulario.")
            self._set_fields_ready(False)
            return

        self._clear_fields_ui()
        for field in self._fields:
            control = self._control_for_field(field)
            self._field_controls[field.name] = control
            self._fields_layout.insertWidget(
                max(0, self._fields_layout.count() - 1),
                self._build_field_row(field, control),
            )

        supported = sum(1 for field in self._fields if field.supported)
        required = sum(1 for field in self._fields if field.supported and field.required)
        self._fields_status_lbl.setText(
            f"{len(self._fields)} campo{'s' if len(self._fields) != 1 else ''} detectado"
            f"{'s' if len(self._fields) != 1 else ''}; {supported} editable"
            f"{'s' if supported != 1 else ''}; {required} requerido"
            f"{'s' if required != 1 else ''}."
        )
        self._set_fields_ready(supported > 0)

    def _clear_fields_ui(self, message: str = "") -> None:
        if not hasattr(self, "_fields_layout"):
            return
        while self._fields_layout.count():
            item = self._fields_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if message:
            empty = QLabel(message)
            empty.setProperty("class", "CardHint")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(180)
            self._fields_layout.addWidget(empty)
        self._fields_layout.addStretch(1)

    def _set_fields_ready(self, ready: bool) -> None:
        self._fields_are_ready = ready
        if hasattr(self, "_nav_next_btn") and self.stack.currentIndex() == 1:
            self._nav_next_btn.setEnabled(ready)

    def _build_field_row(self, field: FormField, control: QWidget) -> QWidget:
        row = QFrame()
        row.setObjectName("FormFieldRow")
        row.setStyleSheet(
            "QFrame#FormFieldRow {"
            "background: #101116;"
            "border: 1px solid #24262F;"
            "border-radius: 8px;"
            "}"
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        info_col = QVBoxLayout()
        info_col.setSpacing(4)
        title = QLabel(field.label or field.name)
        title.setProperty("class", "CardTitle")
        title.setWordWrap(True)
        info_col.addWidget(title)

        pages = _pages_text(field)
        parts = [field.type_label, pages, f"Campo: {field.name}"]
        if field.widget_count > 1:
            parts.append(f"{field.widget_count} instancias")
        if field.required:
            parts.append("Requerido")
        if not field.supported:
            parts.append("No editable")
        meta = QLabel(" · ".join(parts))
        meta.setProperty("class", "CardHint")
        meta.setWordWrap(True)
        info_col.addWidget(meta)
        layout.addLayout(info_col, 2)

        control.setMinimumWidth(260)
        layout.addWidget(control, 3)
        return row

    def _control_for_field(self, field: FormField) -> QWidget:
        if field.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
            combo = QComboBox()
            combo.addItem("No", "Off")
            on_value = next((choice for choice in field.choices if choice != "Off"), "Yes")
            combo.addItem("Sí", on_value)
            combo.setCurrentIndex(1 if field.value and field.value != "Off" else 0)
            combo.setEnabled(field.supported)
            return combo

        if field.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
            combo = QComboBox()
            combo.addItem("Sin seleccionar", "Off")
            for choice in field.choices:
                if choice and choice != "Off":
                    combo.addItem(choice, choice)
            if combo.count() == 1:
                combo.addItem("Seleccionado", "Yes")
            if field.value and field.value != "Off":
                index = combo.findData(field.value)
                if index >= 0:
                    combo.setCurrentIndex(index)
            combo.setEnabled(field.supported)
            return combo

        if field.field_type in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
            combo = QComboBox()
            combo.setEditable(field.field_type == fitz.PDF_WIDGET_TYPE_COMBOBOX)
            if not field.choices:
                combo.setEditable(True)
            for choice in field.choices:
                combo.addItem(choice, choice)
            if field.value:
                index = combo.findText(field.value)
                if index >= 0:
                    combo.setCurrentIndex(index)
                else:
                    combo.setEditText(field.value)
            combo.setEnabled(field.supported)
            return combo

        if field.multiline or "\n" in field.value or len(field.value) > 120:
            edit = QPlainTextEdit()
            edit.setPlainText(field.value)
            edit.setMinimumHeight(92)
            edit.setPlaceholderText("Valor del campo")
            edit.setEnabled(field.supported)
            if not field.supported:
                edit.setPlaceholderText("Tipo no soportado o solo lectura")
            return edit

        edit = QLineEdit(field.value)
        edit.setPlaceholderText("Valor del campo")
        edit.setEnabled(field.supported)
        if not field.supported:
            edit.setPlaceholderText("Tipo no soportado o solo lectura")
        return edit

    def _collect_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for field in self._fields:
            control = self._field_controls.get(field.name)
            if isinstance(control, QComboBox):
                if field.field_type in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
                    values[field.name] = control.currentText()
                else:
                    data = control.currentData()
                    values[field.name] = str(data) if data is not None else control.currentText()
            elif isinstance(control, QLineEdit):
                values[field.name] = control.text()
            elif isinstance(control, QPlainTextEdit):
                values[field.name] = control.toPlainText()
        return values

    def _validate_ready(self) -> Optional[str]:
        if len(self._docs_card.paths()) != 1:
            return "Carga exactamente un PDF."
        self._load_fields()
        if not self._fields:
            return "Este PDF no contiene campos de formulario."
        if not any(field.supported for field in self._fields):
            return "No hay campos compatibles para rellenar."
        values = self._collect_values()
        missing = [
            field.label or field.name
            for field in self._fields
            if field.supported and field.required and _is_empty_form_value(values.get(field.name, ""))
        ]
        if missing:
            names = ", ".join(missing[:3])
            extra = f" y {len(missing) - 3} mas" if len(missing) > 3 else ""
            return f"Completa los campos requeridos: {names}{extra}."
        return None

    def _refresh_summary(self) -> None:
        values = self._collect_values()
        filled = sum(1 for value in values.values() if value.strip())
        rows = [
            f"<b>Documento:</b>&nbsp;&nbsp;{Path(self._docs_card.paths()[0]).name if self._docs_card.paths() else 'Sin documento'}",
            f"<b>Campos detectados:</b>&nbsp;&nbsp;{len(self._fields)}",
            f"<b>Valores no vacios:</b>&nbsp;&nbsp;{filled}",
            f"<b>Salida:</b>&nbsp;&nbsp;{'PDF aplanado' if self._flatten_chk.isChecked() else 'PDF editable'}",
        ]
        error = self._validate_ready()
        if error:
            rows.insert(0, f"<span style='color:#E5484D;'>Atencion: {error}</span>")
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )

    def _build_jobs(self) -> List[FormFillJob]:
        out_dir = make_run_dir("Formularios")
        source = self._docs_card.paths()[0]
        add_suffix = add_tool_suffix_enabled()
        out_path = unique_output_path_for_source(
            out_dir,
            source,
            extension=".pdf",
            tool_suffix="formulario",
            technical_suffix="aplanado" if self._flatten_chk.isChecked() else "editable",
            add_tool_suffix=add_suffix,
            fallback="documento",
        )
        return [
            FormFillJob(
                pdf_path=source,
                output_path=str(out_path),
                values=self._collect_values(),
                options=FormFillOptions(
                    flatten=self._flatten_chk.isChecked(),
                    skip_empty_values=self._skip_empty_chk.isChecked(),
                ),
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
        self._proc_step.set_progress(0, "Preparando formulario...")

        self._worker = FormFillWorker(self._build_jobs())
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
        self._proc_step.set_progress(100, "Formulario procesado")

        output_paths = [
            result.output_path
            for result in self.last_results
            if result.success and result.output_path
        ]
        self.ctx.tray.add_items(output_paths, "Formularios PDF")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        self._result_viewer.set_results(self.last_results)
        self._result_viewer.set_source_dirs([
            str(Path(result.job.pdf_path).parent)
            for result in self.last_results
        ])

        ok = sum(1 for result in self.last_results if result.success)
        if ok:
            show_success(self, "Formulario listo", "Se genero el PDF procesado.")
        else:
            show_warning(self, "Formulario con avisos", "No se pudo generar el PDF.")
        self._switch_section(3)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al procesar formulario", msg)

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
        self._fields = []
        self._field_controls = {}
        self._loaded_path = ""
        self._clear_fields_ui("Carga un PDF para detectar sus campos.")
        self._set_fields_ready(False)
        self._docs_summary_lbl.setText("Sin documento cargado.")
        self._flatten_chk.setChecked(True)
        self._skip_empty_chk.setChecked(False)
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


def _pages_text(field: FormField) -> str:
    pages = field.page_indices or (field.page_index,)
    human_pages = [str(page + 1) for page in pages]
    if len(human_pages) == 1:
        return f"Página {human_pages[0]}"
    if len(human_pages) <= 3:
        return "Páginas " + ", ".join(human_pages)
    return f"Páginas {', '.join(human_pages[:3])} y {len(human_pages) - 3} más"


def _is_empty_form_value(value: str) -> bool:
    normalized = str(value).strip().casefold()
    return normalized in {"", "off", "sin seleccionar"}
