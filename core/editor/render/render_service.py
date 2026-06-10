"""Hilo de render dedicado: ÚNICO dueño del fitz.Document de lectura (spec §5.3).

La UI pide (página, escala) y recibe pixmap_ready(page, scale, generation, QImage).
bump_generation() invalida lo encolado (cambio de zoom): los trabajos con
generación vieja se descartan antes de renderizar — nunca se desperdicia un
render que ya nadie quiere (riesgo histórico de freezes de la suite).

Hits de caché se emiten síncronos desde request_page (sin pasar por la cola).
El caché se comparte entre hilos → todo acceso va bajo self._lock.
"""
from __future__ import annotations

import queue
import threading

import fitz
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QImage

from .pixmap_cache import ByteBudgetLRU

_SENTINEL = None


class RenderService(QObject):
    pixmap_ready = pyqtSignal(int, float, int, QImage)   # page, scale, generation, image
    render_failed = pyqtSignal(int, str)                  # page, error

    def __init__(self, pdf_path: str, cache_budget_mb: int = 384) -> None:
        super().__init__()
        self._path = pdf_path
        self._queue: "queue.Queue" = queue.Queue()
        self._generation = 0
        self._lock = threading.Lock()       # protege generación Y caché
        self._cache = ByteBudgetLRU(cache_budget_mb * 1024 * 1024)
        self._thread: threading.Thread | None = None

    # ── API (hilo de UI) ────────────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="StudioRender", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._queue.put(_SENTINEL)
        if self._thread is not None:
            self._thread.join(timeout=10)

    def bump_generation(self) -> int:
        with self._lock:
            self._generation += 1
            return self._generation

    def request_page(self, page: int, scale: float) -> None:
        key = (page, round(scale, 3))
        with self._lock:
            gen = self._generation
            cached = self._cache.get(key)
        if cached is not None:
            self.pixmap_ready.emit(page, scale, gen, cached)
            return
        self._queue.put((gen, page, scale))

    def drain(self) -> None:
        """Bloquea hasta vaciar la cola (solo para tests)."""
        self._queue.join()

    # ── Hilo de render (único dueño del fitz.Document) ──────────────
    def _run(self) -> None:
        doc = fitz.open(self._path)
        try:
            while True:
                item = self._queue.get()
                if item is _SENTINEL:
                    self._queue.task_done()
                    return
                gen, page_idx, scale = item
                try:
                    with self._lock:
                        current = self._generation
                    if gen < current:
                        continue  # obsoleto: descartar sin renderizar
                    pix = doc[page_idx].get_pixmap(matrix=fitz.Matrix(scale, scale),
                                                   alpha=False)
                    img = QImage(pix.samples, pix.width, pix.height,
                                 pix.stride, QImage.Format.Format_RGB888).copy()
                    with self._lock:
                        self._cache.put((page_idx, round(scale, 3)), img,
                                        img.sizeInBytes())
                    self.pixmap_ready.emit(page_idx, scale, gen, img)
                except Exception as exc:           # noqa: BLE001 — se reporta a UI
                    self.render_failed.emit(page_idx, str(exc))
                finally:
                    self._queue.task_done()
        finally:
            doc.close()
