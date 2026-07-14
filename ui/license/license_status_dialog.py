"""Diálogo "Ver licencia" — envuelve LicensePanel con el mismo lenguaje
visual que ActivationDialog/ReconnectDialog (spec §1.4). Se abre bajo
demanda desde el menú Opciones de la ventana principal; a diferencia de
los otros diálogos de licencia, no es modal-bloqueante para el arranque,
solo una ventana de información que el usuario cierra cuando quiere.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from core.license_token import LicenseClaims
from ui.common.icons import app_qicon, icon_pixmap
from ui.license.license_panel import LicensePanel
from ui.styles import COLORS


class LicenseStatusDialog(QDialog):
    def __init__(self, claims: LicenseClaims, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_pos = None

        self.setWindowTitle("Licencia de PDFlex")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(420)
        self.setMaximumWidth(520)
        self.setWindowIcon(app_qicon())
        self._build(claims)

    def _build(self, claims: LicenseClaims) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("LicenseStatusShell")
        shell.setStyleSheet(f"""
            QFrame#LicenseStatusShell {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border_strong']};
                border-radius: 12px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(shell)
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 16)
        shell.setGraphicsEffect(shadow)
        outer.addWidget(shell)

        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addWidget(self._build_body(claims))
        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("LicenseStatusHeader")
        header.setStyleSheet(f"""
            QFrame#LicenseStatusHeader {{
                background: {COLORS['surface_2']};
                border-bottom: 1px solid {COLORS['border']};
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }}
        """)
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 15, 14, 15)
        h.setSpacing(13)

        icon_box = QFrame()
        icon_box.setFixedSize(42, 42)
        icon_box.setStyleSheet(f"""
            QFrame {{
                background: rgba(94, 106, 210, 0.16);
                border: 1px solid rgba(94, 106, 210, 0.5);
                border-radius: 9px;
            }}
        """)
        ib = QVBoxLayout(icon_box)
        ib.setContentsMargins(0, 0, 0, 0)
        ib_lbl = QLabel()
        ib_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ib_lbl.setPixmap(icon_pixmap("tool-protector", COLORS["accent"], 22))
        ib_lbl.setStyleSheet("background: transparent;")
        ib.addWidget(ib_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        h.addWidget(icon_box)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        t = QLabel("Licencia de PDFlex")
        t.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 14px; font-weight: 700;"
            "background: transparent;"
        )
        title_col.addWidget(t)
        s = QLabel("Estado de tu activación en este equipo.")
        s.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent;"
        )
        title_col.addWidget(s)
        h.addLayout(title_col, 1)
        return header

    def _build_body(self, claims: LicenseClaims) -> QWidget:
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(20, 18, 20, 14)
        v.setSpacing(10)
        self._panel = LicensePanel(claims)
        self._panel.busy_changed.connect(self._on_panel_busy_changed)
        v.addWidget(self._panel)
        return body

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("LicenseStatusFooter")
        footer.setStyleSheet(f"""
            QFrame#LicenseStatusFooter {{
                background: {COLORS['surface_2']};
                border-top: 1px solid {COLORS['border']};
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
            }}
        """)
        f = QHBoxLayout(footer)
        f.setContentsMargins(18, 12, 18, 12)
        f.setSpacing(8)
        f.addStretch(1)

        self._close_btn = QPushButton("Cerrar")
        self._close_btn.setFixedHeight(34)
        self._close_btn.setMinimumWidth(96)
        self._close_btn.setDefault(True)
        self._close_btn.clicked.connect(self.accept)
        f.addWidget(self._close_btn)
        return footer

    def _on_panel_busy_changed(self, busy: bool) -> None:
        self._close_btn.setEnabled(not busy)

    def done(self, result: int) -> None:
        # Igual que ActivationDialog/ReconnectDialog: no permite cerrar
        # mientras LicensePanel tiene una desactivación en curso.
        if self._panel.has_pending_request():
            return
        super().done(result)

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
