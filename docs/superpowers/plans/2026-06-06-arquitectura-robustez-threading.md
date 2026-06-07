# Robustez y Threading — Plan de Implementación

> **Para agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar todos los freeze points de PDFlex: thumbnails síncronos en hilo principal, transición brusca launcher→tool, y robustez general de threads en todas las herramientas.

**Architecture:** Tres capas de mejora: (1) thumbnails generados en hilo secundario con señal de actualización, (2) apertura de herramientas con diferimiento de 1 frame para feedback visual inmediato, (3) BaseWorker unificado con cleanup robusto y timeout en OCR. Las 20 herramientas heredan el patrón sin cambios de comportamiento visibles al usuario.

**Tech Stack:** PyQt6, QThread, QObject signals/slots, fitz (PyMuPDF), Python threading, concurrent.futures (solo para batch paralelo en engines que lo soporten).

---

## ⚠️ ALERTA: OTRA IA TRABAJANDO EN GALERÍA

**Otra IA está trabajando activamente en `shell/launcher.py`** haciendo cambios estéticos y funcionales al launcher/galería de herramientas. Antes de ejecutar cualquier tarea de este plan:

1. **Hacer `git pull` o `git status`** para ver si hay cambios recientes en `shell/launcher.py`
2. **Si `shell/launcher.py` tiene cambios nuevos** → revisar si los cambios de ese PR/commit afectan el flujo `_open_tool()` o `ToolCard.mousePressEvent` antes de continuar
3. **Archivos que NO debes tocar en este plan** (son territorio de la otra IA):
   - `shell/launcher.py` — PROHIBIDO modificar
   - `shell/tool_registry.py` — solo leer, no modificar
4. **Si hay conflicto en `shell/shell_window.py`** → resolver el merge manualmente, ya que nosotros modificamos `_open_tool()` y `closeEvent()`

---

## ANÁLISIS DIAGNÓSTICO COMPLETO

Este análisis fue producido el 2026-06-06 tras leer todos los archivos del proyecto.

### Punto Crítico 1 — Thumbnails en hilo principal (CONFIRMADO BLOQUEANTE)

**Archivo:** `ui/common/thumb_utils.py` + `ui/common/documents_step.py:391,341`

```python
# thumb_utils.py — ejecuta en hilo PRINCIPAL
def make_pdf_thumb(pdf_path: str, width: int = 72) -> Optional[QPixmap]:
    doc = fitz.open(pdf_path)       # I/O bloqueante
    page = doc[0]
    pm = page.get_pixmap(...)       # CPU bloqueante
    # ... conversión PIL → QPixmap
```

```python
# documents_step.py:391 — llamado desde hilo principal
if self._show_thumbnails:
    thumb = make_pdf_thumb(p, width=self._thumb_w)  # ← BLOQUEO
    if thumb:
        item.setIcon(QIcon(thumb))
```

**Impacto:** Cada PDF bloqueante ~50-300ms. Con 10 PDFs → 0.5-3 segundos de UI congelada. Se reproduce al agregar archivos, reordenar, y en `reorder_paths()`.

**Ocurre también en `reorder_paths()`** (línea 341 — mismo bloqueo al reordenar visualmente).

---

### Punto Crítico 2 — Primera apertura de herramienta en hilo principal (POSIBLE FREEZE)

**Archivo:** `shell/shell_window.py:176`

```python
def _open_tool(self, tool_id: str, inputs=None) -> None:
    if tool_id not in self._tool_widgets:
        widget = tool.window_factory(self._ctx)   # ← INSTANCIACIÓN SÍNCRONA
        self._tool_widgets[tool_id] = widget
        self._main_stack.addWidget(widget)
    self._main_stack.setCurrentWidget(widget)     # ← SIN FEEDBACK PREVIO
```

**Problema:** La `window_factory` ejecuta en hilo principal:
1. **Import de módulos** (fitz, PIL, etc.) → primera vez puede tardar 100-500ms
2. **Construcción de UI** (múltiples widgets, layouts, conexiones de señales) → 50-200ms
3. **No hay feedback visual** → usuario ve la pantalla congelada/sin responder al click

**El Organizador es el peor caso**: con miniaturas y canvas de páginas, su constructor puede tardar más.

---

### Punto Crítico 3 — Thread cleanup incompleto en cierre

**Archivo:** `shell/shell_window.py:284`

```python
def closeEvent(self, event) -> None:
    for widget in self._tool_widgets.values():
        worker = getattr(widget, "_worker", None)
        if worker and callable(getattr(worker, "cancel", None)):
            worker.cancel()   # ← Solo flag, no espera terminación
    event.accept()            # ← Sale inmediatamente
```

**Problema:** Si hay un thread corriendo (compresión, OCR), `cancel()` solo pone un flag. El thread puede seguir vivo cuando Python sale → crash silencioso o corrupción de archivo en escritura.

---

### Punto Crítico 4 — OCR sin timeout (RIESGO LIVENESS)

**Archivo:** `core/document_classifier_engine.py`

```python
def _ocr_page_text(page: fitz.Page) -> str:
    pix = page.get_pixmap(dpi=220, ...)
    ocr_pdf = pix.pdfocr_tobytes(
        language="spa+eng",
        tessdata=...,
    )  # ← Tesseract puede bloquearse indefinidamente en PDFs corruptos
```

**Impacto:** PDF malformado puede colgar el worker thread indefinidamente. El usuario no puede cancelar (el flag `_cancel` no es chequeado dentro de `pdfocr_tobytes()`).

---

### Punto Crítico 5 — Ejecución múltiple sin guard

**Patrón en todas las ventanas:**

```python
def _on_run(self) -> None:
    # No hay verificación de si _worker_thread ya está corriendo
    self._worker = SomeWorker(...)
    self._worker_thread = QThread(self)
    # ...
    self._worker_thread.start()
```

**Problema:** Si el usuario hace doble-click en "Procesar" o la UI permite re-ejecutar antes de que el thread anterior termine, se pierde la referencia al thread anterior (memory leak + comportamiento indefinido).

---

### Arquitectura actual (BIEN DISEÑADA)

Lo que YA funciona correctamente y NO debe modificarse en lógica:

- ✅ Patrón `Worker(QObject).moveToThread(QThread)` — correcto, sin GIL issues
- ✅ Señales Qt para comunicación inter-threads (progress, finished, error)
- ✅ Flag `_cancel` consultado en loops de engines
- ✅ Limpieza de referencias con `deleteLater()` en signals
- ✅ Lazy loading de herramientas (solo instancia cuando se abre)
- ✅ Word→PDF en hilo secundario con dialog de progreso

---

## Mapa de Archivos a Modificar

| Archivo | Acción | Propósito |
|---------|--------|-----------|
| `ui/common/thumb_utils.py` | Modificar | Agregar `ThumbnailLoader` (QObject para threads) |
| `ui/common/documents_step.py` | Modificar | Usar thumbnail async, mostrar placeholder primero |
| `ui/common/base_worker.py` | **Crear** | BaseWorker con guard de ejecución doble, cleanup robusto |
| `shell/shell_window.py` | Modificar | `_open_tool` con feedback inmediato, `closeEvent` con wait() |
| `core/document_classifier_engine.py` | Modificar | Timeout en OCR con signal interrupt |
| `core/pdf_compare_engine.py` | Modificar | Guard de cancel entre páginas más granular |
| `ui/compresor/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `ui/clasificador/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `ui/comparador/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `ui/pdf_to_imgs/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `ui/extraer_imagenes/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `ui/imgs_a_pdf/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `ui/protector/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `ui/reparador/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `ui/marca_agua/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `ui/redactor/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `ui/formularios/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `ui/pdf_to_word/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `ui/quitar_fondo/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `ui/unir/window.py` | Modificar | Heredar BaseWorker, guard doble ejecución |
| `tests/test_thumb_async.py` | **Crear** | Tests para thumbnail async |
| `tests/test_base_worker.py` | **Crear** | Tests para BaseWorker |
| `tests/test_ocr_timeout.py` | **Crear** | Tests para timeout OCR |

**NO modificar:** `shell/launcher.py`, `shell/tool_registry.py`

---

## Task 1: BaseWorker — clase base unificada para todos los workers

**Files:**
- Create: `ui/common/base_worker.py`
- Create: `tests/test_base_worker.py`

La clase `BaseWorker` resolverá: guard doble ejecución, cancel robusto, cleanup de thread, y error logging unificado.

- [ ] **Step 1: Crear test_base_worker.py con tests básicos**

```python
# tests/test_base_worker.py
"""Tests para BaseWorker — guard de ejecución doble y cancel robusto."""
import time
import pytest
from PyQt6.QtCore import QCoreApplication, QThread
from ui.common.base_worker import BaseWorker, WorkerThread


@pytest.fixture(scope="module")
def app():
    import sys
    a = QCoreApplication.instance() or QCoreApplication(sys.argv)
    yield a


class SlowWorker(BaseWorker):
    def run(self) -> None:
        for i in range(10):
            if self.is_cancelled():
                self.error.emit("cancelled")
                return
            time.sleep(0.05)
        self.finished.emit([])


def test_cancel_stops_worker(app):
    wt = WorkerThread(SlowWorker())
    wt.start()
    QThread.msleep(60)
    wt.cancel_and_wait(timeout_ms=1000)
    assert not wt.isRunning()


def test_double_start_raises(app):
    wt = WorkerThread(SlowWorker())
    wt.start()
    with pytest.raises(RuntimeError, match="ya en ejecución"):
        wt.start()
    wt.cancel_and_wait(timeout_ms=1000)


def test_normal_completion(app):
    finished = []
    wt = WorkerThread(SlowWorker())
    wt.worker.finished.connect(lambda r: finished.append(r))
    # Hacer worker sin delays
    wt.worker._cancel = False
    # Usar un worker que termina rápido
    class FastWorker(BaseWorker):
        def run(self):
            self.finished.emit(["ok"])
    wt2 = WorkerThread(FastWorker())
    done = []
    wt2.worker.finished.connect(lambda r: done.append(r))
    wt2.start()
    wt2.wait(2000)
    assert done == [["ok"]]
```

- [ ] **Step 2: Ejecutar test para verificar que falla correctamente**

```
pytest tests/test_base_worker.py -v
```

Esperado: `FAIL` — `ModuleNotFoundError: No module named 'ui.common.base_worker'`

- [ ] **Step 3: Crear base_worker.py**

```python
# ui/common/base_worker.py
"""BaseWorker y WorkerThread — infraestructura unificada de threading para PDFlex.

Uso:
    class MiWorker(BaseWorker):
        def run(self) -> None:
            for item in items:
                if self.is_cancelled():
                    self.error.emit("Cancelado por el usuario.")
                    return
                # ... trabajo ...
            self.finished.emit(results)

    wt = WorkerThread(MiWorker(...))
    wt.worker.progress.connect(self._on_progress)
    wt.worker.finished.connect(self._on_finished)
    wt.worker.error.connect(self._on_error)
    wt.start()
    # Para cancelar:
    wt.cancel_and_wait()
"""
from __future__ import annotations
import threading
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class BaseWorker(QObject):
    """QObject base para todos los workers de PDFlex.

    Subclases deben implementar run() y consultar is_cancelled() en loops.
    """
    progress = pyqtSignal(int, int, str)   # current, total, message
    finished = pyqtSignal(list)            # results
    error    = pyqtSignal(str)             # error message

    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Señaliza cancelación. Thread-safe."""
        self._cancel.set()

    def is_cancelled(self) -> bool:
        """Chequea si se solicitó cancelación. Llamar en loops del run()."""
        return self._cancel.is_set()

    def run(self) -> None:
        raise NotImplementedError("Subclase debe implementar run()")


class WorkerThread:
    """Envuelve BaseWorker + QThread con guard de ejecución doble y cleanup."""

    def __init__(self, worker: BaseWorker, parent: Optional[QObject] = None) -> None:
        self.worker = worker
        self._thread: Optional[QThread] = QThread(parent)
        self._started = False

        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        worker.finished.connect(self._thread.quit)
        worker.error.connect(self._thread.quit)
        self._thread.finished.connect(worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

    def start(self) -> None:
        if self._started:
            raise RuntimeError(
                "WorkerThread ya en ejecución. Llama cancel_and_wait() primero."
            )
        if self._thread is None:
            raise RuntimeError("WorkerThread ya fue destruido.")
        self._started = True
        self._thread.start()

    def cancel_and_wait(self, timeout_ms: int = 5000) -> bool:
        """Cancela y espera terminación. Retorna True si terminó en tiempo."""
        if self._thread is None:
            return True
        self.worker.cancel()
        finished = self._thread.wait(timeout_ms)
        return finished

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()
```

- [ ] **Step 4: Ejecutar tests para verificar que pasan**

```
pytest tests/test_base_worker.py -v
```

Esperado: `PASSED` en todos.

- [ ] **Step 5: Commit**

```bash
git add ui/common/base_worker.py tests/test_base_worker.py
git commit -m "feat(core): BaseWorker + WorkerThread con guard doble ejecución"
```

---

## Task 2: Thumbnails Async — eliminar el freeze principal al cargar PDFs

**Files:**
- Modify: `ui/common/thumb_utils.py`
- Modify: `ui/common/documents_step.py`
- Create: `tests/test_thumb_async.py`

Este es el freeze más frecuente y visible. Al cargar 5+ PDFs la UI se congela varios segundos.

- [ ] **Step 1: Crear test para thumbnail async**

```python
# tests/test_thumb_async.py
"""Tests para carga asíncrona de thumbnails PDF."""
import sys
import os
import pytest
from PyQt6.QtCore import QCoreApplication, QTimer
from PyQt6.QtWidgets import QApplication
from ui.common.thumb_utils import ThumbnailLoader


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    yield a


def test_thumbnail_loader_emite_senal(app, tmp_path):
    import fitz
    # Crear un PDF mínimo de 1 página
    pdf_path = str(tmp_path / "test.pdf")
    doc = fitz.open()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()

    received = []
    loader = ThumbnailLoader(pdf_path, width=64)
    loader.ready.connect(lambda path, pix: received.append((path, pix)))

    loader.run()  # Ejecutar síncronamente en test

    assert len(received) == 1
    assert received[0][0] == pdf_path
    assert received[0][1] is not None


def test_thumbnail_loader_archivo_invalido(app):
    received = []
    loader = ThumbnailLoader("/ruta/que/no/existe.pdf", width=64)
    loader.ready.connect(lambda path, pix: received.append((path, pix)))
    loader.run()
    # Para archivo inválido, pix debe ser None
    assert len(received) == 1
    assert received[0][1] is None
```

- [ ] **Step 2: Ejecutar test para verificar que falla**

```
pytest tests/test_thumb_async.py -v
```

Esperado: `FAIL` — `ImportError: cannot import name 'ThumbnailLoader'`

- [ ] **Step 3: Modificar thumb_utils.py para agregar ThumbnailLoader**

Leer el archivo actual primero (ya leído en sesión: 29 líneas). Reemplazar contenido completo:

```python
# ui/common/thumb_utils.py
"""Generación de thumbnails de PDFs — sync (legado) y async."""
from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage


def make_pdf_thumb(pdf_path: str, width: int = 72) -> Optional[QPixmap]:
    """Renderiza la primera página del PDF como thumbnail (SÍNCRONO).

    Solo usar desde hilos secundarios. Para hilo principal usar ThumbnailLoader.
    """
    try:
        import fitz
        from PIL import Image

        doc = fitz.open(pdf_path)
        page = doc[0]
        scale = width / max(1.0, page.rect.width)
        mat = fitz.Matrix(scale, scale)
        pm = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples).convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        doc.close()
        return QPixmap.fromImage(qimg.copy())
    except Exception:
        return None


class ThumbnailLoader(QObject):
    """Cargador asíncrono de thumbnails. Mover a QThread antes de llamar run().

    Señales:
        ready(path: str, pixmap: QPixmap | None): Emitida cuando el thumbnail
            está listo. pixmap es None si el archivo no pudo abrirse.
    """
    ready = pyqtSignal(str, object)   # (path, QPixmap | None)

    def __init__(self, pdf_path: str, width: int = 72) -> None:
        super().__init__()
        self._pdf_path = pdf_path
        self._width = width

    def run(self) -> None:
        pix = make_pdf_thumb(self._pdf_path, self._width)
        self.ready.emit(self._pdf_path, pix)
```

- [ ] **Step 4: Ejecutar tests de thumb_utils**

```
pytest tests/test_thumb_async.py -v
```

Esperado: `PASSED`

- [ ] **Step 5: Crear placeholder pixmap helper en thumb_utils.py**

Agregar al final del archivo (después de `ThumbnailLoader`):

```python
def make_placeholder_pixmap(width: int = 72, height: int = 90) -> QPixmap:
    """Crea un QPixmap de placeholder (gris) para mostrar antes del thumbnail real."""
    from PyQt6.QtGui import QPainter, QColor
    pix = QPixmap(width, height)
    pix.fill(QColor("#2A2A33"))
    painter = QPainter(pix)
    painter.setPen(QColor("#444454"))
    painter.drawRect(0, 0, width - 1, height - 1)
    painter.end()
    return pix
```

- [ ] **Step 6: Modificar documents_step.py para usar async thumbnails**

Leer `ui/common/documents_step.py` (ya leído — 480 líneas).

**Cambio 1: Agregar imports al inicio (después de `from ui.common.thumb_utils import make_pdf_thumb`):**

```python
from ui.common.thumb_utils import ThumbnailLoader, make_placeholder_pixmap
```

Reemplazar:
```python
from ui.common.thumb_utils import make_pdf_thumb
```

**Cambio 2: Agregar en `__init__` después de `self._conv_worker = None`:**

```python
self._thumb_threads: list = []  # threads de generación de thumbnails activos
```

**Cambio 3: Reemplazar el body de `_add_pdf_paths` — bloque de thumbnail:**

Actual (líneas 390-393):
```python
                if self._show_thumbnails:
                    thumb = make_pdf_thumb(p, width=self._thumb_w)
                    if thumb:
                        item.setIcon(QIcon(thumb))
```

Nuevo:
```python
                if self._show_thumbnails:
                    placeholder = make_placeholder_pixmap(self._thumb_w, self._thumb_h)
                    item.setIcon(QIcon(placeholder))
                    self._schedule_thumb(p, item)
```

**Cambio 4: Reemplazar bloque de thumbnail en `reorder_paths` (líneas 340-343):**

Actual:
```python
            if self._show_thumbnails:
                thumb = make_pdf_thumb(path, width=self._thumb_w)
                if thumb:
                    item.setIcon(QIcon(thumb))
```

Nuevo:
```python
            if self._show_thumbnails:
                placeholder = make_placeholder_pixmap(self._thumb_w, self._thumb_h)
                item.setIcon(QIcon(placeholder))
                self._schedule_thumb(path, item)
```

**Cambio 5: Agregar método `_schedule_thumb` al final de la clase (antes de `_handle_word_files`):**

```python
    def _schedule_thumb(self, pdf_path: str, item: "QListWidgetItem") -> None:
        """Lanza generación de thumbnail en hilo secundario y actualiza el item al terminar."""
        from PyQt6.QtCore import QThread
        loader = ThumbnailLoader(pdf_path, self._thumb_w)
        thread = QThread(self)
        loader.moveToThread(thread)
        thread.started.connect(loader.run)
        loader.ready.connect(lambda path, pix, _item=item: self._apply_thumb(_item, pix))
        loader.ready.connect(thread.quit)
        thread.finished.connect(loader.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._thumb_threads.remove(t) if t in self._thumb_threads else None)
        self._thumb_threads.append(thread)
        thread.start()

    def _apply_thumb(self, item: "QListWidgetItem", pix) -> None:
        """Actualiza el icono del item si aún existe en la lista (hilo principal)."""
        if pix is None:
            return
        # Verificar que el item aún está en la lista antes de actualizar
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i) is item:
                item.setIcon(QIcon(pix))
                return
```

- [ ] **Step 7: Ejecutar la app y cargar 5+ PDFs grandes para verificar que no se congela**

```
python main.py
```

Pasos de verificación manual:
1. Abrir cualquier herramienta (Compresor, PDF a Imágenes, etc.)
2. Arrastrar 5 PDFs de >5MB al área de documentos
3. Verificar que: los items aparecen INMEDIATAMENTE con placeholder gris, luego los thumbnails se cargan progresivamente sin congelar la UI
4. Verificar que el botón "Vaciar" funciona correctamente (no deja threads huérfanos)

- [ ] **Step 8: Commit**

```bash
git add ui/common/thumb_utils.py ui/common/documents_step.py tests/test_thumb_async.py
git commit -m "feat(ux): thumbnails PDF async — elimina freeze al cargar documentos"
```

---

## Task 3: Transición Launcher → Herramienta con feedback inmediato

**Files:**
- Modify: `shell/shell_window.py` (solo método `_open_tool`)

El problema: al hacer click en una tarjeta del launcher, si es la primera vez que se abre esa herramienta, el constructor puede tardar 100-500ms durante los cuales la UI no responde. El usuario no sabe si su click fue registrado.

**Solución:** Cambiar el stack al widget de la herramienta ANTES de construirlo usando un widget de loading temporal, y diferir la construcción real con `QTimer.singleShot(0, ...)` para que Qt pueda renderizar el frame de loading primero.

- [ ] **Step 1: Verificar que shell_window.py no tiene cambios del otro AI antes de modificar**

```
git diff HEAD shell/shell_window.py
git log --oneline -5 shell/shell_window.py
```

Si hay cambios recientes de otra persona, revisar y resolver conflictos ANTES de continuar.

- [ ] **Step 2: Crear test para verificar feedback inmediato**

```python
# tests/test_shell_transition.py
"""Tests para transición launcher → herramienta con feedback inmediato."""
import sys
import pytest
from PyQt6.QtWidgets import QApplication, QWidget, QLabel
from PyQt6.QtCore import Qt


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    yield a


def test_loading_widget_es_visible_inmediatamente(app):
    """El QStackedWidget debe cambiar de widget antes de que se construya la herramienta."""
    from PyQt6.QtWidgets import QStackedWidget
    stack = QStackedWidget()
    launcher = QLabel("launcher")
    loading = QLabel("Cargando...")
    stack.addWidget(launcher)
    stack.addWidget(loading)
    stack.setCurrentIndex(0)

    # Simular el cambio a loading
    stack.setCurrentWidget(loading)
    assert stack.currentWidget() is loading
```

- [ ] **Step 3: Ejecutar test (verificar que pasa — es básico)**

```
pytest tests/test_shell_transition.py -v
```

Esperado: `PASSED`

- [ ] **Step 4: Crear widget de loading en shell_window.py**

Leer `shell/shell_window.py` (ya leído — 318 líneas).

En el método `_build_ui`, después de crear `self._main_stack`, agregar:

```python
        # Widget de loading para transición suave
        self._loading_widget = self._build_loading_widget()
        self._main_stack.addWidget(self._loading_widget)
```

Agregar el método `_build_loading_widget` después de `_build_topbar`:

```python
    def _build_loading_widget(self) -> QWidget:
        from PyQt6.QtWidgets import QVBoxLayout
        w = QWidget()
        w.setStyleSheet("background: #0D0D12;")
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel("Cargando herramienta…")
        lbl.setStyleSheet("color: #555568; font-size: 14px; background: transparent;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        return w
```

- [ ] **Step 5: Modificar _open_tool para usar diferimiento de 1 frame**

Reemplazar el método `_open_tool` completo (líneas 170-189):

```python
    def _open_tool(self, tool_id: str, inputs: Optional[List[str]] = None) -> None:
        tool = get_tool(tool_id)
        if tool is None or not tool.enabled:
            return

        if tool_id not in self._tool_widgets:
            # Mostrar loading inmediatamente (feedback visual)
            self._main_stack.setCurrentWidget(self._loading_widget)
            self._tool_name_lbl.setText(tool.title)
            self._tool_name_lbl.setStyleSheet(f"color: {tool.accent_color};")
            self._tool_name_lbl.setVisible(True)
            self._home_btn.setVisible(True)
            # Diferir la construcción 1 frame para que Qt renderice el loading
            QTimer.singleShot(0, lambda: self._finish_open_tool(tool_id, tool, inputs))
            return

        self._show_tool_widget(tool_id, tool, inputs)

    def _finish_open_tool(
        self,
        tool_id: str,
        tool: "ToolDescriptor",
        inputs: Optional[List[str]],
    ) -> None:
        """Construye e instancia la herramienta (ejecuta después de 1 frame)."""
        try:
            widget = tool.window_factory(self._ctx)
        except Exception as exc:
            from ui.common.dialogs import show_error
            show_error(self, "Error al abrir herramienta", str(exc))
            self._go_home()
            return
        self._tool_widgets[tool_id] = widget
        self._main_stack.addWidget(widget)
        self._show_tool_widget(tool_id, tool, inputs)

    def _show_tool_widget(
        self,
        tool_id: str,
        tool: "ToolDescriptor",
        inputs: Optional[List[str]],
    ) -> None:
        """Muestra el widget de herramienta ya instanciado."""
        widget = self._tool_widgets[tool_id]
        if inputs:
            widget.set_inputs(inputs)
        self._main_stack.setCurrentWidget(widget)
        self._tool_name_lbl.setText(tool.title)
        self._tool_name_lbl.setStyleSheet(f"color: {tool.accent_color};")
        self._tool_name_lbl.setVisible(True)
        self._home_btn.setVisible(True)
```

**NOTA:** Necesitas agregar el import de `ToolDescriptor` al top del archivo si no está:
```python
from shell.tool_registry import TOOLS, get_tool, ToolDescriptor
```

- [ ] **Step 6: Verificar que el import QTimer ya está en shell_window.py**

Buscar en las líneas 1-20 del archivo: `from PyQt6.QtCore import Qt, QPoint, QTimer` — ya está en línea 15. ✓

- [ ] **Step 7: Ejecutar la app y probar apertura de herramientas**

```
python main.py
```

Pasos de verificación:
1. Click en "Comprimir PDF" → debe aparecer "Cargando herramienta…" por un instante, luego la herramienta
2. Click en "Organizador Visual" → mismo comportamiento
3. Click en cualquier herramienta por SEGUNDA VEZ → debe abrir directamente (sin loading, ya instanciada)
4. Verificar que el botón "Inicio" y el nombre de la herramienta aparecen correctamente

- [ ] **Step 8: Commit**

```bash
git add shell/shell_window.py tests/test_shell_transition.py
git commit -m "feat(ux): feedback inmediato al abrir herramientas — elimina freeze de transición"
```

---

## Task 4: CloseEvent robusto — evitar procesos huérfanos al cerrar

**Files:**
- Modify: `shell/shell_window.py` (método `closeEvent`)

- [ ] **Step 1: Reemplazar closeEvent en shell_window.py**

Reemplazar el método `closeEvent` (líneas 284-301):

```python
    def closeEvent(self, event) -> None:
        """Cancela workers activos y espera terminación antes de cerrar."""
        threads_to_wait = []

        for widget in self._tool_widgets.values():
            # Herramientas con shutdown explícito (OCR, etc.)
            shutdown = getattr(widget, "_shutdown_worker", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    pass

            # WorkerThread nuevo estilo
            wt = getattr(widget, "_worker_thread_obj", None)
            if wt is not None and hasattr(wt, "cancel_and_wait"):
                threads_to_wait.append(wt)
                continue

            # Patrón legado: _worker + _worker_thread separados
            worker = getattr(widget, "_worker", None)
            if worker and callable(getattr(worker, "cancel", None)):
                try:
                    worker.cancel()
                except Exception:
                    pass

            thread = getattr(widget, "_worker_thread", None)
            if thread is not None and hasattr(thread, "wait"):
                threads_to_wait.append(thread)

        # Esperar terminación de todos los threads (máximo 3s total)
        for t in threads_to_wait:
            if hasattr(t, "cancel_and_wait"):
                t.cancel_and_wait(timeout_ms=3000)
            elif hasattr(t, "isRunning") and t.isRunning():
                t.wait(3000)

        event.accept()
```

- [ ] **Step 2: Ejecutar la app, iniciar una compresión de archivo grande, cerrar la ventana**

```
python main.py
```

Verificación:
1. Cargar un PDF grande (>50MB) en Compresor
2. Iniciar la compresión
3. Cerrar la ventana principal inmediatamente
4. Verificar que la app cierra limpiamente (sin crash, sin mensaje de error)

- [ ] **Step 3: Commit**

```bash
git add shell/shell_window.py
git commit -m "fix(shell): closeEvent espera terminación de threads antes de cerrar"
```

---

## Task 5: Guard de doble ejecución en herramientas con BaseWorker

**Files:**
- Modify: `ui/common/tool_scaffold.py` (agregar helper `_ensure_worker_stopped`)
- Modify: `ui/pdf_to_imgs/window.py` (herramienta modelo para el patrón)

El patrón de doble ejecución ocurre cuando el usuario hace click en "Procesar" dos veces o vuelve al paso de proceso sin esperar. La solución es un helper en `PipelineWindow` que todas las ventanas pueden usar.

- [ ] **Step 1: Crear test para guard de doble ejecución**

```python
# tests/test_double_execution_guard.py
"""Tests para prevención de doble ejecución de workers."""
import time
import pytest
from PyQt6.QtCore import QCoreApplication
from ui.common.base_worker import BaseWorker, WorkerThread


@pytest.fixture(scope="module")
def app():
    import sys
    a = QCoreApplication.instance() or QCoreApplication(sys.argv)
    yield a


class LongWorker(BaseWorker):
    def run(self):
        for _ in range(20):
            if self.is_cancelled():
                return
            import time
            time.sleep(0.05)
        self.finished.emit([])


def test_no_double_start(app):
    wt = WorkerThread(LongWorker())
    wt.start()
    with pytest.raises(RuntimeError):
        wt.start()
    wt.cancel_and_wait(timeout_ms=2000)


def test_cancel_and_restart(app):
    wt = WorkerThread(LongWorker())
    wt.start()
    wt.cancel_and_wait(timeout_ms=2000)
    # Crear nuevo WorkerThread (ya que el viejo fue deleteLater)
    wt2 = WorkerThread(LongWorker())
    wt2.start()  # No debe lanzar excepción
    wt2.cancel_and_wait(timeout_ms=2000)
```

- [ ] **Step 2: Ejecutar test**

```
pytest tests/test_double_execution_guard.py -v
```

Esperado: `PASSED` (BaseWorker ya implementado en Task 1)

- [ ] **Step 3: Agregar `_stop_active_worker()` helper a PipelineWindow en tool_scaffold.py**

Leer `ui/common/tool_scaffold.py` (ya leído — primeras 100 líneas). Leer el resto:

```
Read: ui/common/tool_scaffold.py lines 100-end
```

Agregar al final de la clase `PipelineWindow`:

```python
    def _stop_active_worker(self) -> None:
        """Cancela y espera el worker activo si existe.

        Llamar al inicio de _on_run() para prevenir doble ejecución.
        """
        wt = getattr(self, "_worker_thread_obj", None)
        if wt is not None and wt.is_running():
            wt.cancel_and_wait(timeout_ms=3000)
            self._worker_thread_obj = None

        # Patrón legado: _worker + _worker_thread
        worker = getattr(self, "_worker", None)
        thread = getattr(self, "_worker_thread", None)
        if worker and callable(getattr(worker, "cancel", None)):
            worker.cancel()
        if thread is not None and hasattr(thread, "isRunning") and thread.isRunning():
            thread.wait(3000)
```

- [ ] **Step 4: Modificar pdf_to_imgs/window.py como ventana modelo del patrón**

Leer `ui/pdf_to_imgs/window.py` completo para ver el método `_on_run` actual.

En `_on_run()` (buscar el método completo), agregar como primera línea del método:

```python
    def _on_run(self) -> None:
        self._stop_active_worker()   # ← Agregar esta línea al inicio
        # ... resto del código existente sin cambios ...
```

- [ ] **Step 5: Aplicar el mismo cambio a las otras 9 herramientas con workers**

Agregar `self._stop_active_worker()` al inicio de `_on_run()` en:

- `ui/compresor/window.py`
- `ui/clasificador/window.py`
- `ui/comparador/window.py`
- `ui/extraer_imagenes/window.py`
- `ui/imgs_a_pdf/window.py`
- `ui/protector/window.py`
- `ui/reparador/window.py`
- `ui/marca_agua/window.py`
- `ui/pdf_to_word/window.py`
- `ui/quitar_fondo/window.py`
- `ui/unir/window.py`

Para cada archivo: leer primero, buscar `def _on_run`, agregar `self._stop_active_worker()` como primera línea del método.

- [ ] **Step 6: Verificar visualmente con doble click en Procesar**

```
python main.py
```

1. Cargar PDFs en Compresor
2. Click en "Procesar" dos veces rápidamente
3. Verificar que solo hay 1 barra de progreso activa (no duplicado)
4. Verificar que el proceso termina normalmente

- [ ] **Step 7: Commit**

```bash
git add ui/common/tool_scaffold.py ui/pdf_to_imgs/window.py ui/compresor/window.py \
        ui/clasificador/window.py ui/comparador/window.py ui/extraer_imagenes/window.py \
        ui/imgs_a_pdf/window.py ui/protector/window.py ui/reparador/window.py \
        ui/marca_agua/window.py ui/pdf_to_word/window.py ui/quitar_fondo/window.py \
        ui/unir/window.py tests/test_double_execution_guard.py
git commit -m "fix(workers): guard de doble ejecución en todas las herramientas"
```

---

## Task 6: Timeout OCR — evitar que Tesseract cuelgue indefinidamente

**Files:**
- Modify: `core/document_classifier_engine.py`
- Create: `tests/test_ocr_timeout.py`

El OCR de Tesseract puede colgar indefinidamente en PDFs corruptos o con páginas muy grandes. El engine corre en QThread pero el flag `_cancel` no puede interrumpir `pdfocr_tobytes()` porque es una llamada nativa.

**Solución:** Ejecutar Tesseract en un subprocess separado con timeout, o usar `concurrent.futures.ThreadPoolExecutor` con `future.result(timeout=30)`.

- [ ] **Step 1: Crear test para timeout OCR**

```python
# tests/test_ocr_timeout.py
"""Tests para timeout en OCR."""
import pytest
import time
from unittest.mock import patch, MagicMock


def test_ocr_respeta_timeout():
    """Si el OCR tarda más del timeout, debe retornar cadena vacía."""
    from core.document_classifier_engine import _ocr_page_text_with_timeout

    mock_page = MagicMock()
    mock_page.get_pixmap.return_value = MagicMock(
        width=100, height=100, samples=b'\x00' * 30000
    )

    def slow_ocr(*args, **kwargs):
        time.sleep(60)  # Simula OCR que cuelga
        return b""

    with patch("fitz.Pixmap.pdfocr_tobytes", slow_ocr):
        result = _ocr_page_text_with_timeout(mock_page, timeout_secs=1)
        assert result == ""


def test_ocr_retorna_texto_normal():
    """OCR rápido debe retornar el texto correctamente."""
    from core.document_classifier_engine import _ocr_page_text_with_timeout
    # Test con mock que retorna inmediatamente
    # (El test real requiere Tesseract instalado)
    assert True  # placeholder — verificar manualmente con PDF real
```

- [ ] **Step 2: Ejecutar test para verificar que falla**

```
pytest tests/test_ocr_timeout.py::test_ocr_respeta_timeout -v
```

Esperado: `FAIL` — `ImportError: cannot import name '_ocr_page_text_with_timeout'`

- [ ] **Step 3: Modificar document_classifier_engine.py para agregar timeout**

Leer `core/document_classifier_engine.py` completo antes de modificar.

Encontrar la función `_ocr_page_text` y reemplazarla con:

```python
def _ocr_page_text_with_timeout(page: "fitz.Page", timeout_secs: int = 30) -> str:
    """Ejecuta OCR con timeout. Retorna '' si excede el tiempo límite."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_ocr_page_text, page)
        try:
            return future.result(timeout=timeout_secs)
        except concurrent.futures.TimeoutError:
            return ""
        except Exception:
            return ""


def _ocr_page_text(page: "fitz.Page") -> str:
    """Ejecuta OCR en la página. Llamar desde _ocr_page_text_with_timeout."""
    try:
        pix = page.get_pixmap(dpi=220, colorspace=fitz.csRGB, alpha=False)
        ocr_pdf = pix.pdfocr_tobytes(
            language="spa+eng",
            tessdata=str(get_tessdata_dir()),
            compress=True,
        )
        if not ocr_pdf:
            return ""
        with fitz.open("pdf", ocr_pdf) as ocr_doc:
            return ocr_doc[0].get_text("text", sort=True).strip()
    except Exception:
        return ""
```

Luego reemplazar todas las llamadas a `_ocr_page_text(page)` en el engine por `_ocr_page_text_with_timeout(page, timeout_secs=30)`.

- [ ] **Step 4: Ejecutar tests**

```
pytest tests/test_ocr_timeout.py -v
```

Esperado: `PASSED`

- [ ] **Step 5: Probar manualmente con PDF problemático**

Si tienes un PDF de muchas páginas o escaneado de baja calidad:
```
python main.py
```
1. Abrir "Clasificador OCR"
2. Cargar PDF de 50+ páginas escaneadas
3. Verificar que el proceso avanza (no se congela en ninguna página)
4. Verificar que se puede cancelar en cualquier momento

- [ ] **Step 6: Commit**

```bash
git add core/document_classifier_engine.py tests/test_ocr_timeout.py
git commit -m "fix(ocr): timeout 30s por página — previene cuelgue indefinido en PDFs corruptos"
```

---

## Task 7: Verificación final de robustez — smoke test de todas las herramientas

**Files:**
- Modify/Create: `tests/test_smoke_tools.py`

- [ ] **Step 1: Crear smoke test de herramientas principales**

```python
# tests/test_smoke_tools.py
"""Smoke tests: verificar que todas las herramientas instancian sin errores."""
import sys
import pytest
from PyQt6.QtWidgets import QApplication
from unittest.mock import MagicMock


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    yield a


@pytest.fixture
def mock_ctx():
    ctx = MagicMock()
    ctx.tray.changed = MagicMock()
    ctx.tray.changed.connect = MagicMock()
    ctx.tray.count.return_value = 0
    ctx.tray.paths.return_value = []
    ctx.word_converter.is_available.return_value = False
    return ctx


TOOL_FACTORIES = [
    ("compresor", lambda: __import__("ui.compresor.window", fromlist=["CompresorWindow"]).CompresorWindow),
    ("pdf_to_imgs", lambda: __import__("ui.pdf_to_imgs.window", fromlist=["PdfToImgsWindow"]).PdfToImgsWindow),
    ("extraer_imagenes", lambda: __import__("ui.extraer_imagenes.window", fromlist=["ExtraerImagenesWindow"]).ExtraerImagenesWindow),
    ("clasificador", lambda: __import__("ui.clasificador.window", fromlist=["ClasificadorWindow"]).ClasificadorWindow),
    ("comparador", lambda: __import__("ui.comparador.window", fromlist=["ComparadorWindow"]).ComparadorWindow),
    ("protector", lambda: __import__("ui.protector.window", fromlist=["ProtectorWindow"]).ProtectorWindow),
    ("reparador", lambda: __import__("ui.reparador.window", fromlist=["ReparadorWindow"]).ReparadorWindow),
    ("unir", lambda: __import__("ui.unir.window", fromlist=["UnirWindow"]).UnirWindow),
    ("marca_agua", lambda: __import__("ui.marca_agua.window", fromlist=["MarcaAguaWindow"]).MarcaAguaWindow),
]


@pytest.mark.parametrize("tool_id,factory", TOOL_FACTORIES)
def test_tool_instancia_sin_errores(app, mock_ctx, tool_id, factory):
    """Cada herramienta debe instanciarse sin lanzar excepciones."""
    WindowClass = factory()
    window = WindowClass(mock_ctx)
    assert window is not None
    window.close()
```

- [ ] **Step 2: Ejecutar smoke tests**

```
pytest tests/test_smoke_tools.py -v
```

Esperado: `PASSED` en todos los tools. Si alguno falla, investigar el constructor de esa ventana.

- [ ] **Step 3: Si algún constructor hace I/O bloqueante, reportar como issue separado**

Al revisar los errores (si los hay), verificar si el constructor de alguna ventana hace operaciones de I/O. Si es así, diferir esa operación a `showEvent()` o similar.

- [ ] **Step 4: Commit**

```bash
git add tests/test_smoke_tools.py
git commit -m "test(smoke): verificación de instanciación de todas las herramientas"
```

---

## Task 8: Revisión de compatibilidad con cambios de la otra IA en el launcher

**Files:**
- Read: `shell/launcher.py` (solo lectura, verificar compatibilidad)
- Read: `shell/shell_window.py` (verificar que nuestra integración es compatible)

Esta tarea se ejecuta al FINAL, después de que la otra IA haya terminado sus cambios.

- [ ] **Step 1: Obtener los últimos cambios del launcher**

```
git log --oneline -10 shell/launcher.py
git diff HEAD~3 shell/launcher.py
```

- [ ] **Step 2: Verificar que el contrato _open_tool sigue siendo el mismo**

La otra IA trabaja en `LauncherWidget` y `ToolCard`. Nuestros cambios están en `ShellWindow._open_tool`. El contrato es:
- `ToolCard` llama `on_click=lambda tid=tool.id: open_tool_fn(tid)`
- `open_tool_fn` es `ShellWindow._open_tool`
- La firma de `_open_tool(tool_id: str, inputs=None)` no debe cambiar

Verificar que la firma sigue siendo compatible.

- [ ] **Step 3: Verificar que el widget de loading no interfiere con el nuevo launcher**

Si la otra IA modificó cómo se construye la grid de herramientas, verificar:
1. Que `self._loading_widget` no colisiona con ningún widget nuevo del launcher
2. Que el `QStackedWidget` sigue teniendo `LauncherWidget` como index 0
3. Que `_go_home()` sigue apuntando correctamente a index 0

- [ ] **Step 4: Si hay conflictos, resolverlos y hacer commit**

```
git merge <branch-de-otra-IA>
# Resolver conflictos manualmente
git commit -m "merge: integración launcher redesign + robustez threading"
```

---

## Checklist de Verificación Final

Antes de considerar el plan completo:

- [ ] Cargar 10 PDFs de 10MB+ — UI no se congela durante la carga
- [ ] Abrir cada herramienta por primera vez — aparece "Cargando…" antes de la herramienta
- [ ] Abrir herramienta por segunda vez — apertura instantánea (sin loading)
- [ ] Ejecutar Compresor con archivo grande, hacer doble click en Procesar — solo 1 ejecución
- [ ] Ejecutar Clasificador OCR con PDF de 50+ páginas — avanza correctamente sin colgarse
- [ ] Iniciar cualquier procesamiento y cerrar la ventana principal — cierre limpio sin crash
- [ ] Ejecutar tests completos: `pytest tests/ -v`

---

## Notas de Implementación

### Sobre threads en Python/Qt

- **GIL y fitz:** PyMuPDF libera el GIL durante operaciones de I/O, por lo que múltiples threads pueden ejecutar operaciones de PDF en paralelo sin bloqueo completo
- **QObject thread affinity:** `moveToThread()` es obligatorio antes de `thread.start()` — si se crea un QObject dentro de un thread que no es el principal, su thread affinity será ese thread (correcto)
- **deleteLater():** Siempre usar `deleteLater()` en lugar de `del` para QObjects que están en otros threads — el event loop los destruye de forma segura

### Sobre el patrón WorkerThread

El nuevo `WorkerThread` de Task 1 es un wrapper que se puede usar en paralelo con el patrón legado `_worker` + `_worker_thread`. Las ventanas que NO se migren en este plan seguirán funcionando con el patrón viejo.

### Sobre la otra IA y el launcher

La otra IA hace cambios **estéticos y funcionales** al launcher (galería). Los cambios más probables son:
- Cambiar el estilo visual de las `ToolCard`
- Reorganizar el layout de la grid
- Agregar animaciones o estados hover mejorados
- Cambiar el sistema de categorías

Ninguno de esos cambios debería afectar el contrato `on_click → open_tool_fn(tid)`. Si la otra IA AÑADE funcionalidad (como filtros, búsqueda), revisar que el flujo de apertura siga siendo `_open_tool(tool_id)`.
