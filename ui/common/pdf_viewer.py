"""GenericPdfViewer — visor de resultados PDF reutilizable por todas las herramientas.

Acepta cualquier objeto que tenga los atributos:
    output_path: str
    success: bool
    error: str

No tiene metadatos específicos de ninguna herramienta (sin datos de firma,
sin page_results del Firmador, etc.).
"""
from __future__ import annotations
from pathlib import Path
from typing import List

import fitz
from PIL import Image
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QIcon
from PyQt6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QPushButton,
    QScrollArea, QSpinBox,
)

from ui.styles import COLORS as _COLORS

from ui.common.save_utils import save_files_as_batch
from ui.common.result_ui import (
    ElidedLabel,
    ResultsStatBar,
    configure_result_list,
    format_file_size,
    make_result_list_item,
)
from ui.common.file_dialogs import get_save_file_name
from ui.common.icons import set_button_icon
from ui.common.pdf_fullview_dialog import PdfFullViewDialog


ZOOM_LEVELS = [0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 2.50, 3.00]

# Tamaño máximo del lado largo de la imagen renderizada en el canvas principal.
# Limita el uso de RAM para PDFs escaneados o de tamaño inusual.
_CANVAS_MAX_PX = 2200

# Tamaño objetivo del lado largo de las miniaturas (en píxeles finales).
# El DPI se escala para que ninguna miniatura supere este umbral.
_THUMB_TARGET_PX = 180


def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


class GenericPdfViewer(QWidget):
    """Visor genérico: lista de documentos resultado + render PDF interactivo."""

    openInExplorer = pyqtSignal(str)

    def __init__(self, doc_list_title: str = "Documentos procesados", parent=None) -> None:
        super().__init__(parent)
        self._doc_list_title = doc_list_title
        self._results: list = []
        self._source_dirs: dict = {}
        self._current_doc: fitz.Document | None = None
        self._current_result = None
        self._current_page: int = 0
        self._zoom_index: int = 2
        self._fit_mode: str = "width"

        self._build()

    # ------------------------------------------------------------------ #
    # Construcción
    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Panel izquierdo — lista de documentos
        left = QFrame()
        left.setProperty("class", "Card")
        left.setFixedWidth(240)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 14, 14, 14)
        lv.setSpacing(10)

        title_lbl = QLabel(self._doc_list_title)
        title_lbl.setProperty("class", "CardTitle")
        lv.addWidget(title_lbl)

        # Barra de estadísticas (auto-populated por set_results)
        self._stat_bar = ResultsStatBar()
        lv.addWidget(self._stat_bar)

        # Barra de stats extra (set_extra_stats, usada por herramientas con métricas propias)
        self._extra_stat_bar = ResultsStatBar()
        lv.addWidget(self._extra_stat_bar)

        self.doc_list = QListWidget()
        configure_result_list(self.doc_list)
        self.doc_list.itemSelectionChanged.connect(self._on_doc_selected)
        lv.addWidget(self.doc_list, 1)

        layout.addWidget(left)

        # Panel central — render + controles
        center = QFrame()
        center.setProperty("class", "Card")
        cv = QVBoxLayout(center)
        cv.setContentsMargins(14, 14, 14, 14)
        cv.setSpacing(12)

        # ── Fila 1: título + acciones de archivo ───────────────────────
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        self.title_label = ElidedLabel("Selecciona un documento")
        self.title_label.setProperty("class", "CardTitle")
        title_row.addWidget(self.title_label, 1)

        self.open_file_btn = QPushButton("Abrir PDF")
        self.open_file_btn.setProperty("class", "Ghost")
        set_button_icon(self.open_file_btn, "external-link")
        self.open_file_btn.clicked.connect(self._on_open_file)
        self.open_file_btn.setEnabled(False)
        title_row.addWidget(self.open_file_btn)

        self.fullview_btn = QPushButton("Vista completa")
        self.fullview_btn.setProperty("class", "Ghost")
        set_button_icon(self.fullview_btn, "maximize")
        self.fullview_btn.setToolTip("Abrir en vista completa (modal inmersivo)")
        self.fullview_btn.clicked.connect(self._on_fullview)
        self.fullview_btn.setEnabled(False)
        title_row.addWidget(self.fullview_btn)

        self.open_btn = QPushButton("Abrir carpeta")
        self.open_btn.setProperty("class", "Ghost")
        set_button_icon(self.open_btn, "folder-open")
        self.open_btn.clicked.connect(self._on_open_in_explorer)
        self.open_btn.setEnabled(False)
        title_row.addWidget(self.open_btn)

        self.save_as_btn = QPushButton("Guardar como")
        self.save_as_btn.setProperty("class", "Ghost")
        set_button_icon(self.save_as_btn, "save")
        self.save_as_btn.clicked.connect(self._on_save_as)
        self.save_as_btn.setEnabled(False)
        title_row.addWidget(self.save_as_btn)

        self.save_all_btn = QPushButton("Guardar todo")
        self.save_all_btn.setProperty("class", "Ghost")
        set_button_icon(self.save_all_btn, "download")
        self.save_all_btn.clicked.connect(self._on_save_all)
        self.save_all_btn.setEnabled(False)
        title_row.addWidget(self.save_all_btn)

        cv.addLayout(title_row)

        # ── Fila 2: controles de vista (zoom + ajuste) ─────────────────
        view_bar = QHBoxLayout()
        view_bar.setSpacing(8)
        view_bar.setContentsMargins(0, 0, 0, 0)

        self.zoom_out_btn = QPushButton()
        self.zoom_out_btn.setProperty("class", "IconBtn")
        self.zoom_out_btn.setToolTip("Reducir zoom")
        set_button_icon(self.zoom_out_btn, "minus", size=14, icon_only=True)
        self.zoom_out_btn.clicked.connect(self._zoom_out)
        self.zoom_out_btn.setEnabled(False)
        view_bar.addWidget(self.zoom_out_btn)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setStyleSheet("color: #9094A0; min-width: 40px;")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        view_bar.addWidget(self.zoom_label)

        self.zoom_in_btn = QPushButton()
        self.zoom_in_btn.setProperty("class", "IconBtn")
        self.zoom_in_btn.setToolTip("Aumentar zoom")
        set_button_icon(self.zoom_in_btn, "plus", size=14, icon_only=True)
        self.zoom_in_btn.clicked.connect(self._zoom_in)
        self.zoom_in_btn.setEnabled(False)
        view_bar.addWidget(self.zoom_in_btn)

        self.fit_btn = QPushButton()
        self.fit_btn.setProperty("class", "IconBtn")
        self.fit_btn.setToolTip("Ajustar al ancho")
        set_button_icon(self.fit_btn, "maximize", size=14, icon_only=True)
        self.fit_btn.clicked.connect(self._fit_width)
        self.fit_btn.setEnabled(False)
        view_bar.addWidget(self.fit_btn)

        self.fit_page_btn = QPushButton()
        self.fit_page_btn.setProperty("class", "IconBtn")
        self.fit_page_btn.setToolTip("Ajustar página completa")
        set_button_icon(self.fit_page_btn, "file-text", size=14, icon_only=True)
        self.fit_page_btn.clicked.connect(self._fit_page)
        self.fit_page_btn.setEnabled(False)
        view_bar.addWidget(self.fit_page_btn)

        view_bar.addStretch(1)
        cv.addLayout(view_bar)

        # Body: página miniatura + canvas
        body = QHBoxLayout()
        body.setSpacing(12)

        self.page_list = QListWidget()
        self.page_list.setObjectName("PageThumbList")
        self.page_list.setFixedWidth(132)
        self.page_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.page_list.setIconSize(QSize(92, 118))
        self.page_list.setGridSize(QSize(112, 152))
        self.page_list.setFlow(QListWidget.Flow.TopToBottom)
        self.page_list.setWrapping(False)
        self.page_list.setResizeMode(QListWidget.ResizeMode.Fixed)
        self.page_list.setSpacing(4)
        self.page_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.page_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.page_list.itemSelectionChanged.connect(self._on_page_selected)
        body.addWidget(self.page_list)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("ResultCanvas")
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.canvas = QLabel()
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setStyleSheet("background: transparent;")
        self.scroll.setWidget(self.canvas)
        body.addWidget(self.scroll, 1)

        cv.addLayout(body, 1)

        # ── Footer: metadata (izquierda) + paginador (derecha) ────────
        footer_bar = QHBoxLayout()
        footer_bar.setSpacing(6)
        footer_bar.setContentsMargins(0, 4, 0, 0)

        self.meta_label = ElidedLabel("")
        self.meta_label.setProperty("class", "CardHint")
        footer_bar.addWidget(self.meta_label, 1)

        self.prev_page_btn = QPushButton()
        self.prev_page_btn.setProperty("class", "IconBtn")
        self.prev_page_btn.setToolTip("Página anterior")
        set_button_icon(self.prev_page_btn, "chevron-left", size=14, icon_only=True)
        self.prev_page_btn.clicked.connect(self._prev_page)
        self.prev_page_btn.setEnabled(False)
        footer_bar.addWidget(self.prev_page_btn)

        _pag_lbl = QLabel("Pág.")
        _pag_lbl.setStyleSheet("color: #9094A0; font-size: 12px;")
        footer_bar.addWidget(_pag_lbl)

        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.setEnabled(False)
        self.page_spin.setFixedWidth(54)
        self.page_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.page_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_spin.setStyleSheet(
            f"QSpinBox {{ background: {_COLORS['surface_3']}; color: {_COLORS['text']}; "
            f"border: 1px solid {_COLORS['border']}; border-radius: 4px; "
            f"padding: 1px 4px; font-size: 12px; }}"
        )
        self.page_spin.editingFinished.connect(self._on_page_jump)
        footer_bar.addWidget(self.page_spin)

        self._page_total_lbl = QLabel("/ —")
        self._page_total_lbl.setStyleSheet("color: #9094A0; font-size: 12px; min-width: 32px;")
        footer_bar.addWidget(self._page_total_lbl)

        self.next_page_btn = QPushButton()
        self.next_page_btn.setProperty("class", "IconBtn")
        self.next_page_btn.setToolTip("Página siguiente")
        set_button_icon(self.next_page_btn, "chevron-right", size=14, icon_only=True)
        self.next_page_btn.clicked.connect(self._next_page)
        self.next_page_btn.setEnabled(False)
        footer_bar.addWidget(self.next_page_btn)

        cv.addLayout(footer_bar)

        layout.addWidget(center, 1)

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #

    def set_results(self, results: list) -> None:
        """Acepta cualquier lista de objetos con output_path, success, error."""
        self._results = results
        self._source_dirs = {}
        self.doc_list.clear()
        for r in results:
            out = getattr(r, "output_path", "") or ""
            item = make_result_list_item(
                out,
                success=getattr(r, "success", False),
                error=getattr(r, "error", "") or "",
            )
            self.doc_list.addItem(item)
        if results:
            self.doc_list.setCurrentRow(0)
            self._refresh_auto_stats(results)
        else:
            self._stat_bar.setVisible(False)
            self._clear_view()

    def set_extra_stats(self, stats: list[dict]) -> None:
        """Muestra una barra de stats específica de la herramienta (ej: compresión).

        Cada dict: {"value": int|str, "label": str, "color": str?}
        Llamar después de set_results() para que quede debajo de los stats base.
        """
        self._extra_stat_bar.set_stats(stats)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(60, self._extra_stat_bar.animate)

    def _refresh_auto_stats(self, results: list) -> None:
        from ui.styles import COLORS as _C
        ok = sum(1 for r in results if getattr(r, "success", False))
        errors = len(results) - ok
        stats: list[dict] = [
            {"value": len(results), "label": "archivos", "color": _C["text"]},
            {"value": ok, "label": "correctos", "color": _C["success"]},
        ]
        if errors > 0:
            stats.append({"value": errors, "label": "errores", "color": _C["danger"]})
        self._stat_bar.set_stats(stats)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(30, self._stat_bar.animate)

    def clear_results(self) -> None:
        self._close_doc()
        self._results = []
        self._source_dirs = {}
        self._current_result = None
        self.doc_list.clear()
        self._stat_bar.setVisible(False)
        self._extra_stat_bar.setVisible(False)
        self._clear_view()

    def set_source_dirs(self, dirs: list) -> None:
        """Mapea cada fila de resultados a su carpeta de origen (para el cuadro Save As)."""
        self._source_dirs = {i: d for i, d in enumerate(dirs)}

    @staticmethod
    def _source_dir_from(result) -> str:
        """Devuelve la carpeta del archivo origen a partir de un resultado."""
        import tempfile
        job = getattr(result, "job", None)
        if job:
            pdf_path = getattr(job, "pdf_path", None)
            if pdf_path:
                return str(Path(pdf_path).parent)
        out = getattr(result, "output_path", "") or ""
        if out:
            p = Path(out)
            try:
                p.relative_to(Path(tempfile.gettempdir()))
                # Archivo en temp — proponer carpeta home como destino
                return str(Path.home())
            except ValueError:
                return str(p.parent)
        return str(Path.home())

    def _on_save_as(self) -> None:
        if self._current_result is None:
            return
        out = getattr(self._current_result, "output_path", "") or ""
        if not out or not Path(out).exists():
            return
        row = self.doc_list.currentRow()
        src_dir = self._source_dirs.get(row) or self._source_dir_from(self._current_result)
        new_path, _ = get_save_file_name(
            self, "Guardar como",
            str(Path(src_dir) / Path(out).name),
            "PDF (*.pdf)",
        )
        if new_path:
            import shutil
            shutil.copy2(out, new_path)

    def _on_save_all(self) -> None:
        start_dir = Path.home()
        row = self.doc_list.currentRow()
        if row >= 0:
            src_dir = self._source_dirs.get(row)
            if src_dir:
                start_dir = Path(src_dir)
            elif self._current_result is not None:
                start_dir = Path(self._source_dir_from(self._current_result))
        save_files_as_batch(
            self,
            self._saveable_paths(),
            title="Guardar todo",
            start_dir=start_dir,
        )

    # ------------------------------------------------------------------ #

    def _clear_view(self) -> None:
        self.page_list.blockSignals(True)
        try:
            self.page_list.clear()
        finally:
            self.page_list.blockSignals(False)
        self._current_page = 0
        self.canvas.clear()
        self.title_label.setText("Selecciona un documento")
        self.meta_label.setText("")
        self._set_zoom_enabled(False)
        self.open_btn.setEnabled(False)
        self.open_file_btn.setEnabled(False)
        self.save_as_btn.setEnabled(False)
        self.save_all_btn.setEnabled(False)
        self._update_page_status()

    def _set_zoom_enabled(self, enabled: bool) -> None:
        self.zoom_in_btn.setEnabled(enabled)
        self.zoom_out_btn.setEnabled(enabled)
        self.fit_btn.setEnabled(enabled)
        self.fit_page_btn.setEnabled(enabled)
        self.open_btn.setEnabled(enabled)
        self.open_file_btn.setEnabled(enabled)
        self.fullview_btn.setEnabled(enabled)
        self.save_as_btn.setEnabled(enabled)
        self.save_all_btn.setEnabled(self._has_saveable_results())
        self._update_page_status()

    def _update_page_status(self) -> None:
        if self._current_doc is None or self._current_doc.page_count <= 0:
            self.page_spin.blockSignals(True)
            self.page_spin.setRange(1, 1)
            self.page_spin.setValue(1)
            self.page_spin.blockSignals(False)
            self.page_spin.setEnabled(False)
            self._page_total_lbl.setText("/ —")
            self.prev_page_btn.setEnabled(False)
            self.next_page_btn.setEnabled(False)
            return
        page_count = self._current_doc.page_count
        page = min(max(self._current_page, 0), page_count - 1)
        self.page_spin.blockSignals(True)
        self.page_spin.setRange(1, page_count)
        self.page_spin.setValue(page + 1)
        self.page_spin.blockSignals(False)
        self.page_spin.setEnabled(page_count > 1)
        self._page_total_lbl.setText(f"/ {page_count}")
        self.prev_page_btn.setEnabled(page > 0)
        self.next_page_btn.setEnabled(page < page_count - 1)

    def _has_saveable_results(self) -> bool:
        return bool(self._saveable_paths())

    def _saveable_paths(self) -> list[str]:
        return [
            getattr(r, "output_path", "")
            for r in self._results
            if (
                getattr(r, "success", False)
                and getattr(r, "output_path", "")
                and Path(getattr(r, "output_path", "")).exists()
            )
        ]

    def _close_doc(self) -> None:
        if self._current_doc is not None:
            try:
                self._current_doc.close()
            except Exception:
                pass
            self._current_doc = None

    # ------------------------------------------------------------------ #
    # Handlers
    # ------------------------------------------------------------------ #

    def _on_doc_selected(self) -> None:
        row = self.doc_list.currentRow()
        if row < 0 or row >= len(self._results):
            return
        result = self._results[row]
        self._current_result = result
        self._current_page = 0
        self._close_doc()

        out_path = getattr(result, "output_path", "") or ""
        if not getattr(result, "success", False) or not out_path:
            self.title_label.setText("Error en este documento")
            err = getattr(result, "error", "")
            self.meta_label.setText(err or "")
            self.page_list.blockSignals(True)
            try:
                self.page_list.clear()
            finally:
                self.page_list.blockSignals(False)
            self.canvas.clear()
            self._set_zoom_enabled(False)
            return

        self.title_label.setText(Path(out_path).name)
        self._set_zoom_enabled(True)

        try:
            self._current_doc = fitz.open(out_path)
            if self._current_doc.needs_pass:
                password = (
                    getattr(result, "user_password", "")
                    or getattr(result, "open_password", "")
                    or getattr(getattr(result, "job", None), "open_password", "")
                )
                if not password or not self._current_doc.authenticate(password):
                    raise RuntimeError("El PDF requiere contraseña para previsualizarse.")
        except Exception as e:
            self.meta_label.setText(f"No se pudo abrir: {e}")
            self._close_doc()
            self.page_list.blockSignals(True)
            try:
                self.page_list.clear()
            finally:
                self.page_list.blockSignals(False)
            self.canvas.clear()
            self._set_zoom_enabled(False)
            return

        self.page_list.blockSignals(True)
        try:
            self.page_list.clear()
            for i in range(self._current_doc.page_count):
                # DPI adaptativo: la miniatura nunca ocupa más de _THUMB_TARGET_PX
                # en su lado largo, independientemente del tamaño físico de la página.
                thumb_dpi = self._thumb_dpi_for_page(i)
                thumb = self._render(i, dpi=thumb_dpi)
                item = QListWidgetItem(QIcon(thumb), str(i + 1))
                item.setToolTip(f"Página {i + 1}")
                self.page_list.addItem(item)
        finally:
            self.page_list.blockSignals(False)

        if self._current_doc.page_count > 0:
            self.page_list.setCurrentRow(0)
            self._render_current()
        else:
            self.canvas.clear()

        size = format_file_size(out_path)
        meta_parts = [f"{self._current_doc.page_count} páginas"]
        if size:
            meta_parts.append(size)
        meta_parts.append(Path(out_path).name)
        extra_meta = getattr(result, "meta_text", "")
        if extra_meta:
            meta_parts.append(extra_meta)
        self.meta_label.setText(" · ".join(meta_parts))
        self._update_page_status()

    def _on_page_selected(self) -> None:
        if self._current_doc is None:
            return
        row = self.page_list.currentRow()
        if row < 0:
            return
        if row >= self._current_doc.page_count:
            self._current_page = 0
            self._update_page_status()
            return
        self._current_page = row
        self._render_current()

    # ------------------------------------------------------------------ #
    # Render
    # ------------------------------------------------------------------ #

    def _thumb_dpi_for_page(self, page_idx: int) -> float:
        """DPI adaptativo para miniaturas: la imagen siempre mide ≤ _THUMB_TARGET_PX
        en su lado más largo, evitando crear imágenes enormes para páginas grandes.
        """
        if self._current_doc is None:
            return 12.0
        page = self._current_doc[page_idx]
        page_long = max(1.0, page.rect.width, page.rect.height)
        return max(3.0, min(_THUMB_TARGET_PX * 72.0 / page_long, 30.0))

    def _compute_dpi(self) -> float:
        """DPI adaptativo para el canvas principal.

        El 'base' DPI es el que hace que la página quepa exactamente en el
        viewport (fit-width o fit-page).  El zoom multiplica ese base.

        Cambios respecto a la versión anterior:
        - Se elimina el floor fijo de 36 DPI.  Para páginas muy grandes ese
          floor producía imágenes más anchas que el viewport, impidiendo el
          ajuste real.  Ahora el mínimo es base×zoom_min (50 % del fit DPI),
          lo que garantiza que 'Ajustar' siempre muestra la página completa.
        - El máximo sigue siendo 320 DPI para evitar imágenes de cientos de MB.
        """
        if self._current_doc is None:
            return 96.0
        if self._current_page < 0 or self._current_page >= self._current_doc.page_count:
            return 96.0
        page = self._current_doc[self._current_page]
        vp_w = max(200, self.scroll.viewport().width() - 24)
        vp_h = max(200, self.scroll.viewport().height() - 24)
        page_w = max(1.0, page.rect.width)
        page_h = max(1.0, page.rect.height)
        dpi_w = vp_w / page_w * 72.0
        dpi_h = vp_h / page_h * 72.0
        base = dpi_w if self._fit_mode == "width" else min(dpi_w, dpi_h)
        # Mínimo: zoom más pequeño aplicado al base (nunca < 4 DPI para ser visible)
        min_dpi = max(4.0, base * ZOOM_LEVELS[0])
        # Máximo adicional: limitar tamaño absoluto de imagen en RAM
        # (_CANVAS_MAX_PX px en el lado largo como máximo)
        max_dpi = min(320.0, _CANVAS_MAX_PX / max(page_w, page_h) * 72.0)
        dpi = base * ZOOM_LEVELS[self._zoom_index]
        return max(min_dpi, min(dpi, max_dpi))

    def _render_current(self) -> None:
        if self._current_doc is None:
            return
        if self._current_page < 0 or self._current_page >= self._current_doc.page_count:
            return
        dpi = self._compute_dpi()
        pix = self._render(self._current_page, dpi)
        self.canvas.setPixmap(pix)
        self.canvas.setFixedSize(pix.size())
        zoom = ZOOM_LEVELS[self._zoom_index]
        self.zoom_label.setText(f"{int(zoom * 100)}%")
        self._update_page_status()

    def _render(self, page_idx: int, dpi: float) -> QPixmap:
        page = self._current_doc[page_idx]
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pm = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
        return _pil_to_qpixmap(img)

    # ------------------------------------------------------------------ #
    # Zoom
    # ------------------------------------------------------------------ #

    def _zoom_in(self) -> None:
        self._fit_mode = "manual"
        if self._zoom_index < len(ZOOM_LEVELS) - 1:
            self._zoom_index += 1
            self._render_current()

    def _zoom_out(self) -> None:
        self._fit_mode = "manual"
        if self._zoom_index > 0:
            self._zoom_index -= 1
            self._render_current()

    def _fit_width(self) -> None:
        self._fit_mode = "width"
        self._zoom_index = 2
        self._render_current()

    def _fit_page(self) -> None:
        self._fit_mode = "page"
        self._zoom_index = 2
        self._render_current()

    def _on_page_jump(self) -> None:
        if self._current_doc is None:
            return
        target = max(0, min(self.page_spin.value() - 1, self._current_doc.page_count - 1))
        if target != self._current_page:
            self.page_list.setCurrentRow(target)

    def _prev_page(self) -> None:
        if self._current_doc is None:
            return
        self.page_list.setCurrentRow(max(0, self._current_page - 1))

    def _next_page(self) -> None:
        if self._current_doc is None:
            return
        self.page_list.setCurrentRow(
            min(self._current_doc.page_count - 1, self._current_page + 1)
        )

    def _on_open_file(self) -> None:
        if self._current_result:
            out = getattr(self._current_result, "output_path", "")
            if out and Path(out).exists():
                from PyQt6.QtCore import QUrl
                from PyQt6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def _on_fullview(self) -> None:
        row = self.doc_list.currentRow()
        if row < 0 or not self._results:
            return
        dlg = PdfFullViewDialog(self, results=self._results, current_index=row)
        dlg.exec()

    def _on_open_in_explorer(self) -> None:
        if self._current_result:
            out = getattr(self._current_result, "output_path", "")
            if out:
                self.openInExplorer.emit(out)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._current_doc is not None and self._fit_mode != "manual":
            self._render_current()
