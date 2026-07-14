"""Puerta de licencia: se ejecuta al arrancar PDFlex, antes de construir la
ventana principal (spec §1.1, §1.2).
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from core import license_config, license_storage
from core.license_manager import (
    LicenseRevalidateThread,
    LicenseRevalidateWorker,
    LicenseServerResult,
    revalidate_license_once,
)
from core.license_token import (
    LicenseClaims,
    LicenseInvalidError,
    VerifiedLicense,
    verify_token,
)
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
            license_storage.clear_token()
            verified = None

        if verified is not None:
            return _continue_with_verified_local_token(verified, fingerprint, parent)

    return _activate_with_dialog(fingerprint, parent)


def _activate_with_dialog(fingerprint, parent=None) -> str | None:
    dialog = ActivationDialog(parent)
    dialog.exec()
    if dialog.activated_token is None:
        return None

    try:
        reactivated = verify_token(dialog.activated_token, fingerprint.composite_hash, datetime.now(timezone.utc))
    except LicenseInvalidError:
        license_storage.clear_token()
        return None
    return reactivated.claims.key_id


def _continue_with_verified_local_token(
    verified: VerifiedLicense,
    fingerprint,
    parent=None,
) -> str | None:
    """Decide si el token local puede abrir la app o debe revalidarse.

    El token firmado permite gracia offline, pero si el servidor responde
    durante el arranque que esa activación ya fue liberada/revocada, gana el
    servidor y se borra la copia local antes de abrir la interfaz principal.
    """
    result = _startup_revalidate(verified.claims.key_id, fingerprint)
    if result.ok and result.token:
        try:
            refreshed = verify_token(
                result.token,
                fingerprint.composite_hash,
                datetime.now(timezone.utc),
            )
        except LicenseInvalidError:
            license_storage.clear_token()
            return _activate_with_dialog(fingerprint, parent)
        if refreshed.needs_revalidation:
            license_storage.clear_token()
            return _activate_with_dialog(fingerprint, parent)
        license_storage.save_token(result.token)
        return refreshed.claims.key_id

    if _is_definitive_revalidation_error(result.error_code):
        license_storage.clear_token()
        return _activate_with_dialog(fingerprint, parent)

    if verified.needs_revalidation:
        reconnect = ReconnectDialog(verified.claims.key_id, parent)
        reconnect.exec()
        if reconnect.revalidated_token is None:
            return None
        try:
            refreshed = verify_token(
                reconnect.revalidated_token,
                fingerprint.composite_hash,
                datetime.now(timezone.utc),
            )
        except LicenseInvalidError:
            license_storage.clear_token()
            return _activate_with_dialog(fingerprint, parent)
        if refreshed.needs_revalidation:
            license_storage.clear_token()
            return _activate_with_dialog(fingerprint, parent)
        return refreshed.claims.key_id

    return verified.claims.key_id


def _startup_revalidate(key_id: str, fingerprint) -> LicenseServerResult:
    return revalidate_license_once(
        key_id,
        fingerprint,
        timeout_s=license_config.LICENSE_STARTUP_REVALIDATE_TIMEOUT_S,
        max_retries=license_config.LICENSE_STARTUP_REVALIDATE_MAX_RETRIES,
        retry_delay_s=license_config.LICENSE_STARTUP_REVALIDATE_RETRY_DELAY_S,
    )


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
    "KEY_REVOKED",
    "KEY_EXPIRED",
    "FINGERPRINT_MISMATCH",
    "KEY_NOT_FOUND",
    "ALREADY_ACTIVATED_ELSEWHERE",
    "ACTIVATION_NOT_FOUND",
    "ACTIVATION_RELEASED",
    "ACTIVATION_INACTIVE",
    "ACTIVATION_NOT_ACTIVE",
    "ACTIVATION_DEACTIVATED",
    "KEY_RELEASED",
    "KEY_INACTIVE",
    "KEY_SUSPENDED",
    "KEY_DEACTIVATED",
    "LICENSE_RELEASED",
    "LICENSE_INACTIVE",
    "LICENSE_NOT_ACTIVE",
    "LICENSE_SUSPENDED",
}


def _is_definitive_revalidation_error(error_code: str) -> bool:
    return error_code in _DEFINITIVE_REVOCATION_CODES


def _handle_background_revalidation_error(
    error_code: str,
    message: str,
    parent=None,
) -> None:
    """Si el servidor confirma en la revalidación silenciosa que la
    licencia ya no es válida, borra el token local — de lo contrario
    seguiría pasando la verificación de firma local (que no vuelve a
    contactar al servidor) hasta que naturalmente venza su ventana de
    `LICENSE_OFFLINE_GRACE_DAYS`, dejando usar la app con una licencia ya
    revocada/expirada/reasignada durante ese tiempo.

    Si ya hay una ventana principal, también avisa y cierra la sesión actual:
    continuar trabajando con una licencia que el servidor acaba de invalidar
    sería inconsistente con el panel administrativo."""
    if _is_definitive_revalidation_error(error_code):
        license_storage.clear_token()
        if isinstance(parent, QWidget):
            QMessageBox.warning(
                parent,
                "Licencia no disponible",
                message or "Esta licencia ya no está activa en este equipo.",
            )
            app = QApplication.instance()
            if app is not None:
                app.quit()


class _BackgroundRevalidationReceiver(QObject):
    """Recibe las señales del worker de revalidación en el hilo GUI.

    El worker emite desde el QThread de red; conectar sus señales a lambdas
    sueltas crea conexiones directas que ejecutan el slot en ese hilo de red
    — y el handler de error puede abrir un QMessageBox y llamar app.quit(),
    ambos prohibidos fuera del hilo GUI. Un QObject creado en el hilo GUI
    fuerza entrega encolada (AutoConnection), y si la ventana padre se
    destruye antes de entregar la señal, Qt descarta el evento pendiente en
    vez de ejecutar el slot sobre un padre ya destruido."""

    def __init__(self, parent_widget) -> None:
        super().__init__(parent_widget if isinstance(parent_widget, QObject) else None)
        self._parent_widget = parent_widget

    @Slot(str, object)
    def on_success(self, token: str, license_expires_at) -> None:
        license_storage.save_token(token)

    @Slot(str, str)
    def on_error(self, error_code: str, message: str) -> None:
        _handle_background_revalidation_error(error_code, message, self._parent_widget)


def start_background_revalidation(key_id: str, parent) -> None:
    """Revalidación silenciosa: no bloquea el arranque y tolera fallos
    transitorios. Si el servidor invalida la licencia, borra el token local,
    avisa y cierra la sesión actual. `parent` debe ser un QObject vivo (ej. la
    ventana principal) para que Qt mantenga el hilo vivo mientras corre —
    mismo patrón que UpdateCheckThread en core/updater.py.

    El hilo también se guarda como `parent._license_revalidate_thread`
    para que `ShellWindow.closeEvent` pueda esperar su terminación (hasta
    3s) antes de cerrar — sin esto, cerrar PDFlex mientras esta llamada
    de red sigue en curso destruye un QThread todavía corriendo, lo cual
    Qt trata como error fatal (aborta el proceso: quedan sesiones
    "running" nunca marcadas "clean", y logs de fallo nativo vacíos
    porque no es un segfault real, es este abort intencional de Qt)."""
    fingerprint = compute_fingerprint_or_none()
    if fingerprint is None:
        return
    worker = LicenseRevalidateWorker(key_id, fingerprint)
    thread = LicenseRevalidateThread(worker, parent)
    receiver = _BackgroundRevalidationReceiver(parent)
    worker.success.connect(receiver.on_success)
    worker.error.connect(receiver.on_error)
    worker.success.connect(thread.quit)
    worker.error.connect(thread.quit)
    # El receptor debe sobrevivir mientras el hilo corre aunque `parent` no
    # sea un QObject (p. ej. dobles de prueba): se cuelga del propio thread.
    thread._signal_receiver = receiver

    def _clear_thread_ref(parent=parent):
        # Al terminar, deleteLater destruirá el objeto C++ del QThread pero
        # el wrapper Python guardado en el atributo seguiría vivo; si
        # closeEvent llamara isRunning() sobre ese wrapper obtendría
        # "RuntimeError: libshiboken: Internal C++ object already deleted"
        # (crash real de v2.0.8 al cerrar). Se limpia antes de deleteLater.
        if getattr(parent, "_license_revalidate_thread", None) is thread:
            parent._license_revalidate_thread = None

    thread.finished.connect(_clear_thread_ref)
    thread.finished.connect(thread.deleteLater)
    try:
        parent._license_revalidate_thread = thread
    except AttributeError:
        pass
    thread.start()
