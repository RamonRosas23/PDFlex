import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame

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
