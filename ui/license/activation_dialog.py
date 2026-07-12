"""Diálogo modal de activación de licencia — primer arranque sin licencia
válida (spec §1.1).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from core import license_storage
from core.license_key_format import is_valid_key_format, normalize_key
from core.license_manager import LicenseActivateThread, LicenseActivateWorker
from core.machine_fingerprint import compute_fingerprint
from ui.common.icons import app_qicon, icon_pixmap
from ui.styles import COLORS

_ERROR_MESSAGES = {
    "MALFORMED_KEY": "El formato de la clave no es válido.",
    "KEY_NOT_FOUND": "Esta clave no existe. Verifica que la copiaste completa.",
    "ALREADY_ACTIVATED_ELSEWHERE": "Esta clave ya está activada en otro equipo.",
    "KEY_REVOKED": "Esta clave fue revocada. Contacta a soporte.",
    "KEY_EXPIRED": "Esta clave venció. Contacta a soporte para renovarla.",
    "RATE_LIMITED": "Demasiados intentos. Espera unos minutos.",
    "NETWORK_ERROR": "No se pudo conectar. Verifica tu conexión e inténtalo de nuevo.",
    "SERVER_ERROR": "Ocurrió un error en el servidor. Inténtalo de nuevo.",
}


class ActivationDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.activated_token: str | None = None
        self._thread: LicenseActivateThread | None = None
        self._worker: LicenseActivateWorker | None = None
        self._drag_pos = None

        self.setWindowTitle("Activar PDFlex")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(480)
        self.setMaximumWidth(560)
        self.setWindowIcon(app_qicon())
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("ActivationShell")
        shell.setStyleSheet(f"""
            QFrame#ActivationShell {{
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
        header.setObjectName("ActivationHeader")
        header.setStyleSheet(f"""
            QFrame#ActivationHeader {{
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
        t = QLabel("Activar PDFlex")
        t.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 14px; font-weight: 700;"
            "background: transparent;"
        )
        title_col.addWidget(t)
        s = QLabel("Introduce tu clave de licencia para continuar.")
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

        label = QLabel("CLAVE DE LICENCIA")
        label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px; font-weight: 700;"
            "letter-spacing: 0.8px; background: transparent;"
        )
        v.addWidget(label)

        self._key_input = QLineEdit()
        self._key_input.setPlaceholderText("PDFX-XXXXX-XXXXX-XXXXX-CCCC")
        self._key_input.setMinimumHeight(40)
        self._key_input.textChanged.connect(self._on_key_text_changed)
        v.addWidget(self._key_input)

        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(
            f"color: {COLORS['danger']}; font-size: 11px; background: transparent;"
        )
        self._error_label.setVisible(False)
        v.addWidget(self._error_label)

        contact = QLabel("¿No tienes una clave? Contacta a GRUPO OCMX para obtener una.")
        contact.setWordWrap(True)
        contact.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px; background: transparent;"
        )
        v.addWidget(contact)
        return body

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("ActivationFooter")
        footer.setStyleSheet(f"""
            QFrame#ActivationFooter {{
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

        self._activate_btn = QPushButton("Activar")
        self._activate_btn.setFixedHeight(34)
        self._activate_btn.setMinimumWidth(112)
        self._activate_btn.setEnabled(False)
        self._activate_btn.setDefault(True)
        self._activate_btn.clicked.connect(self._on_activate_clicked)
        f.addWidget(self._activate_btn)
        return footer

    # ── validación local ────────────────────────────────────────────────────

    def _on_key_text_changed(self, text: str) -> None:
        normalized = normalize_key(text)
        if normalized != text:
            cursor = self._key_input.cursorPosition()
            self._key_input.blockSignals(True)
            self._key_input.setText(normalized)
            self._key_input.setCursorPosition(cursor)
            self._key_input.blockSignals(False)

        valid = is_valid_key_format(normalized) if normalized else False
        self._activate_btn.setEnabled(valid)
        looks_complete = len(normalized.replace("-", "")) >= 19
        if normalized and not valid and looks_complete:
            self._show_error("La clave no es válida. Revisa que la copiaste completa.")
        else:
            self._clear_error()

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    def _clear_error(self) -> None:
        self._error_label.setVisible(False)

    # ── activación ───────────────────────────────────────────────────────────

    def _on_activate_clicked(self) -> None:
        license_key = normalize_key(self._key_input.text())
        if not is_valid_key_format(license_key):
            self._show_error("La clave no es válida. Revisa que la copiaste completa.")
            return

        self._clear_error()
        self._activate_btn.setEnabled(False)
        self._activate_btn.setText("Activando…")
        self._start_activation_worker(license_key)

    def _start_activation_worker(self, license_key: str) -> None:
        """Punto de extensión: crea y arranca el worker real. Las pruebas
        sobreescriben este método para simular éxito/error sin red real."""
        fingerprint = compute_fingerprint()
        self._worker = LicenseActivateWorker(
            license_key, fingerprint, _machine_name(), _os_version_string()
        )
        self._thread = LicenseActivateThread(self._worker)
        self._worker.success.connect(self._on_activate_success)
        self._worker.error.connect(self._on_activate_error)
        self._worker.success.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_activate_success(self, token: str, customer_name: str, license_expires_at) -> None:
        license_storage.save_token(token)
        self.activated_token = token
        self.accept()

    def _on_activate_error(self, error_code: str, message: str) -> None:
        self._activate_btn.setEnabled(True)
        self._activate_btn.setText("Activar")
        self._show_error(_ERROR_MESSAGES.get(error_code, message))

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


def _machine_name() -> str:
    import socket

    return socket.gethostname()


def _os_version_string() -> str:
    import platform

    return platform.platform()
