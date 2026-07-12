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
