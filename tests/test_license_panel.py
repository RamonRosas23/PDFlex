import os
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from core.license_token import LicenseClaims
from ui.license.license_panel import LicensePanel

_app = QApplication.instance() or QApplication([])


def _claims(**overrides) -> LicenseClaims:
    base = dict(
        key_id="key-abc",
        fingerprint="fp",
        issued_at=datetime.now(timezone.utc),
        valid_until=datetime.now(timezone.utc),
        license_expires_at=None,
        status="active",
        customer_name="Empresa de Prueba",
        app="pdflex",
        seats_allowed=1,
    )
    base.update(overrides)
    return LicenseClaims(**base)


def test_license_panel_shows_active_status_and_customer():
    panel = LicensePanel(_claims(customer_name="Empresa de Prueba"))
    try:
        assert panel._status_value_label.text() == "Activa"
        assert panel._customer_label.text() == "Cliente: Empresa de Prueba"
        assert panel._expiry_label.text() == "Licencia perpetua"
    finally:
        panel.deleteLater()
        _app.processEvents()


def test_license_panel_shows_expiry_date_for_time_limited_license():
    expires = datetime(2026, 12, 31, tzinfo=timezone.utc)
    panel = LicensePanel(_claims(license_expires_at=expires))
    try:
        assert panel._expiry_label.text() == "Expira: 2026-12-31"
    finally:
        panel.deleteLater()
        _app.processEvents()


def test_deactivate_button_confirms_then_calls_worker_starter():
    panel = LicensePanel(_claims())
    started = {}
    panel._start_deactivation_worker = lambda: started.setdefault("called", True)

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        panel._on_deactivate_clicked()

    try:
        assert started.get("called") is True
        assert panel._deactivate_btn.isEnabled() is False
    finally:
        panel.deleteLater()
        _app.processEvents()


def test_deactivate_button_does_nothing_if_user_cancels_confirmation():
    panel = LicensePanel(_claims())
    started = {}
    panel._start_deactivation_worker = lambda: started.setdefault("called", True)

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
        panel._on_deactivate_clicked()

    try:
        assert "called" not in started
        assert panel._deactivate_btn.isEnabled() is True
    finally:
        panel.deleteLater()
        _app.processEvents()


def test_on_deactivate_success_clears_token_and_updates_button():
    panel = LicensePanel(_claims())

    with patch("core.license_storage.clear_token") as clear_token, \
         patch.object(QMessageBox, "information"):
        panel._on_deactivate_success(2)

    try:
        clear_token.assert_called_once()
        assert panel._deactivate_btn.text() == "Licencia desactivada"
    finally:
        panel.deleteLater()
        _app.processEvents()


def test_on_deactivate_error_reenables_button_and_shows_warning():
    panel = LicensePanel(_claims())
    panel._deactivate_btn.setEnabled(False)

    with patch.object(QMessageBox, "warning") as warning:
        panel._on_deactivate_error("TRANSFER_LIMIT_REACHED", "Demasiadas transferencias recientes.")

    try:
        assert panel._deactivate_btn.isEnabled() is True
        warning.assert_called_once()
    finally:
        panel.deleteLater()
        _app.processEvents()


def test_start_deactivation_worker_shows_error_when_fingerprint_fails_instead_of_crashing():
    panel = LicensePanel(_claims())
    panel._deactivate_btn.setEnabled(False)  # simula el estado tras un clic real

    with patch("ui.license.license_panel.compute_fingerprint_or_none", return_value=None), \
         patch.object(QMessageBox, "warning") as warning:
        panel._start_deactivation_worker()  # no debe lanzar

    try:
        assert panel._deactivate_btn.isEnabled() is True
        warning.assert_called_once()
    finally:
        panel.deleteLater()
        _app.processEvents()
