"""DocumentsCard — tarjeta de carga de documentos reutilizable.

Consolida el paso "Documentos" que era idéntico en los 5 herramientas:
  - Botones Agregar / Vaciar / Cargar desde bandeja
  - Lista con miniaturas PDF, drag-reorder opcional, Delete key
  - Conversión automática Word→PDF en segundo plano
  - Señal files_changed emitida en cada cambio

Uso:
    card = DocumentsCard(ctx, allow_reorder=True)
    card.files_changed.connect(self._on_files_changed)
    layout.addWidget(card, 1)
"""
from __future__ import annotations
import tempfile
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal, QSize, QEvent
from PyQt6.QtGui import QIcon, QKeyEvent
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QProgressDialog,
)

from ui.common.thumb_utils import make_pdf_thumb

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

        self._ctx = ctx
        self._single_file = single_file
        self._show_thumbnails = show_thumbnails
        self._thumb_w, self._thumb_h = thumb_size
        self._file_filter = file_filter
        self._word_tmp = Path(tempfile.gettempdir()).resolve() / "PDFlex" / "converted"

        self._paths: List[str] = []
        self._path_set: set = set()

        self._conv_thread: Optional[QThread] = None
        self._conv_dlg: Optional[QProgressDialog] = None

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
        add_btn.clicked.connect(self._on_browse)
        row.addWidget(add_btn)

        clear_btn = QPushButton("Vaciar")
        clear_btn.setProperty("class", "Ghost")
        clear_btn.clicked.connect(self.clear)
        row.addWidget(clear_btn)

        self._tray_btn = QPushButton("Cargar desde bandeja")
        self._tray_btn.setProperty("class", "Ghost")
        self._tray_btn.clicked.connect(self._on_load_from_tray)
        row.addWidget(self._tray_btn)

        row.addStretch()

        self._count_lbl = QLabel("0 documentos")
        self._count_lbl.setProperty("class", "CardHint")
        row.addWidget(self._count_lbl)

        layout.addLayout(row)

        # ── Hint de reordenado ──────────────────────────────────────────
        if allow_reorder:
            hint = QLabel("Arrastra para reordenar — el orden aquí es el orden de procesamiento")
            hint.setProperty("class", "CardHint")
            layout.addWidget(hint)

        # ── Lista de documentos ─────────────────────────────────────────
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(280)
        self.list_widget.installEventFilter(self)

        if allow_reorder:
            self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
            self.list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
            # Al soltar un elemento, emitir cambio
            self.list_widget.model().rowsMoved.connect(
                lambda: self.files_changed.emit(self.paths())
            )

        if self._show_thumbnails:
            self.list_widget.setIconSize(QSize(self._thumb_w, self._thumb_h))
            self.list_widget.setSpacing(3)

        layout.addWidget(self.list_widget, 1)

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

    def _delete_selected(self) -> None:
        rows = sorted(
            {self.list_widget.row(item) for item in self.list_widget.selectedItems()},
            reverse=True,
        )
        for row in rows:
            if 0 <= row < len(self._paths):
                p = self._paths.pop(row)
                self._path_set.discard(p)
                self.list_widget.takeItem(row)
        self._update_count()
        self.files_changed.emit(self.paths())

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
        self.files_changed.emit([])

    def count(self) -> int:
        return self.list_widget.count()

    def is_empty(self) -> bool:
        return self.list_widget.count() == 0

    def remove_at(self, idx: int) -> None:
        """Elimina el documento en la posición dada."""
        if 0 <= idx < len(self._paths):
            p = self._paths.pop(idx)
            self._path_set.discard(p)
        self.list_widget.takeItem(idx)
        self._update_count()
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
            self.files_changed.emit(self.paths())

    def _update_count(self) -> None:
        n = self.list_widget.count()
        self._count_lbl.setText(f"{n} documento" + ("s" if n != 1 else ""))

    def _on_browse(self) -> None:
        title = "Seleccionar archivo" if self._single_file else "Seleccionar archivos"
        if self._single_file:
            path, _ = QFileDialog.getOpenFileName(
                self.window(), title, "", self._file_filter
            )
            files = [path] if path else []
        else:
            files, _ = QFileDialog.getOpenFileNames(
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
            QMessageBox.information(
                self.window(), "Microsoft Office requerido",
                "Para convertir archivos Word a PDF se necesita Microsoft Office.\n"
                "Los archivos .doc/.docx han sido omitidos.",
            )
            return
        self._conv_dlg = QProgressDialog(
            "Convirtiendo Word a PDF…", None, 0, len(paths), self.window()
        )
        self._conv_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self._conv_dlg.setMinimumDuration(0)
        self._conv_dlg.show()

        from shell.word_to_pdf import WordConvertWorker
        worker = WordConvertWorker(self._ctx.word_converter, paths, self._word_tmp)
        thread = QThread(self.window())
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.finished.connect(self._on_word_done)
        worker.error.connect(self._on_word_error)
        thread.finished.connect(thread.deleteLater)
        self._conv_thread = thread
        thread.start()

    def _on_word_done(self, paths: List[str]) -> None:
        if self._conv_dlg:
            self._conv_dlg.close()
            self._conv_dlg = None
        self._conv_thread = None
        self._add_pdf_paths(paths)

    def _on_word_error(self, msg: str) -> None:
        if self._conv_dlg:
            self._conv_dlg.close()
            self._conv_dlg = None
        self._conv_thread = None
        QMessageBox.warning(self.window(), "Error en conversión Word", msg)
