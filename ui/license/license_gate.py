"""Puerta de licencia: se ejecuta al arrancar PDFlex, antes de construir la
ventana principal (spec §1.1, §1.2).
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtWidgets import QMessageBox

from core import license_storage
from core.license_manager import LicenseRevalidateThread, LicenseRevalidateWorker
from core.license_token import LicenseInvalidError, verify_token
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
    worker.success.connect(thread.quit)
    worker.error.connect(thread.quit)
    thread.start()
