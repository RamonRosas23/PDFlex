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
