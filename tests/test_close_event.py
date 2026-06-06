"""Tests para cleanup de threads en close."""
import sys
import time
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThread
from ui.common.base_worker import BaseWorker, WorkerThread


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    yield a


class SlowWriteWorker(BaseWorker):
    """Simula un worker que escribe un archivo (no hace polling de cancel)."""
    def run(self) -> None:
        time.sleep(0.2)  # Simula escritura
        self.finished.emit([])


def test_cancel_and_wait_completa_antes_de_continuar(app):
    """cancel_and_wait() debe bloquear hasta que el thread termine."""
    wt = WorkerThread(SlowWriteWorker())
    wt.start()
    assert wt.is_running()
    finished = wt.cancel_and_wait(timeout_ms=2000)
    assert finished
    assert not wt.is_running()


def test_cleanup_multiple_threads(app):
    """Múltiples threads pueden cancelarse y esperarse secuencialmente."""
    workers = [WorkerThread(SlowWriteWorker()) for _ in range(3)]
    for wt in workers:
        wt.start()
    for wt in workers:
        wt.cancel_and_wait(timeout_ms=2000)
    assert all(not wt.is_running() for wt in workers)
