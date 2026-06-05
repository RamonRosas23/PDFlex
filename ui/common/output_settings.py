"""Global output naming preferences."""
from __future__ import annotations

from PyQt6.QtCore import QSettings


ORG_NAME = "GRUPO OCMX"
APP_NAME = "PDFlex"
ADD_TOOL_SUFFIX_KEY = "outputs/add_tool_suffix"
DEFAULT_ADD_TOOL_SUFFIX = True


def add_tool_suffix_enabled() -> bool:
    settings = QSettings(ORG_NAME, APP_NAME)
    return _as_bool(
        settings.value(ADD_TOOL_SUFFIX_KEY, DEFAULT_ADD_TOOL_SUFFIX),
        DEFAULT_ADD_TOOL_SUFFIX,
    )


def set_add_tool_suffix_enabled(enabled: bool) -> None:
    settings = QSettings(ORG_NAME, APP_NAME)
    settings.setValue(ADD_TOOL_SUFFIX_KEY, bool(enabled))


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "si", "sí", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default
