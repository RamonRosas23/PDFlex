import os
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QFrame

from ui.license.reconnect_dialog import ReconnectDialog

_app = QApplication.instance() or QApplication([])


def test_dialog_renders_and_starts_a_revalidation_attempt_immediately():
    started = {}
    with patch.object(ReconnectDialog, "_start_revalidation_worker", lambda self: started.setdefault("called", True)):
        dlg = ReconnectDialog("key-abc")
    try:
        assert started.get("called") is True
        assert dlg.findChild(QFrame, "ReconnectHeader") is not None
        assert dlg.findChild(QFrame, "ReconnectFooter") is not None
        assert dlg.revalidated_token is None
        assert dlg.gave_up is False
    finally:
        dlg.close()
        _app.processEvents()


def test_revalidate_success_saves_token_and_accepts():
    with patch.object(ReconnectDialog, "_start_revalidation_worker", lambda self: None):
        dlg = ReconnectDialog("key-abc")
    try:
        with patch("ui.license.reconnect_dialog.license_storage.save_token") as save_token:
            dlg._on_revalidate_success("PLT1.fresh.token", None)

        save_token.assert_called_once_with("PLT1.fresh.token")
        assert dlg.revalidated_token == "PLT1.fresh.token"
        assert dlg.result() == 1  # QDialog.Accepted
    finally:
        dlg.close()
        _app.processEvents()


def test_revalidate_error_shows_message_and_reenables_retry():
    with patch.object(ReconnectDialog, "_start_revalidation_worker", lambda self: None):
        dlg = ReconnectDialog("key-abc")
    try:
        dlg._retry_btn.setEnabled(False)
        with patch("ui.license.reconnect_dialog.license_storage.clear_token") as clear_token:
            dlg._on_revalidate_error("KEY_REVOKED", "mensaje crudo")

        assert dlg._retry_btn.isEnabled() is True
        assert "revocada" in dlg._status_label.text()
        clear_token.assert_called_once()
    finally:
        dlg.close()
        _app.processEvents()


def test_network_error_schedules_auto_retry():
    with patch.object(ReconnectDialog, "_start_revalidation_worker", lambda self: None):
        dlg = ReconnectDialog("key-abc")
    try:
        with patch("ui.license.reconnect_dialog.QTimer.singleShot") as timer_mock:
            dlg._on_revalidate_error("NETWORK_ERROR", "No se pudo conectar.")
        timer_mock.assert_called_once()
    finally:
        dlg.close()
        _app.processEvents()


def test_key_revoked_does_not_schedule_auto_retry():
    with patch.object(ReconnectDialog, "_start_revalidation_worker", lambda self: None):
        dlg = ReconnectDialog("key-abc")
    try:
        with patch("ui.license.reconnect_dialog.QTimer.singleShot") as timer_mock, \
             patch("ui.license.reconnect_dialog.license_storage.clear_token"):
            dlg._on_revalidate_error("KEY_REVOKED", "La licencia fue revocada.")
        timer_mock.assert_not_called()
    finally:
        dlg.close()
        _app.processEvents()


def test_retry_button_disabled_while_a_revalidation_attempt_is_in_flight():
    # No sobreescribe _start_revalidation_worker (a diferencia de las demás
    # pruebas de este archivo) para que su cuerpo real -- incluido el nuevo
    # setEnabled(False) -- se ejecute; solo se mockean sus dependencias de
    # red/threading para que no haya llamadas reales.
    with patch("ui.license.reconnect_dialog.compute_fingerprint_or_none", return_value=Mock(composite_hash="fp")), \
         patch("ui.license.reconnect_dialog.LicenseRevalidateWorker"), \
         patch("ui.license.reconnect_dialog.LicenseRevalidateThread"):
        dlg = ReconnectDialog("key-abc")
    try:
        assert dlg._retry_btn.isEnabled() is False
    finally:
        dlg.close()
        _app.processEvents()


def test_quit_button_disabled_while_a_revalidation_attempt_is_in_flight():
    with patch("ui.license.reconnect_dialog.compute_fingerprint_or_none", return_value=Mock(composite_hash="fp")), \
         patch("ui.license.reconnect_dialog.LicenseRevalidateWorker"), \
         patch("ui.license.reconnect_dialog.LicenseRevalidateThread"):
        dlg = ReconnectDialog("key-abc")
    try:
        assert dlg._quit_btn.isEnabled() is False
    finally:
        dlg._request_in_flight = False
        dlg.close()
        _app.processEvents()


def test_dialog_ignores_close_while_revalidation_in_flight():
    # Mismo bug que ActivationDialog: cerrar (Salir/Esc) mientras la
    # revalidación sigue en curso destruía el QThread de fondo a mitad de
    # la llamada de red.
    with patch("ui.license.reconnect_dialog.compute_fingerprint_or_none", return_value=Mock(composite_hash="fp")), \
         patch("ui.license.reconnect_dialog.LicenseRevalidateWorker"), \
         patch("ui.license.reconnect_dialog.LicenseRevalidateThread"):
        dlg = ReconnectDialog("key-abc")
    try:
        with patch.object(QDialog, "done") as base_done:
            dlg._on_quit_clicked()
        base_done.assert_not_called()

        dlg._request_in_flight = False
        with patch.object(QDialog, "done") as base_done:
            dlg._on_quit_clicked()
        base_done.assert_called_once()
    finally:
        dlg.close()
        _app.processEvents()


def test_revalidate_success_and_error_clear_in_flight_flag():
    with patch.object(ReconnectDialog, "_start_revalidation_worker", lambda self: None):
        dlg = ReconnectDialog("key-abc")
    try:
        dlg._request_in_flight = True
        with patch("ui.license.reconnect_dialog.license_storage.save_token"):
            dlg._on_revalidate_success("PLT1.fresh.token", None)
        assert dlg._request_in_flight is False

        dlg._request_in_flight = True
        with patch("ui.license.reconnect_dialog.license_storage.clear_token"):
            dlg._on_revalidate_error("KEY_REVOKED", "mensaje")
        assert dlg._request_in_flight is False
    finally:
        dlg.close()
        _app.processEvents()


def test_revalidate_error_clears_token_when_activation_was_released():
    with patch.object(ReconnectDialog, "_start_revalidation_worker", lambda self: None):
        dlg = ReconnectDialog("key-abc")
    try:
        with patch("ui.license.reconnect_dialog.license_storage.clear_token") as clear_token:
            dlg._on_revalidate_error(
                "ACTIVATION_RELEASED",
                "Esta activación fue liberada desde el servidor.",
            )

        clear_token.assert_called_once()
        assert "liberada" in dlg._status_label.text()
    finally:
        dlg.close()
        _app.processEvents()


def test_start_revalidation_worker_shows_error_when_fingerprint_fails_instead_of_crashing():
    with patch("ui.license.reconnect_dialog.compute_fingerprint_or_none", return_value=None):
        dlg = ReconnectDialog("key-abc")  # no debe lanzar
    try:
        assert dlg._retry_btn.isEnabled() is True
        assert "identificar este equipo" in dlg._status_label.text()
    finally:
        dlg.close()
        _app.processEvents()


def test_retry_button_calls_worker_seam_again():
    calls = {"count": 0}

    def _fake_start(self):
        calls["count"] += 1

    with patch.object(ReconnectDialog, "_start_revalidation_worker", _fake_start):
        dlg = ReconnectDialog("key-abc")
        try:
            assert calls["count"] == 1  # arranque automático al abrir
            dlg._on_retry_clicked()
            assert calls["count"] == 2
        finally:
            dlg.close()
            _app.processEvents()


def test_quit_button_sets_gave_up_and_rejects():
    with patch.object(ReconnectDialog, "_start_revalidation_worker", lambda self: None):
        dlg = ReconnectDialog("key-abc")
    try:
        dlg._on_quit_clicked()
        assert dlg.gave_up is True
        assert dlg.result() == 0  # QDialog.Rejected
    finally:
        dlg.close()
        _app.processEvents()
