"""DocumentsCard — tarjeta de carga de documentos reutilizable.

Consolida el paso "Documentos" que era idéntico en los 5 herramientas:
  - Botones Agregar / Quitar selección / Vaciar / Cargar desde bandeja
  - Lista con miniaturas PDF, drag-reorder opcional, Delete key
  - Conversión automática Word→PDF en segundo plano
  - Conversión automática Imagen→PDF sin márgenes
  - Señal files_changed emitida en cada cambio

Uso:
    card = DocumentsCard(ctx, allow_reorder=True)
    card.files_changed.connect(self._on_files_changed)
    layout.addWidget(card, 1)
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QObject, QThread, QTimer, pyqtSignal, QSize, QEvent
from ui.common.tool_scaffold import RunnerThread
from PyQt6.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QStackedWidget, QMenu, QToolTip,
)

from ui.common.thumb_utils import make_pdf_thumb, ThumbnailLoader, make_placeholder_pixmap
from ui.common.clipboard_utils import clipboard_file_paths, copy_files_to_clipboard
from ui.common.icons import icon_pixmap, make_icon_label, set_button_icon
from core.media_conversion import (
    DOCUMENT_IMPORT_EXTENSIONS,
    IMAGE_EXTENSIONS,
    PDF_EXTENSIONS,
    WORD_EXTENSIONS,
    accepted_document_paths,
    expand_document_filter,
    images_to_pdf_exact,
)
from ui.common.dialogs import show_error, show_info
from ui.common.file_dialogs import get_open_file_name, get_open_file_names
from ui.common.open_utils import open_file as open_local_file, open_folder as open_local_folder
from ui.common.result_ui import ElidedLabel, format_file_size
from ui.styles import COLORS
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
        show_preview: bool = False,
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
        self._show_preview = show_preview
        self._thumb_w, self._thumb_h = thumb_size
        self._file_filter = expand_document_filter(file_filter)
        self._accent: str = "#5E6AD2"
        self._drop_icon_name = "folder-open"
        self._drop_icon_size = 28
        self._drop_flash_token = 0
        self._paths: List[str] = []
        self._path_set: set = set()

        self._conv_thread: Optional[QThread] = None
        self._conv_worker = None
        self._conv_dlg = None
        self._pending_import_slots: list[tuple[str, str]] | None = None
        self._thumb_threads: list = []  # threads de generación de thumbnails activos
        self._thumb_workers: dict = {}  # mantiene vivos los workers hasta que terminen

        self._build(allow_reorder)
        self.set_accent(self._accent)

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
        row.setSpacing(8)

        self._add_btn = QPushButton("Agregar archivos")
        self._add_btn.setProperty("class", "Primary")
        self._add_btn.setFixedHeight(32)
        set_button_icon(self._add_btn, "plus")
        self._add_btn.clicked.connect(self._on_browse)
        row.addWidget(self._add_btn)

        # Separador visual — solo visible cuando la lista tiene items
        from PyQt6.QtWidgets import QFrame as _QFrame
        self._sep_actions = _QFrame()
        self._sep_actions.setFixedSize(1, 18)
        self._sep_actions.setStyleSheet(f"background: {COLORS['border_strong']}; border: none;")
        self._sep_actions.setVisible(False)
        row.addWidget(self._sep_actions, 0, Qt.AlignmentFlag.AlignVCenter)

        # Quitar seleccionados (visible solo cuando hay items)
        self._remove_btn = QPushButton("Quitar")
        self._remove_btn.setProperty("class", "Ghost")
        self._remove_btn.setFixedHeight(32)
        set_button_icon(self._remove_btn, "x", color=COLORS["danger"])
        self._remove_btn.setEnabled(False)
        self._remove_btn.setVisible(False)
        self._remove_btn.clicked.connect(self.remove_selected)
        row.addWidget(self._remove_btn)

        self._send_to_tray_btn = QPushButton("A bandeja")
        self._send_to_tray_btn.setProperty("class", "Ghost")
        self._send_to_tray_btn.setFixedHeight(32)
        self._send_to_tray_btn.setToolTip("Agregar seleccionados a la bandeja")
        set_button_icon(self._send_to_tray_btn, "arrow-left")
        self._send_to_tray_btn.setEnabled(False)
        self._send_to_tray_btn.setVisible(False)
        self._send_to_tray_btn.clicked.connect(self.send_selected_to_tray)
        row.addWidget(self._send_to_tray_btn)

        self._copy_btn = QPushButton("Copiar")
        self._copy_btn.setProperty("class", "Ghost")
        self._copy_btn.setFixedHeight(32)
        self._copy_btn.setToolTip("Copiar archivos seleccionados")
        set_button_icon(self._copy_btn, "copy")
        self._copy_btn.setEnabled(False)
        self._copy_btn.setVisible(False)
        self._copy_btn.clicked.connect(self.copy_selected_to_clipboard)
        row.addWidget(self._copy_btn)

        # Vaciar todo (visible solo cuando hay items)
        self._clear_btn = QPushButton("Vaciar")
        self._clear_btn.setProperty("class", "Ghost")
        self._clear_btn.setFixedHeight(32)
        self._clear_btn.setToolTip("Vaciar documentos")
        set_button_icon(self._clear_btn, "trash-2", color=COLORS["text_dim"])
        self._clear_btn.setVisible(False)
        self._clear_btn.clicked.connect(self.clear)
        row.addWidget(self._clear_btn)

        # Ordenar (icon-only, visible solo cuando hay items)
        self._sort_btn = QPushButton()
        self._sort_btn.setProperty("class", "IconBtn")
        self._sort_btn.setFixedSize(32, 32)
        self._sort_btn.setToolTip("Ordenar documentos")
        set_button_icon(self._sort_btn, "arrow-up-down", color=COLORS["text_dim"])
        self._sort_btn.setVisible(False)
        self._sort_btn.clicked.connect(self._show_sort_menu)
        row.addWidget(self._sort_btn)

        row.addStretch()

        self._tray_btn = QPushButton("Bandeja")
        self._tray_btn.setProperty("class", "Ghost")
        self._tray_btn.setFixedHeight(32)
        set_button_icon(self._tray_btn, "folder-open")
        self._tray_btn.clicked.connect(self._on_load_from_tray)
        row.addWidget(self._tray_btn)

        self._count_lbl = QLabel("Sin documentos")
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
        self._icon_box = icon_box
        icon_box.setFixedSize(60, 60)
        icon_box.setStyleSheet("""
            QFrame {
                background: rgba(94, 106, 210, 0.14);
                border: 1px solid rgba(94, 106, 210, 0.35);
                border-radius: 14px;
            }
        """)
        ib = QVBoxLayout(icon_box)
        ib.setContentsMargins(0, 0, 0, 0)
        ib_lbl = make_icon_label("folder-open", color="#7B8DE8", size=28)
        self._icon_label = ib_lbl
        ib_lbl.setFixedSize(38, 38)
        ib.addWidget(ib_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        ez.addWidget(icon_box, 0, Qt.AlignmentFlag.AlignCenter)

        ez.addSpacing(18)

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
        self.list_widget.itemSelectionChanged.connect(self._refresh_preview)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_list_context_menu)
        self.list_widget.installEventFilter(self)

        if allow_reorder:
            self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
            self.list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
            self.list_widget.model().rowsMoved.connect(self._sync_after_reorder)

        if self._show_thumbnails:
            self.list_widget.setIconSize(QSize(self._thumb_w, self._thumb_h))
            self.list_widget.setSpacing(3)

        self._content_stack.addWidget(self.list_widget)  # idx 1

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        body.addWidget(self._content_stack, 1)
        if self._show_preview:
            body.addWidget(self._build_preview_panel())
        layout.addLayout(body, 1)
        self._content_stack.setCurrentIndex(0)  # empezar en drop zone
        self._update_count()

    def _build_preview_panel(self) -> QFrame:
        panel = QFrame()
        self._preview_panel = panel
        panel.setObjectName("DocumentPreviewPanel")
        panel.setFixedWidth(260)
        panel.setStyleSheet(
            "QFrame#DocumentPreviewPanel {"
            f"background: {COLORS['surface_2']};"
            f"border: 1px solid {COLORS['border']};"
            "border-radius: 8px;"
            "}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Vista previa")
        title.setProperty("class", "CardTitle")
        layout.addWidget(title)

        self._preview_name_lbl = ElidedLabel("Selecciona un documento")
        self._preview_name_lbl.setProperty("class", "CardHint")
        layout.addWidget(self._preview_name_lbl)

        self._preview_canvas = QLabel("Sin documento")
        self._preview_canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_canvas.setMinimumHeight(250)
        self._preview_canvas.setStyleSheet(
            "background: #0F0F13;"
            f"border: 1px solid {COLORS['border']};"
            "border-radius: 6px;"
            f"color: {COLORS['text_muted']};"
        )
        layout.addWidget(self._preview_canvas, 1)

        self._preview_meta_lbl = QLabel("")
        self._preview_meta_lbl.setProperty("class", "CardHint")
        self._preview_meta_lbl.setWordWrap(True)
        layout.addWidget(self._preview_meta_lbl)
        return panel

    # ------------------------------------------------------------------ #
    # Event filter — Delete key
    # ------------------------------------------------------------------ #

    def eventFilter(self, obj, event) -> bool:
        if obj is self.list_widget and event.type() == QEvent.Type.KeyPress:
            if isinstance(event, QKeyEvent):
                if event.matches(QKeySequence.StandardKey.Paste):
                    self.paste_from_clipboard()
                    return True
                if event.matches(QKeySequence.StandardKey.Copy):
                    self.copy_selected_to_clipboard()
                    return True
                if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    self._delete_selected()
                    return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_from_clipboard()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selected_to_clipboard()
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_drop_active(True)
            return
        super().dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._set_drop_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drop_active(False)
        if event.mimeData().hasUrls():
            from ui.common.file_ordering import paths_from_mime_data

            event.acceptProposedAction()
            self._flash_drop_success()
            paths = paths_from_mime_data(event.mimeData())
            if paths:
                self.add_paths(paths)
            return
        super().dropEvent(event)

    def _set_drop_active(self, active: bool) -> None:
        if not hasattr(self, "_empty_w"):
            return
        self._drop_flash_token += 1
        r, g, b = self._parse_accent_rgb()
        if active:
            self._empty_w.setObjectName("DropZoneActive")
            self._empty_w.setStyleSheet(
                f"QFrame#DropZoneActive {{"
                f"background: rgba({r}, {g}, {b}, 0.06);"
                f"border: 2px solid rgba({r}, {g}, {b}, 0.70);"
                f"border-radius: 10px;"
                f"}}"
            )
            self._start_icon_bounce()
        else:
            self._empty_w.setObjectName("DropZone")
            self._empty_w.setStyleSheet("")
            self._stop_icon_bounce()
        self._empty_w.style().unpolish(self._empty_w)
        self._empty_w.style().polish(self._empty_w)
        self._empty_w.update()

    def _parse_accent_rgb(self) -> tuple[int, int, int]:
        h = self._accent.strip().lstrip("#")
        if len(h) != 6:
            return (94, 106, 210)
        try:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except ValueError:
            return (94, 106, 210)

    def _icon_color(self) -> str:
        r, g, b = self._parse_accent_rgb()
        return f"#{r:02X}{g:02X}{b:02X}"

    def _refresh_drop_icon(self, size: Optional[int] = None) -> None:
        if not hasattr(self, "_icon_label"):
            return
        icon_size = size or self._drop_icon_size
        self._icon_label.setPixmap(
            icon_pixmap(self._drop_icon_name, self._icon_color(), icon_size)
        )

    def _refresh_icon_box_style(self) -> None:
        if not hasattr(self, "_icon_box"):
            return
        r, g, b = self._parse_accent_rgb()
        self._icon_box.setStyleSheet(
            "QFrame {"
            f"background: rgba({r}, {g}, {b}, 0.14);"
            f"border: 1px solid rgba({r}, {g}, {b}, 0.35);"
            "border-radius: 14px;"
            "}"
        )

    def _start_icon_bounce(self) -> None:
        """Anima solo el pixmap interno para no mover el layout."""
        if hasattr(self, "_bounce_timer") and self._bounce_timer.isActive():
            return
        try:
            from ui.common.animations import is_reduced_motion
            if is_reduced_motion():
                return
        except Exception:
            pass

        import math
        self._bounce_step = 0
        self._bounce_timer = QTimer(self)
        self._bounce_timer.setInterval(40)

        def _tick() -> None:
            phase = (self._bounce_step % 20) / 20.0
            scale = 1.0 + 0.12 * ((1.0 - math.cos(phase * math.pi * 2)) / 2.0)
            self._refresh_drop_icon(max(1, round(self._drop_icon_size * scale)))
            self._bounce_step += 1

        self._bounce_timer.timeout.connect(_tick)
        self._bounce_timer.start()

    def _stop_icon_bounce(self) -> None:
        if hasattr(self, "_bounce_timer"):
            self._bounce_timer.stop()
            self._bounce_timer.deleteLater()
            del self._bounce_timer
        self._refresh_drop_icon(self._drop_icon_size)

    def _flash_drop_success(self) -> None:
        """Flash sutil de accent al recibir archivos."""
        if not hasattr(self, "_empty_w"):
            return
        self._drop_flash_token += 1
        token = self._drop_flash_token
        r, g, b = self._parse_accent_rgb()
        self._empty_w.setObjectName("DropZone")
        self._empty_w.setStyleSheet(
            f"QFrame#DropZone {{"
            f"background: rgba({r}, {g}, {b}, 0.15);"
            f"border: 1.5px solid rgba({r}, {g}, {b}, 0.45);"
            f"border-radius: 10px;"
            f"}}"
        )
        QTimer.singleShot(300, lambda: self._clear_drop_flash(token))

    def _clear_drop_flash(self, token: int) -> None:
        if token == self._drop_flash_token and hasattr(self, "_empty_w"):
            self._empty_w.setStyleSheet("")

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
        if not hasattr(self, "_remove_btn"):
            return
        selected = self.list_widget.selectedItems()
        n_sel = len(selected)
        self._remove_btn.setEnabled(n_sel > 0)
        self._send_to_tray_btn.setEnabled(n_sel > 0)
        self._copy_btn.setEnabled(n_sel > 0)
        if n_sel > 1:
            self._remove_btn.setText(f"Quitar ({n_sel})")
        else:
            self._remove_btn.setText("Quitar")
        self._sync_action_density()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_action_density()
        if self._show_preview:
            self._refresh_preview()

    def _sync_action_density(self) -> None:
        if not hasattr(self, "_count_lbl"):
            return
        compact = self.width() < 680
        self._count_lbl.setVisible(not compact)
        self._add_btn.setText("Agregar" if compact else "Agregar archivos")
        compact_buttons = (
            (self._remove_btn, "Quitar"),
            (self._send_to_tray_btn, "A bandeja"),
            (self._copy_btn, "Copiar"),
            (self._clear_btn, "Vaciar"),
        )
        for button, text in compact_buttons:
            if compact:
                button.setText("")
                button.setFixedWidth(34)
            else:
                button.setMinimumWidth(0)
                button.setMaximumWidth(16777215)
                if button is not self._remove_btn:
                    button.setText(text)

    def _show_sort_menu(self) -> None:
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        menu = QMenu(self)

        act_name = QAction("Por nombre (A → Z)", menu)
        act_name.triggered.connect(lambda: self._sort_by("name"))
        menu.addAction(act_name)

        act_size = QAction("Por tamaño (menor primero)", menu)
        act_size.triggered.connect(lambda: self._sort_by("size"))
        menu.addAction(act_size)

        menu.exec(self._sort_btn.mapToGlobal(self._sort_btn.rect().bottomLeft()))

    def _show_list_context_menu(self, pos) -> None:
        clicked = self.list_widget.itemAt(pos)
        if clicked is not None and not clicked.isSelected():
            self.list_widget.clearSelection()
            self.list_widget.setCurrentItem(clicked)
            clicked.setSelected(True)

        selected = self.selected_paths()
        current = self.list_widget.currentItem()
        current_path = current.data(Qt.ItemDataRole.UserRole) if current else ""
        has_clipboard_docs = bool(
            clipboard_file_paths(suffixes=tuple(DOCUMENT_IMPORT_EXTENSIONS))
        )

        menu = QMenu(self)
        add_tray = menu.addAction("Agregar a bandeja")
        add_tray.setEnabled(bool(selected))
        copy_files = menu.addAction("Copiar archivo" + ("s" if len(selected) != 1 else ""))
        copy_files.setEnabled(bool(selected))
        paste_files = menu.addAction("Pegar documentos")
        paste_files.setEnabled(has_clipboard_docs)
        menu.addSeparator()
        open_file = menu.addAction("Abrir documento")
        open_file.setEnabled(bool(current_path and Path(current_path).exists()))
        open_folder = menu.addAction("Abrir carpeta")
        open_folder.setEnabled(bool(current_path and Path(current_path).exists()))
        menu.addSeparator()
        remove = menu.addAction("Quitar seleccionados")
        remove.setEnabled(bool(selected))

        chosen = menu.exec(self.list_widget.viewport().mapToGlobal(pos))
        if chosen == add_tray:
            self.send_selected_to_tray()
        elif chosen == copy_files:
            self.copy_selected_to_clipboard()
        elif chosen == paste_files:
            self.paste_from_clipboard()
        elif chosen == open_file:
            open_local_file(self, current_path, title="Abrir documento")
        elif chosen == open_folder:
            open_local_folder(self, current_path, title="Abrir carpeta")
        elif chosen == remove:
            self.remove_selected()

    def _show_feedback(self, text: str) -> None:
        QToolTip.showText(
            self.mapToGlobal(self.rect().center()),
            text,
            self,
            self.rect(),
            1800,
        )

    def _refresh_preview(self) -> None:
        if not self._show_preview or not hasattr(self, "_preview_canvas"):
            return
        path = ""
        current = self.list_widget.currentItem()
        if current is not None:
            path = current.data(Qt.ItemDataRole.UserRole) or ""
        if not path and self.list_widget.selectedItems():
            path = self.list_widget.selectedItems()[0].data(Qt.ItemDataRole.UserRole) or ""
        if not path:
            self._preview_name_lbl.setText("Selecciona un documento")
            self._preview_canvas.clear()
            self._preview_canvas.setText("Sin documento")
            self._preview_meta_lbl.setText("")
            return

        pdf_path = Path(path)
        self._preview_name_lbl.setText(pdf_path.name)
        qimg = make_pdf_thumb(str(pdf_path), width=230)
        if qimg is None:
            self._preview_canvas.clear()
            self._preview_canvas.setText("No se pudo previsualizar")
        else:
            pix = QPixmap.fromImage(qimg)
            self._preview_canvas.setText("")
            self._preview_canvas.setPixmap(
                pix.scaled(
                    max(180, self._preview_canvas.width() - 16),
                    max(220, self._preview_canvas.height() - 16),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        meta = []
        page_count = _pdf_page_count(path)
        if page_count:
            meta.append(f"{page_count} pagina" + ("s" if page_count != 1 else ""))
        size = format_file_size(path)
        if size:
            meta.append(size)
        self._preview_meta_lbl.setText(" · ".join(meta))

    def set_preview_visible(self, visible: bool) -> None:
        if not self._show_preview or not hasattr(self, "_preview_panel"):
            return
        self._preview_panel.setVisible(visible)
        if visible:
            self._refresh_preview()

    def _sort_by(self, key: str) -> None:
        """Ordena los documentos por nombre o tamaño."""
        paths = self.paths()
        if key == "name":
            paths.sort(key=lambda p: Path(p).name.lower())
        elif key == "size":
            paths.sort(key=lambda p: Path(p).stat().st_size if Path(p).exists() else 0)
        else:
            return
        if paths == self.paths():
            return
        # Rebuild list from sorted paths
        self._paths = list(paths)
        self._path_set = set(paths)
        self.list_widget.clear()
        for p in paths:
            item = QListWidgetItem(Path(p).name)
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            if self._show_thumbnails:
                placeholder = make_placeholder_pixmap(self._thumb_w, self._thumb_h)
                item.setIcon(QIcon(placeholder))
                self.list_widget.addItem(item)
                self._schedule_thumb(p, item)
            else:
                self.list_widget.addItem(item)
        self._update_count()
        self._update_remove_btn()
        self.files_changed.emit(list(paths))

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

    def selected_paths(self) -> List[str]:
        rows = sorted({self.list_widget.row(item) for item in self.list_widget.selectedItems()})
        result: List[str] = []
        for row in rows:
            item = self.list_widget.item(row)
            path = item.data(Qt.ItemDataRole.UserRole) if item else None
            if path:
                result.append(path)
        return result

    def copy_selected_to_clipboard(self) -> bool:
        paths = self.selected_paths()
        if not paths:
            current = self.list_widget.currentItem()
            path = current.data(Qt.ItemDataRole.UserRole) if current else None
            paths = [path] if path else []
        ok = copy_files_to_clipboard(paths)
        if ok:
            count = len(paths)
            self._show_feedback(
                f"{count} archivo" + ("s" if count != 1 else "") + " copiado"
            )
        else:
            self._show_feedback("No hay archivos para copiar")
        return ok

    def paste_from_clipboard(self) -> bool:
        paths = clipboard_file_paths(suffixes=tuple(DOCUMENT_IMPORT_EXTENSIONS))
        if not paths:
            self._show_feedback("No hay documentos compatibles en el portapapeles")
            return False
        before = self.count()
        self.add_paths(paths)
        changed = self.count() != before
        self._show_feedback(
            "Documentos agregados" if changed else "Los documentos ya estaban agregados"
        )
        return changed

    def send_selected_to_tray(self) -> bool:
        paths = self.selected_paths()
        if not paths:
            return False
        self._ctx.tray.add_items(
            paths,
            "Documentos",
            kind="manual",
            source_tool_id="manual",
            source_tool_title="Carga manual",
            status="in_work",
        )
        self._ctx.tray.mark_in_work(paths)
        self._show_feedback("Agregado a bandeja")
        return True

    def set_accent(self, accent: str) -> None:
        """Inyecta el accent de la herramienta para feedback visual."""
        self._accent = accent or "#5E6AD2"
        self._refresh_icon_box_style()
        self._refresh_drop_icon(self._drop_icon_size)

    def add_paths(self, raw_paths: List[str]) -> None:
        """Agrega paths, convirtiendo Word o imágenes si es necesario."""
        accepted = accepted_document_paths(raw_paths)
        if self._single_file:
            accepted = accepted[:1]
        slots, words = self._build_import_slots(accepted)
        if words:
            if not self._ctx.word_converter.is_available():
                show_info(
                    self.window(), "Microsoft Office requerido",
                    "Para convertir archivos Word a PDF se necesita Microsoft Office.\n"
                    "Los archivos .doc/.docx han sido omitidos.",
                )
                self._add_import_slots(slots, {})
                return
            self._pending_import_slots = slots
            self._handle_word_files(words)
            return
        self._add_import_slots(slots, {})

    def clear(self) -> None:
        self._paths.clear()
        self._path_set.clear()
        self.list_widget.clear()
        self._update_count()
        self._update_remove_btn()
        self.files_changed.emit([])

    def count(self) -> int:
        return self.list_widget.count()

    def reorder_paths(self, ordered_paths: List[str]) -> None:
        """Reordena los documentos existentes segun una lista externa de paths."""
        current = self.paths()
        if not current:
            return
        current_set = set(current)
        seen: set[str] = set()
        normalized = []
        for path in ordered_paths:
            if path in current_set and path not in seen:
                normalized.append(path)
                seen.add(path)
        normalized.extend(path for path in current if path not in seen)
        if normalized == current:
            return

        self._paths = list(normalized)
        self._path_set = set(normalized)
        self.list_widget.clear()
        for path in normalized:
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            if self._show_thumbnails:
                placeholder = make_placeholder_pixmap(self._thumb_w, self._thumb_h)
                item.setIcon(QIcon(placeholder))
                self.list_widget.addItem(item)
                self._schedule_thumb(path, item)
            else:
                self.list_widget.addItem(item)
        self._update_count()
        self._update_remove_btn()
        self.files_changed.emit(self.paths())

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

    def _build_import_slots(self, paths: List[str]) -> tuple[list[tuple[str, str]], list[str]]:
        slots: list[tuple[str, str]] = []
        words: list[str] = []
        image_out_dir = None
        for path in paths:
            suffix = Path(path).suffix.lower()
            if suffix in PDF_EXTENSIONS:
                slots.append(("pdf", path))
            elif suffix in IMAGE_EXTENSIONS:
                try:
                    if image_out_dir is None:
                        image_out_dir = make_run_dir("converted")
                    converted = images_to_pdf_exact([path], out_dir=image_out_dir)
                except Exception as exc:
                    show_error(
                        self.window(),
                        "No se pudieron convertir las imágenes",
                        str(exc),
                    )
                    continue
                if converted:
                    slots.append(("pdf", converted))
            elif suffix in WORD_EXTENSIONS:
                slots.append(("word", path))
                words.append(path)
        return slots, words

    def _add_import_slots(
        self,
        slots: list[tuple[str, str]],
        word_outputs: dict[str, str],
    ) -> None:
        ordered: list[str] = []
        for kind, path in slots:
            if kind == "pdf":
                ordered.append(path)
            elif kind == "word":
                converted = word_outputs.get(path)
                if converted:
                    ordered.append(converted)
        if ordered:
            self._add_pdf_paths(ordered)

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
                    placeholder = make_placeholder_pixmap(self._thumb_w, self._thumb_h)
                    item.setIcon(QIcon(placeholder))
                    self.list_widget.addItem(item)
                    self._schedule_thumb(p, item)
                else:
                    self.list_widget.addItem(item)
                changed = True

        if changed:
            if self.list_widget.currentRow() < 0 and self.list_widget.count() > 0:
                self.list_widget.setCurrentRow(0)
            self._update_count()
            self._update_remove_btn()
            self.files_changed.emit(self.paths())

    def _handle_image_files(self, paths: List[str]) -> None:
        try:
            source_paths = paths[:1] if self._single_file else paths
            out_dir = make_run_dir("converted")
            converted = [
                result
                for path in source_paths
                if (result := images_to_pdf_exact([path], out_dir=out_dir))
            ]
        except Exception as exc:
            show_error(
                self.window(),
                "No se pudieron convertir las imágenes",
                str(exc),
            )
            return
        if converted:
            self._add_pdf_paths(converted)

    def _update_count(self) -> None:
        n = self.list_widget.count()
        has_items = n > 0
        for attr in (
            "_sep_actions",
            "_remove_btn",
            "_send_to_tray_btn",
            "_copy_btn",
            "_clear_btn",
            "_sort_btn",
        ):
            w = getattr(self, attr, None)
            if w is not None:
                w.setVisible(has_items)
        if n == 0:
            self._count_lbl.setText("Sin documentos")
        else:
            total_bytes = sum(
                Path(p).stat().st_size
                for p in self._paths
                if Path(p).exists()
            )
            if total_bytes >= 1_048_576:
                size_str = f"{total_bytes / 1_048_576:.1f} MB"
            elif total_bytes >= 1024:
                size_str = f"{total_bytes / 1024:.0f} KB"
            else:
                size_str = f"{total_bytes} B"
            doc_word = "doc" if n == 1 else "docs"
            self._count_lbl.setText(f"{n} {doc_word} · {size_str}")
        # Alternar entre drop zone vacía y lista con archivos
        if hasattr(self, "_content_stack"):
            self._content_stack.setCurrentIndex(0 if n == 0 else 1)
        self._refresh_preview()

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

    def _schedule_thumb(self, pdf_path: str, item: "QListWidgetItem") -> None:
        """Lanza generación de thumbnail en hilo secundario."""
        loader = ThumbnailLoader(pdf_path, self._thumb_w)
        thread = RunnerThread(loader.run, self)
        loader.ready.connect(lambda path, pix, _item=item: self._apply_thumb(_item, pix))
        loader.ready.connect(thread.quit)
        thread.finished.connect(loader.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._cleanup_thumb_job(t))
        self._thumb_threads.append(thread)
        self._thumb_workers[thread] = loader
        thread.start()

    def _cleanup_thumb_job(self, thread: QThread) -> None:
        self._thumb_workers.pop(thread, None)
        if thread in self._thumb_threads:
            self._thumb_threads.remove(thread)

    def _apply_thumb(self, item: "QListWidgetItem", pix) -> None:
        """Actualiza icono del item si aún existe en la lista.

        pix es QImage (generado en hilo secundario); se convierte a QPixmap
        aquí en el GUI thread antes de pasarlo a QIcon.
        """
        if pix is None:
            return
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i) is item:
                item.setIcon(QIcon(QPixmap.fromImage(pix)))
                return

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
        self._conv_thread = RunnerThread(worker.run, self.window())
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
        # Iniciar el thread DESPUÉS de que exec() abra el event loop.
        # Si el thread arranca antes de exec(), en el .exe (más rápido) la señal
        # finished llega antes de que el diálogo procese su primer evento y
        # el progreso nunca se ve. singleShot(0) garantiza el orden correcto.
        QTimer.singleShot(0, self._conv_thread.start)
        self._conv_dlg.exec()

    def _on_word_done(self, paths: List[str]) -> None:
        self._conv_thread = None
        self._conv_worker = None
        slots = self._pending_import_slots
        self._pending_import_slots = None
        if slots is None:
            self._add_pdf_paths(paths)
            return
        words = [path for kind, path in slots if kind == "word"]
        self._add_import_slots(
            slots,
            {
                source: output
                for source, output in zip(words, paths)
                if output
            },
        )

    def _on_word_error(self, msg: str) -> None:
        self._conv_thread = None
        self._conv_worker = None
        slots = self._pending_import_slots
        self._pending_import_slots = None
        if slots is not None:
            self._add_import_slots(slots, {})


def _pdf_page_count(path: str) -> int:
    try:
        import fitz

        doc = fitz.open(path)
        try:
            return int(doc.page_count)
        finally:
            doc.close()
    except Exception:
        return 0
