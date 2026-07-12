import os
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core import license_manager as lm
from core.machine_fingerprint import Fingerprint

_app = QApplication.instance() or QApplication([])


def _fake_response(status_code: int, json_body: dict):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    return resp


def test_activate_worker_emits_success_on_200():
    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseActivateWorker("PDFX-AAAAA-BBBBB-CCCCC-DDDD", fp, "PC-1", "Windows 11")
    results = {}
    worker.success.connect(lambda token, customer, expires: results.update(
        token=token, customer=customer, expires=expires
    ))
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch("requests.post", return_value=_fake_response(200, {
        "token": "PLT1.x.y", "customer_name": "Empresa X", "license_expires_at": None
    })):
        worker.run()

    assert results["token"] == "PLT1.x.y"
    assert results["customer"] == "Empresa X"
    assert "error_code" not in results


def test_activate_worker_emits_error_on_key_not_found():
    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseActivateWorker("PDFX-AAAAA-BBBBB-CCCCC-DDDD", fp, "PC-1", "Windows 11")
    results = {}
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch("requests.post", return_value=_fake_response(404, {
        "error_code": "KEY_NOT_FOUND", "message": "Esta clave no existe."
    })):
        worker.run()

    assert results["error_code"] == "KEY_NOT_FOUND"


def test_activate_worker_retries_and_reports_network_error():
    import requests

    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseActivateWorker("PDFX-AAAAA-BBBBB-CCCCC-DDDD", fp, "PC-1", "Windows 11")
    results = {}
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch("requests.post", side_effect=requests.exceptions.ConnectionError()), \
         patch("time.sleep"):
        worker.run()

    assert results["error_code"] == "NETWORK_ERROR"


def test_revalidate_worker_emits_success_with_fresh_token():
    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseRevalidateWorker("key-id-123", fp)
    results = {}
    worker.success.connect(lambda token, expires: results.update(token=token, expires=expires))

    with patch("requests.post", return_value=_fake_response(200, {
        "token": "PLT1.new.token", "license_expires_at": None
    })):
        worker.run()

    assert results["token"] == "PLT1.new.token"


def test_revalidate_worker_emits_fingerprint_mismatch_error():
    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseRevalidateWorker("key-id-123", fp)
    results = {}
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch("requests.post", return_value=_fake_response(409, {
        "error_code": "FINGERPRINT_MISMATCH", "message": "Esta licencia pertenece a otro equipo."
    })):
        worker.run()

    assert results["error_code"] == "FINGERPRINT_MISMATCH"


def test_deactivate_worker_emits_transfers_remaining():
    worker = lm.LicenseDeactivateWorker("key-id-123", "composite-hash")
    results = {}
    worker.success.connect(lambda remaining: results.update(remaining=remaining))

    with patch("requests.post", return_value=_fake_response(200, {"ok": True, "transfers_remaining": 2})):
        worker.run()

    assert results["remaining"] == 2


def test_deactivate_worker_emits_transfer_limit_error():
    worker = lm.LicenseDeactivateWorker("key-id-123", "composite-hash")
    results = {}
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch("requests.post", return_value=_fake_response(429, {
        "error_code": "TRANSFER_LIMIT_REACHED", "message": "Demasiadas transferencias recientes."
    })):
        worker.run()

    assert results["error_code"] == "TRANSFER_LIMIT_REACHED"


def test_activate_worker_emits_error_when_200_response_missing_token():
    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseActivateWorker("PDFX-AAAAA-BBBBB-CCCCC-DDDD", fp, "PC-1", "Windows 11")
    results = {}
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch("requests.post", return_value=_fake_response(200, {"customer_name": "X"})):
        worker.run()

    assert results["error_code"] == "SERVER_ERROR"


def test_revalidate_worker_emits_error_when_200_response_missing_token():
    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseRevalidateWorker("key-id-123", fp)
    results = {}
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch("requests.post", return_value=_fake_response(200, {"license_expires_at": None})):
        worker.run()

    assert results["error_code"] == "SERVER_ERROR"


def test_activate_worker_emits_error_when_requests_not_importable():
    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseActivateWorker("PDFX-AAAAA-BBBBB-CCCCC-DDDD", fp, "PC-1", "Windows 11")
    results = {}
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch.dict("sys.modules", {"requests": None}):
        worker.run()

    assert results["error_code"] == "NETWORK_ERROR"


def test_deactivate_worker_handles_null_transfers_remaining():
    worker = lm.LicenseDeactivateWorker("key-id-123", "composite-hash")
    results = {}
    worker.success.connect(lambda remaining: results.update(remaining=remaining))

    with patch("requests.post", return_value=_fake_response(200, {"ok": True, "transfers_remaining": None})):
        worker.run()

    assert results["remaining"] == 0


def test_activate_worker_emits_server_error_when_response_json_is_not_an_object():
    # JSON válido pero no es un objeto (ej. una lista suelta) -- body.get(...)
    # reventaría con AttributeError si no se blindara en _post_with_retries.
    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseActivateWorker("PDFX-AAAAA-BBBBB-CCCCC-DDDD", fp, "PC-1", "Windows 11")
    results = {}
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch("requests.post", return_value=_fake_response(200, ["not", "an", "object"])):
        worker.run()  # no debe lanzar AttributeError

    assert results["error_code"] == "SERVER_ERROR"
