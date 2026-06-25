"""Contrato de transferencia entre herramientas."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal
from uuid import uuid4


TransferMode = Literal["replace", "append"]
TrayPolicy = Literal["keep", "replace_with_sent", "clear"]


@dataclass
class ToolTransfer:
    """Describe archivos enviados desde una herramienta a otra."""

    paths: List[str]
    source_tool_id: str = ""
    source_tool_title: str = ""
    mode: TransferMode = "replace"
    tray_policy: TrayPolicy = "keep"
    kind: str = "output"
    batch_id: str = field(default_factory=lambda: uuid4().hex)
    parent_ids: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.paths = [p for p in self.paths if p]
        if self.mode not in ("replace", "append"):
            raise ValueError(f"Modo de transferencia no soportado: {self.mode}")
        if self.tray_policy not in ("keep", "replace_with_sent", "clear"):
            raise ValueError(
                f"Politica de bandeja no soportada: {self.tray_policy}"
            )
