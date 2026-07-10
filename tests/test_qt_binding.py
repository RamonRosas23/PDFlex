"""Regression checks for the single Qt binding used by PDFlex."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtSvg import QSvgRenderer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_PATHS = (
    PROJECT_ROOT / "main.py",
    PROJECT_ROOT / "core",
    PROJECT_ROOT / "shell",
    PROJECT_ROOT / "ui",
    PROJECT_ROOT / "packaging",
)


def _production_python_files():
    for path in PRODUCTION_PATHS:
        if path.is_file():
            yield path
        else:
            yield from path.rglob("*.py")


def test_production_code_uses_pyside6_exclusively() -> None:
    stale_references: list[str] = []
    for path in _production_python_files():
        source = path.read_text(encoding="utf-8")
        if "PyQt6" in source or "pyqtSignal" in source:
            stale_references.append(str(path.relative_to(PROJECT_ROOT)))

    assert stale_references == []


def test_pyside_signal_round_trip() -> None:
    class Emitter(QObject):
        changed = Signal(str)

    received: list[str] = []
    emitter = Emitter()
    emitter.changed.connect(received.append)
    emitter.changed.emit("ready")

    assert received == ["ready"]


def test_qt_svg_module_is_available() -> None:
    assert not QSvgRenderer().isValid()
