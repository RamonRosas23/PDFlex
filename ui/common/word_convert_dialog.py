"""Custom Word -> PDF conversion progress dialog."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ui.common.icons import icon_pixmap, set_button_icon
from ui.styles import COLORS


_SPINNER_FRAMES = 12

_ST_PENDING = "pending"
_ST_OPENING = "opening"
_ST_SAVING = "saving"
_ST_DONE = "done"
_ST_ERROR = "error"


class _FileRow(QFrame):
    """A single file row with state, spinner and compact metadata."""

    def __init__(self, filename: str, index: int, total: int, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("WordConvFileRow")
        self._state = _ST_PENDING
        self._spinner_idx = 0

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 9, 12, 9)
        root.setSpacing(11)

        self._icon_lbl = QLabel()
        self._icon_lbl.setFixedSize(22, 22)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet("background: transparent;")
        root.addWidget(self._icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self._name_lbl = QLabel(filename)
        self._name_lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 13px; font-weight: 500; "
            "background: transparent;"
        )
        self._name_lbl.setMinimumWidth(0)
        text_col.addWidget(self._name_lbl)

        self._meta_lbl = QLabel(f"Archivo {index} de {total}")
        self._meta_lbl.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 11px; background: transparent;"
        )
        text_col.addWidget(self._meta_lbl)
        root.addLayout(text_col, 1)

        self._state_lbl = QLabel("Pendiente")
        self._state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_lbl.setFixedWidth(84)
        root.addWidget(self._state_lbl)

        self._apply_state_style()

    def set_state(self, state: str, spinner_idx: int = 0) -> None:
        self._state = state
        self._spinner_idx = spinner_idx
        self._apply_state_style()

    def _apply_state_style(self) -> None:
        if self._state == _ST_PENDING:
            icon_name, icon_color = "dot", COLORS["text_dim"]
            state_text, state_color = "Pendiente", COLORS["text_dim"]
            bg = "transparent"
            border = COLORS["border"]
        elif self._state == _ST_OPENING:
            icon_name, icon_color = "loader", COLORS["accent"]
            state_text, state_color = "Abriendo", COLORS["accent"]
            bg = "rgba(94, 106, 210, 0.10)"
            border = "rgba(94, 106, 210, 0.32)"
        elif self._state == _ST_SAVING:
            icon_name, icon_color = "loader", COLORS["accent"]
            state_text, state_color = "Guardando", COLORS["accent"]
            bg = "rgba(94, 106, 210, 0.10)"
            border = "rgba(94, 106, 210, 0.32)"
        elif self._state == _ST_DONE:
            icon_name, icon_color = "check", COLORS["success"]
            state_text, state_color = "Listo", COLORS["success"]
            bg = "rgba(59, 211, 124, 0.08)"
            border = "rgba(59, 211, 124, 0.26)"
        else:
            icon_name, icon_color = "x", COLORS["danger"]
            state_text, state_color = "Error", COLORS["danger"]
            bg = "rgba(229, 72, 77, 0.08)"
            border = "rgba(229, 72, 77, 0.28)"

        rotate = self._spinner_idx * 30 if icon_name == "loader" else 0
        self._icon_lbl.setPixmap(icon_pixmap(icon_name, icon_color, 17, rotate))
        self._state_lbl.setText(state_text)
        self._state_lbl.setStyleSheet(f"""
            QLabel {{
                color: {state_color};
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 10px;
                padding: 3px 8px;
                font-size: 11px;
                font-weight: 600;
            }}
        """)
        self.setStyleSheet(f"""
            QFrame#WordConvFileRow {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)


class WordConvertDialog(QDialog):
    """Modal conversion progress for .doc/.docx files."""

    def __init__(self, parent: QWidget | None, paths: List[str]) -> None:
        super().__init__(parent)
        self._paths = paths
        self._n = len(paths)
        self._spinner_frame = 0
        self._active_row = -1
        self._drag_pos: Optional[QPoint] = None

        self.setWindowTitle("Convirtiendo Word a PDF")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setMinimumWidth(520)
        self.setMaximumWidth(620)
        self.setMinimumHeight(260)
        self.setMaximumHeight(620)

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick_spinner)
        self._timer.start()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("WordConvDialogShell")
        shell.setStyleSheet(f"""
            QFrame#WordConvDialogShell {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border_strong']};
                border-radius: 10px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(shell)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(0, 10)
        shell.setGraphicsEffect(shadow)
        outer.addWidget(shell)

        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("WordConvHeader")
        header.setStyleSheet(f"""
            QFrame#WordConvHeader {{
                background-color: {COLORS['surface_2']};
                border-bottom: 1px solid {COLORS['border']};
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }}
        """)
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 15, 14, 15)
        h.setSpacing(14)

        icon_box = QFrame()
        icon_box.setFixedSize(42, 42)
        icon_box.setStyleSheet("""
            QFrame {
                background-color: rgba(28, 94, 168, 0.22);
                border: 1px solid rgba(76, 201, 240, 0.36);
                border-radius: 9px;
            }
        """)
        icon_layout = QVBoxLayout(icon_box)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setPixmap(icon_pixmap("file-output", "#4CC9F0", 22))
        icon_layout.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        h.addWidget(icon_box)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_lbl = QLabel("Convirtiendo Word a PDF")
        title_lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 15px; font-weight: 700; "
            "background: transparent;"
        )
        subtitle_lbl = QLabel(
            f"{self._n} archivo{'s' if self._n != 1 else ''} · proceso local con Microsoft Word"
        )
        subtitle_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent;"
        )
        title_col.addWidget(title_lbl)
        title_col.addWidget(subtitle_lbl)
        h.addLayout(title_col, 1)

        self._close_top_btn = QPushButton()
        self._close_top_btn.setProperty("class", "IconBtn")
        self._close_top_btn.setFixedSize(28, 28)
        self._close_top_btn.setToolTip("Disponible al terminar")
        set_button_icon(self._close_top_btn, "x", size=14, icon_only=True)
        self._close_top_btn.setEnabled(False)
        self._close_top_btn.clicked.connect(self.accept)
        h.addWidget(self._close_top_btn)
        root.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(18, 16, 18, 14)
        body.setSpacing(12)

        self._headline_lbl = QLabel("Preparando conversión...")
        self._headline_lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 13px; font-weight: 600; "
            "background: transparent;"
        )
        body.addWidget(self._headline_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 12px;
                margin: 8px 3px 8px 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS['scroll_handle']};
                min-height: 28px;
                border-radius: 3px;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; background: none; }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{ background: none; }}
        """)

        list_host = QWidget()
        list_host.setStyleSheet(f"background: {COLORS['surface']};")
        list_layout = QVBoxLayout(list_host)
        list_layout.setContentsMargins(8, 8, 8, 8)
        list_layout.setSpacing(6)

        self._rows: List[_FileRow] = []
        for index, path in enumerate(self._paths, start=1):
            row = _FileRow(Path(path).name, index, self._n)
            self._rows.append(row)
            list_layout.addWidget(row)
        list_layout.addStretch(1)
        scroll.setWidget(list_host)
        body.addWidget(scroll, 1)
        root.addLayout(body, 1)

        footer = QFrame()
        footer.setObjectName("WordConvFooter")
        footer.setStyleSheet(f"""
            QFrame#WordConvFooter {{
                background-color: {COLORS['surface_2']};
                border-top: 1px solid {COLORS['border']};
                border-bottom-left-radius: 10px;
                border-bottom-right-radius: 10px;
            }}
        """)
        f = QVBoxLayout(footer)
        f.setContentsMargins(18, 14, 18, 14)
        f.setSpacing(10)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, max(1, self._n * 2))
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(6)
        self._set_progress_color(COLORS["accent"])
        f.addWidget(self._progress_bar)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self._msg_lbl = QLabel("Esperando a Microsoft Word...")
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 11px; background: transparent;"
        )
        bottom.addWidget(self._msg_lbl, 1)

        self._close_btn = QPushButton("Cerrar")
        self._close_btn.setFixedSize(112, 34)
        self._close_btn.setEnabled(False)
        self._close_btn.setStyleSheet(self._close_button_style(enabled=False))
        self._close_btn.clicked.connect(self.accept)
        bottom.addWidget(self._close_btn)
        f.addLayout(bottom)
        root.addWidget(footer)

    def on_progress(self, current: int, total: int, message: str) -> None:
        self._progress_bar.setMaximum(max(1, total))
        self._progress_bar.setValue(min(current, max(1, total)))
        self._msg_lbl.setText(message)
        self._headline_lbl.setText("Convirtiendo documentos...")

        if total <= 0:
            return
        file_idx = min(current // 2, max(0, self._n - 1))
        is_saving = current % 2 == 1

        for i in range(file_idx):
            if self._rows[i]._state not in (_ST_DONE, _ST_ERROR):
                self._rows[i].set_state(_ST_DONE)

        if 0 <= file_idx < len(self._rows):
            self._active_row = file_idx
            self._rows[file_idx].set_state(
                _ST_SAVING if is_saving else _ST_OPENING,
                self._spinner_frame,
            )

    def on_finished(self, results: list) -> None:
        self._timer.stop()
        self._set_progress_color(COLORS["success"])
        self._progress_bar.setValue(self._progress_bar.maximum())
        for row in self._rows:
            row.set_state(_ST_DONE)
        n = len(results)
        self._headline_lbl.setText("Conversión completa")
        self._msg_lbl.setText(
            f"{n} archivo{'s' if n != 1 else ''} convertido{'s' if n != 1 else ''} correctamente."
        )
        self._msg_lbl.setStyleSheet(
            f"color: {COLORS['success']}; font-size: 11px; background: transparent;"
        )
        self._enable_close()

    def on_error(self, msg: str) -> None:
        self._timer.stop()
        self._set_progress_color(COLORS["danger"])
        if 0 <= self._active_row < len(self._rows):
            self._rows[self._active_row].set_state(_ST_ERROR)
        self._headline_lbl.setText("No se pudo convertir")
        self._msg_lbl.setText(msg)
        self._msg_lbl.setStyleSheet(
            f"color: {COLORS['danger']}; font-size: 11px; background: transparent;"
        )
        self._enable_close()

    def _enable_close(self) -> None:
        self._close_btn.setEnabled(True)
        self._close_btn.setStyleSheet(self._close_button_style(enabled=True))
        self._close_top_btn.setEnabled(True)
        self._close_top_btn.setToolTip("Cerrar")

    def _set_progress_color(self, color: str) -> None:
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLORS['border']};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 3px;
            }}
        """)

    def _close_button_style(self, *, enabled: bool) -> str:
        if enabled:
            return f"""
                QPushButton {{
                    background-color: {COLORS['accent']};
                    color: white;
                    border: 1px solid {COLORS['accent']};
                    border-radius: 7px;
                    font-size: 12px;
                    font-weight: 600;
                }}
                QPushButton:hover {{ background-color: {COLORS['accent_hover']}; }}
                QPushButton:pressed {{ background-color: {COLORS['accent_press']}; }}
            """
        return f"""
            QPushButton {{
                background-color: {COLORS['surface_3']};
                color: {COLORS['text_dim']};
                border: 1px solid {COLORS['border']};
                border-radius: 7px;
                font-size: 12px;
                font-weight: 500;
            }}
        """

    def _tick_spinner(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % _SPINNER_FRAMES
        if 0 <= self._active_row < len(self._rows):
            row = self._rows[self._active_row]
            if row._state in (_ST_OPENING, _ST_SAVING):
                row.set_state(row._state, self._spinner_frame)

    def reject(self) -> None:
        if self._close_btn.isEnabled():
            super().reject()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)
