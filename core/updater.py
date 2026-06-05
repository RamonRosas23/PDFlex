"""Core del auto-updater: detección de versiones, descarga y verificación.

Flujo completo:
  UpdateCheckThread  → detecta si hay versión más nueva
  UpdateDownloadThread → descarga, verifica SHA-256
  launch_installer_and_quit → lanza .exe y cierra la app
"""
from __future__ import annotations

import hashlib
import os
import sys
import time
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.update_config import (
    APP_VERSION,
    UPDATE_API_BASE,
    UPDATE_APP_KEY,
    UPDATE_CHANNEL,
    UPDATE_CHECK_TIMEOUT_S,
    UPDATE_DOWNLOAD_TIMEOUT_S,
    UPDATE_MAX_RETRIES,
    UPDATE_RETRY_DELAY_S,
)


def update_log_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    return base / "PDFlex" / "updates" / "update_check.log"


def log_update_event(message: str) -> None:
    try:
        path = update_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Modelo de datos (espejo de la API)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UpdateInfo:
    app: str
    channel: str
    version: str
    url: str
    sha256: str
    size_bytes: int
    mandatory: bool
    min_supported_version: str
    published_at: str
    notes: str

    @classmethod
    def from_dict(cls, d: dict) -> "UpdateInfo":
        return cls(
            app=str(d.get("app", "")),
            channel=str(d.get("channel", "stable")),
            version=str(d.get("version", "0.0.0")),
            url=str(d.get("url", "")),
            sha256=str(d.get("sha256", "")),
            size_bytes=int(d.get("size_bytes", 0) or 0),
            mandatory=bool(d.get("mandatory", False)),
            min_supported_version=str(d.get("min_supported_version", "0.0.0")),
            published_at=str(d.get("published_at", "")),
            notes=str(d.get("notes", "")),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades de versiones SemVer (sin dependencias externas)
# ─────────────────────────────────────────────────────────────────────────────

def _version_tuple(v: str) -> tuple[int, ...]:
    """Convierte 'X.Y.Z' o 'vX.Y.Z' a tupla comparable."""
    parts = v.strip().lstrip("v").split(".")
    result: list[int] = []
    for p in parts[:3]:
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    while len(result) < 3:
        result.append(0)
    return tuple(result)


def is_newer_version(current: str, candidate: str) -> bool:
    """True si candidate es estrictamente más nuevo que current."""
    return _version_tuple(candidate) > _version_tuple(current)


def is_below_minimum(current: str, minimum: str) -> bool:
    """True si current está por debajo del mínimo soportado."""
    return _version_tuple(current) < _version_tuple(minimum)


def is_update_forced(info: UpdateInfo) -> bool:
    """True si la actualización no puede ser ignorada."""
    if info.mandatory:
        return True
    if info.min_supported_version:
        return is_below_minimum(APP_VERSION, info.min_supported_version)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de formato
# ─────────────────────────────────────────────────────────────────────────────

def format_bytes(n: int) -> str:
    if n < 1_024:
        return f"{n} B"
    if n < 1_048_576:
        return f"{n / 1_024:.1f} KB"
    if n < 1_073_741_824:
        return f"{n / 1_048_576:.1f} MB"
    return f"{n / 1_073_741_824:.2f} GB"


# ─────────────────────────────────────────────────────────────────────────────
# Worker: comprobación de actualización
# ─────────────────────────────────────────────────────────────────────────────

class UpdateCheckWorker(QObject):
    """Consulta la API en segundo plano y emite el resultado."""

    update_available = pyqtSignal(object)   # UpdateInfo
    up_to_date       = pyqtSignal(str)      # version_actual
    check_error      = pyqtSignal(str)      # mensaje de error

    def run(self) -> None:
        try:
            import requests
        except ImportError:
            self.check_error.emit(
                "Librería 'requests' no disponible. Reinstala PDFlex."
            )
            return

        url = (
            f"{UPDATE_API_BASE}/api/desktop-apps"
            f"/{UPDATE_APP_KEY}/releases/latest"
        )
        params = {"channel": UPDATE_CHANNEL}
        headers = {"User-Agent": f"PDFlex-Updater/{APP_VERSION}"}
        log_update_event(
            f"Checking updates app={UPDATE_APP_KEY} channel={UPDATE_CHANNEL} "
            f"current={APP_VERSION} url={url}"
        )

        last_error = ""
        for attempt in range(1, UPDATE_MAX_RETRIES + 1):
            try:
                resp = requests.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=UPDATE_CHECK_TIMEOUT_S,
                )
                log_update_event(
                    f"Update check response status={resp.status_code} attempt={attempt}"
                )
                break
            except requests.exceptions.ConnectionError:
                last_error = "Sin conexión a Internet."
            except requests.exceptions.Timeout:
                last_error = "El servidor tardó demasiado en responder."
            except requests.exceptions.RequestException as exc:
                last_error = f"Error de red: {exc}"
            log_update_event(f"Update check attempt={attempt} failed: {last_error}")

            if attempt < UPDATE_MAX_RETRIES:
                time.sleep(UPDATE_RETRY_DELAY_S * attempt)
        else:
            log_update_event(f"Update check failed permanently: {last_error}")
            self.check_error.emit(last_error)
            return

        if resp.status_code == 404:
            log_update_event("No release found for this app/channel.")
            self.up_to_date.emit(APP_VERSION)
            return

        if resp.status_code != 200:
            message = f"Error del servidor ({resp.status_code})."
            log_update_event(message)
            self.check_error.emit(message)
            return

        try:
            data = resp.json()
        except Exception:
            message = "Respuesta del servidor inválida."
            log_update_event(f"{message} Body={resp.text[:500]}")
            self.check_error.emit(message)
            return

        try:
            info = UpdateInfo.from_dict(data)
        except Exception as exc:
            message = f"No se pudo parsear la respuesta: {exc}"
            log_update_event(message)
            self.check_error.emit(message)
            return

        log_update_event(
            f"Latest release version={info.version} mandatory={info.mandatory} "
            f"min_supported={info.min_supported_version} size={info.size_bytes} "
            f"sha256={info.sha256}"
        )

        if is_newer_version(APP_VERSION, info.version):
            log_update_event(f"Update available current={APP_VERSION} latest={info.version}")
            self.update_available.emit(info)
        else:
            log_update_event(f"Already up to date current={APP_VERSION} latest={info.version}")
            self.up_to_date.emit(APP_VERSION)


class UpdateCheckThread(QThread):
    def __init__(self, worker: UpdateCheckWorker, parent=None) -> None:
        super().__init__(parent)
        self._worker = worker

    def run(self) -> None:
        try:
            self._worker.run()
        except Exception:
            import sys
            from core.crash_handler import handle_crash
            handle_crash(*sys.exc_info(),
                         context="UpdateCheckThread", fatal=False)


# ─────────────────────────────────────────────────────────────────────────────
# Worker: descarga, verificación SHA-256
# ─────────────────────────────────────────────────────────────────────────────

class UpdateDownloadWorker(QObject):
    """Descarga el instalador y verifica su integridad."""

    progress       = pyqtSignal(int, int, float)  # descargado, total, velocidad_bps
    status_message = pyqtSignal(str)
    verifying      = pyqtSignal()                  # comienza verificación SHA-256
    verified       = pyqtSignal(str)               # ruta del instalador
    hash_mismatch  = pyqtSignal()
    download_error = pyqtSignal(str)

    def __init__(self, info: UpdateInfo, parent=None) -> None:
        super().__init__(parent)
        self._info      = info
        self._cancelled = False
        self._temp_path: Optional[Path] = None

    def cancel(self) -> None:
        self._cancelled = True

    # ── run ──────────────────────────────────────────────────────────────────

    def run(self) -> None:
        try:
            import requests  # noqa: F401
        except ImportError:
            self.download_error.emit("Librería 'requests' no disponible.")
            return

        # Directorio temporal
        tmp_dir = Path(tempfile.gettempdir()) / "PDFlex" / "updates"
        try:
            tmp_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.download_error.emit(f"No se pudo crear directorio temporal:\n{exc}")
            return

        filename = (
            self._info.url.rsplit("/", 1)[-1]
            or f"PDFlex_{self._info.version}_setup.exe"
        )
        self._temp_path = tmp_dir / filename

        # Reintentos de descarga
        success = False
        last_error = "Error de descarga desconocido."
        for attempt in range(1, UPDATE_MAX_RETRIES + 1):
            if self._cancelled:
                break
            if attempt > 1:
                self.status_message.emit(
                    f"Reintentando descarga ({attempt}/{UPDATE_MAX_RETRIES})..."
                )
                time.sleep(UPDATE_RETRY_DELAY_S * (attempt - 1))

            ok, last_error = self._attempt_download()
            if ok:
                success = True
                break

        if self._cancelled:
            self._cleanup()
            return

        if not success:
            self.download_error.emit(last_error)
            self._cleanup()
            return

        # Verificar integridad
        self.verifying.emit()
        try:
            local_hash = self._sha256(self._temp_path)
        except OSError as exc:
            self.download_error.emit(f"Error al leer el archivo descargado:\n{exc}")
            self._cleanup()
            return

        if local_hash.lower() != self._info.sha256.lower():
            self.hash_mismatch.emit()
            self._cleanup()
            return

        self.verified.emit(str(self._temp_path))

    # ── descarga individual ───────────────────────────────────────────────────

    def _attempt_download(self) -> tuple[bool, str]:
        import requests

        try:
            resp = requests.get(
                self._info.url,
                stream=True,
                timeout=UPDATE_DOWNLOAD_TIMEOUT_S,
                headers={"User-Agent": f"PDFlex-Updater/{APP_VERSION}"},
            )
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            return False, "Sin conexión a Internet. Verifica tu red."
        except requests.exceptions.Timeout:
            return False, "La descarga tardó demasiado. Verifica tu conexión."
        except requests.exceptions.HTTPError as exc:
            return False, f"Error HTTP {exc.response.status_code} al descargar."
        except requests.exceptions.RequestException as exc:
            return False, f"Error de red: {exc}"

        total = int(
            resp.headers.get("Content-Length", self._info.size_bytes or 0)
        )
        downloaded = 0
        speed_samples: list[tuple[float, int]] = []  # (tiempo, bytes_acumulados)

        try:
            with open(self._temp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65_536):
                    if self._cancelled:
                        return False, "Cancelado."
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.monotonic()
                    speed_samples.append((now, downloaded))
                    # Ventana deslizante de 3 segundos para cálculo de velocidad
                    cutoff = now - 3.0
                    speed_samples = [
                        (t, b) for t, b in speed_samples if t >= cutoff
                    ]

                    speed = 0.0
                    if len(speed_samples) >= 2:
                        dt = speed_samples[-1][0] - speed_samples[0][0]
                        db = speed_samples[-1][1] - speed_samples[0][1]
                        if dt > 0:
                            speed = db / dt

                    self.progress.emit(downloaded, total, speed)

        except OSError as exc:
            return False, f"Error de escritura en disco:\n{exc}"
        except Exception as exc:
            return False, f"Error inesperado durante la descarga:\n{exc}"

        return True, ""

    # ── SHA-256 ───────────────────────────────────────────────────────────────

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65_536), b""):
                h.update(chunk)
        return h.hexdigest()

    # ── limpieza ──────────────────────────────────────────────────────────────

    def _cleanup(self) -> None:
        if self._temp_path and self._temp_path.exists():
            try:
                self._temp_path.unlink(missing_ok=True)
            except OSError:
                pass


class UpdateDownloadThread(QThread):
    def __init__(self, worker: UpdateDownloadWorker, parent=None) -> None:
        super().__init__(parent)
        self._worker = worker

    def run(self) -> None:
        try:
            self._worker.run()
        except Exception:
            import sys
            from core.crash_handler import handle_crash
            handle_crash(*sys.exc_info(),
                         context="UpdateDownloadThread", fatal=False)


# ─────────────────────────────────────────────────────────────────────────────
# Lanzador del instalador
# ─────────────────────────────────────────────────────────────────────────────

def launch_installer_and_quit(installer_path: str) -> None:
    """Lanza el instalador Inno Setup de forma desacoplada y cierra PDFlex.

    Pasa /SILENT para mostrar solo la barra de progreso (sin wizard).
    /NORESTART evita un reinicio automático del sistema.
    /CLOSEAPPLICATIONS cierra instancias adicionales de PDFlex si las hay.
    """
    import subprocess
    from PyQt6.QtWidgets import QApplication

    path = Path(installer_path)
    if not path.exists():
        raise FileNotFoundError(f"Instalador no encontrado: {installer_path}")

    if sys.platform == "win32":
        subprocess.Popen(
            [str(path), "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS"],
            creationflags=(
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
            ),
            close_fds=True,
        )
    else:
        subprocess.Popen([str(path)])

    QApplication.quit()
