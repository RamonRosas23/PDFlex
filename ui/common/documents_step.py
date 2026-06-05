"""DocumentsCard — tarjeta de carga de documentos reutilizable.

Consolida el paso "Documentos" que era idéntico en los 5 herramientas:
  - Botones Agregar / Quitar selección / Vaciar / Cargar desde bandeja
  - Lista con miniaturas PDF, drag-reorder opcional, Delete key
  - Conversión automática Word→PDF en segundo plano
  - Señal files_changed emitida en cada cambio

Uso:
    card = DocumentsCard(ctx, allow_reorder=True)
    card.files_changed.connect(self._on_files_changed)
    layout.addWidget(card, 1)
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal, QSize, QEvent
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QKeyEvent
from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QStackedWidget,
)

from ui.common.thumb_utils import make_pdf_thumb
from ui.common.icons import make_icon_label, set_button_icon
from ui.common.dialogs import show_info
from ui.common.file_dialogs import get_open_file_name, get_open_file_names
from core.output_paths import make_run_dir

if TYPE_CHECKING:
    from shell.context import ShellContext


class DocumentsCard(QFrame):
    """Tarjeta reutilizable de carga y ordenado de documentos PDF.

    Signals:
        files_changed(list[str]): Emitida cuando la lista cambia (orden incluido).
    """

    files_changed = pyqtSignal(list)

    def __init__(
        self,
        ctx: "ShellContext",
        *,
        single_file: bool = False,
        allow_reorder: bool = False,
        show_thumbnails: bool = True,
        thumb_size: tuple[int, int] = (64, 82),
        file_filter: str = (
            "PDF y Word (*.pdf *.doc *.docx);;"
            "PDF (*.pdf);;"
            "Word (*.doc *.docx)"
        ),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "Card")
        self.setAcceptDrops(True)

        self._ctx = ctx
        self._single_file = single_file
        self._show_thumbnails = show_thumbnails
        self._thumb_w, self._thumb_h = thumb_size
        self._file_filter = file_filter
        self._paths: List[str] = []
        self._path_set: set = set()

        self._conv_thread: Optional[QThread] = None
        self._conv_worker = None
        self._conv_dlg = None

        self._build(allow_reorder)

        ctx.tray.changed.connect(self._refresh_tray_btn)
        self._refresh_tray_btn()

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #

    def _build(self, allow_reorder: bool) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # ── Botones de acción ──────────────────────────────────────────
        row = QHBoxLayout()
        row.setSpacing(10)

        add_btn = QPushButton("Agregar archivos")
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
        self._remove_btn.setToolTip("Quita del lote los documentos seleccionados. No borra archivos del disco.")
        self._remove_btn.clicked.connect(self.remove_selected)
        self._remove_btn.setEnabled(False)
        row.addWidget(self._remove_btn)

        self._tray_btn = QPushButton("Cargar desde bandeja")
        self._tray_btn.setProperty("class", "Ghost")
        set_button_icon(self._tray_btn, "folder-open")
        self._tray_btn.clicked.connect(self._on_load_from_tray)
        row.addWidget(self._tray_btn)

        row.addStretch()

        self._count_lbl = QLabel("0 documentos")
        self._count_lbl.setProperty("class", "CardHint")
        row.addWidget(self._count_lbl)

        layout.addLayout(row)

        # ── Hint de reordenado ──────────────────────────────────────────
        if allow_reorder:
            hint = QLabel(
                "Arrastra para reordenar · selecciona y usa Quitar o Supr"
            )
            hint.setProperty("class", "CardHint")
            layout.addWidget(hint)

        # ── Área central: drop zone o lista ────────────────────────────
        self._content_stack = QStackedWidget()

        # ── Estado vacío (drop zone visual) ────────────────────────────
        self._empty_w = QFrame()
        self._empty_w.setObjectName("DropZone")
        self._empty_w.setMinimumHeight(220)
        self._empty_w.setCursor(Qt.CursorShape.ArrowCursor)
        ez = QVBoxLayout(self._empty_w)
        ez.setContentsMargins(32, 28, 32, 28)
        ez.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ez.setSpacing(0)

        # Ícono con badge coloreado
        icon_box = QFrame()
        icon_box.setFixedSize(56, 56)
        icon_box.setStyleSheet("""
            QFrame {
                background: rgba(94, 106, 210, 0.14);
                border: 1px solid rgba(94, 106, 210, 0.35);
                border-radius: 12px;
            }
        """)
        ib = QVBoxLayout(icon_box)
        ib.setContentsMargins(0, 0, 0, 0)
        ib_lbl = make_icon_label("folder-open", color="#7B8DE8", size=28)
        ib.addWidget(ib_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        ez.addWidget(icon_box, 0, Qt.AlignmentFlag.AlignCenter)

        ez.addSpacing(16)

        drop_title = QLabel("Arrastra archivos aquí")
        drop_title.setObjectName("DropZoneTitle")
        drop_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ez.addWidget(drop_title)

        ez.addSpacing(6)

        drop_sub = QLabel("o usa el botón <b>Agregar archivos</b>")
        drop_sub.setTextFormat(Qt.TextFormat.RichText)
        drop_sub.setObjectName("DropZoneHint")
        drop_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ez.addWidget(drop_sub)

        self._content_stack.addWidget(self._empty_w)   # idx 0

        # ── Lista de documentos ─────────────────────────────────────────
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(260)
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self._update_remove_btn)
        self.list_widget.installEventFilter(self)

        if allow_reorder:
            self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
            self.list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
            self.list_widget.model().rowsMoved.connect(self._sync_after_reorder)

        if self._show_thumbnails:
            self.list_widget.setIconSize(QSize(self._thumb_w, self._thumb_h))
            self.list_widget.setSpacing(3)

        self._content_stack.addWidget(self.list_widget)  # idx 1
        layout.addWidget(self._content_stack, 1)
        self._content_stack.setCurrentIndex(0)  # empezar en drop zone

    # ------------------------------------------------------------------ #
    # Event filter — Delete key
    # ------------------------------------------------------------------ #

    def eventFilter(self, obj, event) -> bool:
        if obj is self.list_widget and event.type() == QEvent.Type.KeyPress:
            if isinstance(event, QKeyEvent):
                if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    self._delete_selected()
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
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def _set_drop_active(self, active: bool) -> None:
        if not hasattr(self, "_empty_w"):
            return
        self._empty_w.setObjectName("DropZoneActive" if active else "DropZone")
        self._empty_w.style().unpolish(self._empty_w)
        self._empty_w.style().polish(self._empty_w)
        self._empty_w.update()

    def _delete_selected(self) -> None:
        self.remove_selected()

    def remove_selected(self) -> None:
        """Quita los documentos seleccionados del lote sin borrar archivos."""
        rows = sorted(
            {self.list_widget.row(item) for item in self.list_widget.selectedItems()},
            reverse=True,
        )
        if not rows:
            return
        next_row = min(rows[-1], max(0, self.list_widget.count() - len(rows) - 1))
        for row in rows:
            if 0 <= row < self.list_widget.count():
                item = self.list_widget.item(row)
                p = item.data(Qt.ItemDataRole.UserRole) if item else None
                if p:
                    self._path_set.discard(p)
                self.list_widget.takeItem(row)
        self._sync_paths_from_list()
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(next_row)
        self._update_count()
        self._update_remove_btn()
        self.files_changed.emit(self.paths())

    def _sync_paths_from_list(self) -> None:
        self._paths = self.paths()
        self._path_set = set(self._paths)

    def _sync_after_reorder(self) -> None:
        self._sync_paths_from_list()
        self.files_changed.emit(self.paths())

    def _update_remove_btn(self) -> None:
        selected = len(self.list_widget.selectedItems())
        self._remove_btn.setEnabled(selected > 0)
        if selected > 1:
            self._remove_btn.setText(f"Quitar ({selected})")
        else:
            self._remove_btn.setText("Quitar")

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #

    def paths(self) -> List[str]:
        """Retorna los paths en orden actual (respeta drag-reorder)."""
        result = []
        for i in range(self.list_widget.count()):
            p = self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            if p:
                result.append(p)
        return result

    def add_paths(self, raw_paths: List[str]) -> None:
        """Agrega paths, convirtiendo Word si es necesario."""
        pdfs = [p for p in raw_paths if p.lower().endswith(".pdf")]
        words = [p for p in raw_paths if p.lower().endswith((".doc", ".docx"))]
        if pdfs:
            self._add_pdf_paths(pdfs)
        if words:
            self._handle_word_files(words)

    def clear(self) -> None:
        self._paths.clear()
        self._path_set.clear()
        self.list_widget.clear()
        self._update_count()
        self._update_remove_btn()
        self.files_changed.emit([])

    def count(self) -> int:
        return self.list_widget.count()

    def is_empty(self) -> bool:
        return self.list_widget.count() == 0

    def remove_at(self, idx: int) -> None:
        """Elimina el documento en la posición dada."""
        if not (0 <= idx < self.list_widget.count()):
            return
        item = self.list_widget.item(idx)
        p = item.data(Qt.ItemDataRole.UserRole) if item else None
        if p:
            self._path_set.discard(p)
        self.list_widget.takeItem(idx)
        self._sync_paths_from_list()
        self._update_count()
        self._update_remove_btn()
        self.files_changed.emit(self.paths())

    def remove_path(self, path: str) -> None:
        """Elimina un documento por path."""
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).data(Qt.ItemDataRole.UserRole) == path:
                self.remove_at(i)
                return

    # ------------------------------------------------------------------ #
    # Internos
    # ------------------------------------------------------------------ #

    def _add_pdf_paths(self, paths: List[str]) -> None:
        if self._single_file:
            self.clear()
            paths = paths[:1]

        changed = False
        for p in paths:
            if p not in self._path_set:
                self._path_set.add(p)
                self._paths.append(p)
                item = QListWidgetItem(Path(p).name)
                item.setData(Qt.ItemDataRole.UserRole, p)
                item.setToolTip(p)
                if self._show_thumbnails:
                    thumb = make_pdf_thumb(p, width=self._thumb_w)
                    if thumb:
                        item.setIcon(QIcon(thumb))
                self.list_widget.addItem(item)
                changed = True

        if changed:
            self._update_count()
            self._update_remove_btn()
            self.files_changed.emit(self.paths())

    def _update_count(self) -> None:
        n = self.list_widget.count()
        self._count_lbl.setText(f"{n} documento" + ("s" if n != 1 else ""))
        # Alternar entre drop zone vacía y lista con archivos
        if hasattr(self, "_content_stack"):
            self._content_stack.setCurrentIndex(0 if n == 0 else 1)

    def _on_browse(self) -> None:
        title = "Seleccionar archivo" if self._single_file else "Seleccionar archivos"
        if self._single_file:
            path, _ = get_open_file_name(
                self.window(), title, "", self._file_filter
            )
            files = [path] if path else []
        else:
            files, _ = get_open_file_names(
                self.window(), title, "", self._file_filter
            )
        if files:
            self.add_paths(files)

    def _on_load_from_tray(self) -> None:
        paths = self._ctx.tray.paths()
        if self._single_file:
            self.add_paths(paths[:1])
        else:
            self.add_paths(paths)

    def _refresh_tray_btn(self) -> None:
        self._tray_btn.setVisible(self._ctx.tray.count() > 0)

    # ------------------------------------------------------------------ #
    # Word → PDF
    # ------------------------------------------------------------------ #

    def _handle_word_files(self, paths: List[str]) -> None:
        if not self._ctx.word_converter.is_available():
            show_info(
                self.window(), "Microsoft Office requerido",
                "Para convertir archivos Word a PDF se necesita Microsoft Office.\n"
                "Los archivos .doc/.docx han sido omitidos.",
            )
            return

        from shell.word_to_pdf import WordConvertWorker
        from ui.common.word_convert_dialog import WordConvertDialog

        self._conv_dlg = WordConvertDialog(self.window(), paths)

        worker = WordConvertWorker(
            self._ctx.word_converter,
            paths,
            make_run_dir("converted"),
        )
        self._conv_thread = QThread(self.window())
        self._conv_worker = worker
        worker.moveToThread(self._conv_thread)
        self._conv_thread.started.connect(worker.run)
        worker.progress.connect(self._conv_dlg.on_progress)
        worker.finished.connect(self._on_word_done)
        worker.finished.connect(self._conv_dlg.on_finished)
        worker.error.connect(self._on_word_error)
        worker.error.connect(self._conv_dlg.on_error)
        worker.finished.connect(self._conv_thread.quit)
        worker.error.connect(self._conv_thread.quit)
        self._conv_thread.finished.connect(worker.deleteLater)
        self._conv_thread.finished.connect(self._conv_thread.deleteLater)
        self._conv_thread.start()
        self._conv_dlg.exec()

    def _on_word_done(self, paths: List[str]) -> None:
        self._conv_thread = None
        self._conv_worker = None
        self._add_pdf_paths(paths)

    def _on_word_error(self, msg: str) -> None:
        self._conv_thread = None
        self._conv_worker = None
