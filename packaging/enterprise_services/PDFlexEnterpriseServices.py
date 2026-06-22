"""Administrative helper for PDFlex Enterprise Services.

Responsabilidades:
  - Valida manifests y SHA-256 del payload ZIP.
  - Extrae el ZIP en staging temporal con validación de rutas seguras.
  - Valida archivos esperados declarados en manifest.expectedFiles.
  - Hace backup del payload anterior antes de desplegar (rollback posible).
  - Copia archivos al destino final con swaps atómicos.
  - Registra Servicios Windows declarados en manifest.windowsServices (sc.exe).
  - Registra Tareas Programadas declaradas en manifest.scheduledTasks (schtasks + XML).
  - Escribe state.json y HKLM\\Software\\GRUPO OCMX\\PDFlexEnterpriseServices.
  - Ejecuta status() internamente tras install para confirmar éxito.
  - En error: rollback completo (payload, servicios, tareas, registro).
  - Idempotente: misma versión + status OK → retorna 0 sin cambios.

Manifest de referencia (enterprise_services_manifest.json):
  {
    "componentName": "PDFlex Enterprise Services",
    "version":       "1.0.0",
    "payloadZip":    "recursos_monitoreo.zip",    // opcional
    "payloadSha256": "<64 hex chars>",            // obligatorio si payloadZip presente
    "expectedFiles": ["agente.exe", "cfg.json"],  // opcional
    "windowsServices": [                          // opcional
      {
        "name":        "PDFlexEntMonitor",
        "displayName": "PDFlex Enterprise Monitor (GRUPO OCMX)",
        "description": "Agente de monitoreo PDFlex.",
        "executable":  "agente.exe",
        "arguments":   "--headless",
        "startType":   "auto"
      }
    ],
    "scheduledTasks": [                           // opcional
      {
        "name":       "GRUPO OCMX\\PDFlex Enterprise Monitor",
        "description":"Monitoreo PDFlex Enterprise.",
        "executable": "agente.exe",
        "arguments":  "--tarea",
        "trigger":    "onLogon",
        "runLevel":   "highest"
      }
    ]
  }

Códigos de salida:
  0  EXIT_OK                  – todo correcto
  10 EXIT_MISSING_PREREQ      – archivo o herramienta requerida no encontrada
  20 EXIT_INVALID_PAYLOAD     – manifest, ZIP o hash inválido
  30 EXIT_INCOMPLETE_INSTALL  – fallo al registrar servicio, tarea o copiar archivos
  40 EXIT_STATUS_FAILED       – verificación post-install o status manual falló
  50 EXIT_PERMISSION          – no se pudo escribir HKLM o requiere admin
  90 EXIT_UNEXPECTED          – error no manejado
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import winreg
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


# ── Constantes ────────────────────────────────────────────────────────────────

COMPONENT_NAME = "PDFlex Enterprise Services"
PUBLISHER      = "GRUPO OCMX"
REG_PATH       = r"Software\GRUPO OCMX\PDFlexEnterpriseServices"

_PROG_DATA     = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
INSTALL_DIR    = _PROG_DATA / PUBLISHER / COMPONENT_NAME
LOG_DIR        = INSTALL_DIR / "Logs"
PAYLOAD_DIR    = INSTALL_DIR / "Payload"
PAYLOAD_BACKUP = INSTALL_DIR / "Payload.bak"
STATE_FILE     = INSTALL_DIR / "state.json"

CMD_TIMEOUT    = 30   # segundos para sc.exe / schtasks.exe
SVC_STOP_WAIT  = 15   # segundos máx. esperando STOPPED


# ── Códigos de salida ─────────────────────────────────────────────────────────

EXIT_OK                  = 0
EXIT_MISSING_PREREQ      = 10
EXIT_INVALID_PAYLOAD     = 20
EXIT_INCOMPLETE_INSTALL  = 30
EXIT_STATUS_FAILED       = 40
EXIT_PERMISSION          = 50
EXIT_UNEXPECTED          = 90


# ── Estructuras de datos ──────────────────────────────────────────────────────

@dataclass
class HelperError(Exception):
    code: int
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass
class ServiceSpec:
    """Servicio Windows declarado en manifest.windowsServices."""
    name:         str
    display_name: str
    executable:   str
    description:  str = ""
    start_type:   str = "auto"   # auto | demand | disabled
    arguments:    str = ""


@dataclass
class TaskSpec:
    """Tarea programada declarada en manifest.scheduledTasks."""
    name:        str
    executable:  str
    description: str = ""
    arguments:   str = ""
    trigger:     str = "onlogon"   # onlogon | startup | daily
    run_level:   str = "highest"   # highest | limited


@dataclass
class DeployContext:
    """Registra el estado del deploy para posible rollback."""
    backup_created:   bool       = False
    services_created: List[str]  = field(default_factory=list)
    tasks_created:    List[str]  = field(default_factory=list)


# ── Logging ───────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log_path() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"enterprise_services_{datetime.now().strftime('%Y%m%d')}.log"


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with _log_path().open("a", encoding="utf-8") as fh:
        fh.write(f"[{_utc_now()}] {message}\n")


# ── Utilidades generales ──────────────────────────────────────────────────────

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise HelperError(
            EXIT_INVALID_PAYLOAD, f"No se pudo leer JSON '{path}': {exc}"
        ) from exc


def atomic_copy(src: Path, dst: Path) -> None:
    """Copia src→dst usando un archivo temporal en el mismo directorio (swap atómico)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=dst.name + ".", suffix=".tmp", dir=str(dst.parent)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copy2(src, tmp)
        tmp.replace(dst)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def run_cmd(args: List[str]) -> subprocess.CompletedProcess:
    """Ejecuta un comando del sistema. No lanza por returncode != 0, sí por timeout/no encontrado."""
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise HelperError(
            EXIT_UNEXPECTED, f"Timeout ejecutando '{args[0]}' ({CMD_TIMEOUT}s)."
        ) from exc
    except FileNotFoundError as exc:
        raise HelperError(
            EXIT_MISSING_PREREQ, f"Herramienta del sistema no encontrada: '{args[0]}'."
        ) from exc


# ── Registro HKLM ─────────────────────────────────────────────────────────────

def write_registry(values: Dict[str, object]) -> None:
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_LOCAL_MACHINE, REG_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            for name, value in values.items():
                if isinstance(value, int):
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
                else:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
    except PermissionError as exc:
        raise HelperError(
            EXIT_PERMISSION, "No se pudo escribir HKLM. Ejecuta como Administrador."
        ) from exc
    except OSError as exc:
        raise HelperError(EXIT_PERMISSION, f"Error escribiendo HKLM: {exc}") from exc


def read_registry() -> dict:
    result: dict = {}
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, REG_PATH, 0, winreg.KEY_READ
        ) as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    result[name] = value
                    i += 1
                except OSError:
                    break
    except FileNotFoundError:
        return {}
    return result


def delete_registry_tree() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, REG_PATH)
    except FileNotFoundError:
        return
    except PermissionError as exc:
        raise HelperError(
            EXIT_PERMISSION, "No se pudo borrar HKLM. Ejecuta como Administrador."
        ) from exc
    except OSError as exc:
        raise HelperError(EXIT_PERMISSION, f"Error borrando HKLM: {exc}") from exc


# ── State (state.json) ────────────────────────────────────────────────────────

def write_state(state: dict) -> None:
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(STATE_FILE)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return read_json(STATE_FILE)
    except HelperError:
        return {}


# ── Validación de manifests ───────────────────────────────────────────────────

def validate_manifest(path: Path) -> dict:
    """
    Valida enterprise_services_manifest.json.
    Verifica componentName, version y coherencia de payloadZip/payloadSha256.
    """
    if not path.exists():
        raise HelperError(EXIT_MISSING_PREREQ, f"Manifest no encontrado: {path}")

    data = read_json(path)

    if data.get("componentName") != COMPONENT_NAME:
        raise HelperError(
            EXIT_INVALID_PAYLOAD,
            f"Manifest no corresponde a '{COMPONENT_NAME}' "
            f"(componentName='{data.get('componentName')}').",
        )
    if not str(data.get("version") or "").strip():
        raise HelperError(EXIT_INVALID_PAYLOAD, "Manifest no contiene campo 'version'.")

    payload_zip = str(data.get("payloadZip") or "").strip()
    payload_sha = str(data.get("payloadSha256") or "").strip()
    if payload_zip:
        if payload_zip != Path(payload_zip).name:
            raise HelperError(
                EXIT_INVALID_PAYLOAD,
                "payloadZip debe ser solo nombre de archivo, sin subdirectorios.",
            )
        valid_hex = set("0123456789abcdefABCDEF")
        if len(payload_sha) != 64 or any(c not in valid_hex for c in payload_sha):
            raise HelperError(
                EXIT_INVALID_PAYLOAD,
                "payloadSha256 debe ser un hash SHA-256 válido (64 caracteres hexadecimales).",
            )
    return data


def _parse_service_specs(manifest: dict) -> List[ServiceSpec]:
    specs = []
    for raw in manifest.get("windowsServices") or []:
        if not raw.get("name") or not raw.get("executable"):
            raise HelperError(
                EXIT_INVALID_PAYLOAD,
                "windowsServices: cada entrada requiere 'name' y 'executable'.",
            )
        specs.append(ServiceSpec(
            name         = str(raw["name"]),
            display_name = str(raw.get("displayName") or raw["name"]),
            executable   = str(raw["executable"]),
            description  = str(raw.get("description") or ""),
            start_type   = str(raw.get("startType") or "auto").lower(),
            arguments    = str(raw.get("arguments") or ""),
        ))
    return specs


def _parse_task_specs(manifest: dict) -> List[TaskSpec]:
    specs = []
    for raw in manifest.get("scheduledTasks") or []:
        if not raw.get("name") or not raw.get("executable"):
            raise HelperError(
                EXIT_INVALID_PAYLOAD,
                "scheduledTasks: cada entrada requiere 'name' y 'executable'.",
            )
        specs.append(TaskSpec(
            name        = str(raw["name"]),
            executable  = str(raw["executable"]),
            description = str(raw.get("description") or ""),
            arguments   = str(raw.get("arguments") or ""),
            trigger     = str(raw.get("trigger") or "onLogon").lower(),
            run_level   = str(raw.get("runLevel") or "highest").lower(),
        ))
    return specs


# ── Gestión de Servicios Windows (sc.exe) ─────────────────────────────────────

def _svc_state(name: str) -> Optional[str]:
    """Retorna estado del servicio ('RUNNING', 'STOPPED', …) o None si no existe."""
    result = run_cmd(["sc", "query", name])
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("STATE"):
            parts = stripped.split()
            # Formato SC: "STATE              4  RUNNING"
            return parts[-1] if len(parts) >= 2 else None
    return None


def _svc_stop(name: str) -> None:
    """Detiene el servicio y espera hasta SVC_STOP_WAIT segundos."""
    if _svc_state(name) != "RUNNING":
        return
    log(f"  Deteniendo servicio '{name}'...")
    run_cmd(["sc", "stop", name])
    for _ in range(SVC_STOP_WAIT):
        time.sleep(1)
        state = _svc_state(name)
        if state in ("STOPPED", None):
            break
    log(f"  Servicio '{name}' detenido.")


def register_service(spec: ServiceSpec, payload_dir: Path) -> None:
    """
    Registra o actualiza un Servicio Windows. Idempotente.
    Si ya existe, lo detiene y actualiza la configuración.
    """
    exe_path = payload_dir / spec.executable
    if not exe_path.exists():
        raise HelperError(
            EXIT_INCOMPLETE_INSTALL,
            f"Ejecutable de servicio no encontrado: {exe_path}",
        )

    # sc.exe requiere el espacio entre 'binPath=' y el valor
    bin_path_arg = f'"{exe_path}"'
    if spec.arguments:
        bin_path_arg += f" {spec.arguments}"

    sc_start = {"auto": "auto", "demand": "demand", "disabled": "disabled"}.get(
        spec.start_type, "auto"
    )

    if _svc_state(spec.name) is not None:
        log(f"  Servicio '{spec.name}' existe. Actualizando...")
        _svc_stop(spec.name)
        result = run_cmd([
            "sc", "config", spec.name,
            "binPath=", bin_path_arg,
            "DisplayName=", spec.display_name,
            "start=", sc_start,
        ])
        if result.returncode != 0:
            raise HelperError(
                EXIT_INCOMPLETE_INSTALL,
                f"Error actualizando servicio '{spec.name}': "
                f"{(result.stderr or result.stdout).strip()}",
            )
    else:
        log(f"  Creando servicio '{spec.name}'...")
        result = run_cmd([
            "sc", "create", spec.name,
            "binPath=", bin_path_arg,
            "DisplayName=", spec.display_name,
            "start=", sc_start,
        ])
        if result.returncode != 0:
            raise HelperError(
                EXIT_INCOMPLETE_INSTALL,
                f"Error creando servicio '{spec.name}': "
                f"{(result.stderr or result.stdout).strip()}",
            )

    if spec.description:
        run_cmd(["sc", "description", spec.name, spec.description])

    if sc_start == "auto":
        r = run_cmd(["sc", "start", spec.name])
        if r.returncode not in (0, 1056):  # 1056 = ya está corriendo
            log(f"  Advertencia: no se pudo iniciar '{spec.name}': {r.stderr.strip()}")

    log(f"  Servicio registrado: {spec.name}")


def deregister_service(name: str) -> None:
    """Detiene y elimina un Servicio Windows."""
    if _svc_state(name) is None:
        return
    _svc_stop(name)
    result = run_cmd(["sc", "delete", name])
    if result.returncode != 0:
        log(f"  Advertencia: no se pudo eliminar servicio '{name}': {result.stderr.strip()}")
    else:
        log(f"  Servicio eliminado: {name}")


def _verify_service(name: str) -> Optional[str]:
    """Retorna None si el servicio existe, o descripción del problema."""
    if _svc_state(name) is None:
        return f"Servicio '{name}' no está registrado."
    return None


# ── Gestión de Tareas Programadas (schtasks.exe + XML) ───────────────────────

def _xml_e(s: str) -> str:
    """Escapa caracteres especiales XML."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&apos;")
    )


def _build_task_xml(spec: TaskSpec, exe_path: Path) -> str:
    """
    Genera XML para Task Scheduler (especificación v1.4).
    La codificación del archivo resultante debe ser UTF-16 (requerido por schtasks).
    """
    _triggers = {
        "onlogon": (
            "<LogonTrigger>"
            "<Enabled>true</Enabled>"
            "<Delay>PT30S</Delay>"
            "</LogonTrigger>"
        ),
        "startup": (
            "<BootTrigger>"
            "<Enabled>true</Enabled>"
            "<Delay>PT1M</Delay>"
            "</BootTrigger>"
        ),
        "daily": (
            "<CalendarTrigger>"
            "<StartBoundary>2000-01-01T00:00:00</StartBoundary>"
            "<Enabled>true</Enabled>"
            "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
            "</CalendarTrigger>"
        ),
    }
    trigger_xml = _triggers.get(
        spec.trigger,
        _triggers["onlogon"],  # fallback seguro
    )
    run_level_xml = (
        "HighestAvailable" if spec.run_level == "highest" else "LeastPrivilege"
    )

    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.4"'
        ' xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        f"    <Description>{_xml_e(spec.description)}</Description>\n"
        f"    <Author>{_xml_e(PUBLISHER)}</Author>\n"
        "  </RegistrationInfo>\n"
        f"  <Triggers>{trigger_xml}</Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        "      <LogonType>InteractiveToken</LogonType>\n"
        f"      <RunLevel>{run_level_xml}</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <AllowHardTerminate>false</AllowHardTerminate>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
        "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
        "    <Enabled>true</Enabled>\n"
        "    <Hidden>false</Hidden>\n"
        "    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n"
        "    <WakeToRun>false</WakeToRun>\n"
        "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
        "    <Priority>7</Priority>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{_xml_e(str(exe_path))}</Command>\n"
        f"      <Arguments>{_xml_e(spec.arguments)}</Arguments>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>"
    )


def _task_exists(name: str) -> bool:
    result = run_cmd(["schtasks", "/Query", "/TN", name, "/FO", "LIST"])
    return result.returncode == 0


def register_task(spec: TaskSpec, payload_dir: Path) -> None:
    """
    Registra o actualiza una Tarea Programada vía XML. Idempotente.
    El flag /F fuerza sobrescritura si la tarea ya existe.
    """
    exe_path = payload_dir / spec.executable
    if not exe_path.exists():
        raise HelperError(
            EXIT_INCOMPLETE_INSTALL,
            f"Ejecutable de tarea no encontrado: {exe_path}",
        )

    xml_content = _build_task_xml(spec, exe_path)
    action_label = "Actualizando" if _task_exists(spec.name) else "Creando"
    log(f"  {action_label} tarea '{spec.name}'...")

    fd, xml_tmp = tempfile.mkstemp(suffix=".xml", prefix="pdflex_task_")
    os.close(fd)
    try:
        # schtasks requiere UTF-16 para /XML
        Path(xml_tmp).write_text(xml_content, encoding="utf-16")
        result = run_cmd(["schtasks", "/Create", "/TN", spec.name, "/XML", xml_tmp, "/F"])
        if result.returncode != 0:
            raise HelperError(
                EXIT_INCOMPLETE_INSTALL,
                f"Error registrando tarea '{spec.name}': "
                f"{(result.stderr or result.stdout).strip()}",
            )
    finally:
        try:
            os.unlink(xml_tmp)
        except OSError:
            pass

    log(f"  Tarea registrada: {spec.name}")


def deregister_task(name: str) -> None:
    """Elimina una Tarea Programada."""
    if not _task_exists(name):
        return
    result = run_cmd(["schtasks", "/Delete", "/TN", name, "/F"])
    if result.returncode != 0:
        log(f"  Advertencia: no se pudo eliminar tarea '{name}': {result.stderr.strip()}")
    else:
        log(f"  Tarea eliminada: {name}")


def _verify_task(name: str) -> Optional[str]:
    """Retorna None si la tarea existe, o descripción del problema."""
    if not _task_exists(name):
        return f"Tarea programada '{name}' no está registrada."
    return None


# ── Despliegue de archivos ────────────────────────────────────────────────────

def _extract_payload(zip_path: Path, staging_dir: Path) -> None:
    """
    Extrae zip_path en staging_dir.
    Rechaza rutas absolutas y traversal (../) para evitar path-traversal attacks.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.namelist()
            unsafe = [
                m for m in members
                if m.startswith("/") or ".." in m.replace("\\", "/").split("/")
            ]
            if unsafe:
                raise HelperError(
                    EXIT_INVALID_PAYLOAD,
                    f"ZIP contiene rutas no seguras: {', '.join(unsafe[:5])}",
                )
            zf.extractall(staging_dir)
    except zipfile.BadZipFile as exc:
        raise HelperError(EXIT_INVALID_PAYLOAD, f"Archivo ZIP corrupto: {exc}") from exc
    except HelperError:
        raise
    except Exception as exc:
        raise HelperError(EXIT_INVALID_PAYLOAD, f"Error extrayendo ZIP: {exc}") from exc


def _validate_expected_files(staging_dir: Path, expected: List[str]) -> None:
    """Verifica que todos los archivos de manifest.expectedFiles estén en staging_dir."""
    if not expected:
        return
    missing = [f for f in expected if not (staging_dir / f).exists()]
    if missing:
        raise HelperError(
            EXIT_INVALID_PAYLOAD,
            f"Archivos faltantes en payload ({len(missing)}): {', '.join(missing)}",
        )
    log(f"  Archivos esperados validados: {len(expected)} presentes.")


def _deploy_files(src_dir: Path, dst_dir: Path) -> int:
    """Copia recursivamente src_dir → dst_dir con atomic_copy. Retorna cantidad copiada."""
    count = 0
    for src in src_dir.rglob("*"):
        if src.is_file():
            dst = dst_dir / src.relative_to(src_dir)
            atomic_copy(src, dst)
            count += 1
    return count


# ── Rollback ──────────────────────────────────────────────────────────────────

def _rollback(ctx: DeployContext) -> None:
    """
    Deshace la instalación parcial según lo registrado en ctx.
    Nunca lanza excepciones; loguea cada problema individualmente.
    """
    log("  [ROLLBACK] Iniciando rollback...")

    # 1. Eliminar tareas creadas en esta sesión (en orden inverso)
    for name in reversed(ctx.tasks_created):
        try:
            deregister_task(name)
        except Exception as exc:
            log(f"  [ROLLBACK] Error eliminando tarea '{name}': {exc}")

    # 2. Eliminar servicios creados en esta sesión (en orden inverso)
    for name in reversed(ctx.services_created):
        try:
            deregister_service(name)
        except Exception as exc:
            log(f"  [ROLLBACK] Error eliminando servicio '{name}': {exc}")

    # 3a. Si había backup → restaurar
    if ctx.backup_created and PAYLOAD_BACKUP.exists():
        try:
            if PAYLOAD_DIR.exists():
                shutil.rmtree(PAYLOAD_DIR)
            shutil.copytree(PAYLOAD_BACKUP, PAYLOAD_DIR)
            log("  [ROLLBACK] Payload restaurado desde backup.")
        except Exception as exc:
            log(f"  [ROLLBACK] Error restaurando backup: {exc}")
    # 3b. Sin backup → eliminar payload parcial
    elif not ctx.backup_created and PAYLOAD_DIR.exists():
        try:
            shutil.rmtree(PAYLOAD_DIR)
            log("  [ROLLBACK] Payload parcial eliminado.")
        except Exception as exc:
            log(f"  [ROLLBACK] Error eliminando payload parcial: {exc}")

    # 4. Limpiar backup
    if PAYLOAD_BACKUP.exists():
        try:
            shutil.rmtree(PAYLOAD_BACKUP)
        except Exception as exc:
            log(f"  [ROLLBACK] Error eliminando backup: {exc}")

    # 5. Eliminar state.json
    if STATE_FILE.exists():
        try:
            STATE_FILE.unlink()
        except Exception as exc:
            log(f"  [ROLLBACK] Error eliminando state.json: {exc}")

    # 6. Eliminar clave de registro
    try:
        delete_registry_tree()
    except Exception as exc:
        log(f"  [ROLLBACK] Error eliminando registro HKLM: {exc}")

    log("  [ROLLBACK] Completado.")


# ── Verificación interna (status checks) ─────────────────────────────────────

def _run_status_checks() -> int:
    """
    Ejecuta todas las verificaciones de integridad.
    Retorna EXIT_OK (0) o EXIT_STATUS_FAILED (40).
    No modifica el estado de la instalación (solo-lectura, excepto la clave HKLM).
    """
    problems: List[str] = []

    # 1. Directorio de instalación
    if not INSTALL_DIR.exists():
        problems.append(f"Directorio de instalación no existe: {INSTALL_DIR}")

    # 2. state.json
    if not STATE_FILE.exists():
        problems.append("state.json no encontrado.")

    # 3. Registro HKLM
    if not read_registry():
        problems.append(f"Clave HKLM no encontrada: HKLM\\{REG_PATH}")

    # 4. Manifest instalado + payload hash
    manifest_installed = INSTALL_DIR / "enterprise_services_manifest.json"
    if not manifest_installed.exists():
        problems.append("enterprise_services_manifest.json instalado no existe.")
    else:
        try:
            manifest = validate_manifest(manifest_installed)
            payload_name = str(manifest.get("payloadZip") or "").strip()
            payload_sha  = str(manifest.get("payloadSha256") or "").strip().upper()
            if payload_name:
                staged = PAYLOAD_DIR / payload_name
                if not staged.exists():
                    problems.append(f"Payload instalado no existe: {staged}")
                else:
                    actual_sha = sha256_file(staged)
                    if actual_sha != payload_sha:
                        problems.append(
                            "SHA-256 del payload instalado no coincide con manifest."
                        )
        except HelperError as exc:
            problems.append(str(exc))

    # 5. Servicios y tareas declarados en state.json
    state = load_state()
    for svc_name in state.get("registeredServices") or []:
        problem = _verify_service(svc_name)
        if problem:
            problems.append(problem)
    for task_name in state.get("registeredTasks") or []:
        problem = _verify_task(task_name)
        if problem:
            problems.append(problem)

    if problems:
        for p in problems:
            log(f"  Status FAIL: {p}")
        try:
            write_registry({
                "LastStatus":   "FAILED",
                "LastExitCode": EXIT_STATUS_FAILED,
                "LastLogPath":  str(_log_path()),
            })
        except Exception:
            pass
        return EXIT_STATUS_FAILED

    log("  Status OK.")
    try:
        write_registry({
            "LastStatus":   "OK",
            "LastExitCode": EXIT_OK,
            "LastLogPath":  str(_log_path()),
        })
    except Exception:
        pass
    return EXIT_OK


# ── Comandos principales ──────────────────────────────────────────────────────

def install(args: argparse.Namespace) -> int:
    """
    Instala o actualiza PDFlex Enterprise Services.

    Flujo completo:
      1.  Valida privilegios de administrador.
      2.  Valida enterprise_services_manifest.json y enterprise_services_build_manifest.json.
      3.  Verifica SHA-256 del payload ZIP.
      4.  Idempotencia: misma versión + status OK → retorna 0 sin modificar nada.
      5.  Extrae ZIP a staging temporal con validación de rutas seguras.
      6.  Valida archivos esperados (manifest.expectedFiles).
      7.  Valida ejecutables de servicios y tareas dentro del payload extraído.
      8.  Hace backup del payload anterior (si existe).
      9.  Despliega archivos a Payload/ con atomic_copy.
      10. Registra Servicios Windows declarados (sc.exe). Idempotente.
      11. Registra Tareas Programadas declaradas (schtasks + XML). Idempotente.
      12. Escribe state.json y HKLM (estado PENDING).
      13. Ejecuta verificación post-install (_run_status_checks).
      14. En éxito: actualiza state/HKLM a OK y elimina backup + staging.
      15. En error: rollback completo y relanza la excepción.
    """
    log("=" * 68)
    log(f"INSTALL iniciado. PDFlex version: {args.pdflex_version or 'N/A'}")

    # ── 1. Admin ────────────────────────────────────────────────────────────
    if not is_admin():
        raise HelperError(EXIT_PERMISSION, "Se requieren privilegios de Administrador.")

    # ── 2. Manifests ────────────────────────────────────────────────────────
    manifest_path       = Path(args.manifest).resolve()
    build_manifest_path = Path(args.build_manifest).resolve()

    manifest = validate_manifest(manifest_path)
    version  = str(manifest["version"])

    if not build_manifest_path.exists():
        raise HelperError(
            EXIT_MISSING_PREREQ,
            f"Build manifest no encontrado: {build_manifest_path}",
        )
    build_manifest = read_json(build_manifest_path)
    log(f"  Version a instalar:  {version}")
    log(f"  Build timestamp:     {build_manifest.get('builtAtUtc', 'N/A')}")
    log(f"  Mode:                {build_manifest.get('mode', 'N/A')}")

    # ── 3. Payload ──────────────────────────────────────────────────────────
    expected_zip  = str(manifest.get("payloadZip") or "").strip()
    expected_sha  = str(manifest.get("payloadSha256") or "").strip().upper()
    payload_path: Optional[Path] = Path(args.payload).resolve() if args.payload else None

    if expected_zip:
        if payload_path is None:
            raise HelperError(
                EXIT_INVALID_PAYLOAD,
                "Manifest declara 'payloadZip' pero no se proporcionó --payload.",
            )
        if payload_path.name != expected_zip:
            raise HelperError(
                EXIT_INVALID_PAYLOAD,
                f"Nombre del payload recibido ('{payload_path.name}') "
                f"no coincide con manifest ('{expected_zip}').",
            )
        if not payload_path.exists():
            raise HelperError(EXIT_INVALID_PAYLOAD, f"Payload no encontrado: {payload_path}")

        actual_sha = sha256_file(payload_path)
        if actual_sha != expected_sha:
            raise HelperError(
                EXIT_INVALID_PAYLOAD,
                f"SHA-256 del payload no coincide.\n"
                f"  Esperado:  {expected_sha}\n"
                f"  Calculado: {actual_sha}",
            )
        log(f"  SHA-256 verificado: {actual_sha[:16]}…")

    # ── Parsear specs de servicios/tareas y archivos esperados ────────────
    service_specs  = _parse_service_specs(manifest)
    task_specs     = _parse_task_specs(manifest)
    expected_files = [str(f) for f in (manifest.get("expectedFiles") or [])]

    log(f"  Servicios declarados: {len(service_specs)}")
    log(f"  Tareas declaradas:    {len(task_specs)}")
    log(f"  Archivos esperados:   {len(expected_files)}")

    # ── 4. Idempotencia ─────────────────────────────────────────────────────
    current_state = load_state()
    if current_state.get("version") == version:
        log("  Misma versión detectada. Verificando estado actual…")
        try:
            if _run_status_checks() == EXIT_OK:
                log("  Instalación ya correcta para esta versión. Sin cambios.")
                return EXIT_OK
            log("  Estado no saludable. Procediendo con reinstalación…")
        except Exception as exc:
            log(f"  Verificación previa falló ({exc}). Reinstalando…")

    # ── 5-7. Extracción y validación del payload ───────────────────────────
    ctx: DeployContext = DeployContext()
    staging_dir: Optional[Path] = None

    try:
        if expected_zip and payload_path is not None:
            staging_dir = Path(tempfile.mkdtemp(prefix="pdflex_es_"))
            log(f"  Staging temporal: {staging_dir}")

            log(f"  Extrayendo {expected_zip}…")
            _extract_payload(payload_path, staging_dir)
            _validate_expected_files(staging_dir, expected_files)

            # Verificar ejecutables de servicios y tareas dentro del ZIP
            for spec in service_specs:
                if not (staging_dir / spec.executable).exists():
                    raise HelperError(
                        EXIT_INVALID_PAYLOAD,
                        f"Ejecutable de servicio '{spec.executable}' "
                        f"no encontrado dentro del payload.",
                    )
            for spec in task_specs:
                if not (staging_dir / spec.executable).exists():
                    raise HelperError(
                        EXIT_INVALID_PAYLOAD,
                        f"Ejecutable de tarea '{spec.executable}' "
                        f"no encontrado dentro del payload.",
                    )

        # ── 8. Backup del payload existente ─────────────────────────────────
        INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)

        if PAYLOAD_DIR.exists() and any(PAYLOAD_DIR.iterdir()):
            log("  Creando backup del payload existente…")
            if PAYLOAD_BACKUP.exists():
                shutil.rmtree(PAYLOAD_BACKUP)
            shutil.copytree(PAYLOAD_DIR, PAYLOAD_BACKUP)
            ctx.backup_created = True
            log("  Backup creado.")

        # ── 9. Desplegar archivos de payload ─────────────────────────────────
        if expected_zip and staging_dir is not None:
            log(f"  Desplegando archivos a {PAYLOAD_DIR}…")
            count = _deploy_files(staging_dir, PAYLOAD_DIR)
            log(f"  Archivos desplegados: {count}")

        # Copiar manifests a INSTALL_DIR
        atomic_copy(manifest_path,       INSTALL_DIR / "enterprise_services_manifest.json")
        atomic_copy(build_manifest_path, INSTALL_DIR / "enterprise_services_build_manifest.json")

        # ── 10. Registrar Servicios Windows ──────────────────────────────────
        for spec in service_specs:
            log(f"  Registrando servicio: {spec.name}")
            existed = _svc_state(spec.name) is not None
            register_service(spec, PAYLOAD_DIR)
            if not existed:
                ctx.services_created.append(spec.name)

        # ── 11. Registrar Tareas Programadas ─────────────────────────────────
        for spec in task_specs:
            log(f"  Registrando tarea: {spec.name}")
            existed = _task_exists(spec.name)
            register_task(spec, PAYLOAD_DIR)
            if not existed:
                ctx.tasks_created.append(spec.name)

        # ── 12. Escribir estado (PENDING hasta confirmar status) ──────────────
        payload_size = payload_path.stat().st_size if payload_path and expected_zip else 0
        state: dict = {
            "componentName":            COMPONENT_NAME,
            "version":                  version,
            "installPath":              str(INSTALL_DIR),
            "installedByPdflexVersion": str(args.pdflex_version or ""),
            "installMode":              "Required",
            "lastInstallUtc":           _utc_now(),
            "lastStatus":               "PENDING",
            "lastExitCode":             -1,
            "lastLogPath":              str(_log_path()),
            "payloadFile":              expected_zip,
            "payloadSha256":            expected_sha,
            "payloadSizeBytes":         payload_size,
            "registeredServices":       [s.name for s in service_specs],
            "registeredTasks":          [t.name for t in task_specs],
        }
        write_state(state)
        write_registry({
            "Version":                  version,
            "InstallPath":              str(INSTALL_DIR),
            "InstalledByPdflexVersion": str(args.pdflex_version or ""),
            "InstallMode":              "Required",
            "LastInstallUtc":           _utc_now(),
            "LastStatus":               "PENDING",
            "LastExitCode":             -1,
            "LastLogPath":              str(_log_path()),
        })

        # ── 13. Verificación post-install ─────────────────────────────────────
        log("  Ejecutando verificación post-install…")
        status_code = _run_status_checks()
        if status_code != EXIT_OK:
            raise HelperError(
                EXIT_STATUS_FAILED,
                "La verificación post-install falló. Revisa el log para detalles.",
            )

        # ── 14. Éxito: actualizar estado y limpiar ─────────────────────────
        state["lastStatus"]   = "OK"
        state["lastExitCode"] = EXIT_OK
        write_state(state)

        if ctx.backup_created and PAYLOAD_BACKUP.exists():
            shutil.rmtree(PAYLOAD_BACKUP)
            log("  Backup eliminado tras instalación exitosa.")

        log(f"INSTALL completado exitosamente. Versión: {version}")
        return EXIT_OK

    except Exception as install_exc:
        # Loguear el error con detalle
        if isinstance(install_exc, HelperError):
            log(f"ERROR {install_exc.code}: {install_exc.message}")
        else:
            log(f"ERROR INESPERADO: {install_exc}")
            log(traceback.format_exc())

        # ── 15. Rollback ───────────────────────────────────────────────────
        try:
            _rollback(ctx)
        except Exception as rb_exc:
            log(f"Error durante rollback: {rb_exc}")

        raise  # main() captura y retorna el código de salida correcto

    finally:
        # Siempre limpiar staging temporal
        if staging_dir is not None and staging_dir.exists():
            try:
                shutil.rmtree(staging_dir)
                log(f"  Staging temporal eliminado.")
            except Exception as exc:
                log(f"  No se pudo limpiar staging temporal: {exc}")


def status(args: argparse.Namespace) -> int:
    """
    Verifica la integridad completa de la instalación.
    Comprueba: directorio, state.json, manifest, SHA-256 del payload,
    servicios Windows y tareas programadas declarados en state.
    Retorna 0 solo si todo está correcto.
    """
    log("STATUS iniciado.")
    code = _run_status_checks()
    log(f"STATUS finalizado: {'OK' if code == EXIT_OK else 'FAILED'} (exit={code})")
    return code


def uninstall(args: argparse.Namespace) -> int:
    """
    Desinstala PDFlex Enterprise Services completamente:
    elimina servicios, tareas, archivos en ProgramData y la clave HKLM.
    """
    log("=" * 68)
    log("UNINSTALL iniciado.")

    if not is_admin():
        raise HelperError(EXIT_PERMISSION, "Se requieren privilegios de Administrador.")

    state = load_state()

    # Eliminar servicios registrados
    for svc_name in state.get("registeredServices") or []:
        log(f"  Eliminando servicio: {svc_name}")
        try:
            deregister_service(svc_name)
        except Exception as exc:
            log(f"  Error eliminando servicio '{svc_name}': {exc}")

    # Eliminar tareas registradas
    for task_name in state.get("registeredTasks") or []:
        log(f"  Eliminando tarea: {task_name}")
        try:
            deregister_task(task_name)
        except Exception as exc:
            log(f"  Error eliminando tarea '{task_name}': {exc}")

    # Eliminar directorio completo (incluye logs, payload, state)
    if INSTALL_DIR.exists():
        try:
            shutil.rmtree(INSTALL_DIR)
            log(f"  Directorio eliminado: {INSTALL_DIR}")
        except Exception as exc:
            raise HelperError(
                EXIT_INCOMPLETE_INSTALL,
                f"No se pudo eliminar el directorio de instalación: {exc}",
            ) from exc

    # Eliminar clave HKLM
    try:
        delete_registry_tree()
        log(f"  Registro eliminado: HKLM\\{REG_PATH}")
    except Exception as exc:
        log(f"  Advertencia: error eliminando registro: {exc}")

    log("UNINSTALL completado.")
    return EXIT_OK


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="PDFlexEnterpriseServices",
        description=(
            f"Administrador administrativo de {COMPONENT_NAME}. "
            "Requiere ejecutar como Administrador."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # install
    p_install = sub.add_parser(
        "install",
        help="Instala o actualiza PDFlex Enterprise Services.",
    )
    p_install.add_argument(
        "--quiet", action="store_true",
        help="Suprime mensajes en stderr (solo códigos de salida y log).",
    )
    p_install.add_argument(
        "--pdflex-version", default="", metavar="VER",
        help="Versión de PDFlex que instala este componente (para trazabilidad).",
    )
    p_install.add_argument(
        "--manifest", required=True, metavar="PATH",
        help="Ruta a enterprise_services_manifest.json.",
    )
    p_install.add_argument(
        "--build-manifest", required=True, metavar="PATH",
        help="Ruta a enterprise_services_build_manifest.json (generado por build_setup.ps1).",
    )
    p_install.add_argument(
        "--payload", default="", metavar="PATH",
        help="Ruta al ZIP del payload (obligatorio si manifest.payloadZip está definido).",
    )
    p_install.set_defaults(func=install)

    # status
    p_status = sub.add_parser(
        "status",
        help="Verifica la integridad de la instalación.",
    )
    p_status.add_argument("--quiet", action="store_true")
    p_status.set_defaults(func=status)

    # uninstall
    p_uninstall = sub.add_parser(
        "uninstall",
        help="Desinstala PDFlex Enterprise Services completamente.",
    )
    p_uninstall.add_argument("--quiet", action="store_true")
    p_uninstall.set_defaults(func=uninstall)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))

    except HelperError as exc:
        log(f"HelperError {exc.code}: {exc.message}")
        if not getattr(args, "quiet", False):
            print(exc.message, file=sys.stderr)
        # Intentar registrar el fallo en HKLM (puede fallar si el error fue de permisos)
        try:
            write_registry({
                "LastStatus":   "FAILED",
                "LastExitCode": exc.code,
                "LastLogPath":  str(_log_path()),
            })
        except Exception:
            pass
        return int(exc.code)

    except Exception as exc:
        log(f"ERROR INESPERADO (main): {exc}")
        log(traceback.format_exc())
        if not getattr(args, "quiet", False):
            print(str(exc), file=sys.stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    raise SystemExit(main())
