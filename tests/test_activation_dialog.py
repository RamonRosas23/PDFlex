import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame

from ui.license.activation_dialog import ActivationDialog

_app = QApplication.instance() or QApplication([])


def test_dialog_renders_header_body_footer():
    dlg = ActivationDialog()
    try:
        assert dlg.windowTitle() == "Activar PDFlex"
        assert dlg.findChild(QFrame, "ActivationHeader") is not None
        assert dlg.findChild(QFrame, "ActivationFooter") is not None
        assert dlg.activated_token is None
    finally:
        dlg.close()
        _app.processEvents()


def test_activate_button_disabled_for_malformed_key():
    dlg = ActivationDialog()
    try:
        dlg._key_input.setText("not-a-valid-key")
        assert dlg._activate_btn.isEnabled() is False
    finally:
        dlg.close()
        _app.processEvents()


def test_activate_button_enabled_for_well_formed_key():
    dlg = ActivationDialog()
    try:
        dlg._key_input.setText("pdfx-abcde-fghjk-mnpqr-718b")
        assert dlg._key_input.text() == "PDFX-ABCDE-FGHJK-MNPQR-718B"
        assert dlg._activate_btn.isEnabled() is True
    finally:
        dlg.close()
        _app.processEvents()


def test_clicking_activate_calls_start_worker_seam_with_normalized_key():
    dlg = ActivationDialog()
    started = {}
    dlg._start_activation_worker = lambda license_key: started.setdefault("key", license_key)
    dlg._key_input.setText("pdfx-abcde-fghjk-mnpqr-718b")

    try:
        dlg._on_activate_clicked()
        assert started["key"] == "PDFX-ABCDE-FGHJK-MNPQR-718B"
        assert dlg._activate_btn.isEnabled() is False
    finally:
        dlg.close()
        _app.processEvents()


def test_activate_success_saves_token_and_accepts():
    dlg = ActivationDialog()
    try:
        with patch("ui.license.activation_dialog.license_storage.save_token") as save_token:
            dlg._on_activate_success("PLT1.x.y", "Empresa X", None)

        save_token.assert_called_once_with("PLT1.x.y")
        assert dlg.activated_token == "PLT1.x.y"
        assert dlg.result() == 1  # QDialog.Accepted
    finally:
        dlg.close()
        _app.processEvents()


def test_activate_error_shows_mapped_message_and_reenables_button():
    dlg = ActivationDialog()
    try:
        dlg._activate_btn.setEnabled(False)
        dlg._on_activate_error("KEY_NOT_FOUND", "mensaje crudo del servidor")

        assert dlg._activate_btn.isEnabled() is True
        assert "no existe" in dlg._error_label.text()
    finally:
        dlg.close()
        _app.processEvents()


def test_activate_error_falls_back_to_server_message_for_unknown_code():
    dlg = ActivationDialog()
    try:
        dlg._on_activate_error("SOME_UNMAPPED_CODE", "mensaje literal del servidor")
        assert dlg._error_label.text() == "mensaje literal del servidor"
    finally:
        dlg.close()
        _app.processEvents()


def test_start_activation_worker_shows_error_when_fingerprint_fails_instead_of_crashing():
    dlg = ActivationDialog()
    try:
        with patch("ui.license.activation_dialog.compute_fingerprint_or_none", return_value=None):
            dlg._start_activation_worker("PDFX-ABCDE-FGHJK-MNPQR-718B")  # no debe lanzar

        assert dlg._activate_btn.isEnabled() is True
        assert "identificar este equipo" in dlg._error_label.text()
    finally:
        dlg.close()
        _app.processEvents()
