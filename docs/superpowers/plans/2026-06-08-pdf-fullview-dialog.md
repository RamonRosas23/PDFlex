# PdfFullViewDialog — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir un modal inmersivo de vista completa PDF a la etapa de resultados, con navegación entre documentos del lote, paginador funcional, zoom, thumbnails de páginas y atajos de teclado completos.

**Architecture:** `PdfFullViewDialog` es un `QDialog` frameless independiente en `ui/common/pdf_fullview_dialog.py`. Reutiliza el engine de render `fitz` ya establecido en `GenericPdfViewer`. Se integra en `GenericPdfViewer` y `ResultsViewer` con un botón "Vista completa" en la fila de título.

**Tech Stack:** PyQt6, fitz (PyMuPDF), PIL, Python 3.11+

---

## Mapa de archivos

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `ui/common/icons.py` | Modificar | Añadir ícono `columns` para toggle sidebar |
| `ui/common/pdf_fullview_dialog.py` | **Crear** | Modal completo: layout, render, navegación, eventos |
| `ui/common/pdf_viewer.py` | Modificar | Botón "Vista completa" en `title_row` |
| `ui/results_viewer.py` | Modificar | Botón "Vista completa" en `title_row` |
| `tests/test_pdf_fullview_dialog.py` | **Crear** | Tests de smoke, navegación y controles |

---

## Task 1: Añadir ícono `columns` a `ui/common/icons.py`

**Files:**
- Modify: `ui/common/icons.py`

- [ ] **Step 1.1: Añadir la entrada `columns` al dict `_ICONS`**

Abrir `ui/common/icons.py`. Localizar el bloque `_ICONS = {` (línea ~59). Añadir justo después de la entrada `"panel-top"` (línea ~94):

```python
    "columns": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
```

El dict queda:
```python
    "panel-top": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/>',
    "columns": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
    "more-horizontal": ...
```

- [ ] **Step 1.2: Verificar sintaxis**

```bash
python -c "from ui.common.icons import icon; print(icon('columns', '#5E6AD2', 16))"
```

Resultado esperado: `<PyQt6.QtGui.QIcon object at ...>` (sin excepciones).

- [ ] **Step 1.3: Commit**

```bash
git add ui/common/icons.py
git commit -m "feat(icons): add 'columns' icon for sidebar toggle"
```

---

## Task 2: Crear `ui/common/pdf_fullview_dialog.py`

**Files:**
- Create: `ui/common/pdf_fullview_dialog.py`

- [ ] **Step 2.1: Crear el archivo con la implementación completa**

Crear `ui/common/pdf_fullview_dialog.py` con el siguiente contenido:

```python
"""PdfFullViewDialog — modal inmersivo de visualización PDF para PDFlex.

API:
    dlg = PdfFullViewDialog(parent, results=lista, current_index=0)
    dlg.exec()

`results` debe ser una lista de objetos con atributos:
    output_path: str   — ruta del PDF generado
    success: bool      — si el procesamiento fue exitoso
    error: str         — mensaje de error (si success=False)

Atributos opcionales que se respetan si están presentes:
    user_password / open_password — para PDFs protegidos
    job.open_password             — alternativa al anterior
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import fitz
from PIL import Image
from PyQt6.QtCore import (
    Qt, QSize, QPoint, QPropertyAnimation, QEasingCurve, QTimer,
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QImage, QKeyEvent, QWheelEvent, QPainter, QColor,
)
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from ui.common.animations import AnimationHelper
from ui.common.icons import set_button_icon
from ui.common.result_ui import ElidedLabel
from ui.styles import COLORS

# ── Constantes ────────────────────────────────────────────────────────────────
ZOOM_LEVELS = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 2.50, 3.00, 4.00]
_FIT_ZOOM_IDX = 3        # índice de zoom=1.00 (base "fit")
_CANVAS_MAX_PX = 2400    # píxeles máximos en el lado largo del canvas
_THUMB_TARGET_PX = 140   # lado largo objetivo de miniaturas en px

_SIDEBAR_W = 120
_TOOLBAR_H = 46
_STRIP_H = 52


def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


# ─────────────────────────────────────────────────────────────────────────────
class PdfFullViewDialog(QDialog):
    """Modal inmersivo de visualización PDF con navegación entre documentos."""

    def __init__(
        self,
        parent: Optional[QWidget],
        results: list,
        current_index: int = 0,
        accent_color: str = "",
    ) -> None:
        super().__init__(parent)
        self._results = list(results)
        self._current_doc_idx = max(0, min(current_index, len(results) - 1))
        self._current_doc: Optional[fitz.Document] = None
        self._current_page: int = 0
        self._zoom_index: int = _FIT_ZOOM_IDX
        self._fit_mode: str = "width"
        self._accent = accent_color or COLORS["accent"]
        self._sidebar_visible: bool = True
        self._sidebar_anim: Optional[QPropertyAnimation] = None
        self._doc_chips: list[QFrame] = []
        self._drag_pos: Optional[QPoint] = None

        self._setup_window()
        self._build()
        QTimer.singleShot(0, lambda: self._load_doc(self._current_doc_idx))

    # ── Window setup ──────────────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        screen = (
            QApplication.screenAt(self.mapToGlobal(QPoint(0, 0)))
            or QApplication.primaryScreen()
        )
        if screen:
            avail = screen.availableGeometry()
            w = int(avail.width() * 0.92)
            h = int(avail.height() * 0.92)
            self.resize(w, h)
            self.move(
                avail.x() + (avail.width() - w) // 2,
                avail.y() + (avail.height() - h) // 2,
            )

        from ui.common.icons import app_qicon
        self.setWindowIcon(app_qicon())

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("FullViewShell")
        shell.setStyleSheet(
            "QFrame#FullViewShell {"
            f"  background-color: {COLORS['surface']};"
            f"  border: 1px solid {COLORS['border_strong']};"
            "  border-radius: 12px;"
            "}"
        )
        outer.addWidget(shell)

        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())
        root.addWidget(self._make_hsep())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar_container = self._build_sidebar()
        body.addWidget(self._sidebar_container)

        self._sidebar_sep = self._make_vsep()
        body.addWidget(self._sidebar_sep)

        body.addWidget(self._build_canvas(), 1)
        root.addLayout(body, 1)

        root.addWidget(self._make_hsep())
        root.addWidget(self._build_doc_strip())

    # ── Toolbar ───────────────────────────────────────────────────────────────

    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("FullViewToolbar")
        bar.setFixedHeight(_TOOLBAR_H)
        bar.setStyleSheet(
            "QFrame#FullViewToolbar {"
            f"  background-color: {COLORS['surface_2']};"
            "  border-top-left-radius: 12px;"
            "  border-top-right-radius: 12px;"
            "  border: none;"
            "}"
        )

        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 0, 10, 0)
        h.setSpacing(4)

        # G1: Toggle sidebar
        self._toggle_btn = QPushButton()
        self._toggle_btn.setProperty("class", "IconBtn")
        self._toggle_btn.setFixedSize(32, 32)
        self._toggle_btn.setToolTip("Mostrar/ocultar miniaturas (panel izquierdo)")
        set_button_icon(self._toggle_btn, "columns", size=15, icon_only=True)
        self._toggle_btn.clicked.connect(self._toggle_sidebar)
        h.addWidget(self._toggle_btn)

        h.addSpacing(2)
        h.addWidget(self._make_tsep())
        h.addSpacing(2)

        # G2: Navegación de documentos
        self._prev_doc_btn = QPushButton()
        self._prev_doc_btn.setProperty("class", "IconBtn")
        self._prev_doc_btn.setFixedSize(26, 26)
        self._prev_doc_btn.setToolTip("Documento anterior (←)")
        set_button_icon(self._prev_doc_btn, "chevron-left", size=13, icon_only=True)
        self._prev_doc_btn.clicked.connect(lambda: self._navigate_doc(-1))
        h.addWidget(self._prev_doc_btn)

        self._doc_nav_lbl = QLabel("Doc 1 / 1")
        self._doc_nav_lbl.setFixedWidth(76)
        self._doc_nav_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._doc_nav_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px;"
        )
        h.addWidget(self._doc_nav_lbl)

        self._next_doc_btn = QPushButton()
        self._next_doc_btn.setProperty("class", "IconBtn")
        self._next_doc_btn.setFixedSize(26, 26)
        self._next_doc_btn.setToolTip("Documento siguiente (→)")
        set_button_icon(self._next_doc_btn, "chevron-right", size=13, icon_only=True)
        self._next_doc_btn.clicked.connect(lambda: self._navigate_doc(1))
        h.addWidget(self._next_doc_btn)

        h.addSpacing(2)
        h.addWidget(self._make_tsep())
        h.addSpacing(2)

        # G3: Nombre del archivo (expanding)
        self._filename_lbl = ElidedLabel("—")
        self._filename_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px;"
        )
        h.addWidget(self._filename_lbl, 1)

        h.addSpacing(2)
        h.addWidget(self._make_tsep())
        h.addSpacing(2)

        # G4: Zoom
        self._zoom_out_btn = QPushButton()
        self._zoom_out_btn.setProperty("class", "IconBtn")
        self._zoom_out_btn.setFixedSize(28, 28)
        self._zoom_out_btn.setToolTip("Reducir zoom (Ctrl+−)")
        set_button_icon(self._zoom_out_btn, "minus", size=13, icon_only=True)
        self._zoom_out_btn.clicked.connect(self._zoom_out)
        h.addWidget(self._zoom_out_btn)

        self._zoom_lbl = QLabel("100%")
        self._zoom_lbl.setFixedWidth(46)
        self._zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px;"
        )
        h.addWidget(self._zoom_lbl)

        self._zoom_in_btn = QPushButton()
        self._zoom_in_btn.setProperty("class", "IconBtn")
        self._zoom_in_btn.setFixedSize(28, 28)
        self._zoom_in_btn.setToolTip("Aumentar zoom (Ctrl+=)")
        set_button_icon(self._zoom_in_btn, "plus", size=13, icon_only=True)
        self._zoom_in_btn.clicked.connect(self._zoom_in)
        h.addWidget(self._zoom_in_btn)

        self._fit_w_btn = QPushButton()
        self._fit_w_btn.setProperty("class", "IconBtn")
        self._fit_w_btn.setFixedSize(28, 28)
        self._fit_w_btn.setToolTip("Ajustar al ancho (Ctrl+0)")
        set_button_icon(self._fit_w_btn, "maximize", size=13, icon_only=True)
        self._fit_w_btn.clicked.connect(self._fit_width)
        h.addWidget(self._fit_w_btn)

        self._fit_p_btn = QPushButton()
        self._fit_p_btn.setProperty("class", "IconBtn")
        self._fit_p_btn.setFixedSize(28, 28)
        self._fit_p_btn.setToolTip("Ajustar página completa (Ctrl+Shift+0)")
        set_button_icon(self._fit_p_btn, "file-text", size=13, icon_only=True)
        self._fit_p_btn.clicked.connect(self._fit_page)
        h.addWidget(self._fit_p_btn)

        h.addSpacing(2)
        h.addWidget(self._make_tsep())
        h.addSpacing(2)

        # G5: Paginador
        _pag_lbl = QLabel("Pág.")
        _pag_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px;"
        )
        h.addWidget(_pag_lbl)

        self._page_spin = QSpinBox()
        self._page_spin.setRange(1, 1)
        self._page_spin.setEnabled(False)
        self._page_spin.setFixedWidth(54)
        self._page_spin.setFixedHeight(28)
        self._page_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._page_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_spin.setStyleSheet(
            f"QSpinBox {{ background: {COLORS['surface_3']}; color: {COLORS['text']}; "
            f"border: 1px solid {COLORS['border_strong']}; border-radius: 5px; "
            f"padding: 1px 4px; font-size: 12px; }}"
            f"QSpinBox:focus {{ border-color: {COLORS['border_focus']}; }}"
        )
        self._page_spin.editingFinished.connect(self._on_page_jump)
        h.addWidget(self._page_spin)

        self._page_total_lbl = QLabel("/ —")
        self._page_total_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px; min-width: 34px;"
        )
        h.addWidget(self._page_total_lbl)

        self._prev_page_btn = QPushButton()
        self._prev_page_btn.setProperty("class", "IconBtn")
        self._prev_page_btn.setFixedSize(26, 26)
        self._prev_page_btn.setToolTip("Página anterior (Re Pág)")
        set_button_icon(self._prev_page_btn, "chevron-left", size=13, icon_only=True)
        self._prev_page_btn.clicked.connect(self._prev_page)
        h.addWidget(self._prev_page_btn)

        self._next_page_btn = QPushButton()
        self._next_page_btn.setProperty("class", "IconBtn")
        self._next_page_btn.setFixedSize(26, 26)
        self._next_page_btn.setToolTip("Página siguiente (Av Pág)")
        set_button_icon(self._next_page_btn, "chevron-right", size=13, icon_only=True)
        self._next_page_btn.clicked.connect(self._next_page)
        h.addWidget(self._next_page_btn)

        h.addSpacing(2)
        h.addWidget(self._make_tsep())
        h.addSpacing(2)

        # G6: Cerrar
        close_btn = QPushButton()
        close_btn.setProperty("class", "IconBtn")
        close_btn.setFixedSize(32, 32)
        close_btn.setToolTip("Cerrar (Esc)")
        set_button_icon(close_btn, "x", size=15, icon_only=True)
        close_btn.clicked.connect(self.reject)
        h.addWidget(close_btn)

        return bar

    # ── Sidebar (page thumbnails) ─────────────────────────────────────────────

    def _build_sidebar(self) -> QFrame:
        container = QFrame()
        container.setObjectName("FullViewSidebar")
        container.setFixedWidth(_SIDEBAR_W)
        container.setStyleSheet(
            "QFrame#FullViewSidebar { border: none; background: transparent; }"
        )

        cv = QVBoxLayout(container)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        self._page_list = QListWidget()
        self._page_list.setObjectName("FullViewPageList")
        self._page_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._page_list.setIconSize(QSize(80, 103))
        self._page_list.setGridSize(QSize(100, 130))
        self._page_list.setFlow(QListWidget.Flow.TopToBottom)
        self._page_list.setWrapping(False)
        self._page_list.setResizeMode(QListWidget.ResizeMode.Fixed)
        self._page_list.setSpacing(4)
        self._page_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._page_list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._page_list.itemSelectionChanged.connect(self._on_thumb_selected)
        cv.addWidget(self._page_list, 1)

        return container

    # ── Canvas ────────────────────────────────────────────────────────────────

    def _build_canvas(self) -> QScrollArea:
        self._scroll = QScrollArea()
        self._scroll.setObjectName("FullViewCanvas")
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setStyleSheet(
            f"QScrollArea#FullViewCanvas {{ background: {COLORS['bg']}; border: none; }}"
            f"QScrollArea#FullViewCanvas > QWidget > QWidget {{ background: {COLORS['bg']}; }}"
        )

        self._canvas = QLabel()
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas.setStyleSheet("background: transparent;")
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._scroll.setWidget(self._canvas)

        return self._scroll

    # ── Doc strip (bottom) ────────────────────────────────────────────────────

    def _build_doc_strip(self) -> QScrollArea:
        self._strip_scroll = QScrollArea()
        self._strip_scroll.setObjectName("FullViewDocStrip")
        self._strip_scroll.setFixedHeight(_STRIP_H)
        self._strip_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._strip_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._strip_scroll.setWidgetResizable(True)
        self._strip_scroll.setStyleSheet(
            "QScrollArea#FullViewDocStrip {"
            f"  background: {COLORS['surface_2']};"
            "  border: none;"
            "  border-bottom-left-radius: 12px;"
            "  border-bottom-right-radius: 12px;"
            "}"
        )

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self._strip_inner = QHBoxLayout(container)
        self._strip_inner.setContentsMargins(10, 6, 10, 6)
        self._strip_inner.setSpacing(6)
        self._strip_inner.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self._doc_chips = []
        for i, result in enumerate(self._results):
            chip = self._make_chip(i, result)
            self._doc_chips.append(chip)
            self._strip_inner.addWidget(chip)
        self._strip_inner.addStretch()

        self._strip_scroll.setWidget(container)
        return self._strip_scroll

    def _make_chip(self, index: int, result) -> QFrame:
        success = getattr(result, "success", False)
        out = getattr(result, "output_path", "") or ""
        name = Path(out).name if out else "(error)"

        chip = QFrame()
        chip.setFixedHeight(36)
        chip.setMinimumWidth(90)
        chip.setMaximumWidth(190)

        if success:
            chip.setCursor(Qt.CursorShape.PointingHandCursor)

        cl = QHBoxLayout(chip)
        cl.setContentsMargins(8, 0, 10, 0)
        cl.setSpacing(6)

        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(
            f"background: {COLORS['success'] if success else COLORS['danger']};"
            "border-radius: 4px; border: none;"
        )
        cl.addWidget(dot)

        name_lbl = QLabel()
        name_lbl.setStyleSheet(
            f"color: {COLORS['text'] if success else COLORS['text_muted']};"
            "font-size: 11px; background: transparent; border: none;"
        )
        metrics = name_lbl.fontMetrics()
        name_lbl.setText(metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, 140))
        name_lbl.setToolTip(name)
        cl.addWidget(name_lbl)

        self._style_chip(chip, active=False, success=success)

        if success:
            chip.mousePressEvent = lambda _e, idx=index: self._load_doc(idx)

        return chip

    def _style_chip(self, chip: QFrame, *, active: bool, success: bool) -> None:
        if active:
            chip.setStyleSheet(
                "QFrame {"
                f"  background: {COLORS['surface_4']};"
                f"  border: 1.5px solid {self._accent};"
                "  border-radius: 8px;"
                "}"
            )
        elif not success:
            chip.setStyleSheet(
                "QFrame {"
                "  background: transparent;"
                f"  border: 1px solid {COLORS['border']};"
                "  border-radius: 8px;"
                "}"
            )
        else:
            chip.setStyleSheet(
                "QFrame {"
                f"  background: {COLORS['surface_3']};"
                f"  border: 1px solid {COLORS['border']};"
                "  border-radius: 8px;"
                "}"
                "QFrame:hover {"
                f"  background: {COLORS['surface_4']};"
                f"  border-color: {COLORS['border_strong']};"
                "}"
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_hsep(self) -> QFrame:
        f = QFrame()
        f.setFixedHeight(1)
        f.setStyleSheet(f"background: {COLORS['border']}; border: none;")
        return f

    def _make_vsep(self) -> QFrame:
        f = QFrame()
        f.setFixedWidth(1)
        f.setStyleSheet(f"background: {COLORS['border']}; border: none;")
        return f

    def _make_tsep(self) -> QFrame:
        """Separador vertical delgado para la toolbar."""
        f = QFrame()
        f.setFixedSize(1, 22)
        f.setStyleSheet(f"background: {COLORS['border_strong']}; border: none;")
        return f

    # ── Document loading ──────────────────────────────────────────────────────

    def _load_doc(self, index: int) -> None:
        if not (0 <= index < len(self._results)):
            return

        result = self._results[index]
        success = getattr(result, "success", False)
        out_path = getattr(result, "output_path", "") or ""

        # Actualizar chips
        for i, chip in enumerate(self._doc_chips):
            r = self._results[i]
            self._style_chip(chip, active=(i == index), success=getattr(r, "success", False))

        self._current_doc_idx = index
        n = len(self._results)
        self._doc_nav_lbl.setText(f"Doc {index + 1} / {n}")
        self._prev_doc_btn.setEnabled(index > 0)
        self._next_doc_btn.setEnabled(index < n - 1)

        self._scroll_chip_visible(index)
        self._close_doc()
        self._current_page = 0
        self._zoom_index = _FIT_ZOOM_IDX
        self._fit_mode = "width"

        self._filename_lbl.setText(Path(out_path).name if out_path else "—")

        if not success or not out_path:
            self._show_canvas_error(getattr(result, "error", "") or "Documento con error")
            return

        try:
            self._current_doc = fitz.open(out_path)
            if self._current_doc.needs_pass:
                pwd = (
                    getattr(result, "user_password", "")
                    or getattr(result, "open_password", "")
                    or getattr(getattr(result, "job", None), "open_password", "")
                )
                if not pwd or not self._current_doc.authenticate(pwd):
                    self._show_canvas_error("El PDF requiere contraseña para abrirse")
                    return
        except Exception as exc:
            self._show_canvas_error(f"No se pudo abrir: {exc}")
            return

        self._load_thumbnails()
        if self._current_doc.page_count > 0:
            self._page_list.blockSignals(True)
            self._page_list.setCurrentRow(0)
            self._page_list.blockSignals(False)
            self._render_page()
        self._sync_controls()

    def _show_canvas_error(self, msg: str) -> None:
        self._close_doc()
        self._page_list.blockSignals(True)
        self._page_list.clear()
        self._page_list.blockSignals(False)
        self._canvas.setPixmap(QPixmap())
        self._canvas.setText(msg)
        self._canvas.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 13px; background: transparent;"
        )
        self._canvas.setFixedSize(500, 140)
        self._sync_controls()

    def _load_thumbnails(self) -> None:
        if self._current_doc is None:
            return
        self._page_list.blockSignals(True)
        try:
            self._page_list.clear()
            for i in range(self._current_doc.page_count):
                dpi = self._thumb_dpi(i)
                pix = self._render_fitz(i, dpi)
                item = QListWidgetItem(QIcon(pix), str(i + 1))
                item.setToolTip(f"Página {i + 1}")
                self._page_list.addItem(item)
        finally:
            self._page_list.blockSignals(False)

    def _close_doc(self) -> None:
        if self._current_doc is not None:
            try:
                self._current_doc.close()
            except Exception:
                pass
            self._current_doc = None

    def _scroll_chip_visible(self, index: int) -> None:
        if 0 <= index < len(self._doc_chips):
            self._strip_scroll.ensureWidgetVisible(self._doc_chips[index])

    # ── Render ────────────────────────────────────────────────────────────────

    def _thumb_dpi(self, page_idx: int) -> float:
        if self._current_doc is None:
            return 12.0
        page = self._current_doc[page_idx]
        long_side = max(1.0, page.rect.width, page.rect.height)
        return max(3.0, min(_THUMB_TARGET_PX * 72.0 / long_side, 30.0))

    def _compute_dpi(self) -> float:
        if self._current_doc is None:
            return 96.0
        if not (0 <= self._current_page < self._current_doc.page_count):
            return 96.0
        page = self._current_doc[self._current_page]
        vp_w = max(200, self._scroll.viewport().width() - 24)
        vp_h = max(200, self._scroll.viewport().height() - 24)
        pw = max(1.0, page.rect.width)
        ph = max(1.0, page.rect.height)
        dpi_w = vp_w / pw * 72.0
        dpi_h = vp_h / ph * 72.0
        base = dpi_w if self._fit_mode == "width" else min(dpi_w, dpi_h)
        min_dpi = max(4.0, base * ZOOM_LEVELS[0])
        max_dpi = min(320.0, _CANVAS_MAX_PX / max(pw, ph) * 72.0)
        return max(min_dpi, min(base * ZOOM_LEVELS[self._zoom_index], max_dpi))

    def _render_fitz(self, page_idx: int, dpi: float) -> QPixmap:
        page = self._current_doc[page_idx]
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pm = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
        return _pil_to_qpixmap(img)

    def _render_page(self) -> None:
        if self._current_doc is None:
            return
        if not (0 <= self._current_page < self._current_doc.page_count):
            return
        dpi = self._compute_dpi()
        pix = self._render_fitz(self._current_page, dpi)
        self._canvas.setStyleSheet("background: transparent;")
        self._canvas.clear()
        self._canvas.setPixmap(pix)
        self._canvas.setFixedSize(pix.size())
        self._zoom_lbl.setText(f"{int(ZOOM_LEVELS[self._zoom_index] * 100)}%")
        self._sync_controls()

    # ── Controls sync ─────────────────────────────────────────────────────────

    def _sync_controls(self) -> None:
        n = self._current_doc.page_count if self._current_doc else 0
        pg = self._current_page

        self._page_spin.blockSignals(True)
        self._page_spin.setRange(1, max(1, n))
        self._page_spin.setValue(pg + 1 if n > 0 else 1)
        self._page_spin.blockSignals(False)
        self._page_spin.setEnabled(n > 1)
        self._page_total_lbl.setText(f"/ {n}" if n > 0 else "/ —")
        self._prev_page_btn.setEnabled(pg > 0)
        self._next_page_btn.setEnabled(n > 1 and pg < n - 1)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate_doc(self, delta: int) -> None:
        target = self._current_doc_idx + delta
        if 0 <= target < len(self._results):
            self._load_doc(target)

    def _prev_page(self) -> None:
        if self._current_doc and self._current_page > 0:
            self._current_page -= 1
            self._page_list.blockSignals(True)
            self._page_list.setCurrentRow(self._current_page)
            self._page_list.blockSignals(False)
            self._render_page()

    def _next_page(self) -> None:
        if self._current_doc and self._current_page < self._current_doc.page_count - 1:
            self._current_page += 1
            self._page_list.blockSignals(True)
            self._page_list.setCurrentRow(self._current_page)
            self._page_list.blockSignals(False)
            self._render_page()

    def _on_page_jump(self) -> None:
        if self._current_doc is None:
            return
        target = max(0, min(self._page_spin.value() - 1, self._current_doc.page_count - 1))
        if target != self._current_page:
            self._current_page = target
            self._page_list.blockSignals(True)
            self._page_list.setCurrentRow(target)
            self._page_list.blockSignals(False)
            self._render_page()

    def _on_thumb_selected(self) -> None:
        if self._current_doc is None:
            return
        row = self._page_list.currentRow()
        if not (0 <= row < self._current_doc.page_count):
            return
        if row == self._current_page:
            return
        self._current_page = row
        self._render_page()

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def _zoom_out(self) -> None:
        self._fit_mode = "manual"
        if self._zoom_index > 0:
            self._zoom_index -= 1
            self._render_page()

    def _zoom_in(self) -> None:
        self._fit_mode = "manual"
        if self._zoom_index < len(ZOOM_LEVELS) - 1:
            self._zoom_index += 1
            self._render_page()

    def _fit_width(self) -> None:
        self._fit_mode = "width"
        self._zoom_index = _FIT_ZOOM_IDX
        self._render_page()

    def _fit_page(self) -> None:
        self._fit_mode = "page"
        self._zoom_index = _FIT_ZOOM_IDX
        self._render_page()

    # ── Sidebar toggle ────────────────────────────────────────────────────────

    def _toggle_sidebar(self) -> None:
        self._sidebar_visible = not self._sidebar_visible
        target_w = _SIDEBAR_W if self._sidebar_visible else 0

        if self._sidebar_anim is not None:
            self._sidebar_anim.stop()

        anim = QPropertyAnimation(self._sidebar_container, b"maximumWidth")
        anim.setDuration(180)
        anim.setStartValue(self._sidebar_container.width())
        anim.setEndValue(target_w)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self._after_sidebar_toggle(target_w))
        self._sidebar_anim = anim
        self._sidebar_sep.setVisible(self._sidebar_visible)
        anim.start()

    def _after_sidebar_toggle(self, target_w: int) -> None:
        if target_w == 0:
            self._sidebar_container.setMaximumWidth(0)
            self._sidebar_container.setFixedWidth(0)
        else:
            self._sidebar_container.setMaximumWidth(_SIDEBAR_W)
            self._sidebar_container.setFixedWidth(_SIDEBAR_W)
        if self._current_doc and self._fit_mode != "manual":
            self._render_page()

    # ── Qt events ─────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 160))
        p.end()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        ctrl = Qt.KeyboardModifier.ControlModifier
        mods = event.modifiers()

        if key == Qt.Key.Key_Escape:
            self.reject()
        elif key == Qt.Key.Key_Left and not (mods & ctrl):
            self._navigate_doc(-1)
        elif key == Qt.Key.Key_Right and not (mods & ctrl):
            self._navigate_doc(1)
        elif key == Qt.Key.Key_PageUp:
            self._prev_page()
        elif key == Qt.Key.Key_PageDown:
            self._next_page()
        elif key == Qt.Key.Key_Minus and (mods & ctrl):
            self._zoom_out()
        elif key == Qt.Key.Key_Equal and (mods & ctrl):
            self._zoom_in()
        elif key == Qt.Key.Key_0 and (mods & ctrl):
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self._fit_page()
            else:
                self._fit_width()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self._zoom_in()
            else:
                self._zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._current_doc and self._fit_mode != "manual":
            self._render_page()

    def closeEvent(self, event) -> None:
        self._close_doc()
        super().closeEvent(event)

    # ── Draggable via toolbar ─────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            toolbar = self.findChild(QFrame, "FullViewToolbar")
            if toolbar and toolbar.underMouse():
                self._drag_pos = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._drag_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)
```

- [ ] **Step 2.2: Verificar sintaxis**

```bash
python -c "
import ast, sys
with open('ui/common/pdf_fullview_dialog.py', encoding='utf-8') as f:
    src = f.read()
ast.parse(src)
print('OK — sin errores de sintaxis')
"
```

Resultado esperado: `OK — sin errores de sintaxis`

- [ ] **Step 2.3: Smoke import test**

```bash
python -c "
import os; os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from PyQt6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication(sys.argv)
from ui.common.pdf_fullview_dialog import PdfFullViewDialog
print('Import OK')
"
```

Resultado esperado: `Import OK`

- [ ] **Step 2.4: Commit**

```bash
git add ui/common/pdf_fullview_dialog.py
git commit -m "feat: add PdfFullViewDialog — immersive PDF full-view modal"
```

---

## Task 3: Integrar botón en `ui/common/pdf_viewer.py`

**Files:**
- Modify: `ui/common/pdf_viewer.py`

- [ ] **Step 3.1: Añadir import de `PdfFullViewDialog`**

En `ui/common/pdf_viewer.py`, localizar el bloque de imports al inicio. Añadir al final del bloque de imports locales (después de `from ui.common.icons import set_button_icon`):

```python
from ui.common.pdf_fullview_dialog import PdfFullViewDialog
```

- [ ] **Step 3.2: Añadir botón "Vista completa" en `title_row`**

En `_build()`, localizar el bloque `title_row` (alrededor de línea 119). Añadir el botón "Vista completa" **entre** `open_file_btn` y `open_btn`:

Encontrar:
```python
        self.open_file_btn = QPushButton("Abrir PDF")
        self.open_file_btn.setProperty("class", "Ghost")
        set_button_icon(self.open_file_btn, "external-link")
        self.open_file_btn.clicked.connect(self._on_open_file)
        self.open_file_btn.setEnabled(False)
        title_row.addWidget(self.open_file_btn)

        self.open_btn = QPushButton("Abrir carpeta")
```

Reemplazar con:
```python
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
```

- [ ] **Step 3.3: Añadir método `_on_fullview` y habilitar el botón**

Al final de `_set_zoom_enabled()`, añadir la línea que habilita `fullview_btn`:

Encontrar el método `_set_zoom_enabled`:
```python
    def _set_zoom_enabled(self, enabled: bool) -> None:
        self.zoom_in_btn.setEnabled(enabled)
        self.zoom_out_btn.setEnabled(enabled)
        self.fit_btn.setEnabled(enabled)
        self.fit_page_btn.setEnabled(enabled)
        self.open_btn.setEnabled(enabled)
        self.open_file_btn.setEnabled(enabled)
        self.save_as_btn.setEnabled(enabled)
        self.save_all_btn.setEnabled(self._has_saveable_results())
        self._update_page_status()
```

Reemplazar con:
```python
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
```

Añadir el método `_on_fullview` justo después de `_on_open_file`:

```python
    def _on_fullview(self) -> None:
        row = self.doc_list.currentRow()
        if row < 0 or not self._results:
            return
        dlg = PdfFullViewDialog(self, results=self._results, current_index=row)
        dlg.exec()
```

- [ ] **Step 3.4: Verificar**

```bash
python -c "
import os; os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from PyQt6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication(sys.argv)
from ui.common.pdf_viewer import GenericPdfViewer
v = GenericPdfViewer()
assert hasattr(v, 'fullview_btn'), 'falta fullview_btn'
assert not v.fullview_btn.isEnabled(), 'debe estar deshabilitado sin resultados'
print('OK')
"
```

Resultado esperado: `OK`

- [ ] **Step 3.5: Commit**

```bash
git add ui/common/pdf_viewer.py
git commit -m "feat(pdf_viewer): add 'Vista completa' button opening PdfFullViewDialog"
```

---

## Task 4: Integrar botón en `ui/results_viewer.py`

**Files:**
- Modify: `ui/results_viewer.py`

- [ ] **Step 4.1: Añadir import**

En `ui/results_viewer.py`, añadir al final del bloque de imports locales:

```python
from ui.common.pdf_fullview_dialog import PdfFullViewDialog
```

- [ ] **Step 4.2: Añadir botón en `title_row`**

Localizar en `_build()` la sección `title_row`. Encontrar:

```python
        self.open_file_btn = QPushButton("Abrir PDF")
        self.open_file_btn.setProperty("class", "Ghost")
        set_button_icon(self.open_file_btn, "external-link")
        self.open_file_btn.clicked.connect(self._on_open_file)
        self.open_file_btn.setEnabled(False)
        title_row.addWidget(self.open_file_btn)

        self.open_btn = QPushButton("Abrir carpeta")
```

Reemplazar con:

```python
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
```

- [ ] **Step 4.3: Habilitar en `_set_actions_enabled` y añadir `_on_fullview`**

Localizar `_set_actions_enabled`:

```python
    def _set_actions_enabled(self, enabled: bool) -> None:
```

Dentro de ese método, añadir `self.fullview_btn.setEnabled(enabled)` junto al resto de botones que se habilitan. Añadir también el método:

```python
    def _on_fullview(self) -> None:
        row = self.doc_list.currentRow()
        if row < 0 or not self._results:
            return
        dlg = PdfFullViewDialog(self, results=self._results, current_index=row)
        dlg.exec()
```

Para hacer esto, primero leer las líneas de `_set_actions_enabled` en `results_viewer.py` y añadir la línea correspondiente.

- [ ] **Step 4.4: Verificar**

```bash
python -c "
import os; os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from PyQt6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication(sys.argv)
from ui.results_viewer import ResultsViewer
v = ResultsViewer()
assert hasattr(v, 'fullview_btn'), 'falta fullview_btn'
assert not v.fullview_btn.isEnabled(), 'debe estar deshabilitado sin resultados'
print('OK')
"
```

Resultado esperado: `OK`

- [ ] **Step 4.5: Commit**

```bash
git add ui/results_viewer.py
git commit -m "feat(results_viewer): add 'Vista completa' button opening PdfFullViewDialog"
```

---

## Task 5: Tests

**Files:**
- Create: `tests/test_pdf_fullview_dialog.py`

- [ ] **Step 5.1: Crear el archivo de tests**

Crear `tests/test_pdf_fullview_dialog.py`:

```python
"""Tests para PdfFullViewDialog."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PyQt6.QtWidgets import QApplication

from ui.common.pdf_fullview_dialog import PdfFullViewDialog, ZOOM_LEVELS


def _make_pdf(path: Path, pages: int = 3) -> Path:
    """Crea un PDF mínimo con N páginas para tests."""
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Página {i + 1}")
    doc.save(str(path))
    doc.close()
    return path


def _ok_result(path: str) -> SimpleNamespace:
    return SimpleNamespace(output_path=path, success=True, error="")


def _err_result() -> SimpleNamespace:
    return SimpleNamespace(output_path="", success=False, error="Fallo simulado")


class TestPdfFullViewDialogSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pdf1 = str(_make_pdf(Path(cls.tmp.name) / "a.pdf", pages=5))
        cls.pdf2 = str(_make_pdf(Path(cls.tmp.name) / "b.pdf", pages=2))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def _make_dlg(self, results=None, idx=0) -> PdfFullViewDialog:
        if results is None:
            results = [_ok_result(self.pdf1)]
        dlg = PdfFullViewDialog(None, results=results, current_index=idx)
        self.app.processEvents()
        return dlg

    # ── Smoke ────────────────────────────────────────────────────────────────

    def test_instantiates_without_error(self) -> None:
        dlg = self._make_dlg()
        self.assertIsNotNone(dlg)
        dlg.close()
        self.app.processEvents()

    def test_has_all_toolbar_controls(self) -> None:
        dlg = self._make_dlg()
        self.app.processEvents()
        self.assertTrue(hasattr(dlg, "_page_spin"))
        self.assertTrue(hasattr(dlg, "_prev_page_btn"))
        self.assertTrue(hasattr(dlg, "_next_page_btn"))
        self.assertTrue(hasattr(dlg, "_prev_doc_btn"))
        self.assertTrue(hasattr(dlg, "_next_doc_btn"))
        self.assertTrue(hasattr(dlg, "_zoom_out_btn"))
        self.assertTrue(hasattr(dlg, "_zoom_in_btn"))
        self.assertTrue(hasattr(dlg, "_toggle_btn"))
        dlg.close()
        self.app.processEvents()

    def test_doc_nav_label_shows_correct_index(self) -> None:
        results = [_ok_result(self.pdf1), _ok_result(self.pdf2)]
        dlg = self._make_dlg(results, idx=0)
        self.app.processEvents()
        self.assertIn("1", dlg._doc_nav_lbl.text())
        self.assertIn("2", dlg._doc_nav_lbl.text())
        dlg.close()
        self.app.processEvents()

    # ── Navigation ───────────────────────────────────────────────────────────

    def test_navigate_doc_forward(self) -> None:
        results = [_ok_result(self.pdf1), _ok_result(self.pdf2)]
        dlg = self._make_dlg(results, idx=0)
        self.app.processEvents()
        self.assertEqual(dlg._current_doc_idx, 0)
        dlg._navigate_doc(1)
        self.app.processEvents()
        self.assertEqual(dlg._current_doc_idx, 1)
        dlg.close()
        self.app.processEvents()

    def test_navigate_doc_backward(self) -> None:
        results = [_ok_result(self.pdf1), _ok_result(self.pdf2)]
        dlg = self._make_dlg(results, idx=1)
        self.app.processEvents()
        self.assertEqual(dlg._current_doc_idx, 1)
        dlg._navigate_doc(-1)
        self.app.processEvents()
        self.assertEqual(dlg._current_doc_idx, 0)
        dlg.close()
        self.app.processEvents()

    def test_navigate_doc_clamps_at_bounds(self) -> None:
        results = [_ok_result(self.pdf1)]
        dlg = self._make_dlg(results, idx=0)
        self.app.processEvents()
        dlg._navigate_doc(-1)   # no debe moverse
        self.assertEqual(dlg._current_doc_idx, 0)
        dlg._navigate_doc(1)    # no debe moverse
        self.assertEqual(dlg._current_doc_idx, 0)
        dlg.close()
        self.app.processEvents()

    def test_prev_doc_btn_disabled_at_first(self) -> None:
        results = [_ok_result(self.pdf1), _ok_result(self.pdf2)]
        dlg = self._make_dlg(results, idx=0)
        self.app.processEvents()
        self.assertFalse(dlg._prev_doc_btn.isEnabled())
        self.assertTrue(dlg._next_doc_btn.isEnabled())
        dlg.close()
        self.app.processEvents()

    def test_next_doc_btn_disabled_at_last(self) -> None:
        results = [_ok_result(self.pdf1), _ok_result(self.pdf2)]
        dlg = self._make_dlg(results, idx=1)
        self.app.processEvents()
        self.assertTrue(dlg._prev_doc_btn.isEnabled())
        self.assertFalse(dlg._next_doc_btn.isEnabled())
        dlg.close()
        self.app.processEvents()

    # ── Page navigation ──────────────────────────────────────────────────────

    def test_page_spin_range_matches_doc_pages(self) -> None:
        dlg = self._make_dlg([_ok_result(self.pdf1)])  # 5 páginas
        self.app.processEvents()
        self.assertEqual(dlg._page_spin.maximum(), 5)
        dlg.close()
        self.app.processEvents()

    def test_prev_page_decrements_current_page(self) -> None:
        dlg = self._make_dlg([_ok_result(self.pdf1)])
        self.app.processEvents()
        # Ir a página 3 primero
        dlg._current_page = 2
        dlg._prev_page()
        self.app.processEvents()
        self.assertEqual(dlg._current_page, 1)
        dlg.close()
        self.app.processEvents()

    def test_next_page_increments_current_page(self) -> None:
        dlg = self._make_dlg([_ok_result(self.pdf1)])
        self.app.processEvents()
        dlg._current_page = 0
        dlg._next_page()
        self.app.processEvents()
        self.assertEqual(dlg._current_page, 1)
        dlg.close()
        self.app.processEvents()

    def test_on_page_jump_clamps(self) -> None:
        dlg = self._make_dlg([_ok_result(self.pdf1)])  # 5 páginas
        self.app.processEvents()
        dlg._page_spin.setValue(999)
        dlg._on_page_jump()
        self.app.processEvents()
        self.assertEqual(dlg._current_page, 4)  # índice 0-based de página 5
        dlg.close()
        self.app.processEvents()

    # ── Zoom ─────────────────────────────────────────────────────────────────

    def test_zoom_in_increments_index(self) -> None:
        dlg = self._make_dlg()
        self.app.processEvents()
        initial = dlg._zoom_index
        dlg._zoom_in()
        self.app.processEvents()
        self.assertEqual(dlg._zoom_index, initial + 1)
        dlg.close()
        self.app.processEvents()

    def test_zoom_out_decrements_index(self) -> None:
        dlg = self._make_dlg()
        self.app.processEvents()
        dlg._zoom_index = 5  # en el medio para tener espacio
        dlg._zoom_out()
        self.app.processEvents()
        self.assertEqual(dlg._zoom_index, 4)
        dlg.close()
        self.app.processEvents()

    def test_zoom_clamps_at_boundaries(self) -> None:
        dlg = self._make_dlg()
        self.app.processEvents()
        dlg._zoom_index = 0
        dlg._zoom_out()
        self.assertEqual(dlg._zoom_index, 0)  # no baja de 0
        dlg._zoom_index = len(ZOOM_LEVELS) - 1
        dlg._zoom_in()
        self.assertEqual(dlg._zoom_index, len(ZOOM_LEVELS) - 1)  # no sube del máximo
        dlg.close()
        self.app.processEvents()

    def test_fit_width_resets_fit_mode(self) -> None:
        dlg = self._make_dlg()
        self.app.processEvents()
        dlg._fit_mode = "manual"
        dlg._fit_width()
        self.app.processEvents()
        self.assertEqual(dlg._fit_mode, "width")
        dlg.close()
        self.app.processEvents()

    # ── Error result ─────────────────────────────────────────────────────────

    def test_error_result_does_not_crash(self) -> None:
        dlg = self._make_dlg([_err_result()])
        self.app.processEvents()
        # No debe haber doc cargado
        self.assertIsNone(dlg._current_doc)
        dlg.close()
        self.app.processEvents()

    def test_mixed_results_loads_ok_doc(self) -> None:
        results = [_err_result(), _ok_result(self.pdf2)]
        dlg = self._make_dlg(results, idx=1)
        self.app.processEvents()
        self.assertIsNotNone(dlg._current_doc)
        dlg.close()
        self.app.processEvents()

    # ── Chips ────────────────────────────────────────────────────────────────

    def test_chips_count_matches_results(self) -> None:
        results = [_ok_result(self.pdf1), _ok_result(self.pdf2), _err_result()]
        dlg = self._make_dlg(results)
        self.app.processEvents()
        self.assertEqual(len(dlg._doc_chips), 3)
        dlg.close()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5.2: Ejecutar tests**

```bash
python -m pytest tests/test_pdf_fullview_dialog.py -v
```

Resultado esperado: todos los tests pasan (verde).

- [ ] **Step 5.3: Ejecutar suite completa para verificar no haber roto nada**

```bash
python -m pytest tests/ -q
```

Resultado esperado: `200+ passed` (igual o más que antes, ningún failure nuevo).

- [ ] **Step 5.4: Commit final**

```bash
git add tests/test_pdf_fullview_dialog.py
git commit -m "test: add PdfFullViewDialog test suite (smoke, navigation, zoom, chips)"
```

---

## Self-review del plan

**Cobertura del spec:**
- ✅ Sección 3 (layout visual): Task 2 — toolbar, sidebar, canvas, strip
- ✅ Sección 4 (API): Task 2, `__init__` signature
- ✅ Sección 5.1 (shell): Task 2, `_setup_window` + `paintEvent`
- ✅ Sección 5.2 (toolbar grupos G1-G6): Task 2, `_build_toolbar`
- ✅ Sección 5.3 (sidebar): Task 2, `_build_sidebar`
- ✅ Sección 5.4 (canvas): Task 2, `_build_canvas`
- ✅ Sección 5.5 (strip chips): Task 2, `_build_doc_strip` + `_make_chip`
- ✅ Sección 6 (render): Task 2, `_render_fitz`, `_compute_dpi`, `_thumb_dpi`
- ✅ Sección 7 (atajos): Task 2, `keyPressEvent` + `wheelEvent`
- ✅ Sección 8 (accent_color): Task 2, `__init__` parámetro + `_style_chip`
- ✅ Sección 9 (error handling): Task 2, `_show_canvas_error`
- ✅ Sección 10 (integración): Tasks 3 y 4
- ✅ Tests: Task 5

**Nombres consistentes en todo el plan:**
- `_load_doc(index)` — igual en Task 2, chips, y tests
- `_navigate_doc(delta)` — igual en toolbar y keyPressEvent
- `_render_page()` — método sin argumentos, usa estado interno
- `_sync_controls()` — llamado desde render y load_doc
- `_make_chip(i, result)` — igual en `_build_doc_strip` y referenciado en tests

**Sin placeholders:** todo el código está completo y listo para copiar.
