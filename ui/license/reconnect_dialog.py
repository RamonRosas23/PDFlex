"""Diálogo ligero de reconexión — se muestra cuando el token local es
válido pero superó su ventana de confianza offline (spec §1.2 punto 4, §8).
No pide la clave de nuevo: solo necesita volver a contactar al servidor.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from core import license_storage
from core.license_manager import LicenseRevalidateThread, LicenseRevalidateWorker
from core.machine_fingerprint import compute_fingerprint
from ui.common.icons import app_qicon, icon_pixmap
from ui.styles import COLORS

_AUTO_RETRY_MS = 30_000

_ERROR_MESSAGES = {
    "KEY_NOT_FOUND": "Esta licencia ya no existe. Vuelve a activar PDFlex con una clave válida.",
    "KEY_REVOKED": "Esta licencia fue revocada. Contacta a soporte.",
    "KEY_EXPIRED": "Esta licencia venció. Contacta a soporte para renovarla.",
    "FINGERPRINT_MISMATCH": "Esta licencia pertenece a otro equipo.",
    "RATE_LIMITED": "Demasiados intentos. Espera unos minutos.",
    "NETWORK_ERROR": "No se pudo conectar. Verifica tu conexión.",
    "SERVER_ERROR": "Ocurrió un error en el servidor. Inténtalo de nuevo.",
}
_AUTO_RETRY_CODES = {"NETWORK_ERROR", "SERVER_ERROR"}


class ReconnectDialog(QDialog):
    def __init__(self, key_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._key_id = key_id
        self.revalidated_token: str | None = None
        self.gave_up = False
        self._thread: LicenseRevalidateThread | None = None
        self._worker: LicenseRevalidateWorker | None = None
        self._drag_pos = None

        self.setWindowTitle("Reconectar licencia — PDFlex")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(480)
        self.setMaximumWidth(560)
        self.setWindowIcon(app_qicon())
        self._build()
        self._start_revalidation_worker()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("ReconnectShell")
        shell.setStyleSheet(f"""
            QFrame#ReconnectShell {{
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
        root.addWidget(self._build_body())
        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("ReconnectHeader")
        header.setStyleSheet(f"""
            QFrame#ReconnectHeader {{
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
        ib_lbl.setPixmap(icon_pixmap("refresh-cw", COLORS["accent"], 22))
        ib_lbl.setStyleSheet("background: transparent;")
        ib.addWidget(ib_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        h.addWidget(icon_box)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        t = QLabel("Reconectando licencia")
        t.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 14px; font-weight: 700;"
            "background: transparent;"
        )
        title_col.addWidget(t)
        s = QLabel("PDFlex necesita conectarse a internet para continuar.")
        s.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent;"
        )
        title_col.addWidget(s)
        h.addLayout(title_col, 1)
        return header

    def _build_body(self) -> QWidget:
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(20, 18, 20, 14)
        v.setSpacing(10)

        self._status_label = QLabel("Verificando tu licencia…")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 12px; background: transparent;"
        )
        v.addWidget(self._status_label)
        return body

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("ReconnectFooter")
        footer.setStyleSheet(f"""
            QFrame#ReconnectFooter {{
                background: {COLORS['surface_2']};
                border-top: 1px solid {COLORS['border']};
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
            }}
        """)
        f = QHBoxLayout(footer)
        f.setContentsMargins(18, 12, 18, 12)
        f.setSpacing(8)

        self._quit_btn = QPushButton("Salir")
        self._quit_btn.setFixedHeight(34)
        self._quit_btn.clicked.connect(self._on_quit_clicked)
        f.addWidget(self._quit_btn)
        f.addStretch(1)

        self._retry_btn = QPushButton("Reintentar")
        self._retry_btn.setFixedHeight(34)
        self._retry_btn.setDefault(True)
        self._retry_btn.clicked.connect(self._on_retry_clicked)
        f.addWidget(self._retry_btn)
        return footer

    def _on_quit_clicked(self) -> None:
        self.gave_up = True
        self.reject()

    def _on_retry_clicked(self) -> None:
        self._retry_btn.setEnabled(False)
        self._status_label.setText("Verificando tu licencia…")
        self._start_revalidation_worker()

    def _start_revalidation_worker(self) -> None:
        """Punto de extensión: crea y arranca el worker real. Las pruebas
        sobreescriben este método para simular éxito/error sin red real."""
        fingerprint = compute_fingerprint()
        self._worker = LicenseRevalidateWorker(self._key_id, fingerprint)
        self._thread = LicenseRevalidateThread(self._worker)
        self._worker.success.connect(self._on_revalidate_success)
        self._worker.error.connect(self._on_revalidate_error)
        self._worker.success.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_revalidate_success(self, token: str, license_expires_at) -> None:
        license_storage.save_token(token)
        self.revalidated_token = token
        self.accept()

    def _on_revalidate_error(self, error_code: str, message: str) -> None:
        self._retry_btn.setEnabled(True)
        self._status_label.setText(_ERROR_MESSAGES.get(error_code, message))
        if error_code in _AUTO_RETRY_CODES:
            QTimer.singleShot(_AUTO_RETRY_MS, self._auto_retry_if_still_open)

    def _auto_retry_if_still_open(self) -> None:
        if self.isVisible():
            self._on_retry_clicked()

    # ── arrastre de ventana sin bordes ──────────────────────────────────────

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
