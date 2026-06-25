"""ShellContext — objeto compartido inyectado en cada herramienta."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, List, TYPE_CHECKING

from .transfer import ToolTransfer

if TYPE_CHECKING:
    from .tray import PdfTray
    from .word_to_pdf import WordToPdfConverter


@dataclass
class ShellContext:
    tray: "PdfTray"
    word_converter: "WordToPdfConverter"
    open_tool: Callable[[str, List[str] | ToolTransfer | None], None]
