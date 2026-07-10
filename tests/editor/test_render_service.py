"""Caché LRU por presupuesto de bytes + RenderService con cancelación por generación."""
import pytest

from core.editor.render.pixmap_cache import ByteBudgetLRU


def test_lru_evicts_by_byte_budget():
    cache = ByteBudgetLRU(budget_bytes=100)
    cache.put("a", object(), size_bytes=40)
    cache.put("b", object(), size_bytes=40)
    assert cache.get("a") is not None          # 'a' queda como más reciente
    cache.put("c", object(), size_bytes=40)    # presupuesto: expulsa 'b' (LRU)
    assert cache.get("b") is None
    assert cache.get("a") is not None and cache.get("c") is not None
    assert cache.used_bytes <= 100


def test_lru_rejects_oversized_item_without_breaking():
    cache = ByteBudgetLRU(budget_bytes=10)
    cache.put("big", object(), size_bytes=50)  # no cabe: no se almacena
    assert cache.get("big") is None
    assert cache.used_bytes == 0


def test_lru_replaces_existing_key_accounting_bytes():
    cache = ByteBudgetLRU(budget_bytes=100)
    cache.put("a", "v1", size_bytes=60)
    cache.put("a", "v2", size_bytes=30)        # reemplazo: libera los 60 primero
    assert cache.get("a") == "v2"
    assert cache.used_bytes == 30
    cache.clear()
    assert cache.get("a") is None and cache.used_bytes == 0


# ── RenderService (Qt en la frontera, patrón qapp de la suite) ──────────────

import sys

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    """QApplication compartida para todo el módulo (patrón test_smoke_tools)."""
    instance = QApplication.instance() or QApplication(sys.argv)
    yield instance


def _wait_for(app, predicate, timeout_ms=8000):
    from PySide6.QtCore import QElapsedTimer
    t = QElapsedTimer()
    t.start()
    while not predicate():
        app.processEvents()
        if t.elapsed() > timeout_ms:
            raise TimeoutError("el render no llegó a tiempo")


def test_render_service_delivers_pixmap(qapp, make_pdf):
    from core.editor.render.render_service import RenderService
    path = make_pdf(rotations=[0, 90])
    svc = RenderService(str(path))
    got = []
    svc.pixmap_ready.connect(lambda page, scale, gen, img: got.append((page, scale, img)))
    svc.start()
    try:
        svc.request_page(page=1, scale=1.5)
        _wait_for(qapp, lambda: len(got) == 1)
        page, scale, img = got[0]
        assert page == 1 and scale == 1.5
        # página /Rotate=90 → display 842x595 pt → a 1.5x ≈ 1263x892 px
        assert abs(img.width() - round(842 * 1.5)) <= 2
        assert abs(img.height() - round(595 * 1.5)) <= 2
    finally:
        svc.stop()


def test_render_service_serves_from_cache_synchronously(qapp, make_pdf):
    from core.editor.render.render_service import RenderService
    path = make_pdf(rotations=[0])
    svc = RenderService(str(path))
    got = []
    svc.pixmap_ready.connect(lambda page, scale, gen, img: got.append(img))
    svc.start()
    try:
        svc.request_page(page=0, scale=1.0)
        _wait_for(qapp, lambda: len(got) == 1)
        svc.request_page(page=0, scale=1.0)   # caché: emite sin pasar por la cola
        assert len(got) == 2
    finally:
        svc.stop()


def test_render_service_generation_cancels_stale(qapp, make_pdf):
    from core.editor.render.render_service import RenderService
    path = make_pdf(rotations=[0] * 12)
    svc = RenderService(str(path))
    got = []
    svc.pixmap_ready.connect(lambda page, scale, gen, img: got.append(gen))
    svc.start()
    try:
        for p in range(12):
            svc.request_page(page=p, scale=2.0)   # generación 0 (zoom viejo)
        svc.bump_generation()                      # usuario cambió el zoom
        svc.request_page(page=0, scale=3.0)        # generación 1
        _wait_for(qapp, lambda: 1 in got)
        svc.drain()                                # procesa lo que quede en vuelo
        stale = [g for g in got if g == 0]
        assert len(stale) <= 2, f"se entregaron {len(stale)} renders obsoletos"
    finally:
        svc.stop()


def test_render_service_reports_failures(qapp, make_pdf):
    from core.editor.render.render_service import RenderService
    path = make_pdf(rotations=[0])
    svc = RenderService(str(path))
    errors = []
    svc.render_failed.connect(lambda page, msg: errors.append((page, msg)))
    svc.start()
    try:
        svc.request_page(page=99, scale=1.0)       # página inexistente
        _wait_for(qapp, lambda: len(errors) == 1)
        assert errors[0][0] == 99 and errors[0][1]
    finally:
        svc.stop()
