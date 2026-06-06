"""Tests para ui/common/base_worker.py — BaseWorker + WorkerThread."""
from __future__ import annotations

import sys
import pytest
from PyQt6.QtCore import QThread


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication(sys.argv)
    yield a


# ---------------------------------------------------------------------------
# Workers de ayuda para los tests
# ---------------------------------------------------------------------------

def _make_fast_worker():
    """Worker que termina inmediatamente emitiendo finished con ['ok']."""
    from ui.common.base_worker import BaseWorker

    class FastWorker(BaseWorker):
        def run(self):
            self.finished.emit(["ok"])

    return FastWorker()


def _make_sleeping_worker(sleep_ms: int = 5000):
    """Worker que duerme en loop hasta que se cancele."""
    from ui.common.base_worker import BaseWorker

    class SleepingWorker(BaseWorker):
        def run(self):
            while not self.is_cancelled():
                QThread.msleep(50)
            self.finished.emit([])

    return SleepingWorker()


def _make_notimpl_worker():
    """Subclase de BaseWorker que no implementa run()."""
    from ui.common.base_worker import BaseWorker
    return BaseWorker()


# ---------------------------------------------------------------------------
# Test 1: cancel_and_wait() detiene un worker que duerme en loop
# ---------------------------------------------------------------------------

def test_cancel_and_wait_stops_sleeping_worker(app):
    from ui.common.base_worker import WorkerThread

    worker = _make_sleeping_worker(sleep_ms=5000)
    wt = WorkerThread(worker)
    wt.start()

    # Pequeña pausa para asegurarnos de que el thread arrancó
    QThread.msleep(100)
    assert wt.is_running()

    finished = wt.cancel_and_wait(timeout_ms=3000)
    assert finished, "cancel_and_wait() debería retornar True cuando el thread termina"
    assert not wt.is_running()


# ---------------------------------------------------------------------------
# Test 2: llamar start() dos veces lanza RuntimeError
# ---------------------------------------------------------------------------

def test_double_start_raises_runtime_error(app):
    from ui.common.base_worker import WorkerThread

    worker = _make_sleeping_worker()
    wt = WorkerThread(worker)
    wt.start()

    try:
        with pytest.raises(RuntimeError, match="ya en ejecución"):
            wt.start()
    finally:
        wt.cancel_and_wait(timeout_ms=3000)


# ---------------------------------------------------------------------------
# Test 3: worker rápido emite finished correctamente
# ---------------------------------------------------------------------------

def test_fast_worker_emits_finished(app):
    from PyQt6.QtCore import Qt
    from ui.common.base_worker import WorkerThread

    worker = _make_fast_worker()
    results_received = []
    # DirectConnection: el slot se ejecuta en el worker thread, sin necesidad
    # de event loop en el thread principal para procesar la señal.
    worker.finished.connect(
        lambda r: results_received.extend(r),
        Qt.ConnectionType.DirectConnection,
    )

    wt = WorkerThread(worker)
    wt.start()

    # Esperar a que el thread termine (max 3s)
    wt._thread.wait(3000)

    assert results_received == ["ok"], f"Se esperaba ['ok'], se obtuvo {results_received}"
    assert not wt.is_running()


# ---------------------------------------------------------------------------
# Test 4: is_cancelled() retorna True después de cancel()
# ---------------------------------------------------------------------------

def test_is_cancelled_after_cancel(app):
    from ui.common.base_worker import BaseWorker

    class ConcreteWorker(BaseWorker):
        def run(self):
            self.finished.emit([])

    worker = ConcreteWorker()
    assert not worker.is_cancelled()
    worker.cancel()
    assert worker.is_cancelled()


# ---------------------------------------------------------------------------
# Test 5: run() en BaseWorker base lanza NotImplementedError
# ---------------------------------------------------------------------------

def test_base_worker_run_raises_not_implemented(app):
    from ui.common.base_worker import BaseWorker

    worker = BaseWorker()
    with pytest.raises(NotImplementedError):
        worker.run()


# ---------------------------------------------------------------------------
# Test 6: cancel() es thread-safe — múltiples llamadas no fallan
# ---------------------------------------------------------------------------

def test_cancel_is_idempotent(app):
    from ui.common.base_worker import BaseWorker

    class ConcreteWorker(BaseWorker):
        def run(self):
            self.finished.emit([])

    worker = ConcreteWorker()
    worker.cancel()
    worker.cancel()  # segunda llamada no debe fallar
    assert worker.is_cancelled()


# ---------------------------------------------------------------------------
# Test 7: WorkerThread.is_running() es False antes de start()
# ---------------------------------------------------------------------------

def test_is_running_false_before_start(app):
    from ui.common.base_worker import WorkerThread

    worker = _make_fast_worker()
    wt = WorkerThread(worker)
    assert not wt.is_running()
