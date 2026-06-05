"""Configuración del sistema de auto-actualización de PDFlex."""

# ── Versión actual de la aplicación ──────────────────────────────────────────
APP_VERSION = "2.0.3"

# ── Servidor de actualizaciones ───────────────────────────────────────────────
UPDATE_API_BASE = "https://grupocmx.mx"
UPDATE_APP_KEY  = "pdflex"
UPDATE_CHANNEL  = "stable"           # "stable" | "beta" | "dev"

# ── Timeouts y reintentos ─────────────────────────────────────────────────────
UPDATE_CHECK_TIMEOUT_S    = 12       # GET /releases/latest
UPDATE_DOWNLOAD_TIMEOUT_S = 60       # timeout por chunk stream
UPDATE_MAX_RETRIES        = 3        # intentos de descarga
UPDATE_RETRY_DELAY_S      = 2        # espera base entre reintentos (se multiplica)

# ── Comportamiento al inicio ──────────────────────────────────────────────────
UPDATE_STARTUP_DELAY_MS = 4000       # ms de espera tras arranque antes de comprobar
