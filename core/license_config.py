"""Configuración del sistema de activación y licencias de PDFlex."""

from core.update_config import UPDATE_API_BASE

# ── Servidor de licencias (mismo host que el auto-updater) ──────────────────
LICENSE_API_BASE = UPDATE_API_BASE
LICENSE_APP_KEY = "pdflex"

# ── Timeouts y reintentos ─────────────────────────────────────────────────────
LICENSE_CHECK_TIMEOUT_S = 12
LICENSE_MAX_RETRIES = 3
LICENSE_RETRY_DELAY_S = 2

# ── Política de licencia ──────────────────────────────────────────────────────
LICENSE_OFFLINE_GRACE_DAYS = 14
LICENSE_REVALIDATE_WARNING_DAYS = 3
LICENSE_TRANSFER_LIMIT = 3
LICENSE_TRANSFER_WINDOW_DAYS = 90

# ── Criptografía ───────────────────────────────────────────────────────────────
# Clave pública Ed25519 (32 bytes crudos, base64 estándar) entregada por el
# servidor. Placeholder de desarrollo — DEBE reemplazarse por la clave real
# de producción antes de compilar un release comercial.
LICENSE_PUBLIC_KEY_ED25519 = "REPLACE_WITH_SERVER_PUBLIC_KEY_BASE64_BEFORE_RELEASE"

# Pepper fijo para normalizar identificadores de hardware antes de enviarlos.
# No es un secreto de seguridad — solo evita transmitir IDs de hardware en crudo.
FINGERPRINT_PEPPER = "PDFlex-Fingerprint-Pepper-v1-GRUPOOCMX"
