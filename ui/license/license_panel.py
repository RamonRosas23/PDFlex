"""Panel de estado de licencia y autoservicio de transferencia
(spec §1.4, §9)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core import license_storage
from core.license_manager import LicenseDeactivateThread, LicenseDeactivateWorker
from core.license_token import LicenseClaims
from core.machine_fingerprint import compute_fingerprint_or_none
from ui.styles import COLORS


class LicensePanel(QWidget):
    def __init__(self, claims: LicenseClaims, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._claims = claims
        self._thread: LicenseDeactivateThread | None = None
        self._worker: LicenseDeactivateWorker | None = None
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        status_row = QHBoxLayout()
        status_label = QLabel("Estado:")
        status_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        status_row.addWidget(status_label)
        value = "Activa" if self._claims.status == "active" else self._claims.status
        self._status_value_label = QLabel(value)
        self._status_value_label.setStyleSheet(
            f"color: {COLORS['success']}; font-size: 12px; font-weight: 600;"
        )
        status_row.addWidget(self._status_value_label)
        status_row.addStretch(1)
        v.addLayout(status_row)

        self._customer_label = QLabel(f"Cliente: {self._claims.customer_name}")
        self._customer_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        self._customer_label.setVisible(bool(self._claims.customer_name))
        v.addWidget(self._customer_label)

        if self._claims.license_expires_at:
            expiry_text = f"Expira: {self._claims.license_expires_at.strftime('%Y-%m-%d')}"
        else:
            expiry_text = "Licencia perpetua"
        self._expiry_label = QLabel(expiry_text)
        self._expiry_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        v.addWidget(self._expiry_label)

        self._deactivate_btn = QPushButton("Desactivar esta licencia")
        self._deactivate_btn.setFixedHeight(34)
        self._deactivate_btn.clicked.connect(self._on_deactivate_clicked)
        v.addWidget(self._deactivate_btn)

    def _on_deactivate_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Desactivar licencia",
            "Esto libera tu licencia de este equipo para poder activarla en otro. "
            "¿Deseas continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._deactivate_btn.setEnabled(False)
        self._deactivate_btn.setText("Desactivando…")
        self._start_deactivation_worker()

    def _start_deactivation_worker(self) -> None:
        """Punto de extensión: crea y arranca el worker real. Las pruebas
        sobreescriben este método para simular éxito/error sin red real."""
        fingerprint = compute_fingerprint_or_none()
        if fingerprint is None:
            self._on_deactivate_error(
                "FINGERPRINT_ERROR", "No se pudo identificar este equipo. Inténtalo de nuevo."
            )
            return
        self._worker = LicenseDeactivateWorker(self._claims.key_id, fingerprint.composite_hash)
        self._thread = LicenseDeactivateThread(self._worker)
        self._worker.success.connect(self._on_deactivate_success)
        self._worker.error.connect(self._on_deactivate_error)
        self._worker.success.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_deactivate_success(self, transfers_remaining: int) -> None:
        license_storage.clear_token()
        QMessageBox.information(
            self,
            "Licencia desactivada",
            f"Este equipo quedó liberado. Transferencias restantes este trimestre: {transfers_remaining}.",
        )
        self._deactivate_btn.setText("Licencia desactivada")

    def _on_deactivate_error(self, error_code: str, message: str) -> None:
        self._deactivate_btn.setEnabled(True)
        self._deactivate_btn.setText("Desactivar esta licencia")
        QMessageBox.warning(self, "No se pudo desactivar", message)
