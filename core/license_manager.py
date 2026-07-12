"""Workers de red para activar, revalidar y desactivar la licencia de PDFlex.

Mismo patrón que core/updater.py: QObject + señales, envuelto en QThread con
reporte de excepciones a core.crash_handler.handle_crash(fatal=False).
Ver docs/superpowers/specs/2026-07-11-pdflex-licensing-design.md §6.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QThread, Signal

from core import license_config
from core.machine_fingerprint import Fingerprint
from core.update_config import APP_VERSION


def _headers() -> dict:
    return {"User-Agent": f"PDFlex-License/{APP_VERSION}"}


def _post_with_retries(url: str, payload: dict) -> tuple[int, dict]:
    """POST con reintentos. Devuelve (status_code, json_body).

    Si todos los intentos fallan por red (sin respuesta del servidor),
    devuelve (0, {"error_code": "NETWORK_ERROR", "message": "..."})  en vez
    de lanzar, para que los workers manejen un único camino de error.
    """
    try:
        import requests
    except ImportError:
        return 0, {
            "error_code": "NETWORK_ERROR",
            "message": "Librería 'requests' no disponible. Reinstala PDFlex.",
        }

    last_message = "No se pudo conectar."
    for attempt in range(1, license_config.LICENSE_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                url,
                json=payload,
                headers=_headers(),
                timeout=license_config.LICENSE_CHECK_TIMEOUT_S,
            )
            try:
                body = resp.json()
            except ValueError:
                body = None
            # `resp.json()` puede tener éxito con JSON válido que no es un
            # objeto (ej. una lista o un escalar suelto) — tratarlo igual
            # que JSON inválido, para que ningún worker llame `.get(...)`
            # sobre algo que no es un dict.
            if not isinstance(body, dict):
                body = {"error_code": "SERVER_ERROR", "message": "Respuesta del servidor inválida."}
            return resp.status_code, body
        except requests.exceptions.ConnectionError:
            last_message = "Sin conexión a Internet."
        except requests.exceptions.Timeout:
            last_message = "El servidor tardó demasiado en responder."
        except requests.exceptions.RequestException as exc:
            last_message = f"Error de red: {exc}"

        if attempt < license_config.LICENSE_MAX_RETRIES:
            time.sleep(license_config.LICENSE_RETRY_DELAY_S * attempt)

    return 0, {"error_code": "NETWORK_ERROR", "message": last_message}


def _thread_run_with_crash_report(worker, context: str) -> None:
    try:
        worker.run()
    except Exception:
        import sys

        from core.crash_handler import handle_crash

        handle_crash(*sys.exc_info(), context=context, fatal=False)


class LicenseActivateWorker(QObject):
    success = Signal(str, str, object)  # token, customer_name, license_expires_at
    error = Signal(str, str)            # error_code, message

    def __init__(
        self,
        license_key: str,
        fingerprint: Fingerprint,
        machine_name: str,
        os_version: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._license_key = license_key
        self._fingerprint = fingerprint
        self._machine_name = machine_name
        self._os_version = os_version

    def run(self) -> None:
        url = (
            f"{license_config.LICENSE_API_BASE}/api/desktop-apps/"
            f"{license_config.LICENSE_APP_KEY}/licenses/activate"
        )
        payload = {
            "license_key": self._license_key,
            "fingerprint": self._fingerprint.to_dict(),
            "machine_name": self._machine_name,
            "os_version": self._os_version,
            "app_version": APP_VERSION,
        }
        status, body = _post_with_retries(url, payload)
        if status == 200:
            token = body.get("token")
            if not token:
                self.error.emit("SERVER_ERROR", "Respuesta del servidor inválida.")
                return
            self.success.emit(token, body.get("customer_name") or "", body.get("license_expires_at"))
        else:
            self.error.emit(body.get("error_code", "SERVER_ERROR"), body.get("message", "Error desconocido."))


class LicenseActivateThread(QThread):
    def __init__(self, worker: LicenseActivateWorker, parent=None) -> None:
        super().__init__(parent)
        self._worker = worker

    def run(self) -> None:
        _thread_run_with_crash_report(self._worker, "LicenseActivateThread")


class LicenseRevalidateWorker(QObject):
    success = Signal(str, object)  # token, license_expires_at
    error = Signal(str, str)

    def __init__(self, key_id: str, fingerprint: Fingerprint, parent=None) -> None:
        super().__init__(parent)
        self._key_id = key_id
        self._fingerprint = fingerprint

    def run(self) -> None:
        url = (
            f"{license_config.LICENSE_API_BASE}/api/desktop-apps/"
            f"{license_config.LICENSE_APP_KEY}/licenses/revalidate"
        )
        payload = {
            "key_id": self._key_id,
            "fingerprint": self._fingerprint.to_dict(),
            "app_version": APP_VERSION,
        }
        status, body = _post_with_retries(url, payload)
        if status == 200:
            token = body.get("token")
            if not token:
                self.error.emit("SERVER_ERROR", "Respuesta del servidor inválida.")
                return
            self.success.emit(token, body.get("license_expires_at"))
        else:
            self.error.emit(body.get("error_code", "SERVER_ERROR"), body.get("message", "Error desconocido."))


class LicenseRevalidateThread(QThread):
    def __init__(self, worker: LicenseRevalidateWorker, parent=None) -> None:
        super().__init__(parent)
        self._worker = worker

    def run(self) -> None:
        _thread_run_with_crash_report(self._worker, "LicenseRevalidateThread")


class LicenseDeactivateWorker(QObject):
    success = Signal(int)  # transfers_remaining
    error = Signal(str, str)

    def __init__(self, key_id: str, composite_hash: str, parent=None) -> None:
        super().__init__(parent)
        self._key_id = key_id
        self._composite_hash = composite_hash

    def run(self) -> None:
        url = (
            f"{license_config.LICENSE_API_BASE}/api/desktop-apps/"
            f"{license_config.LICENSE_APP_KEY}/licenses/deactivate"
        )
        payload = {"key_id": self._key_id, "fingerprint": {"composite_hash": self._composite_hash}}
        status, body = _post_with_retries(url, payload)
        if status == 200:
            transfers_remaining = body.get("transfers_remaining")
            self.success.emit(int(transfers_remaining) if transfers_remaining is not None else 0)
        else:
            self.error.emit(body.get("error_code", "SERVER_ERROR"), body.get("message", "Error desconocido."))


class LicenseDeactivateThread(QThread):
    def __init__(self, worker: LicenseDeactivateWorker, parent=None) -> None:
        super().__init__(parent)
        self._worker = worker

    def run(self) -> None:
        _thread_run_with_crash_report(self._worker, "LicenseDeactivateThread")
