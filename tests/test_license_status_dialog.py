import os
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QFrame

from core.license_token import LicenseClaims
from ui.license.license_status_dialog import LicenseStatusDialog

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


def test_dialog_renders_header_body_footer_and_embeds_license_panel():
    dlg = LicenseStatusDialog(_claims())
    try:
        assert dlg.windowTitle() == "Licencia de PDFlex"
        assert dlg.findChild(QFrame, "LicenseStatusHeader") is not None
        assert dlg.findChild(QFrame, "LicenseStatusFooter") is not None
        assert dlg._panel._status_value_label.text() == "Activa"
        assert dlg._panel._customer_label.text() == "Cliente: Empresa de Prueba"
    finally:
        dlg.close()
        _app.processEvents()


def test_close_button_accepts_dialog():
    dlg = LicenseStatusDialog(_claims())
    try:
        dlg.accept()
        assert dlg.result() == 1  # QDialog.Accepted
    finally:
        dlg.close()
        _app.processEvents()


def test_close_button_disabled_while_panel_has_pending_deactivation():
    dlg = LicenseStatusDialog(_claims())
    try:
        dlg._panel.busy_changed.emit(True)
        assert dlg._close_btn.isEnabled() is False

        dlg._panel.busy_changed.emit(False)
        assert dlg._close_btn.isEnabled() is True
    finally:
        dlg.close()
        _app.processEvents()


def test_dialog_ignores_close_while_panel_has_pending_deactivation():
    # Reproduce el crash reportado: cerrar "Ver licencia" mientras
    # LicensePanel tenía una desactivación en curso destruía el QThread de
    # fondo sin que nada esperara su terminación (access violation en
    # notify()).
    dlg = LicenseStatusDialog(_claims())
    try:
        dlg._panel._request_in_flight = True
        with patch.object(QDialog, "done") as base_done:
            dlg.accept()
        base_done.assert_not_called()

        dlg._panel._request_in_flight = False
        with patch.object(QDialog, "done") as base_done:
            dlg.accept()
        base_done.assert_called_once()
    finally:
        dlg.close()
        _app.processEvents()
