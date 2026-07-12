# PDFlex License Activation System (Client) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the PDFlex-side (client) of the license activation system: hardware-bound, cryptographically-signed license tokens, a blocking activation gate at startup, periodic silent revalidation, and self-service license transfer.

**Architecture:** Nine new modules under `core/` and `ui/license/`, wired into `main.py`'s startup sequence before `ShellWindow` is constructed, following the exact `QObject`+`QThread`+`crash_handler` pattern already used by `core/updater.py`. Two small, surgical changes to `main.py` and `installer.iss`. No changes to `shell/shell_window.py` — background revalidation is scheduled from `main.py` directly to avoid touching that large, sensitive file.

**Tech Stack:** Python 3.11, PySide6, `cryptography` (Ed25519 — new dependency), `pywin32` (already a dependency: `winreg`, `win32crypt`, `win32api`, `win32com.client`), `requests` (already a dependency).

**Spec:** `docs/superpowers/specs/2026-07-11-pdflex-licensing-design.md` — every task below implements one or more numbered sections of that spec. Read it once before starting; this plan repeats the exact values/algorithms needed per-task so you should not need to re-open it mid-task.

## Global Constraints

- 1 license key = 1 machine. No trial — PDFlex is fully blocked until activated (spec §1.1).
- Offline grace: `LICENSE_OFFLINE_GRACE_DAYS = 14`. Revalidation warning starts `LICENSE_REVALIDATE_WARNING_DAYS = 3` days before grace runs out.
- Self-service transfer limit: `LICENSE_TRANSFER_LIMIT = 3` per `LICENSE_TRANSFER_WINDOW_DAYS = 90` (enforced server-side; client just surfaces the count).
- License key format: `PDFX-XXXXX-XXXXX-XXXXX-CCCC`, Crockford32 alphabet `0123456789ABCDEFGHJKMNPQRSTVWXYZ`, checksum = low 20 bits of `zlib.crc32` (IEEE 802.3) of the 15-char payload, encoded big-endian as 4 more Crockford32 chars. Verified worked example: payload `ABCDEFGHJKMNPQR` → key `PDFX-ABCDE-FGHJK-MNPQR-718B`.
- Token format: `PLT1.<base64url-no-padding(claims_json)>.<base64url-no-padding(ed25519_signature)>`. Signature is verified over the raw decoded claims bytes, never a re-serialization.
- Registry storage path is `HKLM\Software\GRUPO OCMX\PDFlexLicense` — a **sibling** of `Software\GRUPO OCMX\PDFlex`, never nested under it (that key has `Flags: uninsdeletekey` in `installer.iss` and would wipe a nested license key on uninstall).
- File storage path is `C:\ProgramData\GRUPO OCMX\PDFlex\License\license.dat`. Both copies are DPAPI-protected with `CRYPTPROTECT_LOCAL_MACHINE` (machine-scope, not user-scope — the license is per-machine).
- New dependency: add `cryptography` to `requirements.txt`.
- Reuse `core.update_config.UPDATE_API_BASE` and `core.update_config.APP_VERSION` — do not duplicate these constants.
- Run tests with the project's real interpreter (has PySide6/pywin32/cryptography installed — the bare `py`/system Python does not):
  `.venv_nuitka/Scripts/python.exe -m pytest <path> -v`
- Qt-based tests must set `QT_QPA_PLATFORM=offscreen` before importing PySide6, exactly like the existing `tests/test_crash_handler.py` and `tests/test_organizador_window.py` do.

---

### Task 1: `core/license_config.py` — constants

**Files:**
- Create: `core/license_config.py`
- Test: `tests/test_license_config.py`

**Interfaces:**
- Produces: `LICENSE_API_BASE: str`, `LICENSE_APP_KEY: str`, `LICENSE_CHECK_TIMEOUT_S: int`, `LICENSE_MAX_RETRIES: int`, `LICENSE_RETRY_DELAY_S: int`, `LICENSE_OFFLINE_GRACE_DAYS: int`, `LICENSE_REVALIDATE_WARNING_DAYS: int`, `LICENSE_TRANSFER_LIMIT: int`, `LICENSE_TRANSFER_WINDOW_DAYS: int`, `LICENSE_PUBLIC_KEY_ED25519: str`, `FINGERPRINT_PEPPER: str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_license_config.py`:

```python
from core import license_config as lc
from core.update_config import UPDATE_API_BASE


def test_license_api_base_matches_updater():
    assert lc.LICENSE_API_BASE == UPDATE_API_BASE


def test_license_app_key_is_pdflex():
    assert lc.LICENSE_APP_KEY == "pdflex"


def test_offline_grace_is_fourteen_days():
    assert lc.LICENSE_OFFLINE_GRACE_DAYS == 14


def test_revalidate_warning_is_three_days():
    assert lc.LICENSE_REVALIDATE_WARNING_DAYS == 3


def test_transfer_limit_settings():
    assert lc.LICENSE_TRANSFER_LIMIT == 3
    assert lc.LICENSE_TRANSFER_WINDOW_DAYS == 90


def test_public_key_and_pepper_are_nonempty_strings():
    assert isinstance(lc.LICENSE_PUBLIC_KEY_ED25519, str) and lc.LICENSE_PUBLIC_KEY_ED25519
    assert isinstance(lc.FINGERPRINT_PEPPER, str) and lc.FINGERPRINT_PEPPER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.license_config'`

- [ ] **Step 3: Write minimal implementation**

Create `core/license_config.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_config.py -v`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add core/license_config.py tests/test_license_config.py
git commit -m "feat: add license system configuration constants"
```

---

### Task 2: `core/machine_fingerprint.py` — hardware fingerprint

**Files:**
- Create: `core/machine_fingerprint.py`
- Test: `tests/test_machine_fingerprint.py`

**Interfaces:**
- Consumes: `core.license_config.FINGERPRINT_PEPPER` (Task 1).
- Produces: `class Fingerprint` (frozen dataclass with `machine_guid_hash: str`, `volume_serial_hash: str`, `cpu_id_hash: str`, `composite_hash: str`, and `.to_dict() -> dict`), `compute_fingerprint() -> Fingerprint`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_machine_fingerprint.py`:

```python
from unittest.mock import patch

from core import machine_fingerprint as mf


def test_hash_component_is_deterministic_and_hex():
    first = mf._hash_component("same-input")
    second = mf._hash_component("same-input")
    assert first == second
    assert len(first) == 64
    int(first, 16)


def test_hash_component_differs_for_different_input():
    assert mf._hash_component("input-a") != mf._hash_component("input-b")


def test_compute_fingerprint_combines_all_three_sources():
    with patch.object(mf, "_read_machine_guid", return_value="guid-123"), \
         patch.object(mf, "_read_volume_serial", return_value="serial-456"), \
         patch.object(mf, "_read_cpu_id", return_value="cpu-789"):
        fp = mf.compute_fingerprint()

    assert fp.machine_guid_hash == mf._hash_component("guid-123")
    assert fp.volume_serial_hash == mf._hash_component("serial-456")
    assert fp.cpu_id_hash == mf._hash_component("cpu-789")
    assert len(fp.composite_hash) == 64
    int(fp.composite_hash, 16)


def test_compute_fingerprint_is_stable_for_same_raw_values():
    with patch.object(mf, "_read_machine_guid", return_value="guid-123"), \
         patch.object(mf, "_read_volume_serial", return_value="serial-456"), \
         patch.object(mf, "_read_cpu_id", return_value="cpu-789"):
        first = mf.compute_fingerprint()
        second = mf.compute_fingerprint()

    assert first == second


def test_compute_fingerprint_changes_if_any_component_changes():
    with patch.object(mf, "_read_machine_guid", return_value="guid-123"), \
         patch.object(mf, "_read_volume_serial", return_value="serial-456"), \
         patch.object(mf, "_read_cpu_id", return_value="cpu-789"):
        baseline = mf.compute_fingerprint()

    with patch.object(mf, "_read_machine_guid", return_value="guid-DIFFERENT"), \
         patch.object(mf, "_read_volume_serial", return_value="serial-456"), \
         patch.object(mf, "_read_cpu_id", return_value="cpu-789"):
        changed = mf.compute_fingerprint()

    assert baseline.composite_hash != changed.composite_hash


def test_to_dict_contains_all_four_hashes():
    fp = mf.Fingerprint("a", "b", "c", "d")
    assert fp.to_dict() == {
        "machine_guid_hash": "a",
        "volume_serial_hash": "b",
        "cpu_id_hash": "c",
        "composite_hash": "d",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_machine_fingerprint.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.machine_fingerprint'`

- [ ] **Step 3: Write minimal implementation**

Create `core/machine_fingerprint.py`:

```python
"""Fingerprint de hardware para atar una activación de licencia a un equipo.

Ver docs/superpowers/specs/2026-07-11-pdflex-licensing-design.md §3.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from core import license_config


@dataclass(frozen=True)
class Fingerprint:
    machine_guid_hash: str
    volume_serial_hash: str
    cpu_id_hash: str
    composite_hash: str

    def to_dict(self) -> dict:
        return {
            "machine_guid_hash": self.machine_guid_hash,
            "volume_serial_hash": self.volume_serial_hash,
            "cpu_id_hash": self.cpu_id_hash,
            "composite_hash": self.composite_hash,
        }


def _hash_component(raw_value: str) -> str:
    return hmac.new(
        license_config.FINGERPRINT_PEPPER.encode("utf-8"),
        raw_value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _read_machine_guid() -> str:
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
    ) as key:
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(value)


def _read_volume_serial() -> str:
    import win32api

    _, serial, _, _, _ = win32api.GetVolumeInformation("C:\\")
    return str(serial)


def _read_cpu_id() -> str:
    import win32com.client

    wmi = win32com.client.GetObject("winmgmts:")
    for processor in wmi.InstancesOf("Win32_Processor"):
        processor_id = getattr(processor, "ProcessorId", None)
        if processor_id:
            return str(processor_id)
    return ""


def compute_fingerprint() -> Fingerprint:
    machine_guid_hash = _hash_component(_read_machine_guid())
    volume_serial_hash = _hash_component(_read_volume_serial())
    cpu_id_hash = _hash_component(_read_cpu_id())
    composite_hash = hashlib.sha256(
        f"{machine_guid_hash}|{volume_serial_hash}|{cpu_id_hash}".encode("utf-8")
    ).hexdigest()
    return Fingerprint(
        machine_guid_hash=machine_guid_hash,
        volume_serial_hash=volume_serial_hash,
        cpu_id_hash=cpu_id_hash,
        composite_hash=composite_hash,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_machine_fingerprint.py -v`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add core/machine_fingerprint.py tests/test_machine_fingerprint.py
git commit -m "feat: add hardware fingerprint computation for license binding"
```

---

### Task 3: `core/license_key_format.py` — key checksum validation

**Files:**
- Create: `core/license_key_format.py`
- Test: `tests/test_license_key_format.py`

**Interfaces:**
- Produces: `is_valid_key_format(raw_key: str) -> bool`, `normalize_key(raw_key: str) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_license_key_format.py`. These fixtures were computed and verified with the real implementation (`zlib.crc32`, low-20-bits mask, Crockford32 big-endian encode) before writing this plan — they are not hand-derived:

```python
from core.license_key_format import is_valid_key_format, normalize_key


def test_valid_key_passes():
    assert is_valid_key_format("PDFX-ABCDE-FGHJK-MNPQR-718B") is True


def test_valid_key_with_all_zero_groups_passes():
    assert is_valid_key_format("PDFX-00000-00000-00000-0SHN") is True


def test_lowercase_key_is_normalized_and_passes():
    assert is_valid_key_format("pdfx-abcde-fghjk-mnpqr-718b") is True


def test_tampered_group_fails():
    assert is_valid_key_format("PDFX-ABCDE-FGHJK-MNPQS-718B") is False


def test_tampered_checksum_fails():
    assert is_valid_key_format("PDFX-ABCDE-FGHJK-MNPQR-718C") is False


def test_missing_group_fails():
    assert is_valid_key_format("PDFX-ABCDE-FGHJK-MNPQR") is False


def test_excluded_alphabet_character_fails():
    # 'I' no está en el alfabeto Crockford32 usado por PDFlex.
    assert is_valid_key_format("PDFX-ABCDI-FGHJK-MNPQR-0000") is False


def test_wrong_prefix_fails():
    assert is_valid_key_format("XXXX-ABCDE-FGHJK-MNPQR-718B") is False


def test_empty_string_fails():
    assert is_valid_key_format("") is False


def test_normalize_key_uppercases_and_strips_whitespace():
    assert normalize_key("  pdfx-abcde-fghjk-mnpqr-718b  ") == "PDFX-ABCDE-FGHJK-MNPQR-718B"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_key_format.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.license_key_format'`

- [ ] **Step 3: Write minimal implementation**

Create `core/license_key_format.py`:

```python
"""Generación y validación del formato de clave de licencia de PDFlex.

Formato: PDFX-XXXXX-XXXXX-XXXXX-CCCC. El servidor genera las claves; el
cliente solo valida el checksum localmente antes de llamar a la red.
Ver docs/superpowers/specs/2026-07-11-pdflex-licensing-design.md §5.
"""

from __future__ import annotations

import zlib

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ALPHABET_INDEX = {char: i for i, char in enumerate(_ALPHABET)}
_PREFIX = "PDFX"


def _checksum(payload: str) -> str:
    crc = zlib.crc32(payload.encode("ascii")) & 0xFFFFFFFF
    bits = crc & 0xFFFFF
    return "".join(_ALPHABET[(bits >> shift) & 0x1F] for shift in (15, 10, 5, 0))


def normalize_key(raw_key: str) -> str:
    """Normaliza a mayúsculas sin espacios, sin validar el checksum."""
    return raw_key.strip().upper()


def is_valid_key_format(raw_key: str) -> bool:
    """True si `raw_key` tiene el formato y el checksum correctos.

    No verifica contra el servidor — solo detecta typos localmente.
    """
    candidate = normalize_key(raw_key)
    parts = candidate.split("-")
    if len(parts) != 5:
        return False

    prefix, group1, group2, group3, checksum = parts
    if prefix != _PREFIX:
        return False
    if len(group1) != 5 or len(group2) != 5 or len(group3) != 5 or len(checksum) != 4:
        return False

    payload = group1 + group2 + group3
    if not all(char in _ALPHABET_INDEX for char in payload + checksum):
        return False

    return _checksum(payload) == checksum
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_key_format.py -v`
Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add core/license_key_format.py tests/test_license_key_format.py
git commit -m "feat: add license key format and checksum validation"
```

---

### Task 4: `core/license_token.py` — signed token verification

**Files:**
- Create: `core/license_token.py`
- Modify: `requirements.txt` (add `cryptography`)
- Test: `tests/test_license_token.py`

**Interfaces:**
- Consumes: `core.license_config.LICENSE_PUBLIC_KEY_ED25519` (Task 1, read at call time via module attribute, not imported by name, so tests can monkeypatch it).
- Produces: `class LicenseClaims` (frozen dataclass: `key_id: str`, `fingerprint: str`, `issued_at: datetime`, `valid_until: datetime`, `license_expires_at: datetime | None`, `status: str`, `customer_name: str`, `app: str`, `seats_allowed: int`), `class VerifiedLicense` (frozen dataclass: `claims: LicenseClaims`, `needs_revalidation: bool`), exception hierarchy `LicenseInvalidError` → `LicenseFormatError`, `LicenseSignatureError`, `LicenseFingerprintMismatchError`, `LicenseRevokedError`, `LicenseExpiredError`, and `verify_token(token: str, expected_fingerprint: str, now: datetime) -> VerifiedLicense` (raises `LicenseInvalidError` subclasses; `now` must be timezone-aware UTC).

- [ ] **Step 1: Add the new dependency**

Add to `requirements.txt` (after `requests>=2.31.0`):

```
cryptography>=42.0.0,<46
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_license_token.py`:

```python
import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core import license_config
from core import license_token as lt


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@pytest.fixture()
def keypair(monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes_raw()
    monkeypatch.setattr(
        license_config,
        "LICENSE_PUBLIC_KEY_ED25519",
        base64.b64encode(public_bytes).decode("ascii"),
    )
    return private_key


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _make_token(private_key, **overrides) -> str:
    now = overrides.pop("now", datetime.now(timezone.utc))
    claims = {
        "v": 1,
        "key_id": "key-abc",
        "fingerprint": "fp-hash-123",
        "issued_at": _iso(now),
        "valid_until": _iso(now + timedelta(days=14)),
        "license_expires_at": None,
        "status": "active",
        "customer_name": "Empresa de Prueba",
        "app": "pdflex",
        "seats_allowed": 1,
    }
    claims.update(overrides)
    claims_bytes = json.dumps(claims, separators=(",", ":")).encode("utf-8")
    signature = private_key.sign(claims_bytes)
    return "PLT1." + _b64url_encode(claims_bytes) + "." + _b64url_encode(signature)


def test_verify_token_accepts_valid_token(keypair):
    now = datetime.now(timezone.utc)
    token = _make_token(keypair, now=now)

    result = lt.verify_token(token, expected_fingerprint="fp-hash-123", now=now)

    assert result.claims.key_id == "key-abc"
    assert result.claims.status == "active"
    assert result.needs_revalidation is False


def test_verify_token_rejects_tampered_signature(keypair):
    now = datetime.now(timezone.utc)
    token = _make_token(keypair, now=now)
    tag, claims_seg, sig_seg = token.split(".")
    flipped_tail = "AA" if not sig_seg.endswith("AA") else "BB"
    tampered = f"{tag}.{claims_seg}.{sig_seg[:-2]}{flipped_tail}"

    with pytest.raises(lt.LicenseSignatureError):
        lt.verify_token(tampered, expected_fingerprint="fp-hash-123", now=now)


def test_verify_token_rejects_wrong_fingerprint(keypair):
    now = datetime.now(timezone.utc)
    token = _make_token(keypair, now=now, fingerprint="fp-hash-123")

    with pytest.raises(lt.LicenseFingerprintMismatchError):
        lt.verify_token(token, expected_fingerprint="a-different-fingerprint", now=now)


def test_verify_token_rejects_revoked_status(keypair):
    now = datetime.now(timezone.utc)
    token = _make_token(keypair, now=now, status="revoked")

    with pytest.raises(lt.LicenseRevokedError):
        lt.verify_token(token, expected_fingerprint="fp-hash-123", now=now)


def test_verify_token_rejects_expired_license(keypair):
    now = datetime.now(timezone.utc)
    token = _make_token(
        keypair,
        now=now - timedelta(days=1),
        license_expires_at=_iso(now - timedelta(hours=1)),
    )

    with pytest.raises(lt.LicenseExpiredError):
        lt.verify_token(token, expected_fingerprint="fp-hash-123", now=now)


def test_verify_token_flags_needs_revalidation_past_valid_until(keypair):
    issued = datetime.now(timezone.utc) - timedelta(days=20)
    token = _make_token(keypair, now=issued)
    check_time = issued + timedelta(days=15)  # pasó valid_until (issued+14), no es error

    result = lt.verify_token(token, expected_fingerprint="fp-hash-123", now=check_time)

    assert result.needs_revalidation is True
    assert result.claims.key_id == "key-abc"


def test_verify_token_rejects_malformed_token(keypair):
    with pytest.raises(lt.LicenseFormatError):
        lt.verify_token(
            "not-a-real-token",
            expected_fingerprint="fp-hash-123",
            now=datetime.now(timezone.utc),
        )


def test_verify_token_rejects_unsupported_version_tag(keypair):
    now = datetime.now(timezone.utc)
    token = _make_token(keypair, now=now)
    _tag, claims_seg, sig_seg = token.split(".")
    wrong_tag_token = f"PLT9.{claims_seg}.{sig_seg}"

    with pytest.raises(lt.LicenseFormatError):
        lt.verify_token(wrong_tag_token, expected_fingerprint="fp-hash-123", now=now)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_token.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.license_token'`

- [ ] **Step 4: Write minimal implementation**

Create `core/license_token.py`:

```python
"""Verificación local de tokens de licencia firmados (formato PLT1).

Ver docs/superpowers/specs/2026-07-11-pdflex-licensing-design.md §4.
`now` siempre se recibe como parámetro (nunca se lee el reloj del sistema
aquí dentro) para que el llamador controle la guarda anti-rollback (spec
§11) y para que esta función sea determinista en pruebas. Debe ser
timezone-aware en UTC.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core import license_config

_TOKEN_TAG = "PLT1"


class LicenseInvalidError(Exception):
    """Base: el token no es confiable, tratar como no-activado."""


class LicenseFormatError(LicenseInvalidError):
    pass


class LicenseSignatureError(LicenseInvalidError):
    pass


class LicenseFingerprintMismatchError(LicenseInvalidError):
    pass


class LicenseRevokedError(LicenseInvalidError):
    pass


class LicenseExpiredError(LicenseInvalidError):
    pass


@dataclass(frozen=True)
class LicenseClaims:
    key_id: str
    fingerprint: str
    issued_at: datetime
    valid_until: datetime
    license_expires_at: datetime | None
    status: str
    customer_name: str
    app: str
    seats_allowed: int


@dataclass(frozen=True)
class VerifiedLicense:
    claims: LicenseClaims
    needs_revalidation: bool


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def verify_token(token: str, expected_fingerprint: str, now: datetime) -> VerifiedLicense:
    """Verifica un token PLT1 de punta a punta. Lanza LicenseInvalidError
    (o una subclase) si el token no es confiable."""
    try:
        tag, claims_segment, signature_segment = token.split(".")
    except ValueError as exc:
        raise LicenseFormatError("Formato de token inválido.") from exc

    if tag != _TOKEN_TAG:
        raise LicenseFormatError(f"Versión de token no soportada: {tag!r}.")

    try:
        claims_bytes = _b64url_decode(claims_segment)
        signature_bytes = _b64url_decode(signature_segment)
    except Exception as exc:
        raise LicenseFormatError("No se pudo decodificar el token.") from exc

    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(license_config.LICENSE_PUBLIC_KEY_ED25519)
        )
        public_key.verify(signature_bytes, claims_bytes)
    except (InvalidSignature, ValueError) as exc:
        raise LicenseSignatureError("Firma del token inválida.") from exc

    try:
        raw = json.loads(claims_bytes)
    except json.JSONDecodeError as exc:
        raise LicenseFormatError("El token no contiene JSON válido.") from exc

    if raw.get("app") != "pdflex":
        raise LicenseFormatError("El token no corresponde a esta aplicación.")

    if raw.get("fingerprint") != expected_fingerprint:
        raise LicenseFingerprintMismatchError("Esta licencia pertenece a otro equipo.")

    status = raw.get("status")
    if status != "active":
        raise LicenseRevokedError(f"La licencia no está activa (estado: {status}).")

    license_expires_raw = raw.get("license_expires_at")
    license_expires_at = _parse_datetime(license_expires_raw) if license_expires_raw else None
    if license_expires_at is not None and now > license_expires_at:
        raise LicenseExpiredError("La licencia expiró.")

    valid_until = _parse_datetime(raw["valid_until"])
    claims = LicenseClaims(
        key_id=raw["key_id"],
        fingerprint=raw["fingerprint"],
        issued_at=_parse_datetime(raw["issued_at"]),
        valid_until=valid_until,
        license_expires_at=license_expires_at,
        status=status,
        customer_name=raw.get("customer_name") or "",
        app=raw["app"],
        seats_allowed=int(raw.get("seats_allowed", 1)),
    )
    return VerifiedLicense(claims=claims, needs_revalidation=now > valid_until)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_token.py -v`
Expected: `8 passed`

- [ ] **Step 6: Install the new dependency in the dev environment**

Run: `.venv_nuitka/Scripts/python.exe -m pip install "cryptography>=42.0.0,<46"`
Expected: `Successfully installed cryptography-...` (or `Requirement already satisfied` — this venv already had `cryptography` 46.0.5 as a transitive dependency at plan-writing time; if that version falls outside `<46`, either widen the pin or `pip install` will report a conflict to resolve before continuing).

- [ ] **Step 7: Commit**

```bash
git add core/license_token.py tests/test_license_token.py requirements.txt
git commit -m "feat: add signed license token verification"
```

---

### Task 5: `core/license_storage.py` — local secure storage

**Files:**
- Create: `core/license_storage.py`
- Test: `tests/test_license_storage.py`

**Interfaces:**
- Produces: `save_token(token: str) -> None`, `load_token() -> str | None`, `clear_token() -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_license_storage.py`:

```python
import base64
from unittest.mock import patch

from core import license_storage as ls


def test_save_token_writes_both_registry_and_file():
    with patch.object(ls, "_dpapi_protect", return_value=b"PROTECTED") as protect, \
         patch.object(ls, "_registry_write") as reg_write, \
         patch.object(ls, "_file_write") as file_write:
        ls.save_token("PLT1.claims.sig")

    protect.assert_called_once_with(b"PLT1.claims.sig")
    reg_write.assert_called_once()
    file_write.assert_called_once_with(b"PROTECTED")


def test_load_token_returns_none_when_both_copies_missing():
    with patch.object(ls, "_registry_read", return_value=None), \
         patch.object(ls, "_file_read", return_value=None):
        assert ls.load_token() is None


def test_load_token_reads_from_registry_when_file_missing():
    protected = b"PROTECTED-BYTES"
    with patch.object(ls, "_registry_read", return_value=base64.b64encode(protected).decode()), \
         patch.object(ls, "_file_read", return_value=None), \
         patch.object(ls, "_dpapi_unprotect", return_value=b"PLT1.claims.sig") as unprotect, \
         patch.object(ls, "_file_write") as file_write:
        token = ls.load_token()

    assert token == "PLT1.claims.sig"
    unprotect.assert_called_once_with(protected)
    file_write.assert_called_once_with(protected)  # repara la copia faltante


def test_load_token_reads_from_file_when_registry_missing():
    protected = b"PROTECTED-BYTES"
    with patch.object(ls, "_registry_read", return_value=None), \
         patch.object(ls, "_file_read", return_value=protected), \
         patch.object(ls, "_dpapi_unprotect", return_value=b"PLT1.claims.sig"), \
         patch.object(ls, "_registry_write") as reg_write:
        token = ls.load_token()

    assert token == "PLT1.claims.sig"
    reg_write.assert_called_once()  # repara la copia faltante


def test_load_token_returns_none_when_dpapi_fails_on_all_candidates():
    protected = b"PROTECTED-BYTES"
    with patch.object(ls, "_registry_read", return_value=base64.b64encode(protected).decode()), \
         patch.object(ls, "_file_read", return_value=protected), \
         patch.object(ls, "_dpapi_unprotect", side_effect=Exception("blob corrupto o de otra máquina")):
        assert ls.load_token() is None


def test_load_token_prefers_registry_and_repairs_mismatched_file():
    registry_protected = b"REGISTRY-VERSION"
    file_protected = b"STALE-FILE-VERSION"
    with patch.object(ls, "_registry_read", return_value=base64.b64encode(registry_protected).decode()), \
         patch.object(ls, "_file_read", return_value=file_protected), \
         patch.object(ls, "_dpapi_unprotect", return_value=b"PLT1.claims.sig"), \
         patch.object(ls, "_file_write") as file_write:
        token = ls.load_token()

    assert token == "PLT1.claims.sig"
    file_write.assert_called_once_with(registry_protected)


def test_clear_token_deletes_both_copies():
    with patch.object(ls, "_registry_delete") as reg_delete, \
         patch.object(ls, "_file_delete") as file_delete:
        ls.clear_token()

    reg_delete.assert_called_once()
    file_delete.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.license_storage'`

- [ ] **Step 3: Write minimal implementation**

Create `core/license_storage.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_storage.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add core/license_storage.py tests/test_license_storage.py
git commit -m "feat: add DPAPI-backed local license storage with reconciliation"
```

---

### Task 6: `core/license_manager.py` — network workers (activate/revalidate/deactivate)

**Files:**
- Create: `core/license_manager.py`
- Test: `tests/test_license_manager.py`

**Interfaces:**
- Consumes: `core.license_config.*` (Task 1), `core.machine_fingerprint.Fingerprint` (Task 2), `core.update_config.APP_VERSION` (existing), `core.crash_handler.handle_crash` (existing).
- Produces: `class LicenseActivateWorker(QObject)` (signals `success(str, str, object)` = token, customer_name, license_expires_at; `error(str, str)` = error_code, message; constructor `(license_key: str, fingerprint: Fingerprint, machine_name: str, os_version: str, parent=None)`), `class LicenseActivateThread(QThread)` (`(worker, parent=None)`), `class LicenseRevalidateWorker(QObject)` (signals `success(str, object)` = token, license_expires_at; `error(str, str)`; constructor `(key_id: str, fingerprint: Fingerprint, parent=None)`), `class LicenseRevalidateThread(QThread)`, `class LicenseDeactivateWorker(QObject)` (signals `success(int)` = transfers_remaining; `error(str, str)`; constructor `(key_id: str, composite_hash: str, parent=None)`), `class LicenseDeactivateThread(QThread)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_license_manager.py`:

```python
import os
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from core import license_manager as lm
from core.machine_fingerprint import Fingerprint

_app = QCoreApplication.instance() or QCoreApplication([])


def _fake_response(status_code: int, json_body: dict):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    return resp


def test_activate_worker_emits_success_on_200():
    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseActivateWorker("PDFX-AAAAA-BBBBB-CCCCC-DDDD", fp, "PC-1", "Windows 11")
    results = {}
    worker.success.connect(lambda token, customer, expires: results.update(
        token=token, customer=customer, expires=expires
    ))
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch("requests.post", return_value=_fake_response(200, {
        "token": "PLT1.x.y", "customer_name": "Empresa X", "license_expires_at": None
    })):
        worker.run()

    assert results["token"] == "PLT1.x.y"
    assert results["customer"] == "Empresa X"
    assert "error_code" not in results


def test_activate_worker_emits_error_on_key_not_found():
    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseActivateWorker("PDFX-AAAAA-BBBBB-CCCCC-DDDD", fp, "PC-1", "Windows 11")
    results = {}
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch("requests.post", return_value=_fake_response(404, {
        "error_code": "KEY_NOT_FOUND", "message": "Esta clave no existe."
    })):
        worker.run()

    assert results["error_code"] == "KEY_NOT_FOUND"


def test_activate_worker_retries_and_reports_network_error():
    import requests

    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseActivateWorker("PDFX-AAAAA-BBBBB-CCCCC-DDDD", fp, "PC-1", "Windows 11")
    results = {}
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch("requests.post", side_effect=requests.exceptions.ConnectionError()), \
         patch("time.sleep"):
        worker.run()

    assert results["error_code"] == "NETWORK_ERROR"


def test_revalidate_worker_emits_success_with_fresh_token():
    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseRevalidateWorker("key-id-123", fp)
    results = {}
    worker.success.connect(lambda token, expires: results.update(token=token, expires=expires))

    with patch("requests.post", return_value=_fake_response(200, {
        "token": "PLT1.new.token", "license_expires_at": None
    })):
        worker.run()

    assert results["token"] == "PLT1.new.token"


def test_revalidate_worker_emits_fingerprint_mismatch_error():
    fp = Fingerprint("g", "v", "c", "composite")
    worker = lm.LicenseRevalidateWorker("key-id-123", fp)
    results = {}
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch("requests.post", return_value=_fake_response(409, {
        "error_code": "FINGERPRINT_MISMATCH", "message": "Esta licencia pertenece a otro equipo."
    })):
        worker.run()

    assert results["error_code"] == "FINGERPRINT_MISMATCH"


def test_deactivate_worker_emits_transfers_remaining():
    worker = lm.LicenseDeactivateWorker("key-id-123", "composite-hash")
    results = {}
    worker.success.connect(lambda remaining: results.update(remaining=remaining))

    with patch("requests.post", return_value=_fake_response(200, {"ok": True, "transfers_remaining": 2})):
        worker.run()

    assert results["remaining"] == 2


def test_deactivate_worker_emits_transfer_limit_error():
    worker = lm.LicenseDeactivateWorker("key-id-123", "composite-hash")
    results = {}
    worker.error.connect(lambda code, msg: results.update(error_code=code, message=msg))

    with patch("requests.post", return_value=_fake_response(429, {
        "error_code": "TRANSFER_LIMIT_REACHED", "message": "Demasiadas transferencias recientes."
    })):
        worker.run()

    assert results["error_code"] == "TRANSFER_LIMIT_REACHED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.license_manager'`

- [ ] **Step 3: Write minimal implementation**

Create `core/license_manager.py`:

```python
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
    import requests

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
            self.success.emit(body["token"], body.get("customer_name") or "", body.get("license_expires_at"))
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
            self.success.emit(body["token"], body.get("license_expires_at"))
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
            self.success.emit(int(body.get("transfers_remaining", 0)))
        else:
            self.error.emit(body.get("error_code", "SERVER_ERROR"), body.get("message", "Error desconocido."))


class LicenseDeactivateThread(QThread):
    def __init__(self, worker: LicenseDeactivateWorker, parent=None) -> None:
        super().__init__(parent)
        self._worker = worker

    def run(self) -> None:
        _thread_run_with_crash_report(self._worker, "LicenseDeactivateThread")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_manager.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add core/license_manager.py tests/test_license_manager.py
git commit -m "feat: add activate/revalidate/deactivate network workers"
```

---

### Task 7: `ui/license/activation_dialog.py` — activation dialog

**Files:**
- Create: `ui/license/__init__.py` (empty)
- Create: `ui/license/activation_dialog.py`
- Test: `tests/test_activation_dialog.py`

**Interfaces:**
- Consumes: `core.license_storage.save_token` (Task 5), `core.license_key_format.is_valid_key_format`/`normalize_key` (Task 3), `core.license_manager.LicenseActivateWorker`/`LicenseActivateThread` (Task 6), `core.machine_fingerprint.compute_fingerprint` (Task 2), `ui.styles.COLORS` (existing), `ui.common.icons.app_qicon`/`icon_pixmap` (existing).
- Produces: `class ActivationDialog(QDialog)` with public attribute `activated_token: str | None` (set on success, `None` if closed without activating), and an overridable seam `_start_activation_worker(self, license_key: str) -> None` (tests replace this to simulate success/error without real threads/network).

- [ ] **Step 1: Write the failing test**

Create `ui/license/__init__.py` (empty file).

Create `tests/test_activation_dialog.py`:

```python
import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame

from ui.license.activation_dialog import ActivationDialog

_app = QApplication.instance() or QApplication([])


def test_dialog_renders_header_body_footer():
    dlg = ActivationDialog()
    try:
        assert dlg.windowTitle() == "Activar PDFlex"
        assert dlg.findChild(QFrame, "ActivationHeader") is not None
        assert dlg.findChild(QFrame, "ActivationFooter") is not None
        assert dlg.activated_token is None
    finally:
        dlg.close()
        _app.processEvents()


def test_activate_button_disabled_for_malformed_key():
    dlg = ActivationDialog()
    try:
        dlg._key_input.setText("not-a-valid-key")
        assert dlg._activate_btn.isEnabled() is False
    finally:
        dlg.close()
        _app.processEvents()


def test_activate_button_enabled_for_well_formed_key():
    dlg = ActivationDialog()
    try:
        dlg._key_input.setText("pdfx-abcde-fghjk-mnpqr-718b")
        assert dlg._key_input.text() == "PDFX-ABCDE-FGHJK-MNPQR-718B"
        assert dlg._activate_btn.isEnabled() is True
    finally:
        dlg.close()
        _app.processEvents()


def test_clicking_activate_calls_start_worker_seam_with_normalized_key():
    dlg = ActivationDialog()
    started = {}
    dlg._start_activation_worker = lambda license_key: started.setdefault("key", license_key)
    dlg._key_input.setText("pdfx-abcde-fghjk-mnpqr-718b")

    try:
        dlg._on_activate_clicked()
        assert started["key"] == "PDFX-ABCDE-FGHJK-MNPQR-718B"
        assert dlg._activate_btn.isEnabled() is False
    finally:
        dlg.close()
        _app.processEvents()


def test_activate_success_saves_token_and_accepts():
    dlg = ActivationDialog()
    try:
        with patch("ui.license.activation_dialog.license_storage.save_token") as save_token:
            dlg._on_activate_success("PLT1.x.y", "Empresa X", None)

        save_token.assert_called_once_with("PLT1.x.y")
        assert dlg.activated_token == "PLT1.x.y"
        assert dlg.result() == 1  # QDialog.Accepted
    finally:
        dlg.close()
        _app.processEvents()


def test_activate_error_shows_mapped_message_and_reenables_button():
    dlg = ActivationDialog()
    try:
        dlg._activate_btn.setEnabled(False)
        dlg._on_activate_error("KEY_NOT_FOUND", "mensaje crudo del servidor")

        assert dlg._activate_btn.isEnabled() is True
        assert dlg._error_label.isVisible() is True
        assert "no existe" in dlg._error_label.text()
    finally:
        dlg.close()
        _app.processEvents()


def test_activate_error_falls_back_to_server_message_for_unknown_code():
    dlg = ActivationDialog()
    try:
        dlg._on_activate_error("SOME_UNMAPPED_CODE", "mensaje literal del servidor")
        assert dlg._error_label.text() == "mensaje literal del servidor"
    finally:
        dlg.close()
        _app.processEvents()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_activation_dialog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ui.license'`

- [ ] **Step 3: Write minimal implementation**

Create `ui/license/activation_dialog.py`:

```python
"""Diálogo modal de activación de licencia — primer arranque sin licencia
válida (spec §1.1).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from core import license_storage
from core.license_key_format import is_valid_key_format, normalize_key
from core.license_manager import LicenseActivateThread, LicenseActivateWorker
from core.machine_fingerprint import compute_fingerprint
from ui.common.icons import app_qicon, icon_pixmap
from ui.styles import COLORS

_ERROR_MESSAGES = {
    "MALFORMED_KEY": "El formato de la clave no es válido.",
    "KEY_NOT_FOUND": "Esta clave no existe. Verifica que la copiaste completa.",
    "ALREADY_ACTIVATED_ELSEWHERE": "Esta clave ya está activada en otro equipo.",
    "KEY_REVOKED": "Esta clave fue revocada. Contacta a soporte.",
    "KEY_EXPIRED": "Esta clave venció. Contacta a soporte para renovarla.",
    "RATE_LIMITED": "Demasiados intentos. Espera unos minutos.",
    "NETWORK_ERROR": "No se pudo conectar. Verifica tu conexión e inténtalo de nuevo.",
    "SERVER_ERROR": "Ocurrió un error en el servidor. Inténtalo de nuevo.",
}


class ActivationDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.activated_token: str | None = None
        self._thread: LicenseActivateThread | None = None
        self._worker: LicenseActivateWorker | None = None
        self._drag_pos = None

        self.setWindowTitle("Activar PDFlex")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(480)
        self.setMaximumWidth(560)
        self.setWindowIcon(app_qicon())
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("ActivationShell")
        shell.setStyleSheet(f"""
            QFrame#ActivationShell {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border_strong']};
                border-radius: 12px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(shell)
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 16)
        shell.setGraphicsEffect(shadow)
        outer.addWidget(shell)

        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addWidget(self._build_body())
        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("ActivationHeader")
        header.setStyleSheet(f"""
            QFrame#ActivationHeader {{
                background: {COLORS['surface_2']};
                border-bottom: 1px solid {COLORS['border']};
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }}
        """)
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 15, 14, 15)
        h.setSpacing(13)

        icon_box = QFrame()
        icon_box.setFixedSize(42, 42)
        icon_box.setStyleSheet(f"""
            QFrame {{
                background: rgba(94, 106, 210, 0.16);
                border: 1px solid rgba(94, 106, 210, 0.5);
                border-radius: 9px;
            }}
        """)
        ib = QVBoxLayout(icon_box)
        ib.setContentsMargins(0, 0, 0, 0)
        ib_lbl = QLabel()
        ib_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ib_lbl.setPixmap(icon_pixmap("tool-protector", COLORS["accent"], 22))
        ib_lbl.setStyleSheet("background: transparent;")
        ib.addWidget(ib_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        h.addWidget(icon_box)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        t = QLabel("Activar PDFlex")
        t.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 14px; font-weight: 700;"
            "background: transparent;"
        )
        title_col.addWidget(t)
        s = QLabel("Introduce tu clave de licencia para continuar.")
        s.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent;"
        )
        title_col.addWidget(s)
        h.addLayout(title_col, 1)
        return header

    def _build_body(self) -> QWidget:
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(20, 18, 20, 14)
        v.setSpacing(10)

        label = QLabel("CLAVE DE LICENCIA")
        label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px; font-weight: 700;"
            "letter-spacing: 0.8px; background: transparent;"
        )
        v.addWidget(label)

        self._key_input = QLineEdit()
        self._key_input.setPlaceholderText("PDFX-XXXXX-XXXXX-XXXXX-CCCC")
        self._key_input.setMinimumHeight(40)
        self._key_input.textChanged.connect(self._on_key_text_changed)
        v.addWidget(self._key_input)

        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(
            f"color: {COLORS['danger']}; font-size: 11px; background: transparent;"
        )
        self._error_label.setVisible(False)
        v.addWidget(self._error_label)

        contact = QLabel("¿No tienes una clave? Contacta a GRUPO OCMX para obtener una.")
        contact.setWordWrap(True)
        contact.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px; background: transparent;"
        )
        v.addWidget(contact)
        return body

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("ActivationFooter")
        footer.setStyleSheet(f"""
            QFrame#ActivationFooter {{
                background: {COLORS['surface_2']};
                border-top: 1px solid {COLORS['border']};
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
            }}
        """)
        f = QHBoxLayout(footer)
        f.setContentsMargins(18, 12, 18, 12)
        f.setSpacing(8)
        f.addStretch(1)

        self._activate_btn = QPushButton("Activar")
        self._activate_btn.setFixedHeight(34)
        self._activate_btn.setMinimumWidth(112)
        self._activate_btn.setEnabled(False)
        self._activate_btn.setDefault(True)
        self._activate_btn.clicked.connect(self._on_activate_clicked)
        f.addWidget(self._activate_btn)
        return footer

    # ── validación local ────────────────────────────────────────────────────

    def _on_key_text_changed(self, text: str) -> None:
        normalized = normalize_key(text)
        if normalized != text:
            cursor = self._key_input.cursorPosition()
            self._key_input.blockSignals(True)
            self._key_input.setText(normalized)
            self._key_input.setCursorPosition(cursor)
            self._key_input.blockSignals(False)

        valid = is_valid_key_format(normalized) if normalized else False
        self._activate_btn.setEnabled(valid)
        looks_complete = len(normalized.replace("-", "")) >= 19
        if normalized and not valid and looks_complete:
            self._show_error("La clave no es válida. Revisa que la copiaste completa.")
        else:
            self._clear_error()

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    def _clear_error(self) -> None:
        self._error_label.setVisible(False)

    # ── activación ───────────────────────────────────────────────────────────

    def _on_activate_clicked(self) -> None:
        license_key = normalize_key(self._key_input.text())
        if not is_valid_key_format(license_key):
            self._show_error("La clave no es válida. Revisa que la copiaste completa.")
            return

        self._clear_error()
        self._activate_btn.setEnabled(False)
        self._activate_btn.setText("Activando…")
        self._start_activation_worker(license_key)

    def _start_activation_worker(self, license_key: str) -> None:
        """Punto de extensión: crea y arranca el worker real. Las pruebas
        sobreescriben este método para simular éxito/error sin red real."""
        fingerprint = compute_fingerprint()
        self._worker = LicenseActivateWorker(
            license_key, fingerprint, _machine_name(), _os_version_string()
        )
        self._thread = LicenseActivateThread(self._worker)
        self._worker.success.connect(self._on_activate_success)
        self._worker.error.connect(self._on_activate_error)
        self._worker.success.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_activate_success(self, token: str, customer_name: str, license_expires_at) -> None:
        license_storage.save_token(token)
        self.activated_token = token
        self.accept()

    def _on_activate_error(self, error_code: str, message: str) -> None:
        self._activate_btn.setEnabled(True)
        self._activate_btn.setText("Activar")
        self._show_error(_ERROR_MESSAGES.get(error_code, message))

    # ── arrastre de ventana sin bordes ──────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)


def _machine_name() -> str:
    import socket

    return socket.gethostname()


def _os_version_string() -> str:
    import platform

    return platform.platform()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_activation_dialog.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add ui/license/__init__.py ui/license/activation_dialog.py tests/test_activation_dialog.py
git commit -m "feat: add license activation dialog"
```

---

### Task 8: `ui/license/reconnect_dialog.py` — lightweight reconnect dialog

**Files:**
- Create: `ui/license/reconnect_dialog.py`
- Test: `tests/test_reconnect_dialog.py`

**Interfaces:**
- Consumes: `core.license_storage.save_token` (Task 5), `core.license_manager.LicenseRevalidateWorker`/`LicenseRevalidateThread` (Task 6), `core.machine_fingerprint.compute_fingerprint` (Task 2).
- Produces: `class ReconnectDialog(QDialog)` with constructor `(key_id: str, parent=None)`, public attributes `revalidated_token: str | None` and `gave_up: bool`, and overridable seam `_start_revalidation_worker(self) -> None`.

**Note:** shown when a locally-valid token has passed its offline grace window (spec §1.2 point 4, §8) — the user does not re-type their key, PDFlex just needs to reach the server again.

- [ ] **Step 1: Write the failing test**

Create `tests/test_reconnect_dialog.py`:

```python
import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame

from ui.license.reconnect_dialog import ReconnectDialog

_app = QApplication.instance() or QApplication([])


def test_dialog_renders_and_starts_a_revalidation_attempt_immediately():
    started = {}
    with patch.object(ReconnectDialog, "_start_revalidation_worker", lambda self: started.setdefault("called", True)):
        dlg = ReconnectDialog("key-abc")
    try:
        assert started.get("called") is True
        assert dlg.findChild(QFrame, "ReconnectHeader") is not None
        assert dlg.findChild(QFrame, "ReconnectFooter") is not None
        assert dlg.revalidated_token is None
        assert dlg.gave_up is False
    finally:
        dlg.close()
        _app.processEvents()


def test_revalidate_success_saves_token_and_accepts():
    with patch.object(ReconnectDialog, "_start_revalidation_worker", lambda self: None):
        dlg = ReconnectDialog("key-abc")
    try:
        with patch("ui.license.reconnect_dialog.license_storage.save_token") as save_token:
            dlg._on_revalidate_success("PLT1.fresh.token", None)

        save_token.assert_called_once_with("PLT1.fresh.token")
        assert dlg.revalidated_token == "PLT1.fresh.token"
        assert dlg.result() == 1  # QDialog.Accepted
    finally:
        dlg.close()
        _app.processEvents()


def test_revalidate_error_shows_message_and_reenables_retry():
    with patch.object(ReconnectDialog, "_start_revalidation_worker", lambda self: None):
        dlg = ReconnectDialog("key-abc")
    try:
        dlg._retry_btn.setEnabled(False)
        dlg._on_revalidate_error("KEY_REVOKED", "mensaje crudo")

        assert dlg._retry_btn.isEnabled() is True
        assert "revocada" in dlg._status_label.text()
    finally:
        dlg.close()
        _app.processEvents()


def test_retry_button_calls_worker_seam_again():
    calls = {"count": 0}

    def _fake_start(self):
        calls["count"] += 1

    with patch.object(ReconnectDialog, "_start_revalidation_worker", _fake_start):
        dlg = ReconnectDialog("key-abc")
        try:
            assert calls["count"] == 1  # arranque automático al abrir
            dlg._on_retry_clicked()
            assert calls["count"] == 2
        finally:
            dlg.close()
            _app.processEvents()


def test_quit_button_sets_gave_up_and_rejects():
    with patch.object(ReconnectDialog, "_start_revalidation_worker", lambda self: None):
        dlg = ReconnectDialog("key-abc")
    try:
        dlg._on_quit_clicked()
        assert dlg.gave_up is True
        assert dlg.result() == 0  # QDialog.Rejected
    finally:
        dlg.close()
        _app.processEvents()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_reconnect_dialog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ui.license.reconnect_dialog'`

- [ ] **Step 3: Write minimal implementation**

Create `ui/license/reconnect_dialog.py`:

```python
"""Diálogo ligero de reconexión — se muestra cuando el token local es
válido pero superó su ventana de confianza offline (spec §1.2 punto 4, §8).
No pide la clave de nuevo: solo necesita volver a contactar al servidor.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from core import license_storage
from core.license_manager import LicenseRevalidateThread, LicenseRevalidateWorker
from core.machine_fingerprint import compute_fingerprint
from ui.common.icons import app_qicon, icon_pixmap
from ui.styles import COLORS

_AUTO_RETRY_MS = 30_000

_ERROR_MESSAGES = {
    "KEY_NOT_FOUND": "Esta licencia ya no existe. Vuelve a activar PDFlex con una clave válida.",
    "KEY_REVOKED": "Esta licencia fue revocada. Contacta a soporte.",
    "KEY_EXPIRED": "Esta licencia venció. Contacta a soporte para renovarla.",
    "FINGERPRINT_MISMATCH": "Esta licencia pertenece a otro equipo.",
    "RATE_LIMITED": "Demasiados intentos. Espera unos minutos.",
    "NETWORK_ERROR": "No se pudo conectar. Verifica tu conexión.",
    "SERVER_ERROR": "Ocurrió un error en el servidor. Inténtalo de nuevo.",
}
_AUTO_RETRY_CODES = {"NETWORK_ERROR", "SERVER_ERROR"}


class ReconnectDialog(QDialog):
    def __init__(self, key_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._key_id = key_id
        self.revalidated_token: str | None = None
        self.gave_up = False
        self._thread: LicenseRevalidateThread | None = None
        self._worker: LicenseRevalidateWorker | None = None
        self._drag_pos = None

        self.setWindowTitle("Reconectar licencia — PDFlex")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(480)
        self.setMaximumWidth(560)
        self.setWindowIcon(app_qicon())
        self._build()
        self._start_revalidation_worker()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("ReconnectShell")
        shell.setStyleSheet(f"""
            QFrame#ReconnectShell {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border_strong']};
                border-radius: 12px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(shell)
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 16)
        shell.setGraphicsEffect(shadow)
        outer.addWidget(shell)

        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addWidget(self._build_body())
        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("ReconnectHeader")
        header.setStyleSheet(f"""
            QFrame#ReconnectHeader {{
                background: {COLORS['surface_2']};
                border-bottom: 1px solid {COLORS['border']};
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }}
        """)
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 15, 14, 15)
        h.setSpacing(13)

        icon_box = QFrame()
        icon_box.setFixedSize(42, 42)
        icon_box.setStyleSheet(f"""
            QFrame {{
                background: rgba(94, 106, 210, 0.16);
                border: 1px solid rgba(94, 106, 210, 0.5);
                border-radius: 9px;
            }}
        """)
        ib = QVBoxLayout(icon_box)
        ib.setContentsMargins(0, 0, 0, 0)
        ib_lbl = QLabel()
        ib_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ib_lbl.setPixmap(icon_pixmap("refresh-cw", COLORS["accent"], 22))
        ib_lbl.setStyleSheet("background: transparent;")
        ib.addWidget(ib_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        h.addWidget(icon_box)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        t = QLabel("Reconectando licencia")
        t.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 14px; font-weight: 700;"
            "background: transparent;"
        )
        title_col.addWidget(t)
        s = QLabel("PDFlex necesita conectarse a internet para continuar.")
        s.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent;"
        )
        title_col.addWidget(s)
        h.addLayout(title_col, 1)
        return header

    def _build_body(self) -> QWidget:
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(20, 18, 20, 14)
        v.setSpacing(10)

        self._status_label = QLabel("Verificando tu licencia…")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 12px; background: transparent;"
        )
        v.addWidget(self._status_label)
        return body

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("ReconnectFooter")
        footer.setStyleSheet(f"""
            QFrame#ReconnectFooter {{
                background: {COLORS['surface_2']};
                border-top: 1px solid {COLORS['border']};
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
            }}
        """)
        f = QHBoxLayout(footer)
        f.setContentsMargins(18, 12, 18, 12)
        f.setSpacing(8)

        self._quit_btn = QPushButton("Salir")
        self._quit_btn.setFixedHeight(34)
        self._quit_btn.clicked.connect(self._on_quit_clicked)
        f.addWidget(self._quit_btn)
        f.addStretch(1)

        self._retry_btn = QPushButton("Reintentar")
        self._retry_btn.setFixedHeight(34)
        self._retry_btn.setDefault(True)
        self._retry_btn.clicked.connect(self._on_retry_clicked)
        f.addWidget(self._retry_btn)
        return footer

    def _on_quit_clicked(self) -> None:
        self.gave_up = True
        self.reject()

    def _on_retry_clicked(self) -> None:
        self._retry_btn.setEnabled(False)
        self._status_label.setText("Verificando tu licencia…")
        self._start_revalidation_worker()

    def _start_revalidation_worker(self) -> None:
        """Punto de extensión: crea y arranca el worker real. Las pruebas
        sobreescriben este método para simular éxito/error sin red real."""
        fingerprint = compute_fingerprint()
        self._worker = LicenseRevalidateWorker(self._key_id, fingerprint)
        self._thread = LicenseRevalidateThread(self._worker)
        self._worker.success.connect(self._on_revalidate_success)
        self._worker.error.connect(self._on_revalidate_error)
        self._worker.success.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_revalidate_success(self, token: str, license_expires_at) -> None:
        license_storage.save_token(token)
        self.revalidated_token = token
        self.accept()

    def _on_revalidate_error(self, error_code: str, message: str) -> None:
        self._retry_btn.setEnabled(True)
        self._status_label.setText(_ERROR_MESSAGES.get(error_code, message))
        if error_code in _AUTO_RETRY_CODES:
            QTimer.singleShot(_AUTO_RETRY_MS, self._auto_retry_if_still_open)

    def _auto_retry_if_still_open(self) -> None:
        if self.isVisible():
            self._on_retry_clicked()

    # ── arrastre de ventana sin bordes ──────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_reconnect_dialog.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add ui/license/reconnect_dialog.py tests/test_reconnect_dialog.py
git commit -m "feat: add lightweight license reconnect dialog"
```

---

### Task 9: `ui/license/license_panel.py` — status panel and self-service transfer

**Files:**
- Create: `ui/license/license_panel.py`
- Test: `tests/test_license_panel.py`

**Interfaces:**
- Consumes: `core.license_token.LicenseClaims` (Task 4), `core.license_storage.clear_token` (Task 5), `core.license_manager.LicenseDeactivateWorker`/`LicenseDeactivateThread` (Task 6), `core.machine_fingerprint.compute_fingerprint` (Task 2).
- Produces: `class LicensePanel(QWidget)` with constructor `(claims: LicenseClaims, parent=None)`, meant to be embedded wherever PDFlex already exposes an "Acerca de" area.

- [ ] **Step 1: Write the failing test**

Create `tests/test_license_panel.py`:

```python
import os
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from core.license_token import LicenseClaims
from ui.license.license_panel import LicensePanel

_app = QApplication.instance() or QApplication([])


def _claims(**overrides) -> LicenseClaims:
    base = dict(
        key_id="key-abc",
        fingerprint="fp",
        issued_at=datetime.now(timezone.utc),
        valid_until=datetime.now(timezone.utc),
        license_expires_at=None,
        status="active",
        customer_name="Empresa de Prueba",
        app="pdflex",
        seats_allowed=1,
    )
    base.update(overrides)
    return LicenseClaims(**base)


def test_license_panel_shows_active_status_and_customer():
    panel = LicensePanel(_claims(customer_name="Empresa de Prueba"))
    try:
        assert panel._status_value_label.text() == "Activa"
        assert panel._customer_label.text() == "Cliente: Empresa de Prueba"
        assert panel._expiry_label.text() == "Licencia perpetua"
    finally:
        panel.deleteLater()
        _app.processEvents()


def test_license_panel_shows_expiry_date_for_time_limited_license():
    expires = datetime(2026, 12, 31, tzinfo=timezone.utc)
    panel = LicensePanel(_claims(license_expires_at=expires))
    try:
        assert panel._expiry_label.text() == "Expira: 2026-12-31"
    finally:
        panel.deleteLater()
        _app.processEvents()


def test_deactivate_button_confirms_then_calls_worker_starter():
    panel = LicensePanel(_claims())
    started = {}
    panel._start_deactivation_worker = lambda: started.setdefault("called", True)

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        panel._on_deactivate_clicked()

    try:
        assert started.get("called") is True
        assert panel._deactivate_btn.isEnabled() is False
    finally:
        panel.deleteLater()
        _app.processEvents()


def test_deactivate_button_does_nothing_if_user_cancels_confirmation():
    panel = LicensePanel(_claims())
    started = {}
    panel._start_deactivation_worker = lambda: started.setdefault("called", True)

    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
        panel._on_deactivate_clicked()

    try:
        assert "called" not in started
        assert panel._deactivate_btn.isEnabled() is True
    finally:
        panel.deleteLater()
        _app.processEvents()


def test_on_deactivate_success_clears_token_and_updates_button():
    panel = LicensePanel(_claims())

    with patch("core.license_storage.clear_token") as clear_token, \
         patch.object(QMessageBox, "information"):
        panel._on_deactivate_success(2)

    try:
        clear_token.assert_called_once()
        assert panel._deactivate_btn.text() == "Licencia desactivada"
    finally:
        panel.deleteLater()
        _app.processEvents()


def test_on_deactivate_error_reenables_button_and_shows_warning():
    panel = LicensePanel(_claims())
    panel._deactivate_btn.setEnabled(False)

    with patch.object(QMessageBox, "warning") as warning:
        panel._on_deactivate_error("TRANSFER_LIMIT_REACHED", "Demasiadas transferencias recientes.")

    try:
        assert panel._deactivate_btn.isEnabled() is True
        warning.assert_called_once()
    finally:
        panel.deleteLater()
        _app.processEvents()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_panel.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ui.license.license_panel'`

- [ ] **Step 3: Write minimal implementation**

Create `ui/license/license_panel.py`:

```python
"""Panel de estado de licencia y autoservicio de transferencia
(spec §1.4, §9)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core import license_storage
from core.license_manager import LicenseDeactivateThread, LicenseDeactivateWorker
from core.license_token import LicenseClaims
from core.machine_fingerprint import compute_fingerprint
from ui.styles import COLORS


class LicensePanel(QWidget):
    def __init__(self, claims: LicenseClaims, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._claims = claims
        self._thread: LicenseDeactivateThread | None = None
        self._worker: LicenseDeactivateWorker | None = None
        self._build()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        status_row = QHBoxLayout()
        status_label = QLabel("Estado:")
        status_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        status_row.addWidget(status_label)
        value = "Activa" if self._claims.status == "active" else self._claims.status
        self._status_value_label = QLabel(value)
        self._status_value_label.setStyleSheet(
            f"color: {COLORS['success']}; font-size: 12px; font-weight: 600;"
        )
        status_row.addWidget(self._status_value_label)
        status_row.addStretch(1)
        v.addLayout(status_row)

        self._customer_label = QLabel(f"Cliente: {self._claims.customer_name}")
        self._customer_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        self._customer_label.setVisible(bool(self._claims.customer_name))
        v.addWidget(self._customer_label)

        if self._claims.license_expires_at:
            expiry_text = f"Expira: {self._claims.license_expires_at.strftime('%Y-%m-%d')}"
        else:
            expiry_text = "Licencia perpetua"
        self._expiry_label = QLabel(expiry_text)
        self._expiry_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        v.addWidget(self._expiry_label)

        self._deactivate_btn = QPushButton("Desactivar esta licencia")
        self._deactivate_btn.setFixedHeight(34)
        self._deactivate_btn.clicked.connect(self._on_deactivate_clicked)
        v.addWidget(self._deactivate_btn)

    def _on_deactivate_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Desactivar licencia",
            "Esto libera tu licencia de este equipo para poder activarla en otro. "
            "¿Deseas continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._deactivate_btn.setEnabled(False)
        self._deactivate_btn.setText("Desactivando…")
        self._start_deactivation_worker()

    def _start_deactivation_worker(self) -> None:
        """Punto de extensión: crea y arranca el worker real. Las pruebas
        sobreescriben este método para simular éxito/error sin red real."""
        fingerprint = compute_fingerprint()
        self._worker = LicenseDeactivateWorker(self._claims.key_id, fingerprint.composite_hash)
        self._thread = LicenseDeactivateThread(self._worker)
        self._worker.success.connect(self._on_deactivate_success)
        self._worker.error.connect(self._on_deactivate_error)
        self._worker.success.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_deactivate_success(self, transfers_remaining: int) -> None:
        license_storage.clear_token()
        QMessageBox.information(
            self,
            "Licencia desactivada",
            f"Este equipo quedó liberado. Transferencias restantes este trimestre: {transfers_remaining}.",
        )
        self._deactivate_btn.setText("Licencia desactivada")

    def _on_deactivate_error(self, error_code: str, message: str) -> None:
        self._deactivate_btn.setEnabled(True)
        self._deactivate_btn.setText("Desactivar esta licencia")
        QMessageBox.warning(self, "No se pudo desactivar", message)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_panel.py -v`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add ui/license/license_panel.py tests/test_license_panel.py
git commit -m "feat: add license status panel with self-service deactivation"
```

---

### Task 10: `ui/license/license_gate.py` — startup orchestration

**Files:**
- Create: `ui/license/license_gate.py`
- Test: `tests/test_license_gate.py`

**Interfaces:**
- Consumes: `core.license_storage.load_token`/`save_token` (Task 5), `core.license_token.verify_token`/`LicenseInvalidError`/`LicenseClaims`/`VerifiedLicense` (Task 4), `core.machine_fingerprint.compute_fingerprint` (Task 2), `core.license_manager.LicenseRevalidateWorker`/`LicenseRevalidateThread` (Task 6), `ui.license.activation_dialog.ActivationDialog` (Task 7), `ui.license.reconnect_dialog.ReconnectDialog` (Task 8).
- Produces: `ensure_licensed(parent=None) -> str | None` (returns the active `key_id` if PDFlex may continue starting up, `None` if it must exit), `start_background_revalidation(key_id: str, parent) -> None` (fire-and-forget silent revalidation; `parent` must be a live `QObject` — e.g. the main window — so Qt keeps the thread alive; never shown to the user, failures are silently ignored until the next gate check).

- [ ] **Step 1: Write the failing test**

Create `tests/test_license_gate.py`:

```python
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.license_token import LicenseClaims, LicenseInvalidError, VerifiedLicense
from ui.license import license_gate as lg

_app = QApplication.instance() or QApplication([])


def _claims(**overrides) -> LicenseClaims:
    base = dict(
        key_id="key-abc",
        fingerprint="fp",
        issued_at=datetime.now(timezone.utc),
        valid_until=datetime.now(timezone.utc) + timedelta(days=14),
        license_expires_at=None,
        status="active",
        customer_name="Empresa de Prueba",
        app="pdflex",
        seats_allowed=1,
    )
    base.update(overrides)
    return LicenseClaims(**base)


def test_ensure_licensed_returns_key_id_when_local_token_is_fully_valid():
    verified = VerifiedLicense(claims=_claims(), needs_revalidation=False)

    with patch.object(lg.license_storage, "load_token", return_value="PLT1.x.y"), \
         patch.object(lg, "verify_token", return_value=verified), \
         patch.object(lg, "compute_fingerprint", return_value=Mock(composite_hash="fp")):
        result = lg.ensure_licensed()

    assert result == "key-abc"


def test_ensure_licensed_shows_activation_dialog_when_no_token_stored():
    fake_dialog = Mock()
    fake_dialog.activated_token = "PLT1.new.token"
    reactivated = VerifiedLicense(claims=_claims(key_id="key-new"), needs_revalidation=False)

    with patch.object(lg.license_storage, "load_token", return_value=None), \
         patch.object(lg, "compute_fingerprint", return_value=Mock(composite_hash="fp")), \
         patch.object(lg, "ActivationDialog", return_value=fake_dialog) as dialog_cls, \
         patch.object(lg, "verify_token", return_value=reactivated):
        result = lg.ensure_licensed()

    dialog_cls.assert_called_once()
    fake_dialog.exec.assert_called_once()
    assert result == "key-new"


def test_ensure_licensed_returns_none_when_activation_dialog_closed_without_key():
    fake_dialog = Mock()
    fake_dialog.activated_token = None

    with patch.object(lg.license_storage, "load_token", return_value=None), \
         patch.object(lg, "compute_fingerprint", return_value=Mock(composite_hash="fp")), \
         patch.object(lg, "ActivationDialog", return_value=fake_dialog):
        result = lg.ensure_licensed()

    assert result is None


def test_ensure_licensed_shows_activation_dialog_when_local_token_invalid():
    fake_dialog = Mock()
    fake_dialog.activated_token = None

    with patch.object(lg.license_storage, "load_token", return_value="PLT1.corrupt.token"), \
         patch.object(lg, "compute_fingerprint", return_value=Mock(composite_hash="fp")), \
         patch.object(lg, "verify_token", side_effect=LicenseInvalidError("firma inválida")), \
         patch.object(lg, "ActivationDialog", return_value=fake_dialog) as dialog_cls:
        result = lg.ensure_licensed()

    dialog_cls.assert_called_once()
    assert result is None


def test_ensure_licensed_shows_reconnect_dialog_when_grace_expired():
    verified = VerifiedLicense(claims=_claims(key_id="key-abc"), needs_revalidation=True)
    fake_dialog = Mock()
    fake_dialog.revalidated_token = "PLT1.fresh.token"

    with patch.object(lg.license_storage, "load_token", return_value="PLT1.stale.token"), \
         patch.object(lg, "compute_fingerprint", return_value=Mock(composite_hash="fp")), \
         patch.object(lg, "verify_token", return_value=verified), \
         patch.object(lg, "ReconnectDialog", return_value=fake_dialog) as dialog_cls:
        result = lg.ensure_licensed()

    dialog_cls.assert_called_once_with("key-abc", None)
    assert result == "key-abc"


def test_ensure_licensed_returns_none_when_reconnect_dialog_gives_up():
    verified = VerifiedLicense(claims=_claims(key_id="key-abc"), needs_revalidation=True)
    fake_dialog = Mock()
    fake_dialog.revalidated_token = None

    with patch.object(lg.license_storage, "load_token", return_value="PLT1.stale.token"), \
         patch.object(lg, "compute_fingerprint", return_value=Mock(composite_hash="fp")), \
         patch.object(lg, "verify_token", return_value=verified), \
         patch.object(lg, "ReconnectDialog", return_value=fake_dialog):
        result = lg.ensure_licensed()

    assert result is None


def test_start_background_revalidation_saves_token_silently_on_success():
    # Sustituye LicenseRevalidateThread por un fake cuyo start() ejecuta el
    # worker de forma síncrona (mismo hilo que el test) en vez de generar un
    # QThread real — evita depender del timing de un hilo en segundo plano
    # real, que sería no-determinista con un único processEvents().
    class _SyncFakeThread:
        def __init__(self, worker, parent):
            self._worker = worker

        def start(self):
            self._worker.run()

        def quit(self):
            pass

    fake_response = Mock(
        status_code=200,
        json=lambda: {"token": "PLT1.bg.token", "license_expires_at": None},
    )

    with patch.object(lg, "LicenseRevalidateThread", _SyncFakeThread), \
         patch.object(lg, "compute_fingerprint", return_value=Mock(composite_hash="fp")), \
         patch("requests.post", return_value=fake_response), \
         patch.object(lg.license_storage, "save_token") as save_token:
        lg.start_background_revalidation("key-abc", Mock())

    save_token.assert_called_once_with("PLT1.bg.token")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ui.license.license_gate'`

- [ ] **Step 3: Write minimal implementation**

Create `ui/license/license_gate.py`:

```python
"""Puerta de licencia: se ejecuta al arrancar PDFlex, antes de construir la
ventana principal (spec §1.1, §1.2).
"""

from __future__ import annotations

from datetime import datetime, timezone

from core import license_storage
from core.license_manager import LicenseRevalidateThread, LicenseRevalidateWorker
from core.license_token import LicenseInvalidError, verify_token
from core.machine_fingerprint import compute_fingerprint
from ui.license.activation_dialog import ActivationDialog
from ui.license.reconnect_dialog import ReconnectDialog


def ensure_licensed(parent=None) -> str | None:
    """Garantiza que PDFlex tenga una licencia local válida antes de
    continuar el arranque. Devuelve el `key_id` activo si se puede
    continuar, o None si la aplicación debe salir."""
    fingerprint = compute_fingerprint()
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

    reactivated = verify_token(dialog.activated_token, fingerprint.composite_hash, datetime.now(timezone.utc))
    return reactivated.claims.key_id


def start_background_revalidation(key_id: str, parent) -> None:
    """Revalidación silenciosa: no bloquea ni interrumpe al usuario si
    falla. `parent` debe ser un QObject vivo (ej. la ventana principal)
    para que Qt mantenga el hilo vivo mientras corre — mismo patrón que
    UpdateCheckThread en core/updater.py."""
    fingerprint = compute_fingerprint()
    worker = LicenseRevalidateWorker(key_id, fingerprint)
    thread = LicenseRevalidateThread(worker, parent)
    worker.success.connect(lambda token, expires: license_storage.save_token(token))
    worker.success.connect(thread.quit)
    worker.error.connect(thread.quit)
    thread.start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/test_license_gate.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add ui/license/license_gate.py tests/test_license_gate.py
git commit -m "feat: add license gate orchestration for app startup"
```

---

### Task 11: Wire the license gate into `main.py`

**Files:**
- Modify: `main.py:66-95` (the `main()` function)

**Interfaces:**
- Consumes: `ui.license.license_gate.ensure_licensed`/`start_background_revalidation` (Task 10).

This task has no isolated unit to TDD — `main()` is the application entry point, so it is verified by actually running the app (Step 3 below), consistent with how this project already validates UI behavior per `CLAUDE.md`/skill guidance ("For UI or frontend changes... test the feature in a browser/app before reporting complete").

- [ ] **Step 1: Make the change**

Open `main.py`. The current `main()` function body is:

```python
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)

    from PySide6.QtCore import QTimer
    from shell.shell_window import ShellWindow
    from shell.splash import SplashScreen
    splash = SplashScreen()
    splash.start()

    win = ShellWindow()
    win._launcher.ready.connect(lambda: QTimer.singleShot(0, splash.close))
    win.showMaximized()
    return app.exec()
```

Replace it with:

```python
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)

    from ui.license.license_gate import ensure_licensed, start_background_revalidation
    license_key_id = ensure_licensed()
    if license_key_id is None:
        return 0

    from PySide6.QtCore import QTimer
    from core.update_config import UPDATE_STARTUP_DELAY_MS
    from shell.shell_window import ShellWindow
    from shell.splash import SplashScreen
    splash = SplashScreen()
    splash.start()

    win = ShellWindow()
    win._launcher.ready.connect(lambda: QTimer.singleShot(0, splash.close))
    win.showMaximized()

    QTimer.singleShot(
        UPDATE_STARTUP_DELAY_MS,
        lambda: start_background_revalidation(license_key_id, win),
    )

    return app.exec()
```

- [ ] **Step 2: Run the full test suite to make sure nothing broke**

Run: `.venv_nuitka/Scripts/python.exe -m pytest tests/ -v`
Expected: all tests pass (the previously-existing suite plus all tests added in Tasks 1-10).

- [ ] **Step 3: Run the app and manually verify the gate**

Run: `.venv_nuitka/Scripts/python.exe main.py`
Expected: with no local license token present (fresh machine, or after manually deleting `HKLM\Software\GRUPO OCMX\PDFlexLicense` and `C:\ProgramData\GRUPO OCMX\PDFlex\License\license.dat`), the `ActivationDialog` appears before `ShellWindow` and blocks it. Since `LICENSE_PUBLIC_KEY_ED25519` is still the development placeholder from Task 1 and there is no real server endpoint reachable yet, activating with any key will fail with a network/server error — that failure being shown correctly in the dialog (not a Python traceback) is what confirms the wiring is correct. Closing the dialog must close the app instead of opening `ShellWindow`.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: wire license gate into app startup"
```

---

### Task 12: `installer.iss` — non-elevated write access for license storage

**Files:**
- Modify: `installer.iss` (add a `[Dirs]` section before `[Icons]`, and one new `[Registry]` entry after the existing two)

**Interfaces:** none (build-config only; no Python interfaces).

This task is build-config, not testable via pytest. It is verified by actually compiling the installer (Step 3) and inspecting the result, per the project's existing build scripts.

- [ ] **Step 1: Add the `[Dirs]` section**

`installer.iss` currently has no `[Dirs]` section. Insert this new section immediately before the existing `[Icons]` section (which starts at line 148 with `[Icons]` / `; Menú Inicio`):

```ini
[Dirs]
; Carpeta de estado de licencia — permisos relajados para que PDFlex.exe
; (sin elevación tras la instalación) pueda escribir el token de licencia.
; No lleva flags de borrado agresivo: sobrevive a la desinstalación porque
; license.dat lo crea la app en tiempo de ejecución (no el instalador), y
; Inno Setup no borra en desinstalación un directorio que no está vacío.
Name: "{commonappdata}\{#AppPublisher}\{#AppName}\License"; \
    Permissions: users-modify

```

- [ ] **Step 2: Add the new `[Registry]` entry**

In the existing `[Registry]` section, immediately after the current two entries (`InstallPath` and `Version`, ending around line 176), add:

```ini
; Estado de licencia — clave HERMANA de Software\{#AppPublisher}\{#AppName}
; (NO anidada bajo ella): esa clave tiene Flags: uninsdeletekey en su primer
; valor (arriba), y una subclave ahí se borraría al desinstalar PDFlex.
; Mismo patrón que Software\{#AppPublisher}\PDFlexEnterpriseServices.
Root: HKLM; \
    Subkey: "Software\{#AppPublisher}\PDFlexLicense"; \
    Permissions: users-modify
```

The full `[Registry]` section should now read:

```ini
[Registry]
; Ruta de instalación (usada por el auto-updater para detectar instalación existente)
Root: HKLM; \
    Subkey: "Software\{#AppPublisher}\{#AppName}"; \
    ValueType: string; ValueName: "InstallPath"; \
    ValueData: "{app}"; \
    Flags: uninsdeletekey

Root: HKLM; \
    Subkey: "Software\{#AppPublisher}\{#AppName}"; \
    ValueType: string; ValueName: "Version"; \
    ValueData: "{#AppVersion}"

; Estado de licencia — clave HERMANA de Software\{#AppPublisher}\{#AppName}
; (NO anidada bajo ella): esa clave tiene Flags: uninsdeletekey en su primer
; valor (arriba), y una subclave ahí se borraría al desinstalar PDFlex.
; Mismo patrón que Software\{#AppPublisher}\PDFlexEnterpriseServices.
Root: HKLM; \
    Subkey: "Software\{#AppPublisher}\PDFlexLicense"; \
    Permissions: users-modify
```

- [ ] **Step 3: Build the installer and verify the registry/folder permissions**

Run (from an elevated PowerShell, matching the project's existing build process): `.\build_setup.ps1` (or whatever the project's documented Inno Setup build entry point is — check `build_nuitka.ps1`/`build_setup.ps1` for the exact current invocation if this has changed since this plan was written).

Then install the produced `dist\PDFlex_<version>_Setup.exe` on a test machine/VM as an administrator, and as a **different, non-administrator** Windows user on that same machine, run PDFlex and confirm:
- `HKEY_LOCAL_MACHINE\Software\GRUPO OCMX\PDFlexLicense` exists after install.
- `C:\ProgramData\GRUPO OCMX\PDFlex\License` exists after install.
- The non-admin user account can trigger the `ActivationDialog` (Task 11's manual check) without a permissions error — this is the concrete proof that `Permissions: users-modify` took effect.

Expected: no `PermissionError`/`OSError` from `core/license_storage.py` when running as a standard user.

- [ ] **Step 4: Commit**

```bash
git add installer.iss
git commit -m "feat: grant non-elevated write access for license storage paths"
```

---

## Self-Review Notes

- **Spec coverage:** §1 (UX flow) → Tasks 7, 8, 11. §2 (module layout) → Tasks 1-10 collectively match the file list exactly. §3 (fingerprint) → Task 2. §4 (token) → Task 4. §5 (key format) → Task 3. §6 (protocol) → Task 6. §7 (storage) → Task 5, Task 12. §8 (revalidation/grace/revocation) → Tasks 4, 8, 10. §9 (transfer) → Task 9. §10 (anti-tamper v1: multiple check points) → satisfied structurally by Task 10's gate running at startup plus Task 9's panel being the only place a valid `LicenseClaims` object exists to act on; §10's explicitly-deferred items (structural license-context threading, runtime self-checksums) are correctly *not* in this plan, matching the spec's own "fuera de alcance v1". §11 (clock-rollback guard) is **not implemented in this plan** — flagged below as a gap. §12 (updater/installer integration) → Tasks 1, 6, 11, 12. §14 (testing) → every task's own test file.
- **Gap found:** spec §11 (anti-rollback clock guard: remember the last known-good server time, distrust large backward jumps) has no dedicated task. It was deliberately left out of this plan because it depends on capturing a trustworthy server timestamp from HTTP responses, which touches `core/license_manager.py`'s response handling and `core/license_storage.py`'s persisted state in a way that's cleanly a follow-up once the core gate (Tasks 1-11) is proven working end-to-end against a real server. Recommend a small follow-up plan once Task 12 is verified in production, rather than speculatively building it now against a server contract that hasn't been exercised yet.
- **Placeholder scan:** no TBD/TODO markers; the one intentional placeholder (`LICENSE_PUBLIC_KEY_ED25519` in Task 1) is a real, working string that makes the code run today and is explicitly called out at every point it matters (Task 1's comment, Task 11 Step 3's manual-test note) — not a gap in the plan, but a genuine external dependency on the server team's deliverable from `docs/licensing/server-ai-prompt.md` §15.
- **Type consistency checked:** `Fingerprint` (Task 2) → consumed identically in Tasks 6, 7, 8, 9, 10. `LicenseClaims`/`VerifiedLicense`/`LicenseInvalidError` family (Task 4) → consumed identically in Tasks 9, 10. Worker/Thread constructor signatures (Task 6) → match call sites exactly in Tasks 7, 8, 9, 10. `ensure_licensed` return type (`str | None`) is used consistently by its only caller (Task 11).

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-12-pdflex-licensing-client.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
