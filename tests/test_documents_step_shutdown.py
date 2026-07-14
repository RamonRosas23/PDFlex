"""Apagado de los hilos de miniaturas de DocumentsCard.

El wait() sin límite original podía congelar el cierre de PDFlex para
siempre si un render de PDFium se colgaba con un PDF patológico; y destruir
el QThread aún corriendo es un qFatal de Qt (aborta el proceso entero). El
comportamiento correcto es: espera acotada y, si el hilo no termina,
desengancharlo de su padre y conservarlo como zombi referenciado.
"""
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

_app = QApplication.instance() or QApplication([])


def test_shutdown_background_jobs_detaches_hung_thread_instead_of_freezing(monkeypatch):
    import ui.common.documents_step as ds
    from ui.common.tool_scaffold import RunnerThread

    release = threading.Event()

    def _hung_render():
        release.wait(30)  # simula un renderer colgado que ignora la interrupción

    holder = QWidget()  # padre cuya destrucción abortaría el proceso con el hilo vivo
    thread = RunnerThread(_hung_render, holder)
    thread.start()
    deadline = time.monotonic() + 5.0
    while not thread.isRunning() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert thread.isRunning()

    # Solo el estado que shutdown_background_jobs toca; el __init__ completo
    # necesitaría un ToolContext real.
    card = ds.DocumentsCard.__new__(ds.DocumentsCard)
    card._thumb_threads = [thread]
    card._thumb_workers = {thread: object()}

    monkeypatch.setattr(ds, "_SHUTDOWN_WAIT_MS", 100)
    t0 = time.monotonic()
    ds.DocumentsCard.shutdown_background_jobs(card)
    elapsed = time.monotonic() - t0

    try:
        assert elapsed < 3.0  # no se quedó esperando sin límite
        assert thread.parent() is None  # destruir `holder` ya no arrastra al hilo
        assert thread in ds._ZOMBIE_THUMB_THREADS
        assert card._thumb_threads == []
        assert card._thumb_workers == {}
    finally:
        release.set()
        thread.wait(5000)
        if thread in ds._ZOMBIE_THUMB_THREADS:
            ds._ZOMBIE_THUMB_THREADS.remove(thread)


def test_shutdown_background_jobs_waits_fast_threads_normally():
    import ui.common.documents_step as ds
    from ui.common.tool_scaffold import RunnerThread

    holder = QWidget()
    thread = RunnerThread(lambda: None, holder)
    thread.start()

    card = ds.DocumentsCard.__new__(ds.DocumentsCard)
    card._thumb_threads = [thread]
    card._thumb_workers = {thread: object()}

    ds.DocumentsCard.shutdown_background_jobs(card)

    assert not thread.isRunning()
    assert thread not in ds._ZOMBIE_THUMB_THREADS  # terminó dentro del tope
    assert thread.parent() is holder  # sigue colgado de su padre normal
