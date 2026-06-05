"""BaseWorker — patrón QObject/QThread reutilizable para todas las herramientas."""
from __future__ import annotations
from PyQt6.QtCore import QObject, pyqtSignal


class BaseWorker(QObject):
    """Señales estándar que todos los workers de PDFlex emiten."""
    progress = pyqtSignal(int, int, str)   # current, total, message
    finished = pyqtSignal(list)            # lista de resultados
    error = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        raise NotImplementedError
