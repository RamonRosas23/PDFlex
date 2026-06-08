"""SeparadorWindow — pipeline de separación de PDFs por rangos de páginas.

Pipeline:
    01 Documento  →  02 Rangos  →  03 Procesar  →  04 Resultados
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional

import fitz
from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import (
    QPixmap,
    QDragEnterEvent, QDropEvent, QDesktopServices,
)
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QFrame, QProgressBar,
    QLineEdit, QScrollArea, QSpinBox,
    QSizePolicy,
)

from core.split_ranges import (
    SplitRange, ValidationIssue,
    parse_range_text, validate_ranges,
    generate_equal_ranges, generate_one_per_page,
)
from core.splitter_engine import SplitterJob, SplitterEngine, SplitterJobResult
from core.output_paths import make_run_dir
from core.output_naming import output_filename_for_source
from shell.context import ShellContext
from shell.word_to_pdf import WordConvertWorker
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.tool_scaffold import PipelineWindow, RunnerThread
from ui.common.send_to_tool import SendToToolButton
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.process_step import ProcessStep
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.dialogs import (
    ask_int,
    ask_question,
    show_error,
    show_info,
    show_success,
    show_warning,
)
from ui.common.file_dialogs import get_open_file_name
from ui.common.icons import set_button_icon


# ====================================================================== #
#  Worker
# ====================================================================== #

class SplitterWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(object)   # SplitterJobResult
    error = pyqtSignal(str)

    def __init__(self, job: SplitterJob) -> None:
        super().__init__()
        self.job = job
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            engine = SplitterEngine()
            result = engine.run_job(
                self.job,
                progress=lambda c, t, m: self.progress.emit(c, t, m),
                should_cancel=lambda: self._cancel,
            )
            if self._cancel:
                self.error.emit("Operación cancelada.")
            else:
                self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ====================================================================== #
#  Ventana del Separador
# ====================================================================== #

class SeparadorWindow(PipelineWindow):

    SUPPORTED_EXTS = (".pdf", ".doc", ".docx")

    SECTIONS = [
        ("01", "Documento",  "Carga el PDF a separar"),
        ("02", "Rangos",     "Define los tramos"),
        ("03", "Procesar",   "Ejecuta la separación"),
        ("04", "Resultados", "Revisa los archivos separados"),
    ]
    BRAND = "Separador"
    TAGLINE = "Divide un PDF en múltiples archivos"
    ACCENT_COLOR = "#F5A623"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)

        self._pdf_path: Optional[str] = None
        self._total_pages: int = 0
        self._ranges: List[SplitRange] = []
        self.last_result: Optional[SplitterJobResult] = None
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[SplitterWorker] = None
        self._conv_thread: Optional[QThread] = None
        self._conv_dlg = None
        self._thumb_threads: list = []

        self._ranges_layout: Optional[QVBoxLayout] = None  # set during _build

        self._build_pages()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_document_section())
        self.stack.addWidget(self._build_ranges_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    # ------------------------------------------------------------------ #
    # Paso 01: Documento
    # ------------------------------------------------------------------ #

    def _build_document_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documento a separar",
            "Carga el PDF que deseas dividir. "
            "También puedes arrastrar el archivo sobre esta ventana.",
        ))

        # Card de carga
        load_card = make_card("Seleccionar archivo")
        ll = card_layout(load_card)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        open_btn = QPushButton("Seleccionar PDF o Word")
        open_btn.setProperty("class", "Primary")
        open_btn.clicked.connect(self._on_open_file)

        tray_btn = QPushButton("Cargar desde bandeja")
        tray_btn.setProperty("class", "Ghost")
        tray_btn.clicked.connect(self._on_load_from_tray)
        self.ctx.tray.changed.connect(
            lambda: tray_btn.setVisible(self.ctx.tray.count() > 0)
        )
        tray_btn.setVisible(self.ctx.tray.count() > 0)

        btn_row.addWidget(open_btn)
        btn_row.addWidget(tray_btn)
        btn_row.addStretch()
        ll.addLayout(btn_row)
        outer.addWidget(load_card)

        # Card de info del documento
        info_card = make_card("Documento cargado")
        il = card_layout(info_card)

        doc_body = QHBoxLayout()
        doc_body.setSpacing(20)

        # Miniatura primera página
        self._thumb_lbl = QLabel()
        self._thumb_lbl.setFixedSize(100, 130)
        self._thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_lbl.setText("Sin PDF")
        self._thumb_lbl.setStyleSheet(
            "background: #16161A; border: 1px dashed #33333B; border-radius: 6px;"
            " color: #6B6F7A; font-size: 11px;"
        )
        doc_body.addWidget(self._thumb_lbl)

        # Info texto
        info_col = QVBoxLayout()
        info_col.setSpacing(6)
        self._doc_name_lbl = QLabel("—")
        self._doc_name_lbl.setObjectName("CardTitle")
        self._doc_name_lbl.setWordWrap(True)
        self._doc_pages_lbl = QLabel("")
        self._doc_pages_lbl.setProperty("class", "CardHint")
        self._doc_size_lbl = QLabel("")
        self._doc_size_lbl.setProperty("class", "CardHint")
        self._remove_doc_btn = QPushButton("Quitar documento")
        self._remove_doc_btn.setProperty("class", "Ghost")
        self._remove_doc_btn.setToolTip("Quita este documento del flujo. No borra el archivo del disco.")
        self._remove_doc_btn.clicked.connect(self._on_remove_document)
        self._remove_doc_btn.setEnabled(False)
        info_col.addWidget(self._doc_name_lbl)
        info_col.addWidget(self._doc_pages_lbl)
        info_col.addWidget(self._doc_size_lbl)
        info_col.addWidget(self._remove_doc_btn)
        info_col.addStretch()
        doc_body.addLayout(info_col, 1)

        il.addLayout(doc_body)
        outer.addWidget(info_card)
        outer.addStretch(1)

        return page

    # ------------------------------------------------------------------ #
    # Paso 02: Rangos
    # ------------------------------------------------------------------ #

    def _build_ranges_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Definir tramos de separación",
            "Cada tramo se guardará como un archivo PDF independiente. "
            "Usa el formato 1-11 para un rango o 5 para una sola página.",
        ))

        # ---- Agregar tramo ----
        add_card = make_card()
        al = card_layout(add_card)
        al.setSpacing(10)

        add_title = QLabel("Agregar tramo")
        add_title.setProperty("class", "CardTitle")
        al.addWidget(add_title)

        add_row = QHBoxLayout()
        add_row.setSpacing(10)

        pages_lbl = QLabel("Páginas:")
        pages_lbl.setStyleSheet("color: #9094A0;")
        self._range_input = QLineEdit()
        self._range_input.setPlaceholderText("ej: 1-11  o  5")
        self._range_input.setMinimumWidth(170)
        self._range_input.returnPressed.connect(self._on_add_range)

        name_lbl = QLabel("Nombre:")
        name_lbl.setStyleSheet("color: #9094A0;")
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("nombre-salida (opcional)")
        self._name_input.setMinimumWidth(260)
        self._name_input.returnPressed.connect(self._on_add_range)

        add_btn = QPushButton("Agregar")
        add_btn.setProperty("class", "Primary")
        add_btn.setFixedHeight(34)
        set_button_icon(add_btn, "plus")
        add_btn.clicked.connect(self._on_add_range)

        add_row.addWidget(pages_lbl)
        add_row.addWidget(self._range_input, 1)
        add_row.addWidget(name_lbl)
        add_row.addWidget(self._name_input, 2)
        add_row.addWidget(add_btn)
        add_row.addStretch()
        al.addLayout(add_row)

        self._add_error_lbl = QLabel("")
        self._add_error_lbl.setStyleSheet("color: #E5484D; font-size: 11px;")
        al.addWidget(self._add_error_lbl)

        # Accesos rápidos
        quick_row = QHBoxLayout()
        quick_row.setSpacing(8)
        quick_lbl = QLabel("Accesos rápidos:")
        quick_lbl.setProperty("class", "CardHint")
        quick_row.addWidget(quick_lbl)

        equal_btn = QPushButton("Dividir en N partes iguales")
        equal_btn.setProperty("class", "Ghost")
        set_button_icon(equal_btn, "divide")
        equal_btn.clicked.connect(self._on_divide_equal)
        quick_row.addWidget(equal_btn)

        one_btn = QPushButton("Una página por archivo")
        one_btn.setProperty("class", "Ghost")
        set_button_icon(one_btn, "list")
        one_btn.clicked.connect(self._on_one_per_page)
        quick_row.addWidget(one_btn)

        clear_all_btn = QPushButton("Vaciar lista")
        clear_all_btn.setProperty("class", "Ghost")
        clear_all_btn.clicked.connect(self._on_clear_ranges)
        quick_row.addWidget(clear_all_btn)
        quick_row.addStretch()
        al.addLayout(quick_row)

        outer.addWidget(add_card)

        # ---- Lista de tramos ----
        list_card = make_card()
        ll = card_layout(list_card)

        list_header = QHBoxLayout()
        list_header_lbl = QLabel("Tramos configurados")
        list_header_lbl.setProperty("class", "CardTitle")
        self._tramo_count_lbl = QLabel("0 tramos")
        self._tramo_count_lbl.setProperty("class", "CardHint")
        list_header.addWidget(list_header_lbl)
        list_header.addStretch()
        list_header.addWidget(self._tramo_count_lbl)
        ll.addLayout(list_header)

        # Scroll con filas dinámicas
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(220)

        ranges_container = QWidget()
        self._ranges_layout = QVBoxLayout(ranges_container)
        self._ranges_layout.setSpacing(4)
        self._ranges_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(ranges_container)
        ll.addWidget(scroll, 1)

        # Estado de validación
        self._validation_lbl = QLabel("Sin tramos configurados")
        self._validation_lbl.setStyleSheet("color: #9094A0; font-size: 12px;")
        ll.addWidget(self._validation_lbl)

        outer.addWidget(list_card, 1)

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
            "Genera los tramos en temporal; usa \"Guardar como\" para conservarlos.",
        ))

        self._proc_step = ProcessStep(
            run_label="Separar documento",
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
            "Resultados",
            "Revisa los archivos PDF generados por la separación.",
        ))

        self._results_viewer = GenericPdfViewer("Archivos generados")
        self._results_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._results_viewer, 1)

        return page

    # ------------------------------------------------------------------ #
    # Action buttons (navbar footer)
    # ------------------------------------------------------------------ #

    def _build_action_buttons(self) -> None:
        from ui.common.icons import set_button_icon
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Separar documento")
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

        self._send_btn = SendToToolButton(self.ctx, "separador")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()

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
        if paths:
            self._add_file_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        if paths:
            self._add_file_paths(paths)
        self._switch_section(0)

    # ------------------------------------------------------------------ #
    # Carga de documento
    # ------------------------------------------------------------------ #

    def _on_open_file(self) -> None:
        path, _ = get_open_file_name(
            self, "Seleccionar PDF o Word", "",
            "PDF y Word (*.pdf *.doc *.docx);;PDF (*.pdf);;Word (*.doc *.docx)",
        )
        if path:
            self._add_file_paths([path])

    def _on_load_from_tray(self) -> None:
        paths = [
            p for p in self.ctx.tray.paths()
            if Path(p).suffix.lower() in self.SUPPORTED_EXTS
        ]
        if paths:
            self._add_file_paths(paths[:1])  # solo el primero
        else:
            show_info(
                self,
                "Sin documentos compatibles",
                "La bandeja no contiene archivos PDF o Word para separar.",
            )

    def _add_file_paths(self, paths: List[str]) -> None:
        pdfs = [p for p in paths if Path(p).suffix.lower() == ".pdf"]
        words = [p for p in paths if Path(p).suffix.lower() in (".doc", ".docx")]
        if pdfs:
            self._load_pdf(pdfs[0])
        elif words:
            self._handle_word_files(words[:1])
        elif paths:
            show_info(
                self,
                "Archivo no compatible",
                "Selecciona un archivo PDF, DOC o DOCX.",
            )

    def _load_pdf(self, path: str) -> None:
        try:
            doc = fitz.open(path)
            self._total_pages = doc.page_count
            doc.close()
        except Exception as e:
            show_warning(self, "Error al abrir", str(e))
            return

        self._pdf_path = path
        size_kb = Path(path).stat().st_size / 1024
        size_str = f"{size_kb/1024:.1f} MB" if size_kb >= 1024 else f"{size_kb:.0f} KB"

        self._doc_name_lbl.setText(Path(path).name)
        self._doc_pages_lbl.setText(f"{self._total_pages} páginas")
        self._doc_size_lbl.setText(size_str)
        self._remove_doc_btn.setEnabled(True)

        # Mostrar placeholder mientras el thumbnail carga en hilo separado
        self._thumb_lbl.setText("")
        self._thumb_lbl.setStyleSheet(
            "background: #111114; border: 1px solid #26262C; border-radius: 6px;"
        )
        self._schedule_thumb(path)

        # Actualizar validación de rangos existentes
        if self._ranges:
            self._rebuild_ranges_ui()
        self._sync_run_enabled()

    def _schedule_thumb(self, path: str) -> None:
        """Genera el thumbnail del PDF en hilo secundario (no bloquea GUI)."""
        from ui.common.thumb_utils import ThumbnailLoader
        loader = ThumbnailLoader(path, width=94)
        thread = RunnerThread(loader.run, self)
        loader.ready.connect(self._apply_thumb)
        loader.ready.connect(thread.quit)
        thread.finished.connect(loader.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda t=thread: self._thumb_threads.remove(t) if t in self._thumb_threads else None
        )
        self._thumb_threads.append(thread)
        thread.start()

    def _apply_thumb(self, path: str, qimage) -> None:
        """Slot en GUI thread — convierte QImage→QPixmap; ignora resultados obsoletos."""
        if path != self._pdf_path or qimage is None:
            return
        pix = QPixmap.fromImage(qimage)
        if not pix.isNull():
            thumb = pix.scaledToWidth(94, Qt.TransformationMode.SmoothTransformation)
            self._thumb_lbl.setPixmap(thumb)

    def _on_remove_document(self) -> None:
        if not self._pdf_path:
            return
        if self._ranges:
            if not ask_question(
                self,
                "Quitar documento",
                "Se quitará el documento cargado y se perderán los tramos configurados.\n\n"
                "¿Continuar?",
                accept_text="Quitar",
                cancel_text="Cancelar",
                danger=True,
            ):
                return
        self._clear_loaded_document()

    def _clear_loaded_document(self) -> None:
        self._results_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_result = None
        self._pdf_path = None
        self._total_pages = 0
        self._ranges.clear()
        self._doc_name_lbl.setText("—")
        self._doc_pages_lbl.setText("")
        self._doc_size_lbl.setText("")
        self._remove_doc_btn.setEnabled(False)
        self._thumb_lbl.clear()
        self._thumb_lbl.setText("Sin PDF")
        self._thumb_lbl.setStyleSheet(
            "background: #16161A; border: 1px dashed #33333B; border-radius: 6px;"
            " color: #6B6F7A; font-size: 11px;"
        )
        self._proc_step.reset()
        self._rebuild_ranges_ui()
        self._sync_run_enabled()

    # ------------------------------------------------------------------ #
    # Word → PDF
    # ------------------------------------------------------------------ #

    def _handle_word_files(self, paths: List[str]) -> None:
        if self._conv_thread is not None:
            return
        if not self.ctx.word_converter.is_available():
            show_info(
                self, "Microsoft Office requerido",
                "Para convertir archivos Word a PDF se necesita "
                "Microsoft Office instalado.\n\nEl archivo .doc/.docx ha sido omitido.",
            )
            return

        from ui.common.word_convert_dialog import WordConvertDialog

        self._conv_dlg = WordConvertDialog(self, paths)

        worker = WordConvertWorker(
            self.ctx.word_converter,
            paths,
            make_run_dir("converted"),
        )
        thread = RunnerThread(worker.run, self)
        worker.progress.connect(self._conv_dlg.on_progress)
        worker.finished.connect(self._conv_dlg.on_finished)
        worker.error.connect(self._conv_dlg.on_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        worker.finished.connect(self._on_word_convert_done)
        worker.error.connect(self._on_word_convert_error)
        self._conv_thread = thread
        thread.start()
        self._conv_dlg.exec()

    def _on_word_convert_done(self, paths: List[str]) -> None:
        self._conv_thread = None
        if paths:
            self._load_pdf(paths[0])

    def _on_word_convert_error(self, msg: str) -> None:
        self._conv_thread = None

    # ------------------------------------------------------------------ #
    # Editor de rangos
    # ------------------------------------------------------------------ #

    def _sync_names(self) -> None:
        """Lee los nombres de los QLineEdits del UI y actualiza self._ranges."""
        if self._ranges_layout is None:
            return
        edits_found = 0
        for i in range(self._ranges_layout.count()):
            item = self._ranges_layout.itemAt(i)
            if not item or not item.widget():
                continue
            edits = item.widget().findChildren(QLineEdit)
            if edits and edits_found < len(self._ranges):
                self._ranges[edits_found].name = edits[0].text()
                edits_found += 1

    def _rebuild_ranges_ui(self) -> None:
        if self._ranges_layout is None:
            return
        while self._ranges_layout.count():
            item = self._ranges_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, rng in enumerate(self._ranges):
            row = self._make_range_row(i, rng)
            self._ranges_layout.addWidget(row)
        self._ranges_layout.addStretch()

        n = len(self._ranges)
        self._tramo_count_lbl.setText(f"{n} tramo{'s' if n != 1 else ''}")
        self._update_validation_display()
        self._sync_run_enabled()

    def _make_range_row(self, idx: int, rng: SplitRange) -> QFrame:
        row = QFrame()
        row.setProperty("class", "TrayItemRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        # Índice
        num_lbl = QLabel(f"#{idx + 1}")
        num_lbl.setFixedWidth(28)
        num_lbl.setStyleSheet("color: #9094A0; font-size: 12px;")
        h.addWidget(num_lbl)

        # Nombre editable
        name_edit = QLineEdit(rng.name)
        name_edit.setPlaceholderText("nombre-salida")
        name_edit.setFixedWidth(160)
        h.addWidget(name_edit)

        # Rango de páginas
        n_pags = rng.page_count
        pages_txt = (
            f"Págs {rng.start}–{rng.end}  ·  "
            f"{n_pags} pág{'s' if n_pags != 1 else ''}"
        )
        pages_lbl = QLabel(pages_txt)
        pages_lbl.setStyleSheet("color: #9094A0;")
        h.addWidget(pages_lbl, 1)

        # Botones de reordenado
        up_btn = QPushButton()
        up_btn.setProperty("class", "IconBtn")
        up_btn.setFixedSize(28, 28)
        set_button_icon(up_btn, "chevron-up", size=14, icon_only=True)
        up_btn.setEnabled(idx > 0)
        up_btn.clicked.connect(lambda _, i=idx: self._move_range(i, -1))
        h.addWidget(up_btn)

        down_btn = QPushButton()
        down_btn.setProperty("class", "IconBtn")
        down_btn.setFixedSize(28, 28)
        set_button_icon(down_btn, "chevron-down", size=14, icon_only=True)
        down_btn.setEnabled(idx < len(self._ranges) - 1)
        down_btn.clicked.connect(lambda _, i=idx: self._move_range(i, +1))
        h.addWidget(down_btn)

        # Botón eliminar
        del_btn = QPushButton()
        del_btn.setProperty("class", "IconBtn")
        del_btn.setFixedSize(28, 28)
        set_button_icon(del_btn, "x", size=14, icon_only=True)
        del_btn.clicked.connect(lambda _, i=idx: self._delete_range(i))
        h.addWidget(del_btn)

        return row

    def _update_validation_display(self) -> None:
        if not self._ranges:
            self._validation_lbl.setText("Sin tramos configurados")
            self._validation_lbl.setStyleSheet("color: #9094A0; font-size: 12px;")
            return

        issues = validate_ranges(self._ranges, self._total_pages)
        errors = [i for i in issues if i.kind == "error"]
        warnings = [i for i in issues if i.kind == "warning"]
        covered = sum(r.page_count for r in self._ranges)

        if errors:
            self._validation_lbl.setText(f"Error: {errors[0].message}")
            self._validation_lbl.setStyleSheet("color: #E5484D; font-size: 12px;")
        elif warnings:
            total_str = f"/{self._total_pages}" if self._total_pages > 0 else ""
            self._validation_lbl.setText(
                f"Atención: {len(self._ranges)} tramos · "
                f"{covered}{total_str} págs · {warnings[0].message}"
            )
            self._validation_lbl.setStyleSheet("color: #F5A623; font-size: 12px;")
        else:
            total_str = f"/{self._total_pages}" if self._total_pages > 0 else ""
            self._validation_lbl.setText(
                f"{len(self._ranges)} tramos · "
                f"{covered}{total_str} páginas cubiertas · Sin solapamientos"
            )
            self._validation_lbl.setStyleSheet("color: #3BD37C; font-size: 12px;")

    # ---- Acciones del editor ----

    def _on_add_range(self) -> None:
        text = self._range_input.text()
        result = parse_range_text(text)
        if isinstance(result, str):
            self._add_error_lbl.setText(result)
            return

        start, end = result
        if self._total_pages > 0 and end > self._total_pages:
            self._add_error_lbl.setText(
                f"La página {end} excede el total del documento ({self._total_pages})"
            )
            return

        self._add_error_lbl.setText("")
        name = self._name_input.text().strip()
        if not name:
            name = f"parte-{len(self._ranges) + 1:02d}"

        self._sync_names()
        self._ranges.append(SplitRange(start=start, end=end, name=name))
        self._range_input.clear()
        self._name_input.clear()
        self._range_input.setFocus()
        self._rebuild_ranges_ui()

    def _delete_range(self, idx: int) -> None:
        self._sync_names()
        if 0 <= idx < len(self._ranges):
            self._ranges.pop(idx)
        self._rebuild_ranges_ui()

    def _move_range(self, idx: int, direction: int) -> None:
        self._sync_names()
        new_idx = idx + direction
        if 0 <= new_idx < len(self._ranges):
            self._ranges[idx], self._ranges[new_idx] = (
                self._ranges[new_idx], self._ranges[idx]
            )
        self._rebuild_ranges_ui()

    def _on_clear_ranges(self) -> None:
        self._ranges.clear()
        self._rebuild_ranges_ui()

    def _on_divide_equal(self) -> None:
        if self._total_pages == 0:
            show_info(self, "Sin documento", "Carga primero un PDF.")
            return
        n, ok = ask_int(
            self, "Dividir en N partes", "¿En cuántas partes iguales?",
            value=2, minimum=2, maximum=min(self._total_pages, 500),
        )
        if ok and n >= 2:
            self._sync_names()
            self._ranges = generate_equal_ranges(self._total_pages, n)
            self._rebuild_ranges_ui()

    def _on_one_per_page(self) -> None:
        if self._total_pages == 0:
            show_info(self, "Sin documento", "Carga primero un PDF.")
            return
        if self._total_pages > 50:
            if not ask_question(
                self, "Confirmar",
                f"Esto creará {self._total_pages} archivos (uno por página). "
                "¿Continuar?",
                accept_text="Continuar",
                cancel_text="Cancelar",
            ):
                return
        self._sync_names()
        self._ranges = generate_one_per_page(self._total_pages)
        self._rebuild_ranges_ui()

    # ------------------------------------------------------------------ #
    # Procesar
    # ------------------------------------------------------------------ #

    def _refresh_summary(self) -> None:
        self._sync_names()
        issues = validate_ranges(self._ranges, self._total_pages)
        errors = [i for i in issues if i.kind == "error"]
        covered = sum(r.page_count for r in self._ranges)

        rows = []
        if self._pdf_path:
            rows.append(f"<b>Documento:</b> &nbsp; {Path(self._pdf_path).name}")
            rows.append(f"<b>Total páginas:</b> &nbsp; {self._total_pages}")
        rows.append(f"<b>Tramos:</b> &nbsp; {len(self._ranges)}")
        rows.append(f"<b>Páginas cubiertas:</b> &nbsp; {covered}")
        if errors:
            rows.append(f"<b style='color:#E5484D'>Errores:</b> &nbsp; {errors[0].message}")
        else:
            rows.append("<b>Validación:</b> &nbsp; Sin errores")
        if self._ranges:
            rows.append("<b>Archivos a generar:</b>")
            add_suffix = add_tool_suffix_enabled()
            src_stem = Path(self._pdf_path).stem if self._pdf_path else "documento"
            for i, r in enumerate(self._ranges[:5]):
                name = output_filename_for_source(
                    src_stem,
                    extension=".pdf",
                    tool_suffix="separado",
                    add_tool_suffix=add_suffix,
                    technical_suffix=r.name or f"parte-{i+1:02d}",
                    fallback="documento",
                )
                rows.append(
                    f"<span style='color:#9094A0;font-family:monospace'>"
                    f"  {name}"
                    f"  (págs {r.start}–{r.end})</span>"
                )
            if len(self._ranges) > 5:
                rows.append(f"<span style='color:#6B6F7A'>  … y {len(self._ranges)-5} más</span>")

        html = "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        self._proc_step.set_summary_html(html)
        self._sync_run_enabled()

    def _validate_ready(self) -> Optional[str]:
        if not self._pdf_path:
            return "Carga primero un documento PDF."
        if not self._ranges:
            return "Define al menos un tramo en el Paso 02."
        issues = validate_ranges(self._ranges, self._total_pages)
        errors = [i for i in issues if i.kind == "error"]
        if errors:
            return errors[0].message
        return None

    def _sync_run_enabled(self) -> None:
        if not hasattr(self, "_proc_step"):
            return
        self._proc_step.set_run_enabled(self._validate_ready() is None)

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._proc_step.set_progress(self._proc_step._prog_bar.value(), "Cancelando…")

    def _on_run(self) -> None:
        self._stop_active_worker()
        err = self._validate_ready()
        if err:
            show_warning(self, "Falta información", err)
            return
        if self._worker_thread is not None:
            return

        self._sync_names()
        self._results_viewer.clear_results()
        self._send_btn.set_output_paths([])

        src_stem = Path(self._pdf_path).stem
        task_dir = make_run_dir("Separador")

        job = SplitterJob(
            pdf_path=self._pdf_path,
            output_dir=str(task_dir),
            ranges=list(self._ranges),
            base_name=src_stem,
            tool_suffix="separado",
            add_tool_suffix=add_tool_suffix_enabled(),
        )

        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Iniciando…")

        self._worker = SplitterWorker(job)
        self._worker_thread = RunnerThread(self._worker.run, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)

        self._worker_thread.start()

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        self._proc_step.set_progress(int(current / max(1, total) * 100), msg)

    def _on_finished(self, result: SplitterJobResult) -> None:
        self.last_result = result
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Completado")
        self._worker_thread = None
        self._worker = None

        ok = sum(1 for r in result.split_results if r.success)
        fail = len(result.split_results) - ok

        output_paths = [r.output_path for r in result.split_results if r.success and r.output_path]
        self.ctx.tray.add_items(output_paths, "Separador")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        show_success(
            self, "Separación completa",
            f"Se generaron {ok} archivo{'s' if ok != 1 else ''}.\n"
            + (f"Con error: {fail}" if fail else ""),
        )
        self._results_viewer.set_results(result.split_results)
        src_dir = str(Path(result.job.pdf_path).parent)
        self._results_viewer.set_source_dirs([src_dir] * len(result.split_results))
        self._switch_section(3)

    def _on_worker_error(self, msg: str) -> None:
        show_error(self, "Error", msg)
        self._proc_step.set_running(False)
        # thread.quit + deleteLater happen automatically via signal connections in _on_run
        self._worker_thread = None
        self._worker = None

    def _open_in_explorer(self, path: str) -> None:
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    # ------------------------------------------------------------------ #
    # Reset
    # ------------------------------------------------------------------ #

    def _reset_session(self) -> None:
        self._clear_loaded_document()
        self._switch_section(0)

    # ------------------------------------------------------------------ #
    # Drag & drop
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        self._add_file_paths(paths)
        self._switch_section(0)
