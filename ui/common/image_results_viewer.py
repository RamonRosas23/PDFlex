"""Reusable image results viewer for PDFlex tools."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QImage, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFrame,
)
from PIL import Image, ImageDraw

from ui.common.file_dialogs import get_save_file_name
from ui.common.icons import icon, set_button_icon
from ui.common.result_ui import ElidedLabel, configure_result_list
from ui.common.save_utils import save_files_as_batch, save_grouped_files_as_batch


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

    openInExplorer = pyqtSignal(str)

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

        self.file_list = QListWidget()
        configure_result_list(self.file_list)
        self.file_list.itemSelectionChanged.connect(self._on_file_selected)
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

        self.open_file_btn = QPushButton("Abrir imagen")
        self.open_file_btn.setProperty("class", "Ghost")
        set_button_icon(self.open_file_btn, "external-link")
        self.open_file_btn.setEnabled(False)
        self.open_file_btn.clicked.connect(self._on_open_file)
        actions.addWidget(self.open_file_btn)

        self.open_btn = QPushButton("Abrir carpeta")
        self.open_btn.setProperty("class", "Ghost")
        set_button_icon(self.open_btn, "folder-open")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._on_open)
        actions.addWidget(self.open_btn)

        self.save_as_btn = QPushButton("Guardar como")
        self.save_as_btn.setProperty("class", "Ghost")
        set_button_icon(self.save_as_btn, "save")
        self.save_as_btn.setEnabled(False)
        self.save_as_btn.clicked.connect(self._on_save_as)
        actions.addWidget(self.save_as_btn)

        self.save_all_btn = QPushButton("Guardar todo")
        self.save_all_btn.setProperty("class", "Ghost")
        set_button_icon(self.save_all_btn, "download")
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
        rv.addWidget(self.preview_lbl, 1)

        self.compare_widget = QWidget()
        compare_layout = QHBoxLayout(self.compare_widget)
        compare_layout.setContentsMargins(0, 0, 0, 0)
        compare_layout.setSpacing(12)
        self.before_preview_lbl = self._make_compare_panel("Antes")
        self.after_preview_lbl = self._make_compare_panel("Después")
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
            name = Path(out).name if out else "(error)"
            item = QListWidgetItem(name)
            item.setToolTip(out or name)
            if not getattr(r, "success", False):
                item.setForeground(QBrush(QColor("#E5484D")))
                item.setIcon(icon("warning", "#E5484D", 16))
            self.file_list.addItem(item)
        if self._results:
            self.file_list.setCurrentRow(0)
        else:
            self.clear_results()

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
                name = "   " + Path(out).name if out else "   (error)"
                item = QListWidgetItem(name)
                item.setToolTip(out or name.strip())
                if not getattr(r, "success", False):
                    item.setForeground(QBrush(QColor("#E5484D")))
                    item.setIcon(icon("warning", "#E5484D", 16))
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
        self.open_btn.setEnabled(False)
        self.save_as_btn.setEnabled(False)
        self.save_all_btn.setEnabled(False)

    def set_source_dirs(self, dirs: List[str]) -> None:
        """Associate one source directory per result for Save As defaults."""
        self._source_dirs = list(dirs)

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
            self.open_btn.setEnabled(False)
            self.save_as_btn.setEnabled(False)
            self.save_all_btn.setEnabled(self._has_saveable_results())
            return

        path = Path(out)
        self.title_lbl.setText(path.name)
        self.open_file_btn.setEnabled(True)
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
        try:
            size_kb = path.stat().st_size / 1024
            size_str = f"{size_kb / 1024:.1f} MB" if size_kb >= 1024 else f"{size_kb:.0f} KB"
            meta = f"{pix.width()} x {pix.height()} px  ·  {size_str}"
            extra = getattr(r, "meta_text", "")
            if extra:
                meta += f"  ·  {extra}"
            self.meta_lbl.setText(meta)
        except OSError:
            meta = f"{pix.width()} x {pix.height()} px"
            extra = getattr(r, "meta_text", "")
            if extra:
                meta += f"  ·  {extra}"
            self.meta_lbl.setText(meta)

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
        new_path, _ = get_save_file_name(
            self,
            "Guardar como",
            str(Path(src_dir) / Path(out).name),
            file_filter,
        )
        if new_path:
            import shutil
            shutil.copy2(out, new_path)

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

    def _on_open_file(self) -> None:
        row = self.file_list.currentRow()
        r = self._result_at_row(row)
        if r is not None:
            out = getattr(r, "output_path", "") or ""
            if out and Path(out).exists():
                from PyQt6.QtCore import QUrl
                from PyQt6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def _on_open(self) -> None:
        row = self.file_list.currentRow()
        r = self._result_at_row(row)
        if r is not None:
            out = getattr(r, "output_path", "") or ""
            if out:
                self.openInExplorer.emit(out)


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
