"""Uso local de herramientas para ordenar el launcher de PDFlex."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, Mapping

from PyQt6.QtCore import QSettings


ORG_NAME = "GRUPO OCMX"
APP_NAME = "PDFlex"
USAGE_PREFIX = "launcher/usage"


@dataclass(frozen=True)
class ToolUsageStat:
    count: int = 0
    last_used: float = 0.0


def rank_tool_ids(
    tool_ids: Iterable[str],
    usage: Mapping[str, ToolUsageStat],
    fallback_order: Iterable[str],
    *,
    limit: int,
) -> list[str]:
    """Ordena herramientas por uso local y completa con el orden editorial."""
    ids = list(dict.fromkeys(tool_ids))
    fallback = list(dict.fromkeys(fallback_order))
    fallback_pos = {tool_id: index for index, tool_id in enumerate(fallback)}

    def key(tool_id: str) -> tuple[int, int, float, int, str]:
        stat = usage.get(tool_id, ToolUsageStat())
        used = 1 if stat.count > 0 else 0
        return (
            -used,
            -int(stat.count),
            -float(stat.last_used),
            fallback_pos.get(tool_id, 10_000),
            tool_id,
        )

    ranked = sorted(ids, key=key)
    return ranked[: max(0, limit)]


class ToolUsageStore:
    """Persistencia sencilla y local de frecuencia/recencia de uso."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings(ORG_NAME, APP_NAME)

    def record_open(self, tool_id: str, *, now: float | None = None) -> None:
        now = time.time() if now is None else float(now)
        stat = self.stat(tool_id)
        self._settings.setValue(self._count_key(tool_id), int(stat.count) + 1)
        self._settings.setValue(self._last_key(tool_id), now)

    def stat(self, tool_id: str) -> ToolUsageStat:
        return ToolUsageStat(
            count=_as_int(self._settings.value(self._count_key(tool_id), 0)),
            last_used=_as_float(self._settings.value(self._last_key(tool_id), 0.0)),
        )

    def snapshot(self, tool_ids: Iterable[str]) -> dict[str, ToolUsageStat]:
        return {tool_id: self.stat(tool_id) for tool_id in tool_ids}

    def has_usage(self, tool_ids: Iterable[str]) -> bool:
        return any(self.stat(tool_id).count > 0 for tool_id in tool_ids)

    @staticmethod
    def _count_key(tool_id: str) -> str:
        return f"{USAGE_PREFIX}/{tool_id}/count"

    @staticmethod
    def _last_key(tool_id: str) -> str:
        return f"{USAGE_PREFIX}/{tool_id}/last_used"


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
