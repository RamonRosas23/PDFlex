import os
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from core.license_token import LicenseClaims, LicenseInvalidError, VerifiedLicense
from ui.license import license_gate as lg

_app = QApplication.instance() or QApplication([])


def _claims(**overrides) -> LicenseClaims:
    base = dict(
        key_id="key-abc",
        fingerprint="fp",
        issued_at=datetime.now(timezone.utc),
        valid_until=datetime.now(timezone.utc) + timedelta(days=14),
        license_expires_at=None,
        status="active",
        customer_name="Empresa de Prueba",
        app="pdflex",
        seats_allowed=1,
    )
    base.update(overrides)
    return LicenseClaims(**base)


def test_ensure_licensed_returns_key_id_when_local_token_is_fully_valid():
    verified = VerifiedLicense(claims=_claims(), needs_revalidation=False)

    with patch.object(lg.license_storage, "load_token", return_value="PLT1.x.y"), \
         patch.object(lg, "verify_token", return_value=verified), \
         patch.object(lg, "compute_fingerprint_or_none", return_value=Mock(composite_hash="fp")):
        result = lg.ensure_licensed()

    assert result == "key-abc"


def test_ensure_licensed_shows_activation_dialog_when_no_token_stored():
    fake_dialog = Mock()
    fake_dialog.activated_token = "PLT1.new.token"
    reactivated = VerifiedLicense(claims=_claims(key_id="key-new"), needs_revalidation=False)

    with patch.object(lg.license_storage, "load_token", return_value=None), \
         patch.object(lg, "compute_fingerprint_or_none", return_value=Mock(composite_hash="fp")), \
         patch.object(lg, "ActivationDialog", return_value=fake_dialog) as dialog_cls, \
         patch.object(lg, "verify_token", return_value=reactivated):
        result = lg.ensure_licensed()

    dialog_cls.assert_called_once()
    fake_dialog.exec.assert_called_once()
    assert result == "key-new"


def test_ensure_licensed_returns_none_when_activation_dialog_closed_without_key():
    fake_dialog = Mock()
    fake_dialog.activated_token = None

    with patch.object(lg.license_storage, "load_token", return_value=None), \
         patch.object(lg, "compute_fingerprint_or_none", return_value=Mock(composite_hash="fp")), \
         patch.object(lg, "ActivationDialog", return_value=fake_dialog):
        result = lg.ensure_licensed()

    assert result is None


def test_ensure_licensed_shows_activation_dialog_when_local_token_invalid():
    fake_dialog = Mock()
    fake_dialog.activated_token = None

    with patch.object(lg.license_storage, "load_token", return_value="PLT1.corrupt.token"), \
         patch.object(lg, "compute_fingerprint_or_none", return_value=Mock(composite_hash="fp")), \
         patch.object(lg, "verify_token", side_effect=LicenseInvalidError("firma inválida")), \
         patch.object(lg, "ActivationDialog", return_value=fake_dialog) as dialog_cls:
        result = lg.ensure_licensed()

    dialog_cls.assert_called_once()
    assert result is None


def test_ensure_licensed_shows_reconnect_dialog_when_grace_expired():
    verified = VerifiedLicense(claims=_claims(key_id="key-abc"), needs_revalidation=True)
    fake_dialog = Mock()
    fake_dialog.revalidated_token = "PLT1.fresh.token"

    with patch.object(lg.license_storage, "load_token", return_value="PLT1.stale.token"), \
         patch.object(lg, "compute_fingerprint_or_none", return_value=Mock(composite_hash="fp")), \
         patch.object(lg, "verify_token", return_value=verified), \
         patch.object(lg, "ReconnectDialog", return_value=fake_dialog) as dialog_cls:
        result = lg.ensure_licensed()

    dialog_cls.assert_called_once_with("key-abc", None)
    assert result == "key-abc"


def test_ensure_licensed_returns_none_when_reconnect_dialog_gives_up():
    verified = VerifiedLicense(claims=_claims(key_id="key-abc"), needs_revalidation=True)
    fake_dialog = Mock()
    fake_dialog.revalidated_token = None

    with patch.object(lg.license_storage, "load_token", return_value="PLT1.stale.token"), \
         patch.object(lg, "compute_fingerprint_or_none", return_value=Mock(composite_hash="fp")), \
         patch.object(lg, "verify_token", return_value=verified), \
         patch.object(lg, "ReconnectDialog", return_value=fake_dialog):
        result = lg.ensure_licensed()

    assert result is None


def test_ensure_licensed_returns_none_when_freshly_activated_token_fails_verification():
    fake_dialog = Mock()
    fake_dialog.activated_token = "PLT1.corrupt.token"

    with patch.object(lg.license_storage, "load_token", return_value=None), \
         patch.object(lg, "compute_fingerprint_or_none", return_value=Mock(composite_hash="fp")), \
         patch.object(lg, "ActivationDialog", return_value=fake_dialog), \
         patch.object(lg, "verify_token", side_effect=LicenseInvalidError("respuesta corrupta")):
        result = lg.ensure_licensed()

    assert result is None


def test_start_background_revalidation_saves_token_silently_on_success():
    # Sustituye LicenseRevalidateThread por un fake cuyo start() ejecuta el
    # worker de forma síncrona (mismo hilo que el test) en vez de generar un
    # QThread real — evita depender del timing de un hilo en segundo plano
    # real, que sería no-determinista con un único processEvents().
    class _SyncFakeThread:
        def __init__(self, worker, parent):
            self._worker = worker

        def start(self):
            self._worker.run()

        def quit(self):
            pass

    fake_response = Mock(
        status_code=200,
        json=lambda: {"token": "PLT1.bg.token", "license_expires_at": None},
    )

    with patch.object(lg, "LicenseRevalidateThread", _SyncFakeThread), \
         patch.object(lg, "compute_fingerprint_or_none", return_value=Mock(composite_hash="fp")), \
         patch("requests.post", return_value=fake_response), \
         patch.object(lg.license_storage, "save_token") as save_token:
        lg.start_background_revalidation("key-abc", Mock())

    save_token.assert_called_once_with("PLT1.bg.token")


def test_ensure_licensed_returns_none_and_warns_when_fingerprint_fails():
    with patch.object(lg, "compute_fingerprint_or_none", return_value=None), \
         patch.object(lg.license_storage, "load_token") as load_token, \
         patch.object(QMessageBox, "critical") as critical:
        result = lg.ensure_licensed()

    assert result is None
    critical.assert_called_once()
    load_token.assert_not_called()  # falla antes de siquiera mirar el token local


def test_start_background_revalidation_does_nothing_when_fingerprint_fails():
    with patch.object(lg, "compute_fingerprint_or_none", return_value=None), \
         patch.object(lg, "LicenseRevalidateWorker") as worker_cls, \
         patch.object(lg.license_storage, "save_token") as save_token:
        lg.start_background_revalidation("key-abc", Mock())  # no debe lanzar

    worker_cls.assert_not_called()
    save_token.assert_not_called()


def test_start_background_revalidation_does_nothing_visible_on_failure():
    class _SyncFakeThread:
        def __init__(self, worker, parent):
            self._worker = worker

        def start(self):
            self._worker.run()

        def quit(self):
            pass

    fake_response = Mock(
        status_code=404,
        json=lambda: {"error_code": "KEY_NOT_FOUND", "message": "no existe"},
    )

    with patch.object(lg, "LicenseRevalidateThread", _SyncFakeThread), \
         patch.object(lg, "compute_fingerprint_or_none", return_value=Mock(composite_hash="fp")), \
         patch("requests.post", return_value=fake_response), \
         patch.object(lg.license_storage, "save_token") as save_token:
        lg.start_background_revalidation("key-abc", Mock())  # no debe lanzar

    save_token.assert_not_called()
