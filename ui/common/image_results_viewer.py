"""Reusable image results viewer for PDFlex tools."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QMimeData, Qt, QSize, QEvent, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QClipboard, QCursor, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFrame, QApplication, QMenu, QToolTip,
)
from PIL import Image, ImageDraw

from ui.common.clipboard_utils import copy_files_to_clipboard
from ui.common.icons import icon, set_button_icon, set_compact_icon_button
from ui.common.open_utils import open_file, open_folder
from ui.common.result_ui import (
    ElidedLabel,
    ResultsStatBar,
    configure_result_list,
    format_file_size,
    make_result_list_item,
)
from ui.common.save_utils import save_file_as, save_files_as_batch, save_grouped_files_as_batch


@dataclass
class _ResultGroup:
    doc_name: str      # e.g. "contrato.pdf"
    output_dir: str    # per-doc temp subfolder path
    results: list      # List[ImageResult]


class ImageResultsViewer(QWidget):
    """List and preview image outputs with save/open actions.

    Accepts any result object with ``output_path``, ``success`` and ``error``
    attributes.  Also accepts grouped results via ``set_grouped_results``.
    """

    openInExplorer = Signal(str)

    def __init__(
        self,
        list_title: str = "Imágenes generadas",
        parent=None,
        *,
        comparison_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self._list_title = list_title
        self._comparison_mode = comparison_mode
        self._results: list = []
        self._source_dirs: list = []
        # Grouped-mode state
        self._grouped: bool = False
        self._flat_results: list = []
        self._row_map: list = []   # per list row: None = header, int = idx into _flat_results
        self._groups: list = []    # List[_ResultGroup]
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        left = QFrame()
        left.setProperty("class", "Card")
        left.setFixedWidth(260)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 14, 14, 14)
        lv.setSpacing(10)

        title_lbl = QLabel(self._list_title)
        title_lbl.setProperty("class", "CardTitle")
        lv.addWidget(title_lbl)

        self._stat_bar = ResultsStatBar()
        lv.addWidget(self._stat_bar)

        self.file_list = QListWidget()
        configure_result_list(self.file_list)
        self.file_list.itemSelectionChanged.connect(self._on_file_selected)
        QShortcut(QKeySequence.StandardKey.Copy, self.file_list, activated=self._copy_selected_file)
        lv.addWidget(self.file_list, 1)

        layout.addWidget(left)

        right = QFrame()
        right.setProperty("class", "Card")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(14, 14, 14, 14)
        rv.setSpacing(10)

        header = QVBoxLayout()
        header.setSpacing(8)
        self.title_lbl = ElidedLabel("Selecciona un archivo")
        self.title_lbl.setProperty("class", "CardTitle")
        header.addWidget(self.title_lbl)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        self.open_file_btn = QPushButton()
        set_compact_icon_button(self.open_file_btn, "external-link", "Abrir imagen")
        self.open_file_btn.setEnabled(False)
        self.open_file_btn.clicked.connect(self._on_open_file)
        actions.addWidget(self.open_file_btn)

        self.copy_file_btn = QPushButton()
        set_compact_icon_button(self.copy_file_btn, "copy", "Copiar archivo")
        self.copy_file_btn.setEnabled(False)
        self.copy_file_btn.clicked.connect(self._copy_selected_file)
        actions.addWidget(self.copy_file_btn)

        self.open_btn = QPushButton()
        set_compact_icon_button(self.open_btn, "folder-open", "Abrir carpeta")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._on_open)
        actions.addWidget(self.open_btn)

        self.save_as_btn = QPushButton()
        set_compact_icon_button(self.save_as_btn, "save", "Guardar como")
        self.save_as_btn.setEnabled(False)
        self.save_as_btn.clicked.connect(self._on_save_as)
        actions.addWidget(self.save_as_btn)

        self.save_all_btn = QPushButton()
        set_compact_icon_button(self.save_all_btn, "download", "Guardar todo")
        self.save_all_btn.setEnabled(False)
        self.save_all_btn.clicked.connect(self._on_save_all)
        actions.addWidget(self.save_all_btn)
        header.addLayout(actions)
        rv.addLayout(header)

        self.meta_lbl = QLabel("")
        self.meta_lbl.setProperty("class", "Mono")
        self.meta_lbl.setWordWrap(True)
        rv.addWidget(self.meta_lbl)

        self.preview_lbl = QLabel()
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_lbl.setStyleSheet(
            "background: #111114; border: 1px solid #26262C; border-radius: 6px;"
        )
        self._enable_preview_copy(self.preview_lbl)
        rv.addWidget(self.preview_lbl, 1)

        self.compare_widget = QWidget()
        compare_layout = QHBoxLayout(self.compare_widget)
        compare_layout.setContentsMargins(0, 0, 0, 0)
        compare_layout.setSpacing(12)
        self.before_preview_lbl = self._make_compare_panel("Antes")
        self.after_preview_lbl = self._make_compare_panel("Después")
        self._enable_preview_copy(self.before_preview_lbl)
        self._enable_preview_copy(self.after_preview_lbl)
        compare_layout.addWidget(self.before_preview_lbl, 1)
        compare_layout.addWidget(self.after_preview_lbl, 1)
        rv.addWidget(self.compare_widget, 1)
        self.compare_widget.setVisible(False)

        layout.addWidget(right, 1)

    def _make_compare_panel(self, title: str) -> QLabel:
        label = QLabel(title)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumHeight(220)
        label.setStyleSheet(
            "background: #111114; border: 1px solid #26262C; border-radius: 6px;"
            "color: #9094A0;"
        )
        return label

    def _enable_preview_copy(self, label: QLabel) -> None:
        label.setToolTip("Clic derecho para copiar la imagen")
        label.installEventFilter(self)

    # ------------------------------------------------------------------ #
    # Public API — flat results (backward compat)
    # ------------------------------------------------------------------ #

    def set_results(self, results: list) -> None:
        self._grouped = False
        self._flat_results = []
        self._row_map = []
        self._groups = []
        self._results = list(results)
        self._source_dirs = []
        self.file_list.clear()
        for r in self._results:
            out = getattr(r, "output_path", "") or ""
            item = make_result_list_item(
                out,
                success=getattr(r, "success", False),
                error=getattr(r, "error", "") or "",
            )
            self.file_list.addItem(item)
        if self._results:
            self.file_list.setCurrentRow(0)
            self._refresh_stat_bar(self._results)
        else:
            self._stat_bar.setVisible(False)
            self.clear_results()

    def _refresh_stat_bar(self, results: list) -> None:
        from ui.styles import COLORS as _C
        from PySide6.QtCore import QTimer
        ok = sum(1 for r in results if getattr(r, "success", False))
        errors = len(results) - ok
        stats: list[dict] = [
            {"value": len(results), "label": "archivos", "color": _C["text"]},
            {"value": ok, "label": "correctos", "color": _C["success"]},
        ]
        if errors > 0:
            stats.append({"value": errors, "label": "errores", "color": _C["danger"]})
        self._stat_bar.set_stats(stats)
        QTimer.singleShot(30, self._stat_bar.animate)

    # ------------------------------------------------------------------ #
    # Public API — grouped results (PDF-to-Images multi-doc)
    # ------------------------------------------------------------------ #

    def set_grouped_results(self, job_results: list) -> None:
        """Display results grouped by source PDF document.

        Accepts List[PdfToImagesJobResult].  Renders non-selectable group
        header items followed by indented image entries per document.
        """
        self._grouped = True
        self._groups = []
        self._flat_results = []
        self._row_map = []
        self._results = []
        self._source_dirs = []

        self.file_list.clear()

        for job_result in job_results:
            doc_name = Path(job_result.job.pdf_path).name
            out_dir = str(job_result.job.output_dir)
            group_results = list(job_result.image_results)
            self._groups.append(_ResultGroup(doc_name, out_dir, group_results))

            success_count = sum(
                1 for r in group_results if getattr(r, "success", False)
            )
            img_word = "imagen" if success_count == 1 else "imágenes"

            # ── Group header (non-selectable) ────────────────────────────
            header = QListWidgetItem()
            header.setText(f"  {doc_name}  ·  {success_count} {img_word}")
            header.setIcon(icon("file-text", "#9094A0", 13))
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setSizeHint(QSize(200, 26))
            header.setForeground(QBrush(QColor("#9094A0")))
            header.setBackground(QBrush(QColor("#1A1A20")))
            font = header.font()
            font.setPointSize(9)
            header.setFont(font)
            self.file_list.addItem(header)
            self._row_map.append(None)

            # ── Result items ─────────────────────────────────────────────
            for r in group_results:
                out = getattr(r, "output_path", "") or ""
                item = make_result_list_item(
                    out,
                    success=getattr(r, "success", False),
                    error=getattr(r, "error", "") or "",
                    prefix="   ",
                )
                self.file_list.addItem(item)
                self._row_map.append(len(self._flat_results))
                self._flat_results.append(r)

        if self._flat_results:
            for i, v in enumerate(self._row_map):
                if v is not None:
                    self.file_list.setCurrentRow(i)
                    break
        else:
            self.clear_results()

    def clear_results(self) -> None:
        self._results = []
        self._source_dirs = []
        self._grouped = False
        self._flat_results = []
        self._row_map = []
        self._groups = []
        self.file_list.clear()
        self.preview_lbl.clear()
        self.before_preview_lbl.clear()
        self.after_preview_lbl.clear()
        self.compare_widget.setVisible(False)
        self.preview_lbl.setVisible(True)
        self.meta_lbl.setText("")
        self.title_lbl.setText("Selecciona un archivo")
        self.open_file_btn.setEnabled(False)
        self.copy_file_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.save_as_btn.setEnabled(False)
        self.save_all_btn.setEnabled(False)

    def set_source_dirs(self, dirs: List[str]) -> None:
        """Associate one source directory per result for Save As defaults."""
        self._source_dirs = list(dirs)

    def eventFilter(self, obj, event) -> bool:
        preview_labels = tuple(
            label
            for label in (
                getattr(self, "preview_lbl", None),
                getattr(self, "before_preview_lbl", None),
                getattr(self, "after_preview_lbl", None),
            )
            if label is not None
        )
        if obj in preview_labels and event.type() == QEvent.Type.ContextMenu:
            self._show_preview_context_menu(obj, event.globalPos())
            return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _result_at_row(self, row: int):
        """Returns the ImageResult at the given list row, or None (header / OOB)."""
        if not self._grouped:
            if 0 <= row < len(self._results):
                return self._results[row]
            return None
        if 0 <= row < len(self._row_map):
            idx = self._row_map[row]
            if idx is not None and 0 <= idx < len(self._flat_results):
                return self._flat_results[idx]
        return None

    def _selected_result(self):
        row = self.file_list.currentRow()
        return self._result_at_row(row) if row >= 0 else None

    def _preview_image_path(self, label: QLabel) -> str:
        result = self._selected_result()
        if result is None:
            return ""

        if label is self.before_preview_lbl:
            if self.compare_widget.isHidden():
                return ""
            return self._source_image_path(result)

        out = getattr(result, "output_path", "") or ""
        if not getattr(result, "success", False) or not out:
            return ""

        if label is self.after_preview_lbl:
            return out if not self.compare_widget.isHidden() else ""
        if label is self.preview_lbl:
            return out if not self.preview_lbl.isHidden() else ""
        return ""

    def _copy_preview_image(self, label: QLabel) -> bool:
        path = self._preview_image_path(label)
        if not path or not Path(path).exists():
            return False
        if self._copy_image_to_clipboard(path):
            self._show_copy_feedback(label, "Imagen copiada al portapapeles")
            return True

        # Otro proceso puede tener OpenClipboard ocupado de forma transitoria.
        # Reintentar evita fallar por ese instante sin bloquear la interfaz.
        self._retry_copy_preview_image(label, path, attempt=0)
        return False

    def _show_preview_context_menu(self, label: QLabel, global_pos) -> None:
        current_menu = getattr(self, "_preview_context_menu", None)
        if current_menu is not None:
            current_menu.close()

        path = self._preview_image_path(label)
        menu = QMenu(self)
        copy_action = menu.addAction("Copiar imagen")
        copy_action.setEnabled(bool(path and Path(path).exists()))
        copy_action.triggered.connect(lambda _checked=False, target=label: self._copy_preview_image(target))
        menu.aboutToHide.connect(
            lambda current=menu: self._discard_preview_context_menu(current)
        )
        self._preview_context_menu = menu
        menu.popup(global_pos if global_pos is not None else QCursor.pos())

    def _discard_preview_context_menu(self, menu: QMenu) -> None:
        if getattr(self, "_preview_context_menu", None) is menu:
            self._preview_context_menu = None
        menu.deleteLater()

    def _retry_copy_preview_image(self, label: QLabel, path: str, attempt: int) -> None:
        if self._copy_image_to_clipboard(path):
            self._show_copy_feedback(label, "Imagen copiada al portapapeles")
            return
        if attempt >= 2:
            self._show_copy_feedback(label, "No se pudo copiar la imagen")
            return
        delays_ms = (60, 140, 280)
        QTimer.singleShot(
            delays_ms[attempt],
            lambda: self._retry_copy_preview_image(label, path, attempt + 1),
        )

    @staticmethod
    def _show_copy_feedback(label: QLabel, text: str) -> None:
        QToolTip.showText(QCursor.pos(), text, label, label.rect(), 1800)

    @staticmethod
    def _copy_image_to_clipboard(path: str | Path) -> bool:
        image_path = Path(path)
        qimg = _qimage_for_clipboard(image_path)
        if qimg.isNull():
            return False
        png_bytes = _qimage_png_bytes(qimg)
        mime = QMimeData()
        mime.setImageData(qimg)
        if png_bytes:
            mime.setData("image/png", QByteArray(png_bytes))
        clipboard = QApplication.clipboard()
        clipboard.setMimeData(mime, QClipboard.Mode.Clipboard)
        copied_mime = clipboard.mimeData(QClipboard.Mode.Clipboard)
        copied = clipboard.image(QClipboard.Mode.Clipboard)
        return (
            copied_mime.hasImage()
            and not copied.isNull()
            and copied.size() == qimg.size()
            and copied.pixelColor(0, 0) == qimg.pixelColor(0, 0)
        )

    # ------------------------------------------------------------------ #
    # Slots
    # ------------------------------------------------------------------ #

    def _on_file_selected(self) -> None:
        row = self.file_list.currentRow()
        if row < 0:
            return
        r = self._result_at_row(row)
        if r is None:
            # Header row — clear preview, keep save-all enabled if possible
            self.title_lbl.setText("Selecciona un archivo")
            self.meta_lbl.setText("")
            self._clear_preview_area()
            self.compare_widget.setVisible(False)
            self.preview_lbl.setVisible(True)
            self.open_file_btn.setEnabled(False)
            self.copy_file_btn.setEnabled(False)
            self.open_btn.setEnabled(False)
            self.save_as_btn.setEnabled(False)
            self.save_all_btn.setEnabled(self._has_saveable_results())
            return

        out = getattr(r, "output_path", "") or ""
        if not getattr(r, "success", False) or not out:
            self.title_lbl.setText("Error en este archivo")
            self.meta_lbl.setText(getattr(r, "error", "") or "")
            self._clear_preview_area()
            self.compare_widget.setVisible(False)
            self.preview_lbl.setVisible(True)
            self.open_file_btn.setEnabled(False)
            self.copy_file_btn.setEnabled(False)
            self.open_btn.setEnabled(False)
            self.save_as_btn.setEnabled(False)
            self.save_all_btn.setEnabled(self._has_saveable_results())
            return

        path = Path(out)
        self.title_lbl.setText(path.name)
        self.open_file_btn.setEnabled(True)
        self.copy_file_btn.setEnabled(True)
        self.open_btn.setEnabled(True)
        self.save_as_btn.setEnabled(True)
        self.save_all_btn.setEnabled(self._has_saveable_results())

        pix = self._pixmap_for_preview(path)
        if pix.isNull():
            self._clear_preview_area()
            self.meta_lbl.setText("No se pudo previsualizar")
            return

        if self._comparison_mode and self._source_image_path(r):
            self.preview_lbl.setVisible(False)
            self.compare_widget.setVisible(True)
            source_pix = self._pixmap_for_preview(Path(self._source_image_path(r)))
            self._set_scaled_pixmap(self.before_preview_lbl, source_pix)
            self._set_scaled_pixmap(self.after_preview_lbl, pix)
        else:
            self.compare_widget.setVisible(False)
            self.preview_lbl.setVisible(True)
            self._set_scaled_pixmap(self.preview_lbl, pix)
        meta_parts = [f"{pix.width()} x {pix.height()} px"]
        size = format_file_size(path)
        if size:
            meta_parts.append(size)
        extra = getattr(r, "meta_text", "")
        if extra:
            meta_parts.append(extra)
        self.meta_lbl.setText("  ·  ".join(meta_parts))

    def _clear_preview_area(self) -> None:
        self.preview_lbl.clear()
        self.before_preview_lbl.clear()
        self.after_preview_lbl.clear()

    def _set_scaled_pixmap(self, label: QLabel, pix: QPixmap) -> None:
        if pix.isNull():
            label.clear()
            return
        target_w = max(240, label.width())
        target_h = max(220, label.height())
        label.setPixmap(
            pix.scaled(
                target_w,
                target_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _source_image_path(self, result) -> str:
        job = getattr(result, "job", None)
        value = getattr(job, "image_path", "") if job else ""
        return str(value) if value else ""

    def _pixmap_for_preview(self, path: Path) -> QPixmap:
        if self._comparison_mode and path.suffix.lower() == ".png":
            pix = _transparent_png_on_checkerboard(path)
            if not pix.isNull():
                return pix
        return QPixmap(str(path))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.file_list.currentRow() >= 0:
            self._on_file_selected()

    def _saveable_paths(self) -> List[str]:
        source = self._flat_results if self._grouped else self._results
        return [
            getattr(r, "output_path", "")
            for r in source
            if (
                getattr(r, "success", False)
                and getattr(r, "output_path", "")
                and Path(getattr(r, "output_path", "")).exists()
            )
        ]

    def _has_saveable_results(self) -> bool:
        return bool(self._saveable_paths())

    def _on_save_as(self) -> None:
        row = self.file_list.currentRow()
        if row < 0:
            return
        r = self._result_at_row(row)
        if r is None:
            return
        out = getattr(r, "output_path", "") or ""
        if not getattr(r, "success", False) or not out or not Path(out).exists():
            return
        src_dir = str(Path(out).parent)
        suffix = Path(out).suffix.lower()
        filter_map = {
            ".png": "PNG (*.png)",
            ".jpg": "JPEG (*.jpg)",
            ".jpeg": "JPEG (*.jpg)",
            ".webp": "WebP (*.webp)",
        }
        file_filter = filter_map.get(suffix, f"Imagen (*{suffix})")
        save_file_as(
            self,
            out,
            title="Guardar como",
            suggested_path=Path(src_dir) / Path(out).name,
            file_filter=file_filter,
        )

    def _on_save_all(self) -> None:
        if self._grouped:
            groups: list[tuple[str, list[str]]] = []
            for g in self._groups:
                paths = [
                    getattr(r, "output_path", "")
                    for r in g.results
                    if (
                        getattr(r, "success", False)
                        and getattr(r, "output_path", "")
                        and Path(getattr(r, "output_path", "")).exists()
                    )
                ]
                if paths:
                    stem = Path(g.output_dir).name
                    groups.append((stem, paths))
            save_grouped_files_as_batch(
                self,
                groups,
                title="Guardar todo",
                start_dir=str(Path.home()),
            )
            return

        row = self.file_list.currentRow()
        start_dir = (
            self._source_dirs[row]
            if 0 <= row < len(self._source_dirs)
            else str(Path.home())
        )
        save_files_as_batch(
            self,
            self._saveable_paths(),
            title="Guardar todo",
            start_dir=start_dir,
        )

    def _copy_selected_file(self) -> bool:
        row = self.file_list.currentRow()
        result = self._result_at_row(row)
        out = getattr(result, "output_path", "") if result is not None else ""
        if not out or not Path(out).exists():
            QToolTip.showText(QCursor.pos(), "No hay archivo para copiar", self, self.rect(), 1800)
            return False
        ok = copy_files_to_clipboard([out])
        QToolTip.showText(
            QCursor.pos(),
            "Archivo copiado" if ok else "No se pudo copiar el archivo",
            self,
            self.rect(),
            1800,
        )
        return ok

    def _on_open_file(self) -> None:
        row = self.file_list.currentRow()
        r = self._result_at_row(row)
        if r is not None:
            out = getattr(r, "output_path", "") or ""
            open_file(self, out, title="Abrir imagen")

    def _on_open(self) -> None:
        row = self.file_list.currentRow()
        r = self._result_at_row(row)
        if r is not None:
            out = getattr(r, "output_path", "") or ""
            open_folder(self, out, title="Abrir carpeta")


def _transparent_png_on_checkerboard(path: Path, square: int = 18) -> QPixmap:
    try:
        with Image.open(path) as img:
            rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        draw = ImageDraw.Draw(bg)
        light = (238, 238, 238, 255)
        dark = (196, 196, 196, 255)
        for y in range(0, rgba.height, square):
            for x in range(0, rgba.width, square):
                draw.rectangle(
                    (x, y, x + square - 1, y + square - 1),
                    fill=light if ((x // square + y // square) % 2 == 0) else dark,
                )
        bg.alpha_composite(rgba)
        data = bg.tobytes("raw", "RGBA")
        qimg = QImage(data, bg.width, bg.height, QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(qimg.copy())
    except Exception:
        return QPixmap()


def _qimage_for_clipboard(path: Path) -> QImage:
    qimg = QImage(str(path))
    if not qimg.isNull():
        return qimg
    try:
        with Image.open(path) as img:
            rgba = img.convert("RGBA")
        data = rgba.tobytes("raw", "RGBA")
        qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
        return qimg.copy()
    except Exception:
        return QImage()


def _qimage_png_bytes(qimg: QImage) -> bytes:
    if qimg.isNull():
        return b""
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        return b""
    try:
        if not qimg.save(buffer, "PNG"):
            return b""
        return bytes(data)
    finally:
        buffer.close()
