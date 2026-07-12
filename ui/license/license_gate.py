"""Puerta de licencia: se ejecuta al arrancar PDFlex, antes de construir la
ventana principal (spec §1.1, §1.2).
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtWidgets import QMessageBox

from core import license_storage
from core.license_manager import LicenseRevalidateThread, LicenseRevalidateWorker
from core.license_token import LicenseClaims, LicenseInvalidError, verify_token
from core.machine_fingerprint import compute_fingerprint_or_none
from ui.license.activation_dialog import ActivationDialog
from ui.license.reconnect_dialog import ReconnectDialog


def ensure_licensed(parent=None) -> str | None:
    """Garantiza que PDFlex tenga una licencia local válida antes de
    continuar el arranque. Devuelve el `key_id` activo si se puede
    continuar, o None si la aplicación debe salir."""
    fingerprint = compute_fingerprint_or_none()
    if fingerprint is None:
        QMessageBox.critical(
            parent,
            "PDFlex",
            "No se pudo identificar este equipo, así que PDFlex no puede continuar. "
            "Vuelve a intentarlo; si el problema persiste, contacta a soporte.",
        )
        return None

    stored_token = license_storage.load_token()

    if stored_token is not None:
        try:
            verified = verify_token(stored_token, fingerprint.composite_hash, datetime.now(timezone.utc))
        except LicenseInvalidError:
            verified = None

        if verified is not None and not verified.needs_revalidation:
            return verified.claims.key_id

        if verified is not None and verified.needs_revalidation:
            reconnect = ReconnectDialog(verified.claims.key_id, parent)
            reconnect.exec()
            return verified.claims.key_id if reconnect.revalidated_token is not None else None

    dialog = ActivationDialog(parent)
    dialog.exec()
    if dialog.activated_token is None:
        return None

    try:
        reactivated = verify_token(dialog.activated_token, fingerprint.composite_hash, datetime.now(timezone.utc))
    except LicenseInvalidError:
        return None
    return reactivated.claims.key_id


def get_current_claims() -> LicenseClaims | None:
    """Reconstruye las claims de la licencia activa para paneles que se
    abren en cualquier momento después del arranque (ej. la ventana
    "Ver licencia" del menú Opciones). Devuelve None ante cualquier fallo
    (sin token local, fingerprint no disponible, token inválido) — nunca
    lanza; el llamador decide cómo comunicarlo."""
    fingerprint = compute_fingerprint_or_none()
    if fingerprint is None:
        return None

    stored_token = license_storage.load_token()
    if stored_token is None:
        return None

    try:
        verified = verify_token(stored_token, fingerprint.composite_hash, datetime.now(timezone.utc))
    except LicenseInvalidError:
        return None

    return verified.claims


# Códigos que significan "esta licencia ya no es válida, punto" — a
# diferencia de errores transitorios (red, servidor caído, límite de
# tasa), que no deben tocar el token guardado localmente.
_DEFINITIVE_REVOCATION_CODES = {
    "KEY_REVOKED", "KEY_EXPIRED", "FINGERPRINT_MISMATCH", "KEY_NOT_FOUND",
}


def _handle_background_revalidation_error(error_code: str, _message: str) -> None:
    """Si el servidor confirma en la revalidación silenciosa que la
    licencia ya no es válida, borra el token local — de lo contrario
    seguiría pasando la verificación de firma local (que no vuelve a
    contactar al servidor) hasta que naturalmente venza su ventana de
    `LICENSE_OFFLINE_GRACE_DAYS`, dejando usar la app con una licencia
    ya revocada/expirada/reasignada durante ese tiempo. No interrumpe la
    sesión actual — el bloqueo real ocurre en el siguiente arranque, vía
    `ensure_licensed()` sin encontrar ya un token local."""
    if error_code in _DEFINITIVE_REVOCATION_CODES:
        license_storage.clear_token()


def start_background_revalidation(key_id: str, parent) -> None:
    """Revalidación silenciosa: no bloquea ni interrumpe al usuario si
    falla. `parent` debe ser un QObject vivo (ej. la ventana principal)
    para que Qt mantenga el hilo vivo mientras corre — mismo patrón que
    UpdateCheckThread en core/updater.py."""
    fingerprint = compute_fingerprint_or_none()
    if fingerprint is None:
        return
    worker = LicenseRevalidateWorker(key_id, fingerprint)
    thread = LicenseRevalidateThread(worker, parent)
    worker.success.connect(lambda token, expires: license_storage.save_token(token))
    worker.error.connect(_handle_background_revalidation_error)
    worker.success.connect(thread.quit)
    worker.error.connect(thread.quit)
    thread.start()
