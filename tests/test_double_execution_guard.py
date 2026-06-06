"""Tests para prevención de doble ejecución de workers."""
import time
import sys
import pytest
from PyQt6.QtWidgets import QApplication
from ui.common.base_worker import BaseWorker, WorkerThread


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    yield a


class LongRunningWorker(BaseWorker):
    def run(self) -> None:
        for _ in range(30):
            if self.is_cancelled():
                self.error.emit("cancelled")
                return
            time.sleep(0.05)
        self.finished.emit([])


def test_stop_active_worker_cancela_thread_activo(app):
    """_stop_active_worker debe cancelar y esperar el thread activo."""
    from PyQt6.QtWidgets import QWidget
    from PyQt6.QtCore import QThread

    class MockWindow(QWidget):
        def __init__(self):
            super().__init__()
            self._worker = LongRunningWorker()
            self._worker_thread = QThread(self)
            self._worker.moveToThread(self._worker_thread)
            self._worker_thread.started.connect(self._worker.run)
            self._worker.finished.connect(self._worker_thread.quit)
            self._worker.error.connect(self._worker_thread.quit)
            self._worker_thread.finished.connect(self._worker.deleteLater)
            self._worker_thread.finished.connect(self._worker_thread.deleteLater)

        # Importar y usar _stop_active_worker desde PipelineWindow
        # Simulamos el comportamiento directamente
        def _stop_active_worker(self):
            worker = getattr(self, "_worker", None)
            thread = getattr(self, "_worker_thread", None)
            if worker and callable(getattr(worker, "cancel", None)):
                worker.cancel()
            if thread is not None and hasattr(thread, "isRunning") and thread.isRunning():
                try:
                    thread.quit()
                except Exception:
                    pass
                thread.wait(3000)

    win = MockWindow()
    win._worker_thread.start()
    assert win._worker_thread.isRunning()

    win._stop_active_worker()
    assert not win._worker_thread.isRunning()


def test_double_start_raises_con_worker_thread(app):
    """WorkerThread no permite doble start."""
    wt = WorkerThread(LongRunningWorker())
    wt.start()
    with pytest.raises(RuntimeError):
        wt.start()
    wt.cancel_and_wait(timeout_ms=3000)
