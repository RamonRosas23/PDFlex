"""WordAPdfWindow — herramienta dedicada para convertir Word a PDF."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QEvent, QObject, QThread, pyqtSignal, QUrl, QSize
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QKeyEvent, QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFrame, QStackedWidget,
)

from core.output_paths import make_run_dir
from shell.context import ShellContext
from shell.word_to_pdf import WordConvertWorker
from ui.common.cards import make_page_header
from ui.common.dialogs import show_error, show_info, show_success, show_warning
from ui.common.file_dialogs import get_open_file_names
from ui.common.icons import icon, make_icon_label, set_button_icon
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.process_step import ProcessStep
from ui.common.result_ui import configure_result_list, format_file_size
from ui.common.tool_scaffold import PipelineWindow, RunnerThread


WORD_EXTS = {".doc", ".docx"}
WORD_FILTER = "Word (*.doc *.docx);;Todos los archivos (*)"


@dataclass
class WordPdfResult:
    source_path: str
    output_path: str
    success: bool
    error: str = ""


class WordListCard(QFrame):
    """Carga y administra documentos Word sin convertirlos todavía."""

    files_changed = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "Card")
        self.setAcceptDrops(True)
        self._path_set: set[str] = set()
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(10)

        add_btn = QPushButton("Agregar Word")
        add_btn.setProperty("class", "Primary")
        set_button_icon(add_btn, "plus")
        add_btn.clicked.connect(self._on_browse)
        row.addWidget(add_btn)

        clear_btn = QPushButton("Vaciar")
        clear_btn.setProperty("class", "Ghost")
        set_button_icon(clear_btn, "eraser")
        clear_btn.setToolTip("Vacía la lista actual sin borrar archivos del disco.")
        clear_btn.clicked.connect(self.clear)
        row.addWidget(clear_btn)

        self._remove_btn = QPushButton("Quitar")
        self._remove_btn.setProperty("class", "Ghost")
        set_button_icon(self._remove_btn, "trash-2")
        self._remove_btn.setToolTip("Quita de la lista los documentos seleccionados.")
        self._remove_btn.clicked.connect(self.remove_selected)
        self._remove_btn.setEnabled(False)
        row.addWidget(self._remove_btn)

        row.addStretch()

        self._count_lbl = QLabel("0 documentos")
        self._count_lbl.setProperty("class", "CardHint")
        row.addWidget(self._count_lbl)
        layout.addLayout(row)

        self._content_stack = QStackedWidget()

        self._empty_w = QFrame()
        self._empty_w.setObjectName("DropZone")
        self._empty_w.setMinimumHeight(240)
        ez = QVBoxLayout(self._empty_w)
        ez.setContentsMargins(32, 28, 32, 28)
        ez.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ez.setSpacing(0)

        icon_box = QFrame()
        icon_box.setFixedSize(56, 56)
        icon_box.setStyleSheet("""
            QFrame {
                background: rgba(66, 153, 225, 0.14);
                border: 1px solid rgba(66, 153, 225, 0.35);
                border-radius: 12px;
            }
        """)
        ib = QVBoxLayout(icon_box)
        ib.setContentsMargins(0, 0, 0, 0)
        ib.addWidget(
            make_icon_label("file-text", color="#63B3ED", size=28),
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
        ez.addWidget(icon_box, 0, Qt.AlignmentFlag.AlignCenter)
        ez.addSpacing(16)

        drop_title = QLabel("Arrastra documentos Word aquí")
        drop_title.setObjectName("DropZoneTitle")
        drop_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ez.addWidget(drop_title)

        ez.addSpacing(6)
        drop_sub = QLabel("Acepta archivos .doc y .docx")
        drop_sub.setObjectName("DropZoneHint")
        drop_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ez.addWidget(drop_sub)

        self._content_stack.addWidget(self._empty_w)

        self.list_widget = QListWidget()
        configure_result_list(self.list_widget)
        self.list_widget.setMinimumHeight(280)
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self._update_remove_btn)
        self.list_widget.installEventFilter(self)
        self._content_stack.addWidget(self.list_widget)

        layout.addWidget(self._content_stack, 1)
        self._content_stack.setCurrentIndex(0)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.list_widget and event.type() == QEvent.Type.KeyPress:
            if isinstance(event, QKeyEvent) and event.key() in (
                Qt.Key.Key_Delete,
                Qt.Key.Key_Backspace,
            ):
                self.remove_selected()
                return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            self._set_drop_active(True)
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._set_drop_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drop_active(False)
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def paths(self) -> List[str]:
        result = []
        for idx in range(self.list_widget.count()):
            path = self.list_widget.item(idx).data(Qt.ItemDataRole.UserRole)
            if path:
                result.append(path)
        return result

    def add_paths(self, raw_paths: List[str]) -> None:
        changed = False
        for raw in raw_paths:
            path = Path(raw)
            if path.suffix.lower() not in WORD_EXTS or not path.is_file():
                continue
            value = str(path)
            key = value.casefold()
            if key in self._path_set:
                continue
            self._path_set.add(key)
            size = format_file_size(path)
            detail = path.suffix.upper().lstrip(".")
            if size:
                detail += f" · {size}"
            item = QListWidgetItem(f"{path.name}\n{detail}")
            item.setIcon(icon("file-text", "#63B3ED", 15))
            item.setSizeHint(QSize(200, 46))
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setToolTip(value)
            self.list_widget.addItem(item)
            changed = True
        if changed:
            self._sync_after_change()

    def clear(self) -> None:
        self._path_set.clear()
        self.list_widget.clear()
        self._sync_after_change()

    def count(self) -> int:
        return self.list_widget.count()

    def is_empty(self) -> bool:
        return self.count() == 0

    def remove_selected(self) -> None:
        rows = sorted(
            {self.list_widget.row(item) for item in self.list_widget.selectedItems()},
            reverse=True,
        )
        if not rows:
            return
        for row in rows:
            item = self.list_widget.item(row)
            if item:
                path = item.data(Qt.ItemDataRole.UserRole)
                if path:
                    self._path_set.discard(str(path).casefold())
            self.list_widget.takeItem(row)
        self._sync_after_change()

    def _sync_after_change(self) -> None:
        self._update_count()
        self._update_remove_btn()
        self.files_changed.emit(self.paths())

    def _update_count(self) -> None:
        count = self.count()
        self._count_lbl.setText(f"{count} documento" + ("s" if count != 1 else ""))
        self._content_stack.setCurrentIndex(0 if count == 0 else 1)

    def _update_remove_btn(self) -> None:
        selected = len(self.list_widget.selectedItems())
        self._remove_btn.setEnabled(selected > 0)
        self._remove_btn.setText(f"Quitar ({selected})" if selected > 1 else "Quitar")

    def _set_drop_active(self, active: bool) -> None:
        self._empty_w.setObjectName("DropZoneActive" if active else "DropZone")
        self._empty_w.style().unpolish(self._empty_w)
        self._empty_w.style().polish(self._empty_w)
        self._empty_w.update()

    def _on_browse(self) -> None:
        files, _ = get_open_file_names(
            self.window(),
            "Seleccionar documentos Word",
            "",
            WORD_FILTER,
        )
        if files:
            self.add_paths(files)


class WordAPdfWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Documentos", "Carga archivos DOC o DOCX"),
        ("02", "Procesar", "Ejecuta la conversión"),
        ("03", "Resultados", "Revisa los PDFs generados"),
    ]
    BRAND = "Word a PDF"
    TAGLINE = "Convierte documentos Word en PDFs"
    ACCENT_COLOR = "#4299E1"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.last_results: List[WordPdfResult] = []
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[QObject] = None

        self._build_pages()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documentos Word",
            "Carga uno o varios documentos .doc o .docx para convertirlos a PDF.",
        ))

        self._word_card = WordListCard()
        outer.addWidget(self._word_card, 1)

        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Convierte los documentos con Microsoft Word instalado en este equipo.",
        ))

        self._proc_step = ProcessStep(
            run_label="Convertir a PDF",
            show_output_dir=False,
        )
        self._proc_step.watch_documents(self._word_card)
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
            "Revisa los PDFs convertidos y consérvalos con Guardar como.",
        ))

        self._results_viewer = GenericPdfViewer("PDFs convertidos")
        self._results_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._results_viewer, 1)

        return page

    def _build_action_buttons(self) -> None:
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Convertir a PDF")
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

        self._send_btn = SendToToolButton(self.ctx, "word_a_pdf")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()

    def _on_section_activated(self, idx: int) -> None:
        if idx == 1:
            self._refresh_summary()

    def set_inputs(self, paths: List[str]) -> None:
        self._word_card.add_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._word_card.add_paths(paths)
        self._switch_section(0)

    def _refresh_summary(self) -> None:
        count = self._word_card.count()
        converter = getattr(self.ctx, "word_converter", None)
        word_ready = bool(converter and converter.is_available())
        rows = [
            f"<b>Documentos:</b>&nbsp;&nbsp;{count}",
            "<b>Salida:</b>&nbsp;&nbsp;PDF temporal por cada documento Word",
            f"<b>Microsoft Word:</b>&nbsp;&nbsp;{'Disponible' if word_ready else 'No detectado'}",
        ]
        if not word_ready:
            rows.append(
                "<span style='color:#E5484D;'>Se requiere Microsoft Office para convertir.</span>"
            )
        self._proc_step.set_summary_html(
            "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        )

    def _validate_ready(self) -> Optional[str]:
        if self._word_card.is_empty():
            return "Agrega al menos un documento Word."
        converter = getattr(self.ctx, "word_converter", None)
        if converter is None or not converter.is_available():
            return "Para convertir Word a PDF se necesita Microsoft Office instalado."
        return None

    def _on_run(self) -> None:
        self._stop_active_worker()
        error = self._validate_ready()
        if error:
            show_warning(self, "Falta información", error)
            return
        if self._worker_thread is not None:
            return

        self._results_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []

        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Iniciando Microsoft Word...")

        worker = WordConvertWorker(
            self.ctx.word_converter,
            self._word_card.paths(),
            make_run_dir("WordPDF"),
        )
        self._worker = worker
        self._worker_thread = RunnerThread(worker.run, self)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(self._worker_thread.quit)
        worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_cancel(self) -> None:
        self._proc_step.set_progress(
            self._current_progress(),
            "La conversión de Word no se puede interrumpir de forma segura.",
        )
        show_info(
            self,
            "Conversión en curso",
            "Microsoft Word está terminando la conversión actual. "
            "Espera a que finalice para evitar archivos incompletos.",
        )

    def _on_progress(self, current: int, total: int, message: str) -> None:
        self._proc_step.set_progress(int(current / max(1, total) * 100), message)

    def _on_finished(self, output_paths: list) -> None:
        source_paths = self._word_card.paths()
        self.last_results = [
            WordPdfResult(
                source_path=source_paths[idx] if idx < len(source_paths) else "",
                output_path=path,
                success=True,
            )
            for idx, path in enumerate(output_paths)
        ]

        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Conversión completada")
        self._worker_thread = None
        self._worker = None

        self._results_viewer.set_results(self.last_results)
        self._results_viewer.set_source_dirs(
            [
                str(Path(result.source_path).parent)
                if result.source_path else str(Path.home())
                for result in self.last_results
            ]
        )

        self.ctx.tray.add_items(list(output_paths), "Word a PDF")
        self._send_btn.set_output_paths(list(output_paths))
        self.outputs_ready.emit(list(output_paths))

        show_success(
            self,
            "Conversión completa",
            f"Se generaron {len(output_paths)} PDF"
            + ("s." if len(output_paths) != 1 else "."),
        )
        self._switch_section(2)

    def _on_worker_error(self, message: str) -> None:
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, "Error en la conversión")
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
            self._worker_thread.deleteLater()
            self._worker_thread = None
            self._worker = None
        show_error(self, "Error al convertir Word a PDF", message)

    def _current_progress(self) -> int:
        bar = getattr(self._proc_step, "_prog_bar", None)
        return int(bar.value()) if bar is not None else 0

    def _open_in_explorer(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _reset_session(self) -> None:
        self.last_results = []
        self._results_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._word_card.clear()
        self._proc_step.reset()
        self._switch_section(0)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.handle_drop([url.toLocalFile() for url in event.mimeData().urls()])
        event.acceptProposedAction()
