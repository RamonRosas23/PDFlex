"""Reusable image results viewer for PDFlex tools."""
from __future__ import annotations

from pathlib import Path
from typing import List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFrame,
)

from ui.common.file_dialogs import get_save_file_name
from ui.common.icons import icon, set_button_icon
from ui.common.result_ui import ElidedLabel, configure_result_list
from ui.common.save_utils import save_files_as_batch


class ImageResultsViewer(QWidget):
    """List and preview image outputs with save/open actions.

    Accepts any result object with ``output_path``, ``success`` and ``error``
    attributes.
    """

    openInExplorer = pyqtSignal(str)

    def __init__(self, list_title: str = "Imágenes generadas", parent=None) -> None:
        super().__init__(parent)
        self._list_title = list_title
        self._results: list = []
        self._source_dirs: list = []
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

        layout.addWidget(right, 1)

    def set_results(self, results: list) -> None:
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

    def clear_results(self) -> None:
        self._results = []
        self._source_dirs = []
        self.file_list.clear()
        self.preview_lbl.clear()
        self.meta_lbl.setText("")
        self.title_lbl.setText("Selecciona un archivo")
        self.open_file_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.save_as_btn.setEnabled(False)
        self.save_all_btn.setEnabled(False)

    def set_source_dirs(self, dirs: List[str]) -> None:
        """Associate one source directory per result for Save As defaults."""
        self._source_dirs = list(dirs)

    def _on_file_selected(self) -> None:
        row = self.file_list.currentRow()
        if row < 0 or row >= len(self._results):
            return
        r = self._results[row]
        out = getattr(r, "output_path", "") or ""
        if not getattr(r, "success", False) or not out:
            self.title_lbl.setText("Error en este archivo")
            self.meta_lbl.setText(getattr(r, "error", "") or "")
            self.preview_lbl.clear()
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

        pix = QPixmap(str(path))
        if pix.isNull():
            self.preview_lbl.clear()
            self.meta_lbl.setText("No se pudo previsualizar")
            return

        target_w = max(240, self.preview_lbl.width())
        target_h = max(220, self.preview_lbl.height())
        scaled = pix.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_lbl.setPixmap(scaled)
        try:
            size_kb = path.stat().st_size / 1024
            size_str = f"{size_kb / 1024:.1f} MB" if size_kb >= 1024 else f"{size_kb:.0f} KB"
            self.meta_lbl.setText(
                f"{pix.width()} x {pix.height()} px  ·  {size_str}"
            )
        except OSError:
            self.meta_lbl.setText(f"{pix.width()} x {pix.height()} px")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.file_list.currentRow() >= 0:
            self._on_file_selected()

    def _saveable_paths(self) -> List[str]:
        return [
            getattr(r, "output_path", "")
            for r in self._results
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
        if row < 0 or row >= len(self._results):
            return
        r = self._results[row]
        out = getattr(r, "output_path", "") or ""
        if not getattr(r, "success", False) or not out or not Path(out).exists():
            return
        src_dir = (
            self._source_dirs[row]
            if row < len(self._source_dirs)
            else str(Path(out).parent)
        )
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
        if 0 <= row < len(self._results):
            out = getattr(self._results[row], "output_path", "") or ""
            if out and Path(out).exists():
                from PyQt6.QtCore import QUrl
                from PyQt6.QtGui import QDesktopServices

                QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def _on_open(self) -> None:
        row = self.file_list.currentRow()
        if 0 <= row < len(self._results):
            out = getattr(self._results[row], "output_path", "") or ""
            if out:
                self.openInExplorer.emit(out)
