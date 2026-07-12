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
