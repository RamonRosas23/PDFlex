import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame

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
        dlg._on_revalidate_error("KEY_REVOKED", "mensaje crudo")

        assert dlg._retry_btn.isEnabled() is True
        assert "revocada" in dlg._status_label.text()
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
