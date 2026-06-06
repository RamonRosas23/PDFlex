"""BaseWorker y WorkerThread — infraestructura unificada de threading para PDFlex."""
from __future__ import annotations

import threading
from typing import Optional

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal


class BaseWorker(QObject):
    """Worker base thread-safe para todas las herramientas de PDFlex.

    Señales:
        progress(current, total, message): progreso de la tarea.
        finished(results): lista de resultados al completar.
        error(message): mensaje de error si la tarea falla.
    """

    progress = pyqtSignal(int, int, str)   # current, total, message
    finished = pyqtSignal(list)            # lista de resultados
    error = pyqtSignal(str)               # mensaje de error

    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Solicita cancelación del worker. Thread-safe."""
        self._cancel.set()

    def is_cancelled(self) -> bool:
        """Retorna True si se solicitó cancelación. Thread-safe."""
        return self._cancel.is_set()

    def run(self) -> None:
        """Ejecuta la tarea. Las subclases deben implementar este método."""
        raise NotImplementedError


class WorkerThread:
    """Envuelve un BaseWorker en un QThread con manejo correcto del ciclo de vida.

    Uso:
        worker = MiWorker(config)
        worker.finished.connect(on_finished)
        wt = WorkerThread(worker)
        wt.start()
        # Para cancelar:
        wt.cancel_and_wait()
    """

    def __init__(self, worker: BaseWorker, parent: Optional[QObject] = None) -> None:
        self.worker = worker
        self._thread: Optional[QThread] = QThread(parent)
        self._started = False

        # Mover el worker al thread antes de iniciar
        worker.moveToThread(self._thread)

        # Conexiones del ciclo de vida.
        # DirectConnection para finished/error: el worker emite desde su propio
        # thread; con conexión directa, quit() se llama en el mismo thread sin
        # necesitar event loop en el thread principal.
        self._thread.started.connect(worker.run)
        worker.finished.connect(
            self._thread.quit, Qt.ConnectionType.DirectConnection
        )
        worker.error.connect(
            self._thread.quit, Qt.ConnectionType.DirectConnection
        )
        self._thread.finished.connect(worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

    def start(self) -> None:
        """Inicia el thread.

        Raises:
            RuntimeError: si el thread ya está en ejecución.
            RuntimeError: si el thread ya fue destruido.
        """
        if self._started:
            raise RuntimeError(
                "WorkerThread ya en ejecución. Llama cancel_and_wait() primero."
            )
        if self._thread is None:
            raise RuntimeError("WorkerThread ya fue destruido.")

        self._started = True
        self._thread.start()

    def cancel_and_wait(self, timeout_ms: int = 5000) -> bool:
        """Cancela el worker y espera a que el thread termine.

        Args:
            timeout_ms: tiempo máximo de espera en milisegundos.

        Returns:
            True si el thread terminó dentro del timeout, False si agotó el tiempo.
        """
        self.worker.cancel()
        self._thread.quit()
        finished = self._thread.wait(timeout_ms)
        return finished

    def wait(self, timeout_ms: int = 5000) -> bool:
        """Espera terminación sin cancelar. Para uso en tests."""
        if self._thread is None:
            return True
        return self._thread.wait(timeout_ms)

    def is_running(self) -> bool:
        """Retorna True si el thread está actualmente en ejecución."""
        return self._thread is not None and self._thread.isRunning()
