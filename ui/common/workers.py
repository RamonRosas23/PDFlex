# Deprecated: usar ui/common/base_worker.py
"""BaseWorker — patrón QObject/QThread reutilizable para todas las herramientas."""
from __future__ import annotations
from PySide6.QtCore import QObject, Signal


class BaseWorker(QObject):
    """Señales estándar que todos los workers de PDFlex emiten."""
    progress = Signal(int, int, str)   # current, total, message
    finished = Signal(list)            # lista de resultados
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        raise NotImplementedError
