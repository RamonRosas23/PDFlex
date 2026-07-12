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


def test_verify_token_rejects_wrong_app(keypair):
    now = datetime.now(timezone.utc)
    token = _make_token(keypair, now=now, app="some-other-app")

    with pytest.raises(lt.LicenseFormatError):
        lt.verify_token(token, expected_fingerprint="fp-hash-123", now=now)


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


def test_verify_token_rejects_signed_token_missing_required_field(keypair):
    now = datetime.now(timezone.utc)
    claims = {
        "v": 1,
        # "key_id" deliberately omitted
        "fingerprint": "fp-hash-123",
        "issued_at": _iso(now),
        "valid_until": _iso(now + timedelta(days=14)),
        "license_expires_at": None,
        "status": "active",
        "customer_name": "Empresa de Prueba",
        "app": "pdflex",
        "seats_allowed": 1,
    }
    claims_bytes = json.dumps(claims, separators=(",", ":")).encode("utf-8")
    signature = keypair.sign(claims_bytes)
    token = "PLT1." + _b64url_encode(claims_bytes) + "." + _b64url_encode(signature)

    with pytest.raises(lt.LicenseFormatError):
        lt.verify_token(token, expected_fingerprint="fp-hash-123", now=now)


def test_verify_token_rejects_signed_token_with_non_string_date_field(keypair):
    now = datetime.now(timezone.utc)
    claims = {
        "v": 1,
        "key_id": "key-abc",
        "fingerprint": "fp-hash-123",
        "issued_at": 1234567890,  # tipo incorrecto: número en vez de string ISO
        "valid_until": _iso(now + timedelta(days=14)),
        "license_expires_at": None,
        "status": "active",
        "customer_name": "Empresa de Prueba",
        "app": "pdflex",
        "seats_allowed": 1,
    }
    claims_bytes = json.dumps(claims, separators=(",", ":")).encode("utf-8")
    signature = keypair.sign(claims_bytes)
    token = "PLT1." + _b64url_encode(claims_bytes) + "." + _b64url_encode(signature)

    with pytest.raises(lt.LicenseFormatError):
        lt.verify_token(token, expected_fingerprint="fp-hash-123", now=now)
