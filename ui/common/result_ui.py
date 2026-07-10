"""Small UI helpers for result viewers."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ui.common.icons import icon
from ui.styles import COLORS


class ResultsStatBar(QWidget):
    """Barra de estadísticas animadas para la etapa de resultados.

    Muestra 2-4 bloques (valor grande + etiqueta pequeña) separados por
    divisores verticales.  Los valores enteros se animan con count_up.

    Uso:
        bar = ResultsStatBar()
        bar.set_stats([
            {"value": 5,     "label": "archivos",  "color": COLORS["text"]},
            {"value": 5,     "label": "correctos",  "color": COLORS["success"]},
            {"value": 0,     "label": "errores",    "color": COLORS["danger"]},
        ])
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._value_labels: list[QLabel] = []
        self._pending_int_values: list[int | None] = []
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setStyleSheet(
            f"background: {COLORS['surface_2']};"
            f"border: 1px solid {COLORS['border']};"
            "border-radius: 8px;"
        )
        self.setVisible(False)

    # ── API ───────────────────────────────────────────────────────────────

    def set_stats(self, stats: list[dict]) -> None:
        """Reconstruye la barra con la lista de stats dada.

        Cada dict puede tener:
            value  : int o str — el valor a mostrar (int → animable)
            label  : str       — etiqueta bajo el valor (se convierte a MAYÚSCULAS)
            color  : str       — color CSS del valor (default: COLORS["text"])
        """
        # Limpiar existentes
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._value_labels.clear()
        self._pending_int_values.clear()

        for i, stat in enumerate(stats):
            if i > 0:
                sep = QFrame()
                sep.setFixedWidth(1)
                sep.setMinimumHeight(32)
                sep.setStyleSheet(f"background: {COLORS['border']}; border: none;")
                self._layout.addWidget(sep)

            color = stat.get("color", COLORS["text"])
            raw_val = stat.get("value", "–")
            display_val = str(raw_val)
            int_val = raw_val if isinstance(raw_val, int) else None

            block = QWidget()
            block.setStyleSheet("background: transparent;")
            bv = QVBoxLayout(block)
            bv.setContentsMargins(14, 8, 14, 8)
            bv.setSpacing(2)
            bv.setAlignment(Qt.AlignmentFlag.AlignCenter)

            val_lbl = QLabel(display_val)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            font_sz = "17px" if int_val is not None else "13px"
            val_lbl.setStyleSheet(
                f"color: {color}; font-size: {font_sz}; font-weight: 700; "
                "letter-spacing: -0.4px; background: transparent; border: none;"
            )

            label_lbl = QLabel(stat.get("label", "").upper())
            label_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label_lbl.setStyleSheet(
                "color: #606470; font-size: 9px; font-weight: 700; "
                "letter-spacing: 0.9px; background: transparent; border: none;"
            )

            bv.addWidget(val_lbl)
            bv.addWidget(label_lbl)
            self._layout.addWidget(block, 1)

            self._value_labels.append(val_lbl)
            self._pending_int_values.append(int_val)

        self.setVisible(bool(stats))

    def animate(self) -> None:
        """Dispara animación count_up en todos los valores enteros."""
        try:
            from ui.common.animations import AnimationHelper
            for lbl, val in zip(self._value_labels, self._pending_int_values):
                if val is not None:
                    AnimationHelper.count_up(lbl, val, duration=500)
        except Exception:
            pass


class ElidedLabel(QLabel):
    """Label that keeps the full text in a tooltip and elides visually."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__("", parent)
        self._full_text = ""
        self._elide_mode = Qt.TextElideMode.ElideMiddle
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        super().setText(text)
        self.setText(text)

    def setText(self, text: str) -> None:  # type: ignore[override]
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._refresh()

    def text(self) -> str:  # type: ignore[override]
        return self._full_text

    def sizeHint(self) -> QSize:  # type: ignore[override]
        hint = super().sizeHint()
        hint.setWidth(120)
        return hint

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        hint = super().minimumSizeHint()
        hint.setWidth(24)
        return hint

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if not self._full_text:
            super().setText("")
            return
        width = max(24, self.width() - 4)
        metrics = self.fontMetrics()
        super().setText(metrics.elidedText(self._full_text, self._elide_mode, width))


def elide_middle_text(text: str, max_chars: int = 72) -> str:
    """Return a width-independent middle-elided string for item rows/HTML."""
    value = text or ""
    if len(value) <= max_chars:
        return value
    if max_chars <= 3:
        return value[:max_chars]
    left = max(1, (max_chars - 3) // 2)
    right = max(1, max_chars - 3 - left)
    return f"{value[:left]}...{value[-right:]}"


def configure_file_list(widget: QListWidget, *, word_wrap: bool = False) -> None:
    """Keep file rows clipped, scrollable vertically, and stable with long names."""
    widget.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    widget.setWordWrap(word_wrap)
    widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    widget.setHorizontalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
    widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)


def configure_result_list(widget: QListWidget) -> None:
    """Use predictable clipping behavior for result lists."""
    widget.setObjectName("ResultList")
    widget.setSpacing(2)
    configure_file_list(widget, word_wrap=True)


def format_file_size(path: str | Path) -> str:
    """Return a compact, human-readable file size for existing paths."""
    try:
        size = Path(path).stat().st_size
    except (OSError, TypeError, ValueError):
        return ""
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{int(value)} B"
    if value < 10:
        return f"{value:.1f} {unit}"
    return f"{value:.0f} {unit}"


def make_result_list_item(
    output_path: str,
    *,
    success: bool,
    error: str = "",
    fallback_name: str = "(error)",
    prefix: str = "",
) -> QListWidgetItem:
    """Create a consistent two-line row for generated files."""
    out = output_path or ""
    name = Path(out).name if out else fallback_name
    size = format_file_size(out) if out else ""
    exists = bool(size)

    if success and exists:
        status = "Listo"
        color = COLORS["success"]
        item_icon = icon("check", color, 15)
    elif success:
        status = "No encontrado"
        color = COLORS["warning"]
        item_icon = icon("warning", color, 15)
    else:
        status = "Error"
        color = COLORS["danger"]
        item_icon = icon("warning", color, 15)

    detail_parts = [status]
    if size:
        detail_parts.append(size)
    elif error:
        detail_parts.append(error)

    item = QListWidgetItem(f"{prefix}{name}\n{prefix}{' · '.join(detail_parts)}")
    item.setIcon(item_icon)
    item.setToolTip(out or error or name)
    item.setSizeHint(QSize(200, 46))
    if not success or not exists:
        item.setForeground(QBrush(QColor(color)))
    return item
