"""Almacenamiento local de licencia: registro HKLM + archivo ProgramData,
ambos cifrados con DPAPI a nivel de máquina (CRYPTPROTECT_LOCAL_MACHINE,
no user-scope — la licencia es por equipo, no por usuario de Windows).

Registro en Software\\GRUPO OCMX\\PDFlexLicense — clave HERMANA de
Software\\GRUPO OCMX\\PDFlex, nunca anidada, porque esa última tiene
Flags: uninsdeletekey en installer.iss.

Ver docs/superpowers/specs/2026-07-11-pdflex-licensing-design.md §7.
"""

from __future__ import annotations

import base64
from pathlib import Path

_REGISTRY_PATH = r"SOFTWARE\GRUPO OCMX\PDFlexLicense"
_REGISTRY_VALUE = "Token"
_FILE_PATH = Path(r"C:\ProgramData\GRUPO OCMX\PDFlex\License\license.dat")

CRYPTPROTECT_LOCAL_MACHINE = 0x4


def _dpapi_protect(data: bytes) -> bytes:
    import win32crypt

    return win32crypt.CryptProtectData(
        data, "PDFlex License", None, None, None, CRYPTPROTECT_LOCAL_MACHINE
    )


def _dpapi_unprotect(blob: bytes) -> bytes:
    import win32crypt

    _description, data = win32crypt.CryptUnprotectData(
        blob, None, None, None, CRYPTPROTECT_LOCAL_MACHINE
    )
    return data


def _registry_write(protected_b64: str) -> None:
    import winreg

    key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, _REGISTRY_PATH)
    try:
        winreg.SetValueEx(key, _REGISTRY_VALUE, 0, winreg.REG_SZ, protected_b64)
    finally:
        winreg.CloseKey(key)


def _registry_read() -> str | None:
    import winreg

    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REGISTRY_PATH)
    except OSError:
        return None
    try:
        value, _ = winreg.QueryValueEx(key, _REGISTRY_VALUE)
        return str(value)
    except OSError:
        return None
    finally:
        winreg.CloseKey(key)


def _registry_delete() -> None:
    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, _REGISTRY_PATH, 0, winreg.KEY_SET_VALUE
        )
    except OSError:
        return
    try:
        winreg.DeleteValue(key, _REGISTRY_VALUE)
    except OSError:
        pass
    finally:
        winreg.CloseKey(key)


def _file_write(protected: bytes) -> None:
    _FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FILE_PATH.write_bytes(protected)


def _file_read() -> bytes | None:
    if not _FILE_PATH.exists():
        return None
    try:
        return _FILE_PATH.read_bytes()
    except OSError:
        return None


def _file_delete() -> None:
    try:
        _FILE_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def save_token(token: str) -> None:
    """Guarda `token` cifrado con DPAPI, por partida doble (registro + archivo)."""
    protected = _dpapi_protect(token.encode("utf-8"))
    _registry_write(base64.b64encode(protected).decode("ascii"))
    _file_write(protected)


def _repair_if_needed(
    good: bytes, registry_bytes: bytes | None, file_bytes: bytes | None
) -> None:
    if registry_bytes != good:
        _registry_write(base64.b64encode(good).decode("ascii"))
    if file_bytes != good:
        _file_write(good)


def load_token() -> str | None:
    """Recupera el token guardado, reconciliando registro y archivo.

    Si una copia falta o no descifra, se repara desde la otra. Si ninguna
    descifra correctamente, devuelve None — nunca se asume activado
    por defecto.
    """
    registry_b64 = _registry_read()
    file_bytes = _file_read()
    registry_bytes = base64.b64decode(registry_b64) if registry_b64 else None

    for candidate in (registry_bytes, file_bytes):
        if candidate is None:
            continue
        try:
            token_bytes = _dpapi_unprotect(candidate)
        except Exception:
            continue
        _repair_if_needed(candidate, registry_bytes, file_bytes)
        return token_bytes.decode("utf-8")

    return None


def clear_token() -> None:
    """Borra ambas copias (usado tras una desactivación exitosa)."""
    _registry_delete()
    _file_delete()
