"""Workers de red para activar, revalidar y desactivar la licencia de PDFlex.

Mismo patrón que core/updater.py: QObject + señales, envuelto en QThread con
reporte de excepciones a core.crash_handler.handle_crash(fatal=False).
Ver docs/superpowers/specs/2026-07-11-pdflex-licensing-design.md §6.
"""

from __future__ import annotations

from dataclasses import dataclass
import time

from PySide6.QtCore import QObject, QThread, Signal

from core import license_config
from core.machine_fingerprint import Fingerprint
from core.update_config import APP_VERSION


def _headers() -> dict:
    return {"User-Agent": f"PDFlex-License/{APP_VERSION}"}


def _post_with_retries(
    url: str,
    payload: dict,
    *,
    timeout_s: int | float | None = None,
    max_retries: int | None = None,
    retry_delay_s: int | float | None = None,
) -> tuple[int, dict]:
    """POST con reintentos. Devuelve (status_code, json_body).

    Si todos los intentos fallan por red (sin respuesta del servidor),
    devuelve (0, {"error_code": "NETWORK_ERROR", "message": "..."})  en vez
    de lanzar, para que los workers manejen un único camino de error.
    """
    timeout = license_config.LICENSE_CHECK_TIMEOUT_S if timeout_s is None else timeout_s
    retries = license_config.LICENSE_MAX_RETRIES if max_retries is None else max_retries
    retry_delay = license_config.LICENSE_RETRY_DELAY_S if retry_delay_s is None else retry_delay_s

    try:
        import requests
    except ImportError:
        return 0, {
            "error_code": "NETWORK_ERROR",
            "message": "Librería 'requests' no disponible. Reinstala PDFlex.",
        }

    last_message = "No se pudo conectar."
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                url,
                json=payload,
                headers=_headers(),
                timeout=timeout,
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

        if attempt < retries:
            time.sleep(retry_delay * attempt)

    return 0, {"error_code": "NETWORK_ERROR", "message": last_message}


@dataclass(frozen=True)
class LicenseServerResult:
    ok: bool
    token: str | None = None
    license_expires_at: object | None = None
    error_code: str = ""
    message: str = ""


def revalidate_license_once(
    key_id: str,
    fingerprint: Fingerprint,
    *,
    timeout_s: int | float | None = None,
    max_retries: int | None = None,
    retry_delay_s: int | float | None = None,
) -> LicenseServerResult:
    """Revalida una activación y normaliza la respuesta del servidor.

    Se usa tanto desde QThread como desde el arranque bloqueante corto. La
    validación criptográfica del token devuelto sigue viviendo en el llamador,
    que conoce el fingerprint esperado y la política UX adecuada.
    """
    url = (
        f"{license_config.LICENSE_API_BASE}/api/desktop-apps/"
        f"{license_config.LICENSE_APP_KEY}/licenses/revalidate"
    )
    payload = {
        "key_id": key_id,
        "fingerprint": fingerprint.to_dict(),
        "app_version": APP_VERSION,
    }
    status, body = _post_with_retries(
        url,
        payload,
        timeout_s=timeout_s,
        max_retries=max_retries,
        retry_delay_s=retry_delay_s,
    )
    if status == 200:
        token = body.get("token")
        if not token:
            return LicenseServerResult(
                ok=False,
                error_code="SERVER_ERROR",
                message="Respuesta del servidor inválida.",
            )
        return LicenseServerResult(
            ok=True,
            token=str(token),
            license_expires_at=body.get("license_expires_at"),
        )
    return LicenseServerResult(
        ok=False,
        error_code=str(body.get("error_code") or "SERVER_ERROR"),
        message=str(body.get("message") or "Error desconocido."),
    )


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

    def __init__(
        self,
        key_id: str,
        fingerprint: Fingerprint,
        parent=None,
        *,
        timeout_s: int | float | None = None,
        max_retries: int | None = None,
        retry_delay_s: int | float | None = None,
    ) -> None:
        super().__init__(parent)
        self._key_id = key_id
        self._fingerprint = fingerprint
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._retry_delay_s = retry_delay_s

    def run(self) -> None:
        result = revalidate_license_once(
            self._key_id,
            self._fingerprint,
            timeout_s=self._timeout_s,
            max_retries=self._max_retries,
            retry_delay_s=self._retry_delay_s,
        )
        if result.ok and result.token:
            self.success.emit(result.token, result.license_expires_at)
        else:
            self.error.emit(result.error_code, result.message)


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
