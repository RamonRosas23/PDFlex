# Organizador Visual de PDF — Rediseño Completo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar la cuadrícula plana mezclada por un sistema de DocLanes (una fila por documento) con drag & drop entre filas, exportación flexible (individual o fusionada), caché de miniaturas en background, y teclado/menú contextual completo.

**Architecture:** `LaneContainer` (QScrollArea) contiene N `DocLane` (header colapsable + `_PageStrip` QListWidget horizontal). El drag cross-lane usa MIME personalizado `application/x-pdflex-pageref`. El motor recibe `MultiOrganizerJob` con N sub-jobs. `ThumbnailWorker` (QThread) llena `ThumbnailCache` (LRU) en background.

**Tech Stack:** PyQt6, PyMuPDF (fitz), Pillow, Python dataclasses, json, threading via QThread

---

## File Map

| Archivo | Estado | Responsabilidad |
|---|---|---|
| `core/page_organizer_engine.py` | Modify | Agregar `MultiOrganizerJob`, `MultiOrganizerResult`, `run_multi_job()` |
| `ui/organizador/thumb_cache.py` | Create | `ThumbnailCache` LRU + `ThumbnailWorker` QThread |
| `ui/organizador/page_mime.py` | Create | Encode/decode MIME `application/x-pdflex-pageref` |
| `ui/organizador/lane_widget.py` | Create | `_PageStrip` + `DocLane` (header + strip) |
| `ui/organizador/lane_container.py` | Create | `LaneContainer` gestiona N DocLanes |
| `ui/organizador/window.py` | Rewrite | `OrganizadorWindow` usa LaneContainer; paso 02 con tabla multi-output |
| `tests/test_page_organizer_engine.py` | Modify | Agregar tests multi-job |
| `tests/test_organizador_window.py` | Modify | Actualizar + tests cross-lane y multi-output |

---

## Task 1: Motor multi-output

**Files:**
- Modify: `core/page_organizer_engine.py`
- Modify: `tests/test_page_organizer_engine.py`

- [ ] **Step 1: Escribir tests que fallan**

Agregar al final de `tests/test_page_organizer_engine.py`:

```python
from core.page_organizer_engine import MultiOrganizerJob, MultiOrganizerResult


class MultiOrganizerEngineTests(unittest.TestCase):
    def test_run_multi_job_separate_produces_n_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_a = self._make_pdf(root / "a.pdf", ["A1", "A2"])
            pdf_b = self._make_pdf(root / "b.pdf", ["B1"])
            out_a = root / "out" / "lane_a.pdf"
            out_b = root / "out" / "lane_b.pdf"

            job = MultiOrganizerJob(
                lanes=[
                    OrganizerJob(pages=[PageRef(str(pdf_a), 0), PageRef(str(pdf_a), 1)], output_path=str(out_a)),
                    OrganizerJob(pages=[PageRef(str(pdf_b), 0)], output_path=str(out_b)),
                ],
                merge_all=False,
            )
            result = PageOrganizerEngine().run_multi_job(job)

            self.assertTrue(result.success, result.error)
            self.assertEqual(len(result.results), 2)
            self.assertTrue(out_a.exists())
            self.assertTrue(out_b.exists())
            doc_a = fitz.open(out_a)
            self.assertEqual(doc_a.page_count, 2)
            doc_a.close()
            doc_b = fitz.open(out_b)
            self.assertEqual(doc_b.page_count, 1)
            doc_b.close()

    def test_run_multi_job_merged_produces_single_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_a = self._make_pdf(root / "a.pdf", ["A1"])
            pdf_b = self._make_pdf(root / "b.pdf", ["B1", "B2"])
            out = root / "out" / "merged.pdf"

            job = MultiOrganizerJob(
                lanes=[
                    OrganizerJob(pages=[PageRef(str(pdf_a), 0)], output_path=str(out)),
                    OrganizerJob(pages=[PageRef(str(pdf_b), 0), PageRef(str(pdf_b), 1)], output_path=str(out)),
                ],
                merge_all=True,
            )
            result = PageOrganizerEngine().run_multi_job(job)

            self.assertTrue(result.success, result.error)
            self.assertTrue(out.exists())
            doc = fitz.open(out)
            self.assertEqual(doc.page_count, 3)
            doc.close()

    @staticmethod
    def _make_pdf(path: Path, labels: list[str]) -> Path:
        doc = fitz.open()
        for label in labels:
            page = doc.new_page(width=300, height=200)
            page.insert_text((36, 72), label)
        doc.save(path)
        doc.close()
        return path
```

- [ ] **Step 2: Ejecutar para verificar que fallan**

```
python -m pytest tests/test_page_organizer_engine.py::MultiOrganizerEngineTests -v
```
Esperado: FAIL con `ImportError: cannot import name 'MultiOrganizerJob'`

- [ ] **Step 3: Implementar en `core/page_organizer_engine.py`**

Agregar después de `class OrganizerResult`:

```python
@dataclass
class MultiOrganizerJob:
    """N lanes → N PDFs independientes o 1 PDF fusionado."""
    lanes: List[OrganizerJob]
    merge_all: bool = False


@dataclass
class MultiOrganizerResult:
    results: List[OrganizerResult]
    merged_output_path: str = ""
    success: bool = True
    error: str = ""
```

Agregar método `run_multi_job` en `PageOrganizerEngine`:

```python
def run_multi_job(
    self,
    job: MultiOrganizerJob,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> MultiOrganizerResult:
    if not job.lanes:
        return MultiOrganizerResult(results=[], success=False, error="No hay lanes.")

    if job.merge_all:
        all_pages: List[PageRef] = []
        for lane_job in job.lanes:
            all_pages.extend(lane_job.pages)
        # Use the output_path of the first lane as the merged output
        merged_out = job.lanes[0].output_path
        merged_job = OrganizerJob(pages=all_pages, output_path=merged_out)
        result = self.run_job(merged_job, progress=progress, should_cancel=should_cancel)
        return MultiOrganizerResult(
            results=[result],
            merged_output_path=result.output_path,
            success=result.success,
            error=result.error,
        )

    results: List[OrganizerResult] = []
    total_lanes = len(job.lanes)
    for idx, lane_job in enumerate(job.lanes):
        if should_cancel and should_cancel():
            return MultiOrganizerResult(results=results, success=False, error="Operación cancelada.")

        def _prog(c, t, m, _i=idx, _n=total_lanes):
            if progress:
                overall = int((_i + c / max(1, t)) / _n * 100)
                progress(overall, 100, m)

        result = self.run_job(lane_job, progress=_prog, should_cancel=should_cancel)
        results.append(result)

    all_ok = all(r.success for r in results)
    return MultiOrganizerResult(
        results=results,
        success=all_ok,
        error="" if all_ok else "; ".join(r.error for r in results if r.error),
    )
```

- [ ] **Step 4: Verificar que los tests pasan**

```
python -m pytest tests/test_page_organizer_engine.py -v
```
Esperado: 4 passed

- [ ] **Step 5: Commit**

```bash
git add core/page_organizer_engine.py tests/test_page_organizer_engine.py
git commit -m "feat(engine): MultiOrganizerJob + run_multi_job — separate & merged output"
```

---

## Task 2: ThumbnailCache + ThumbnailWorker

**Files:**
- Create: `ui/organizador/thumb_cache.py`
- Modify: `tests/test_organizador_window.py` (agregar un test de caché)

- [ ] **Step 1: Escribir test que falla**

Agregar a `tests/test_organizador_window.py`:

```python
from ui.organizador.thumb_cache import ThumbnailCache, ThumbnailKey, render_page_thumb


class ThumbnailCacheTests(unittest.TestCase):
    def test_cache_hit_returns_same_pixmap(self) -> None:
        cache = ThumbnailCache(max_size=10)
        key = ThumbnailKey(source_path="/fake.pdf", page_index=0, rotation_deg=0, width=116)
        # Initially empty
        self.assertIsNone(cache.get(key))
        # Create a dummy pixmap
        from PyQt6.QtGui import QPixmap
        pix = QPixmap(116, 150)
        cache.put(key, pix)
        result = cache.get(key)
        self.assertIsNotNone(result)
        self.assertEqual(result.width(), 116)

    def test_render_page_thumb_returns_pixmap_for_valid_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "test.pdf"
            doc = fitz.open()
            page = doc.new_page(width=300, height=200)
            page.insert_text((36, 72), "Hello")
            doc.save(pdf)
            doc.close()

            result = render_page_thumb(str(pdf), 0, 0, 116)
            self.assertIsNotNone(result)
            self.assertGreater(result.width(), 0)
```

- [ ] **Step 2: Verificar que falla**

```
python -m pytest tests/test_organizador_window.py::ThumbnailCacheTests -v
```
Esperado: FAIL con `ImportError`

- [ ] **Step 3: Crear `ui/organizador/thumb_cache.py`**

```python
"""Thumbnail cache and background renderer for DocLane page strips."""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

import fitz
from PIL import Image
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap


@dataclass(frozen=True)
class ThumbnailKey:
    source_path: str
    page_index: int
    rotation_deg: int
    width: int


class ThumbnailCache:
    """Thread-safe LRU cache for page thumbnails."""

    def __init__(self, max_size: int = 200) -> None:
        self._cache: OrderedDict[ThumbnailKey, QPixmap] = OrderedDict()
        self._max_size = max_size
        self._lock = threading.Lock()

    def get(self, key: ThumbnailKey) -> Optional[QPixmap]:
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def put(self, key: ThumbnailKey, pixmap: QPixmap) -> None:
        with self._lock:
            self._cache[key] = pixmap
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate_path(self, path: str) -> None:
        with self._lock:
            stale = [k for k in self._cache if k.source_path == path]
            for k in stale:
                del self._cache[k]


def render_page_thumb(
    source_path: str,
    page_index: int,
    rotation_deg: int = 0,
    target_w: int = 116,
) -> Optional[QPixmap]:
    """Render one PDF page to a QPixmap. Returns None on any error."""
    try:
        doc = fitz.open(source_path)
        try:
            page = doc[page_index]
            width = max(1.0, page.rect.width)
            scale = target_w / width
            mat = fitz.Matrix(scale, scale)
            if rotation_deg:
                mat = mat.prerotate(rotation_deg)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
            return QPixmap.fromImage(qimg.copy())
        finally:
            doc.close()
    except Exception:
        return None


class _ThumbRequest:
    __slots__ = ("lane_id", "page_id", "source_path", "page_index", "rotation_deg", "width")

    def __init__(
        self,
        lane_id: str,
        page_id: str,
        source_path: str,
        page_index: int,
        rotation_deg: int,
        width: int,
    ) -> None:
        self.lane_id = lane_id
        self.page_id = page_id
        self.source_path = source_path
        self.page_index = page_index
        self.rotation_deg = rotation_deg
        self.width = width


class ThumbnailWorker(QObject):
    """Background worker that renders thumbnails and emits them via signal."""

    thumb_ready = pyqtSignal(str, str, object)  # lane_id, page_id, QPixmap

    def __init__(self, cache: ThumbnailCache, parent=None) -> None:
        super().__init__(parent)
        self._cache = cache
        self._queue: list[_ThumbRequest] = []
        self._lock = threading.Lock()
        self._running = True

    def request(
        self,
        lane_id: str,
        page_id: str,
        source_path: str,
        page_index: int,
        rotation_deg: int = 0,
        width: int = 116,
    ) -> None:
        """Enqueue a thumbnail request; emits immediately if already cached."""
        key = ThumbnailKey(source_path, page_index, rotation_deg, width)
        cached = self._cache.get(key)
        if cached is not None:
            self.thumb_ready.emit(lane_id, page_id, cached)
            return
        with self._lock:
            self._queue.append(
                _ThumbRequest(lane_id, page_id, source_path, page_index, rotation_deg, width)
            )

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        """Main loop — runs in a QThread. Processes one request every 20 ms."""
        while self._running:
            req: Optional[_ThumbRequest] = None
            with self._lock:
                if self._queue:
                    req = self._queue.pop(0)
            if req is None:
                QThread.msleep(20)
                continue
            key = ThumbnailKey(req.source_path, req.page_index, req.rotation_deg, req.width)
            pixmap = render_page_thumb(req.source_path, req.page_index, req.rotation_deg, req.width)
            if pixmap is not None:
                self._cache.put(key, pixmap)
                self.thumb_ready.emit(req.lane_id, req.page_id, pixmap)
```

- [ ] **Step 4: Verificar que los tests pasan**

```
python -m pytest tests/test_organizador_window.py::ThumbnailCacheTests -v
```
Esperado: 2 passed

- [ ] **Step 5: Commit**

```bash
git add ui/organizador/thumb_cache.py tests/test_organizador_window.py
git commit -m "feat(organizador): ThumbnailCache LRU + ThumbnailWorker background renderer"
```

---

## Task 3: MIME serialization

**Files:**
- Create: `ui/organizador/page_mime.py`
- Modify: `tests/test_organizador_window.py`

- [ ] **Step 1: Escribir test que falla**

Agregar a `tests/test_organizador_window.py`:

```python
from ui.organizador.page_mime import encode_drag, decode_drag
from core.page_organizer_engine import PageRef


class PageMimeTests(unittest.TestCase):
    def test_encode_decode_round_trip(self) -> None:
        refs = [
            PageRef(source_path="/doc/a.pdf", page_index=0, rotation_deg=0, page_id="p1"),
            PageRef(source_path="/doc/a.pdf", page_index=2, rotation_deg=90, page_id="p2"),
        ]
        mime = encode_drag("lane-abc", refs)
        result = decode_drag(mime)
        self.assertIsNotNone(result)
        lane_id, decoded_refs = result
        self.assertEqual(lane_id, "lane-abc")
        self.assertEqual(len(decoded_refs), 2)
        self.assertEqual(decoded_refs[0].page_id, "p1")
        self.assertEqual(decoded_refs[1].rotation_deg, 90)

    def test_decode_returns_none_for_foreign_mime(self) -> None:
        from PyQt6.QtCore import QMimeData
        mime = QMimeData()
        mime.setText("hello")
        self.assertIsNone(decode_drag(mime))
```

- [ ] **Step 2: Verificar que falla**

```
python -m pytest tests/test_organizador_window.py::PageMimeTests -v
```
Esperado: FAIL con `ImportError`

- [ ] **Step 3: Crear `ui/organizador/page_mime.py`**

```python
"""MIME serialization for cross-lane page drag & drop."""
from __future__ import annotations

import json
from typing import List, Optional, Tuple

from PyQt6.QtCore import QMimeData

from core.page_organizer_engine import PageRef

MIME_TYPE = "application/x-pdflex-pageref"


def encode_drag(lane_id: str, refs: List[PageRef]) -> QMimeData:
    payload = {
        "source_lane_id": lane_id,
        "refs": [
            {
                "source_path": r.source_path,
                "page_index": r.page_index,
                "rotation_deg": r.rotation_deg,
                "page_id": r.page_id,
            }
            for r in refs
        ],
    }
    mime = QMimeData()
    mime.setData(MIME_TYPE, json.dumps(payload).encode("utf-8"))
    return mime


def decode_drag(mime: QMimeData) -> Optional[Tuple[str, List[PageRef]]]:
    """Returns (source_lane_id, refs) or None if not our MIME."""
    if not mime.hasFormat(MIME_TYPE):
        return None
    try:
        payload = json.loads(bytes(mime.data(MIME_TYPE)).decode("utf-8"))
        lane_id = str(payload["source_lane_id"])
        refs = [
            PageRef(
                source_path=str(r["source_path"]),
                page_index=int(r["page_index"]),
                rotation_deg=int(r.get("rotation_deg", 0)),
                page_id=str(r.get("page_id", "")),
            )
            for r in payload["refs"]
        ]
        return lane_id, refs
    except (KeyError, ValueError, json.JSONDecodeError):
        return None
```

- [ ] **Step 4: Verificar que los tests pasan**

```
python -m pytest tests/test_organizador_window.py::PageMimeTests -v
```
Esperado: 2 passed

- [ ] **Step 5: Commit**

```bash
git add ui/organizador/page_mime.py tests/test_organizador_window.py
git commit -m "feat(organizador): page_mime — encode/decode MIME for cross-lane drag"
```

---

## Task 4: DocLane widget

**Files:**
- Create: `ui/organizador/lane_widget.py`
- Modify: `tests/test_organizador_window.py`

- [ ] **Step 1: Escribir tests que fallan**

Agregar a `tests/test_organizador_window.py`:

```python
from ui.organizador.lane_widget import DocLane, LANE_COLORS
from ui.organizador.thumb_cache import ThumbnailCache, ThumbnailWorker


class DocLaneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.cache = ThumbnailCache(max_size=10)
        cls.worker = ThumbnailWorker(cls.cache)

    def _make_lane(self, name: str = "Test") -> DocLane:
        return DocLane("lane-1", name, LANE_COLORS[0], self.cache, self.worker)

    def test_add_pdf_creates_items_with_correct_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "test.pdf"
            doc = fitz.open()
            for i in range(3):
                p = doc.new_page()
                p.insert_text((36, 72), f"Pag {i+1}")
            doc.save(pdf)
            doc.close()

            lane = self._make_lane()
            lane.add_pages_from_pdf(str(pdf))

            self.assertEqual(lane.count(), 3)
            refs = lane.page_refs()
            self.assertEqual(refs[0].page_index, 0)
            self.assertEqual(refs[2].page_index, 2)
            self.assertEqual(refs[0].source_path, str(pdf))

    def test_rotate_selected_updates_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "rot.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(pdf)
            doc.close()

            lane = self._make_lane()
            lane.add_pages_from_pdf(str(pdf))
            lane._list.setCurrentRow(0)
            lane.rotate_selected(90)

            self.assertEqual(lane.page_refs()[0].rotation_deg, 90)

    def test_duplicate_selected_inserts_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "dup.pdf"
            doc = fitz.open()
            for i in range(2):
                doc.new_page()
            doc.save(pdf)
            doc.close()

            lane = self._make_lane()
            lane.add_pages_from_pdf(str(pdf))
            lane._list.setCurrentRow(0)
            lane.duplicate_selected()

            self.assertEqual(lane.count(), 3)
            # The duplicate keeps its source_path and page_index
            self.assertEqual(lane.page_refs()[1].page_index, 0)
            # But has a different page_id
            self.assertNotEqual(lane.page_refs()[0].page_id, lane.page_refs()[1].page_id)

    def test_clear_empties_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "clear.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(pdf)
            doc.close()

            lane = self._make_lane()
            lane.add_pages_from_pdf(str(pdf))
            self.assertEqual(lane.count(), 1)
            lane.clear()
            self.assertEqual(lane.count(), 0)
```

- [ ] **Step 2: Verificar que fallan**

```
python -m pytest tests/test_organizador_window.py::DocLaneTests -v
```
Esperado: FAIL con `ImportError`

- [ ] **Step 3: Crear `ui/organizador/lane_widget.py`**

```python
"""DocLane — one horizontal page strip per PDF document."""
from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import fitz
from PyQt6.QtCore import Qt, QEvent, QSize, pyqtSignal
from PyQt6.QtGui import (
    QColor, QDrag, QDragEnterEvent, QDropEvent, QIcon,
    QKeyEvent, QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QPushButton, QVBoxLayout,
    QWidget,
)

from core.page_organizer_engine import PageRef
from ui.common.file_dialogs import get_open_file_names
from ui.common.icons import set_button_icon
from ui.organizador.page_mime import MIME_TYPE, decode_drag, encode_drag
from ui.organizador.thumb_cache import ThumbnailCache, ThumbnailKey, ThumbnailWorker

THUMB_W = 116
THUMB_H = 150
STRIP_HEIGHT = 206
PDF_FILTER = "PDF (*.pdf)"

LANE_COLORS: List[QColor] = [
    QColor(94, 106, 210),   # índigo
    QColor(56, 178, 172),   # teal
    QColor(236, 135, 72),   # naranja
    QColor(168, 85, 247),   # violeta
    QColor(239, 68, 68),    # rojo
    QColor(34, 197, 94),    # verde
    QColor(234, 179, 8),    # amarillo
    QColor(236, 72, 153),   # rosa
]


def _placeholder_pixmap() -> QPixmap:
    pix = QPixmap(THUMB_W, THUMB_H)
    pix.fill(QColor("#26262C"))
    return pix


class _PageStrip(QListWidget):
    """Horizontal QListWidget with custom drag/drop for intra- and cross-lane operations."""

    cross_lane_drop_received = pyqtSignal(str, str, list, bool)  # src_id, dst_id, refs, ctrl
    pdf_file_dropped = pyqtSignal(str)                           # file path
    internal_reorder_done = pyqtSignal()

    def __init__(self, lane_id: str, parent=None) -> None:
        super().__init__(parent)
        self._lane_id = lane_id
        self.setObjectName("DocLaneStrip")
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(False)
        self.setIconSize(QSize(THUMB_W, THUMB_H))
        self.setGridSize(QSize(THUMB_W + 24, THUMB_H + 28))
        self.setSpacing(4)
        self.setFixedHeight(STRIP_HEIGHT)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.viewport().setAcceptDrops(True)
        self.model().rowsMoved.connect(lambda *_: self.internal_reorder_done.emit())

    # ── Drag ──────────────────────────────────────────────────────────────

    def startDrag(self, supported_actions) -> None:
        selected_refs = [
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
            if self.item(i) and self.item(i).isSelected()
        ]
        if not selected_refs:
            return
        mime = encode_drag(self._lane_id, selected_refs)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)

    # ── Drop ──────────────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(MIME_TYPE) or event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_highlight(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_highlight(False)
        decoded = decode_drag(event.mimeData())

        if decoded is not None:
            src_id, refs = decoded
            if src_id == self._lane_id:
                # Internal reorder: find drop position and move items
                target_item = self.itemAt(event.position().toPoint())
                target_row = self.row(target_item) if target_item else self.count()
                self._reorder_to(refs, target_row)
            else:
                ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                self.cross_lane_drop_received.emit(src_id, self._lane_id, refs, ctrl)
            event.acceptProposedAction()
            return

        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path.lower().endswith(".pdf"):
                    self.pdf_file_dropped.emit(path)
            event.acceptProposedAction()
            return

        event.ignore()

    def _reorder_to(self, refs: List[PageRef], target_row: int) -> None:
        page_ids = {r.page_id for r in refs}
        moving_rows = sorted(
            [i for i in range(self.count())
             if self.item(i) and self.item(i).data(Qt.ItemDataRole.UserRole).page_id in page_ids]
        )
        items = []
        adj = target_row
        for row in sorted(moving_rows, reverse=True):
            items.insert(0, self.takeItem(row))
            if row < adj:
                adj -= 1
        for offset, item in enumerate(items):
            self.insertItem(adj + offset, item)
        self.internal_reorder_done.emit()

    def _set_highlight(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                "QListWidget#DocLaneStrip {"
                "  border: 2px solid #14B8A6;"
                "  border-radius: 4px;"
                "  background: rgba(20,184,166,0.06);"
                "}"
            )
        else:
            self.setStyleSheet(
                "QListWidget#DocLaneStrip {"
                "  border: 1px solid #26262C;"
                "  border-radius: 4px;"
                "}"
            )

    # ── Context menu ──────────────────────────────────────────────────────

    def contextMenuEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        if item is None:
            return
        if item not in self.selectedItems():
            self.clearSelection()
            item.setSelected(True)
        # Bubble up to parent DocLane
        parent = self.parent()
        if isinstance(parent, QWidget) and hasattr(parent, "_show_page_context_menu"):
            parent._show_page_context_menu(event.globalPos())


class DocLane(QFrame):
    """Header + horizontal page strip for one document in the organizer."""

    pages_changed = pyqtSignal(str)                               # lane_id
    lane_delete_requested = pyqtSignal(str)                       # lane_id
    reorder_requested = pyqtSignal(str, int)                      # lane_id, direction
    cross_lane_drop_received = pyqtSignal(str, str, list, bool)   # src_id, dst_id, refs, ctrl

    def __init__(
        self,
        lane_id: str,
        display_name: str,
        color: QColor,
        cache: ThumbnailCache,
        worker: ThumbnailWorker,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._lane_id = lane_id
        self._display_name = display_name
        self._color = color
        self._cache = cache
        self._worker = worker
        self._collapsed = False
        # Provider for other-lane names (set by LaneContainer)
        self._siblings_provider: Callable[[], List[Tuple[str, str]]] = lambda: []
        worker.thumb_ready.connect(self._on_thumb_ready)
        self._build()

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def lane_id(self) -> str:
        return self._lane_id

    @property
    def display_name(self) -> str:
        return self._display_name

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setProperty("class", "Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = self._build_header()
        layout.addWidget(self._header)

        self._strip_wrap = QFrame()
        sw = QVBoxLayout(self._strip_wrap)
        sw.setContentsMargins(8, 6, 8, 8)
        sw.setSpacing(0)

        self._list = _PageStrip(self._lane_id)
        self._list.internal_reorder_done.connect(lambda: self.pages_changed.emit(self._lane_id))
        self._list.cross_lane_drop_received.connect(self.cross_lane_drop_received)
        self._list.pdf_file_dropped.connect(self.add_pages_from_pdf)
        self._list.installEventFilter(self)

        sw.addWidget(self._list)
        layout.addWidget(self._strip_wrap)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setFixedHeight(40)
        r, g, b = self._color.red(), self._color.green(), self._color.blue()
        header.setStyleSheet(
            "QFrame { background-color: #1A1A22; border-bottom: 1px solid #26262C; }"
        )
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 8, 0)
        h.setSpacing(0)

        accent = QFrame()
        accent.setFixedWidth(4)
        accent.setStyleSheet(f"background-color: rgb({r},{g},{b});")
        h.addWidget(accent)
        h.addSpacing(8)

        up_btn = QPushButton("↑")
        up_btn.setProperty("class", "IconBtn")
        up_btn.setFixedSize(22, 22)
        up_btn.setToolTip("Mover fila hacia arriba")
        up_btn.clicked.connect(lambda: self.reorder_requested.emit(self._lane_id, -1))
        h.addWidget(up_btn)

        down_btn = QPushButton("↓")
        down_btn.setProperty("class", "IconBtn")
        down_btn.setFixedSize(22, 22)
        down_btn.setToolTip("Mover fila hacia abajo")
        down_btn.clicked.connect(lambda: self.reorder_requested.emit(self._lane_id, +1))
        h.addWidget(down_btn)
        h.addSpacing(8)

        self._name_lbl = QLabel(self._display_name)
        self._name_lbl.setStyleSheet(
            "color: #ECEDEE; font-size: 13px; font-weight: 600; background: transparent;"
        )
        self._name_lbl.setToolTip("Doble clic para renombrar")
        self._name_lbl.mouseDoubleClickEvent = lambda _: self._start_name_edit()
        h.addWidget(self._name_lbl)

        self._name_edit = QLineEdit(self._display_name)
        self._name_edit.setStyleSheet(
            "QLineEdit { background: #26262C; border: 1px solid #5E6AD2; "
            "border-radius: 4px; color: #ECEDEE; font-size: 13px; padding: 2px 6px; }"
        )
        self._name_edit.setMaximumWidth(200)
        self._name_edit.setVisible(False)
        self._name_edit.returnPressed.connect(self._commit_name_edit)
        self._name_edit.editingFinished.connect(self._commit_name_edit)
        h.addWidget(self._name_edit)
        h.addSpacing(10)

        self._count_lbl = QLabel("0 págs")
        self._count_lbl.setStyleSheet(
            "color: #9094A0; font-size: 11px; background: transparent;"
        )
        self._count_lbl.setMinimumWidth(52)
        h.addWidget(self._count_lbl)
        h.addStretch()

        add_btn = QPushButton("+ Agregar")
        add_btn.setProperty("class", "Ghost")
        add_btn.setFixedHeight(26)
        add_btn.setToolTip("Agregar páginas de un PDF")
        add_btn.clicked.connect(self._on_add_pages)
        h.addWidget(add_btn)
        h.addSpacing(4)

        clear_btn = QPushButton()
        clear_btn.setProperty("class", "IconBtn")
        clear_btn.setFixedSize(26, 26)
        clear_btn.setToolTip("Vaciar esta fila")
        set_button_icon(clear_btn, "trash-2", size=13, icon_only=True)
        clear_btn.clicked.connect(self.clear)
        h.addWidget(clear_btn)

        del_btn = QPushButton()
        del_btn.setProperty("class", "IconBtn")
        del_btn.setFixedSize(26, 26)
        del_btn.setToolTip("Eliminar esta fila del organizador")
        set_button_icon(del_btn, "x", size=13, icon_only=True)
        del_btn.clicked.connect(lambda: self.lane_delete_requested.emit(self._lane_id))
        h.addWidget(del_btn)
        h.addSpacing(4)

        self._collapse_btn = QPushButton("▼")
        self._collapse_btn.setProperty("class", "IconBtn")
        self._collapse_btn.setFixedSize(26, 26)
        self._collapse_btn.setToolTip("Colapsar / expandir fila")
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        h.addWidget(self._collapse_btn)

        return header

    # ── Public API ─────────────────────────────────────────────────────────

    def set_siblings_provider(
        self, fn: Callable[[], List[Tuple[str, str]]]
    ) -> None:
        """fn() → [(lane_id, display_name), ...] of OTHER lanes."""
        self._siblings_provider = fn

    def add_pages_from_pdf(self, path: str) -> None:
        try:
            doc = fitz.open(path)
            try:
                for idx in range(doc.page_count):
                    page_id = f"{Path(path).stem}-{idx+1}-{uuid.uuid4().hex[:8]}"
                    ref = PageRef(
                        source_path=path,
                        page_index=idx,
                        rotation_deg=0,
                        page_id=page_id,
                    )
                    item = self._make_item(ref)
                    self._list.addItem(item)
                    self._worker.request(
                        self._lane_id, ref.page_id,
                        ref.source_path, ref.page_index, ref.rotation_deg, THUMB_W,
                    )
            finally:
                doc.close()
        except Exception:
            pass
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    def add_page_ref(self, ref: PageRef, at_row: Optional[int] = None) -> None:
        """Insert a PageRef (cross-lane drop or manual insert)."""
        item = self._make_item(ref)
        if at_row is not None and 0 <= at_row <= self._list.count():
            self._list.insertItem(at_row, item)
        else:
            self._list.addItem(item)
        self._worker.request(
            self._lane_id, ref.page_id,
            ref.source_path, ref.page_index, ref.rotation_deg, THUMB_W,
        )
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    def page_refs(self) -> List[PageRef]:
        return [
            self._list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._list.count())
        ]

    def selected_refs(self) -> List[PageRef]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._list.selectedItems()
        ]

    def count(self) -> int:
        return self._list.count()

    def clear(self) -> None:
        self._list.clear()
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    def remove_by_page_ids(self, page_ids: set) -> None:
        rows = sorted(
            [i for i in range(self._list.count())
             if self._list.item(i).data(Qt.ItemDataRole.UserRole).page_id in page_ids],
            reverse=True,
        )
        for row in rows:
            self._list.takeItem(row)
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    def rotate_selected(self, delta: int) -> None:
        for item in self._list.selectedItems():
            ref = item.data(Qt.ItemDataRole.UserRole)
            updated = replace(ref, rotation_deg=(ref.rotation_deg + delta) % 360)
            item.setData(Qt.ItemDataRole.UserRole, updated)
            item.setText(self._label_for(updated))
            item.setToolTip(f"{Path(updated.source_path).name}\nPágina {updated.page_index + 1}"
                            + (f"\nRot {updated.rotation_deg}°" if updated.rotation_deg else ""))
            key = ThumbnailKey(updated.source_path, updated.page_index, updated.rotation_deg, THUMB_W)
            cached = self._cache.get(key)
            if cached:
                item.setIcon(QIcon(cached))
            else:
                item.setIcon(QIcon(_placeholder_pixmap()))
                self._worker.request(
                    self._lane_id, updated.page_id,
                    updated.source_path, updated.page_index, updated.rotation_deg, THUMB_W,
                )
        self.pages_changed.emit(self._lane_id)

    def duplicate_selected(self) -> None:
        selected = self._list.selectedItems()
        if not selected:
            return
        last_row = max(self._list.row(item) for item in selected)
        clones: List[PageRef] = []
        for item in selected:
            ref = item.data(Qt.ItemDataRole.UserRole)
            stem = Path(ref.source_path).stem
            new_ref = replace(ref, page_id=f"{stem}-{ref.page_index+1}-{uuid.uuid4().hex[:8]}")
            clones.append(new_ref)
        for offset, ref in enumerate(clones):
            new_item = self._make_item(ref)
            self._list.insertItem(last_row + 1 + offset, new_item)
            self._worker.request(
                self._lane_id, ref.page_id,
                ref.source_path, ref.page_index, ref.rotation_deg, THUMB_W,
            )
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    # ── Event filter (keyboard shortcuts) ─────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        if obj is self._list and event.type() == QEvent.Type.KeyPress:
            if isinstance(event, QKeyEvent):
                key = event.key()
                mods = event.modifiers()
                if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    self._remove_selected()
                    return True
                if key == Qt.Key.Key_A and mods & Qt.KeyboardModifier.ControlModifier:
                    self._list.selectAll()
                    return True
                if key == Qt.Key.Key_D and mods & Qt.KeyboardModifier.ControlModifier:
                    self.duplicate_selected()
                    return True
                if key == Qt.Key.Key_R:
                    delta = -90 if mods & Qt.KeyboardModifier.ShiftModifier else 90
                    self.rotate_selected(delta)
                    return True
        return super().eventFilter(obj, event)

    # ── Context menu ──────────────────────────────────────────────────────

    def _show_page_context_menu(self, global_pos) -> None:
        selected = self.selected_refs()
        if not selected:
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#1E1E26; border:1px solid #32323C; border-radius:6px;"
            " padding:4px 0; color:#ECEDEE; font-size:12px; }"
            "QMenu::item { padding:6px 20px 6px 14px; border-radius:4px; margin:1px 4px; }"
            "QMenu::item:selected { background:#2E2E3A; }"
            "QMenu::item:disabled { color:#5A5A6A; }"
            "QMenu::separator { height:1px; background:#32323C; margin:3px 8px; }"
        )

        rot_cw = menu.addAction("Rotar 90° →")
        rot_ccw = menu.addAction("Rotar 90° ←")
        menu.addSeparator()
        dup_act = menu.addAction("Duplicar")
        menu.addSeparator()

        siblings = self._siblings_provider()
        move_menu = None
        copy_menu = None
        if siblings:
            move_menu = menu.addMenu("Mover a…")
            copy_menu = menu.addMenu("Copiar a…")
            move_menu.setStyleSheet(menu.styleSheet())
            copy_menu.setStyleSheet(menu.styleSheet())
            for sib_id, sib_name in siblings:
                move_menu.addAction(sib_name).setData(("move", sib_id))
                copy_menu.addAction(sib_name).setData(("copy", sib_id))

        menu.addSeparator()
        del_act = menu.addAction("Eliminar")

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen == rot_cw:
            self.rotate_selected(90)
        elif chosen == rot_ccw:
            self.rotate_selected(-90)
        elif chosen == dup_act:
            self.duplicate_selected()
        elif chosen == del_act:
            self._remove_selected()
        elif chosen.data() is not None:
            action_type, target_lane_id = chosen.data()
            ctrl_held = (action_type == "copy")
            self.cross_lane_drop_received.emit(
                self._lane_id, target_lane_id, selected, ctrl_held
            )
            if not ctrl_held:
                page_ids = {r.page_id for r in selected}
                self.remove_by_page_ids(page_ids)

    # ── Private helpers ────────────────────────────────────────────────────

    def _make_item(self, ref: PageRef) -> QListWidgetItem:
        item = QListWidgetItem(QIcon(_placeholder_pixmap()), self._label_for(ref))
        item.setData(Qt.ItemDataRole.UserRole, ref)
        item.setSizeHint(QSize(THUMB_W + 24, THUMB_H + 28))
        item.setToolTip(
            f"{Path(ref.source_path).name}\nPágina {ref.page_index + 1}"
            + (f"\nRot {ref.rotation_deg}°" if ref.rotation_deg else "")
        )
        return item

    @staticmethod
    def _label_for(ref: PageRef) -> str:
        rot = f" ↺{ref.rotation_deg}°" if ref.rotation_deg % 360 else ""
        return f"Pág {ref.page_index + 1}{rot}"

    def _on_thumb_ready(self, lane_id: str, page_id: str, pixmap: object) -> None:
        if lane_id != self._lane_id:
            return
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole).page_id == page_id:
                item.setIcon(QIcon(pixmap))
                break

    def _remove_selected(self) -> None:
        rows = sorted(
            {self._list.row(item) for item in self._list.selectedItems()},
            reverse=True,
        )
        for row in rows:
            self._list.takeItem(row)
        self._update_count()
        self.pages_changed.emit(self._lane_id)

    def _update_count(self) -> None:
        n = self._list.count()
        self._count_lbl.setText(f"{n} pág" + ("s" if n != 1 else ""))

    def _on_add_pages(self) -> None:
        files, _ = get_open_file_names(self.window(), "Agregar PDFs", "", PDF_FILTER)
        for path in files:
            self.add_pages_from_pdf(path)

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self._strip_wrap.setVisible(not self._collapsed)
        self._collapse_btn.setText("▶" if self._collapsed else "▼")

    def _start_name_edit(self) -> None:
        self._name_lbl.setVisible(False)
        self._name_edit.setText(self._display_name)
        self._name_edit.setVisible(True)
        self._name_edit.setFocus()
        self._name_edit.selectAll()

    def _commit_name_edit(self) -> None:
        if not self._name_edit.isVisible():
            return
        text = self._name_edit.text().strip() or self._display_name
        self._display_name = text
        self._name_lbl.setText(text)
        self._name_lbl.setVisible(True)
        self._name_edit.setVisible(False)
```

- [ ] **Step 4: Verificar que los tests pasan**

```
python -m pytest tests/test_organizador_window.py::DocLaneTests -v
```
Esperado: 4 passed

- [ ] **Step 5: Commit**

```bash
git add ui/organizador/lane_widget.py tests/test_organizador_window.py
git commit -m "feat(organizador): DocLane — header colapsable + strip con drag/drop + teclado"
```

---

## Task 5: LaneContainer

**Files:**
- Create: `ui/organizador/lane_container.py`
- Modify: `tests/test_organizador_window.py`

- [ ] **Step 1: Escribir tests que fallan**

Agregar a `tests/test_organizador_window.py`:

```python
from ui.organizador.lane_container import LaneContainer


class LaneContainerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_add_blank_lane_creates_empty_lane(self) -> None:
        container = LaneContainer()
        lane = container.add_blank_lane("Mi doc")
        self.assertEqual(len(container.lanes()), 1)
        self.assertEqual(lane.display_name, "Mi doc")
        self.assertEqual(lane.count(), 0)
        container.deleteLater()

    def test_add_pdf_lane_populates_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "x.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.new_page()
            doc.save(pdf)
            doc.close()

            container = LaneContainer()
            lane = container.add_lane_from_pdf(str(pdf))
            self.assertEqual(lane.count(), 2)
            container.deleteLater()

    def test_cross_lane_move_removes_from_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "m.pdf"
            doc = fitz.open()
            for _ in range(3):
                doc.new_page()
            doc.save(pdf)
            doc.close()

            container = LaneContainer()
            src_lane = container.add_lane_from_pdf(str(pdf))
            dst_lane = container.add_blank_lane("destino")

            refs_to_move = src_lane.page_refs()[:2]
            container._on_cross_lane_drop(
                src_lane.lane_id, dst_lane.lane_id, refs_to_move, ctrl_held=False
            )

            self.assertEqual(src_lane.count(), 1)
            self.assertEqual(dst_lane.count(), 2)
            container.deleteLater()

    def test_cross_lane_copy_keeps_source_intact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "c.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(pdf)
            doc.close()

            container = LaneContainer()
            src_lane = container.add_lane_from_pdf(str(pdf))
            dst_lane = container.add_blank_lane("copia")

            refs = src_lane.page_refs()
            container._on_cross_lane_drop(
                src_lane.lane_id, dst_lane.lane_id, refs, ctrl_held=True
            )

            self.assertEqual(src_lane.count(), 1)  # untouched
            self.assertEqual(dst_lane.count(), 1)
            # Copied ref has different page_id
            self.assertNotEqual(
                src_lane.page_refs()[0].page_id,
                dst_lane.page_refs()[0].page_id,
            )
            container.deleteLater()

    def test_remove_lane_removes_widget(self) -> None:
        container = LaneContainer()
        lane = container.add_blank_lane("borrar")
        container.remove_lane(lane.lane_id)
        self.assertEqual(len(container.lanes()), 0)
        container.deleteLater()

    def test_move_lane_changes_order(self) -> None:
        container = LaneContainer()
        lane_a = container.add_blank_lane("A")
        lane_b = container.add_blank_lane("B")
        # Move B up (direction=-1)
        container.move_lane(lane_b.lane_id, -1)
        names = [lane.display_name for lane in container.lanes()]
        self.assertEqual(names, ["B", "A"])
        container.deleteLater()
```

- [ ] **Step 2: Verificar que fallan**

```
python -m pytest tests/test_organizador_window.py::LaneContainerTests -v
```
Esperado: FAIL con `ImportError`

- [ ] **Step 3: Crear `ui/organizador/lane_container.py`**

```python
"""LaneContainer — manages N DocLanes stacked vertically."""
from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from core.page_organizer_engine import PageRef
from ui.common.file_dialogs import get_open_file_names
from ui.common.icons import set_button_icon
from ui.organizador.lane_widget import LANE_COLORS, DocLane
from ui.organizador.thumb_cache import ThumbnailCache, ThumbnailWorker

PDF_FILTER = "PDF (*.pdf)"


class LaneContainer(QWidget):
    """Vertical scroll area containing N DocLanes."""

    layout_changed = pyqtSignal()   # emitted whenever lanes are added/removed/reordered

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lanes: List[DocLane] = []

        # Shared thumbnail cache + background worker
        self._cache = ThumbnailCache(max_size=300)
        self._worker = ThumbnailWorker(self._cache)
        self._thumb_thread = QThread(self)
        self._worker.moveToThread(self._thumb_thread)
        self._thumb_thread.started.connect(self._worker.run)
        self._thumb_thread.start()

        self._build()
        self.destroyed.connect(self._stop_worker)

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(8)
        self._container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._bottom_bar = self._build_bottom_bar()
        self._container_layout.addWidget(self._bottom_bar)

        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, 1)

    def _build_bottom_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("LaneBottomBar")
        bar.setStyleSheet(
            "QFrame#LaneBottomBar { border-top: 1px solid #26262C; padding-top: 4px; }"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 8, 8, 8)
        h.setSpacing(8)

        blank_btn = QPushButton("＋ Nuevo documento vacío")
        blank_btn.setProperty("class", "Ghost")
        set_button_icon(blank_btn, "plus", size=13)
        blank_btn.clicked.connect(self._on_add_blank)
        h.addWidget(blank_btn)

        pdf_btn = QPushButton("＋ Agregar PDFs")
        pdf_btn.setProperty("class", "Primary")
        set_button_icon(pdf_btn, "plus", size=13)
        pdf_btn.clicked.connect(self._on_add_pdfs)
        h.addWidget(pdf_btn)
        h.addStretch()
        return bar

    # ── Public API ─────────────────────────────────────────────────────────

    def lanes(self) -> List[DocLane]:
        return list(self._lanes)

    def add_lane_from_pdf(self, path: str) -> DocLane:
        name = Path(path).name
        lane = self._create_lane(name)
        lane.add_pages_from_pdf(path)
        return lane

    def add_blank_lane(self, name: str = "") -> DocLane:
        display = name or f"Documento {len(self._lanes) + 1}"
        return self._create_lane(display)

    def remove_lane(self, lane_id: str) -> None:
        idx = self._index_of(lane_id)
        if idx < 0:
            return
        lane = self._lanes.pop(idx)
        self._container_layout.removeWidget(lane)
        lane.deleteLater()
        self._refresh_siblings()
        self.layout_changed.emit()

    def move_lane(self, lane_id: str, direction: int) -> None:
        idx = self._index_of(lane_id)
        if idx < 0:
            return
        new_idx = max(0, min(len(self._lanes) - 1, idx + direction))
        if new_idx == idx:
            return
        self._lanes.insert(new_idx, self._lanes.pop(idx))
        self._rebuild_layout()
        self.layout_changed.emit()

    def add_paths(self, paths: List[str]) -> None:
        for path in paths:
            if path.lower().endswith(".pdf") and Path(path).is_file():
                self.add_lane_from_pdf(path)

    def all_lane_states(self) -> List[Tuple[str, str, List[PageRef]]]:
        """Returns [(lane_id, display_name, [PageRef, ...]), ...] in visual order."""
        return [(lane.lane_id, lane.display_name, lane.page_refs()) for lane in self._lanes]

    def total_pages(self) -> int:
        return sum(lane.count() for lane in self._lanes)

    def total_lanes(self) -> int:
        return len(self._lanes)

    def clear(self) -> None:
        for lane in list(self._lanes):
            lane.deleteLater()
        self._lanes.clear()
        self.layout_changed.emit()

    # ── Cross-lane drop coordinator ────────────────────────────────────────

    def _on_cross_lane_drop(
        self,
        src_lane_id: str,
        dst_lane_id: str,
        refs: List[PageRef],
        ctrl_held: bool,
    ) -> None:
        dst = next((l for l in self._lanes if l.lane_id == dst_lane_id), None)
        src = next((l for l in self._lanes if l.lane_id == src_lane_id), None)
        if dst is None:
            return

        # Regenerate page_ids for copies to avoid duplicates
        def _clone(ref: PageRef) -> PageRef:
            stem = Path(ref.source_path).stem
            return replace(ref, page_id=f"{stem}-{ref.page_index+1}-{uuid.uuid4().hex[:8]}")

        for ref in refs:
            dst.add_page_ref(_clone(ref))

        if not ctrl_held and src is not None:
            page_ids = {r.page_id for r in refs}
            src.remove_by_page_ids(page_ids)

    # ── Private helpers ────────────────────────────────────────────────────

    def _create_lane(self, display_name: str) -> DocLane:
        color = LANE_COLORS[len(self._lanes) % len(LANE_COLORS)]
        lane_id = uuid.uuid4().hex[:12]
        lane = DocLane(lane_id, display_name, color, self._cache, self._worker)
        lane.setSizePolicy(
            lane.sizePolicy().horizontalPolicy(),
            lane.sizePolicy().VerticalPolicy.Fixed,
        )
        lane.pages_changed.connect(lambda _: self.layout_changed.emit())
        lane.lane_delete_requested.connect(self.remove_lane)
        lane.reorder_requested.connect(self.move_lane)
        lane.cross_lane_drop_received.connect(self._on_cross_lane_drop)

        self._lanes.append(lane)
        # Insert before the bottom bar
        bottom_idx = self._container_layout.indexOf(self._bottom_bar)
        self._container_layout.insertWidget(bottom_idx, lane)

        self._refresh_siblings()
        self.layout_changed.emit()
        return lane

    def _index_of(self, lane_id: str) -> int:
        for i, lane in enumerate(self._lanes):
            if lane.lane_id == lane_id:
                return i
        return -1

    def _rebuild_layout(self) -> None:
        # Remove all lanes from layout (keep bottom bar)
        for lane in self._lanes:
            self._container_layout.removeWidget(lane)
        # Re-insert in new order
        bottom_idx = self._container_layout.indexOf(self._bottom_bar)
        for i, lane in enumerate(self._lanes):
            self._container_layout.insertWidget(bottom_idx + i, lane)

    def _refresh_siblings(self) -> None:
        for lane in self._lanes:
            siblings = [
                (l.lane_id, l.display_name)
                for l in self._lanes
                if l.lane_id != lane.lane_id
            ]
            lane.set_siblings_provider(lambda s=siblings: s)

    def _on_add_blank(self) -> None:
        self.add_blank_lane()

    def _on_add_pdfs(self) -> None:
        files, _ = get_open_file_names(self.window(), "Agregar PDFs", "", PDF_FILTER)
        self.add_paths(files)

    def _stop_worker(self) -> None:
        self._worker.stop()
        self._thumb_thread.quit()
        self._thumb_thread.wait(2000)
```

- [ ] **Step 4: Verificar que los tests pasan**

```
python -m pytest tests/test_organizador_window.py::LaneContainerTests -v
```
Esperado: 6 passed

- [ ] **Step 5: Commit**

```bash
git add ui/organizador/lane_container.py tests/test_organizador_window.py
git commit -m "feat(organizador): LaneContainer — gestiona N DocLanes, cross-lane DnD, reorden"
```

---

## Task 6: OrganizadorWindow rewrite

**Files:**
- Rewrite: `ui/organizador/window.py`
- Modify: `tests/test_organizador_window.py`

- [ ] **Step 1: Escribir tests de integración que fallan**

Agregar a `tests/test_organizador_window.py`:

```python
class OrganizadorWindowV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _make_ctx(self):
        from shell.context import ShellContext
        from shell.tray import PdfTray
        from shell.word_to_pdf import WordToPdfConverter
        return ShellContext(
            tray=PdfTray(),
            word_converter=WordToPdfConverter(),
            open_tool=lambda *_: None,
        )

    def test_window_creates_two_lanes_for_two_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_a = Path(tmp) / "a.pdf"
            pdf_b = Path(tmp) / "b.pdf"
            for path, label in [(pdf_a, "A"), (pdf_b, "B")]:
                doc = fitz.open()
                doc.new_page().insert_text((36, 72), label)
                doc.save(path)
                doc.close()

            window = OrganizadorWindow(self._make_ctx())
            try:
                window.set_inputs([str(pdf_a), str(pdf_b)])
                self.assertEqual(window._lane_container.total_lanes(), 2)
                pages = sum(
                    lane.count()
                    for lane in window._lane_container.lanes()
                )
                self.assertEqual(pages, 2)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_build_multi_job_separate_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_a = Path(tmp) / "a.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.new_page()
            doc.save(pdf_a)
            doc.close()

            window = OrganizadorWindow(self._make_ctx())
            try:
                window.set_inputs([str(pdf_a)])
                # Default: separate mode (merge not checked)
                job = window._build_multi_job()
                self.assertEqual(len(job.lanes), 1)
                self.assertEqual(len(job.lanes[0].pages), 2)
                self.assertFalse(job.merge_all)
            finally:
                window.deleteLater()
                self.app.processEvents()
```

- [ ] **Step 2: Verificar que fallan**

```
python -m pytest tests/test_organizador_window.py::OrganizadorWindowV2Tests -v
```
Esperado: FAIL (OrganizadorWindow no tiene `_lane_container` ni `_build_multi_job`)

- [ ] **Step 3: Reescribir `ui/organizador/window.py`**

```python
"""OrganizadorWindow — organizador visual multi-lane de páginas PDF.

v2 — Rediseño completo:
  - Un DocLane por PDF (filas separadas, no cuadrícula mezclada).
  - Drag & drop entre filas: mover (default) o copiar (Ctrl).
  - Exportación flexible: N PDFs independientes o uno fusionado.
  - ThumbnailWorker en background: UI no se bloquea al cargar PDFs grandes.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QThread, QUrl, pyqtSignal, Qt, QObject
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core.output_paths import make_run_dir, unique_output_path
from core.page_organizer_engine import (
    MultiOrganizerJob,
    MultiOrganizerResult,
    OrganizerJob,
    OrganizerResult,
    PageOrganizerEngine,
    PageRef,
)
from shell.context import ShellContext
from ui.common.cards import make_page_header
from ui.common.dialogs import show_error, show_warning
from ui.common.icons import set_button_icon
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.process_step import ProcessStep
from ui.common.send_to_tool import SendToToolButton
from ui.common.tool_scaffold import PipelineWindow
from ui.organizador.lane_container import LaneContainer


class _MultiWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(object)   # MultiOrganizerResult
    error = pyqtSignal(str)

    def __init__(self, job: MultiOrganizerJob) -> None:
        super().__init__()
        self.job = job
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        result = PageOrganizerEngine().run_multi_job(
            self.job,
            progress=lambda c, t, m: self.progress.emit(c, t, m),
            should_cancel=lambda: self._cancel,
        )
        if result.success:
            self.finished.emit(result)
        else:
            self.error.emit(result.error or "No se pudo organizar el PDF.")


class OrganizadorWindow(PipelineWindow):
    SECTIONS = [
        ("01", "Páginas",   "Carga, reordena y edita"),
        ("02", "Procesar",  "Configura la salida"),
        ("03", "Resultados","Revisa los documentos"),
    ]
    BRAND = "Organizador"
    TAGLINE = "Reordena, rota, duplica y extrae páginas"
    ACCENT_COLOR = "#14B8A6"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self._last_result: Optional[MultiOrganizerResult] = None
        self._worker: Optional[_MultiWorker] = None
        self._worker_thread: Optional[QThread] = None
        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)

    # ── Build ──────────────────────────────────────────────────────────────

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_pages_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _build_pages_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(16)

        outer.addLayout(make_page_header(
            "Organizador visual de páginas",
            "Cada PDF carga en su propia fila. Arrastra páginas entre filas para moverlas (Ctrl = copiar).",
        ))

        self._lane_container = LaneContainer()
        self._lane_container.layout_changed.connect(self._on_layout_changed)
        outer.addWidget(self._lane_container, 1)

        self._summary_lbl = QLabel("Sin páginas cargadas.")
        self._summary_lbl.setProperty("class", "CardHint")
        outer.addWidget(self._summary_lbl)

        nav = QHBoxLayout()
        nav.addStretch()
        next_btn = QPushButton("Continuar")
        next_btn.setProperty("class", "Primary")
        next_btn.setMinimumWidth(160)
        set_button_icon(next_btn, "arrow-right")
        next_btn.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(next_btn)
        outer.addLayout(nav)
        return page

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Configura el nombre de cada documento de salida o fusiónalo todo en uno.",
        ))

        # Table: one row per lane
        self._output_table = QTableWidget(0, 3)
        self._output_table.setHorizontalHeaderLabels(["Documento", "Páginas", "Nombre de salida"])
        self._output_table.horizontalHeader().setStretchLastSection(True)
        self._output_table.verticalHeader().setVisible(False)
        self._output_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._output_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._output_table.setMaximumHeight(220)
        outer.addWidget(self._output_table)

        merge_row = QHBoxLayout()
        self._merge_chk = QCheckBox("Fusionar todo en un solo PDF:")
        self._merge_chk.toggled.connect(self._on_merge_toggled)
        merge_row.addWidget(self._merge_chk)
        self._merge_name_edit = QLineEdit("organizado_merged")
        self._merge_name_edit.setMaximumWidth(240)
        self._merge_name_edit.setEnabled(False)
        merge_row.addWidget(self._merge_name_edit)
        merge_row.addStretch()
        outer.addLayout(merge_row)

        self._proc_step = ProcessStep(
            run_label="Generar PDFs",
            show_output_dir=False,
        )
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
        outer.addWidget(self._proc_step, 1)

        nav = QHBoxLayout()
        back = QPushButton("Páginas")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(0))
        nav.addWidget(back)
        outer.addLayout(nav)
        return page

    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultado",
            "Los PDFs organizados están listos.",
        ))

        self._result_viewer = GenericPdfViewer("PDF organizado")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        nav = QHBoxLayout()
        back = QPushButton("Procesar")
        back.setProperty("class", "Ghost")
        set_button_icon(back, "arrow-left")
        back.clicked.connect(lambda: self._switch_section(1))
        nav.addWidget(back)
        nav.addStretch()
        self._send_btn = SendToToolButton(self.ctx, "organizador")
        nav.addWidget(self._send_btn)
        restart_btn = QPushButton("Nueva sesión")
        restart_btn.setProperty("class", "Primary")
        restart_btn.setMinimumWidth(180)
        set_button_icon(restart_btn, "refresh-cw")
        restart_btn.clicked.connect(self._reset_session)
        nav.addWidget(restart_btn)
        outer.addLayout(nav)
        return page

    # ── PipelineWindow hooks ───────────────────────────────────────────────

    def _on_section_activated(self, idx: int) -> None:
        if idx == 1:
            self._refresh_output_table()
            self._refresh_proc_summary()

    def set_inputs(self, paths: List[str]) -> None:
        self._lane_container.add_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._lane_container.add_paths(paths)
        self._switch_section(0)

    # ── Slots ──────────────────────────────────────────────────────────────

    def _on_layout_changed(self) -> None:
        total = self._lane_container.total_pages()
        lanes = self._lane_container.total_lanes()
        if total == 0:
            self._summary_lbl.setText("Sin páginas cargadas.")
        else:
            self._summary_lbl.setText(
                f"{total} página{'s' if total != 1 else ''}"
                f" · {lanes} fila{'s' if lanes != 1 else ''}"
            )

    def _on_merge_toggled(self, checked: bool) -> None:
        self._merge_name_edit.setEnabled(checked)
        for row in range(self._output_table.rowCount()):
            w = self._output_table.cellWidget(row, 2)
            if w:
                w.setEnabled(not checked)

    # ── Output table ──────────────────────────────────────────────────────

    def _refresh_output_table(self) -> None:
        states = self._lane_container.all_lane_states()
        self._output_table.setRowCount(len(states))
        for row, (lane_id, name, refs) in enumerate(states):
            self._output_table.setItem(row, 0, QTableWidgetItem(name))
            self._output_table.setItem(row, 1, QTableWidgetItem(str(len(refs))))
            stem = Path(name).stem if "." in name else name
            edit = QLineEdit(f"{stem}_org")
            edit.setProperty("lane_id", lane_id)
            self._output_table.setCellWidget(row, 2, edit)
        self._output_table.resizeColumnsToContents()
        self._output_table.horizontalHeader().setStretchLastSection(True)

    def _output_name_for_row(self, row: int) -> str:
        w = self._output_table.cellWidget(row, 2)
        if isinstance(w, QLineEdit):
            text = w.text().strip()
            if text:
                return text if text.endswith(".pdf") else text + ".pdf"
        return f"doc_{row + 1}_org.pdf"

    # ── Job building ──────────────────────────────────────────────────────

    def _build_multi_job(self) -> MultiOrganizerJob:
        out_dir = make_run_dir("Organizador")
        states = self._lane_container.all_lane_states()
        merge = self._merge_chk.isChecked() if hasattr(self, "_merge_chk") else False

        if merge:
            merged_name = getattr(self, "_merge_name_edit", None)
            merged_stem = merged_name.text().strip() if merged_name else "organizado_merged"
            if not merged_stem:
                merged_stem = "organizado_merged"
            merged_out = str(unique_output_path(out_dir, merged_stem + ".pdf"))
            lanes = [
                OrganizerJob(pages=refs, output_path=merged_out)
                for (_, _, refs) in states
                if refs
            ]
        else:
            lanes = []
            for row, (_, _, refs) in enumerate(states):
                if not refs:
                    continue
                out_name = self._output_name_for_row(row) if row < self._output_table.rowCount() else f"doc_{row+1}_org.pdf"
                out_path = str(unique_output_path(out_dir, out_name))
                lanes.append(OrganizerJob(pages=refs, output_path=out_path))

        return MultiOrganizerJob(lanes=lanes, merge_all=merge)

    # ── Process ──────────────────────────────────────────────────────────

    def _refresh_proc_summary(self) -> None:
        states = self._lane_container.all_lane_states()
        total_pages = sum(len(refs) for _, _, refs in states)
        merge = self._merge_chk.isChecked() if hasattr(self, "_merge_chk") else False
        mode_txt = "Fusionar en un solo PDF" if merge else "PDFs separados por fila"
        rows = [
            f"<b>Filas:</b>&nbsp;&nbsp;{len(states)}",
            f"<b>Páginas totales:</b>&nbsp;&nbsp;{total_pages}",
            f"<b>Modo de salida:</b>&nbsp;&nbsp;{mode_txt}",
        ]
        if total_pages == 0:
            rows.insert(0, "<span style='color:#E5484D'>Sin páginas cargadas.</span>")
        self._proc_step.set_summary_html("<br>".join(rows))

    def _validate_ready(self) -> Optional[str]:
        if self._lane_container.total_pages() == 0:
            return "Agrega al menos un PDF con páginas."
        states = self._lane_container.all_lane_states()
        non_empty = [s for s in states if s[2]]
        if not non_empty:
            return "Todas las filas están vacías."
        return None

    def _on_run(self) -> None:
        err = self._validate_ready()
        if err:
            show_warning(self, "Falta información", err)
            return
        if self._worker_thread is not None:
            return

        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Preparando…")

        self._worker = _MultiWorker(self._build_multi_job())
        self._worker_thread = QThread(self)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        pct = int(current / max(1, total) * 100)
        self._proc_step.set_progress(pct, msg)

    def _on_finished(self, result: MultiOrganizerResult) -> None:
        self._cleanup_thread()
        self._last_result = result
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Listo")

        output_paths = []
        for r in result.results:
            if r.success and r.output_path:
                output_paths.append(r.output_path)

        self.ctx.tray.add_items(output_paths, "Organizador")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        if output_paths:
            # Show the first result in the viewer
            first = result.results[0]
            self._result_viewer.set_results([first])
            if first.job.pages:
                self._result_viewer.set_source_dirs(
                    [str(Path(first.job.pages[0].source_path).parent)]
                )

        self._switch_section(2)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al organizar páginas", msg)

    def _cleanup_thread(self) -> None:
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(2000)
            self._worker_thread = None
        self._worker = None

    def _open_in_explorer(self, path: str) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _reset_session(self) -> None:
        self._lane_container.clear()
        self._last_result = None
        if hasattr(self, "_result_viewer"):
            self._result_viewer.clear_results()
        if hasattr(self, "_send_btn"):
            self._send_btn.set_output_paths([])
        if hasattr(self, "_proc_step"):
            self._proc_step.reset()
        self._switch_section(0)

    # ── Drag & drop (window-level) ────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self.handle_drop(paths)
        event.acceptProposedAction()
```

- [ ] **Step 4: Actualizar test existente del organizador** — el test `test_page_grid_rotates_duplicates_and_removes_pages` usa `_page_grid` que ya no existe. Reemplázalo en `tests/test_organizador_window.py`:

```python
class OrganizadorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_tool_registry_exposes_organizer_for_pdfs(self) -> None:
        from shell.tool_registry import get_tool
        tool = get_tool("organizador")
        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Organizador visual")
        self.assertIn(".pdf", tool.input_extensions)

    def test_window_loads_pdfs_into_separate_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from shell.context import ShellContext
            from shell.tray import PdfTray
            from shell.word_to_pdf import WordToPdfConverter

            pdf_path = Path(tmp) / "input.pdf"
            doc = fitz.open()
            for i in range(2):
                doc.new_page().insert_text((36, 72), f"Page {i+1}")
            doc.save(pdf_path)
            doc.close()

            ctx = ShellContext(
                tray=PdfTray(),
                word_converter=WordToPdfConverter(),
                open_tool=lambda *_: None,
            )
            window = OrganizadorWindow(ctx)
            try:
                window.set_inputs([str(pdf_path)])
                self.assertEqual(window._lane_container.total_lanes(), 1)
                self.assertEqual(window._lane_container.total_pages(), 2)
            finally:
                window.deleteLater()
                self.app.processEvents()
```

- [ ] **Step 5: Verificar todos los tests**

```
python -m pytest tests/test_organizador_window.py tests/test_page_organizer_engine.py -v
```
Esperado: todos los tests de organizador pasan

- [ ] **Step 6: Verificar suite completa**

```
python -m pytest tests/ -v
```
Esperado: todos los tests pasan (37+ tests)

- [ ] **Step 7: Commit**

```bash
git add ui/organizador/window.py tests/test_organizador_window.py
git commit -m "feat(organizador): reescritura completa — LaneContainer, multi-output, tabla de exportación"
```

---

## Task 7: Verificación final e imports

**Files:**
- Verify: `ui/organizador/__init__.py`

- [ ] **Step 1: Verificar que todos los módulos importan sin error**

```
python -c "
from ui.organizador.thumb_cache import ThumbnailCache, ThumbnailWorker
from ui.organizador.page_mime import encode_drag, decode_drag
from ui.organizador.lane_widget import DocLane, LANE_COLORS
from ui.organizador.lane_container import LaneContainer
from ui.organizador.window import OrganizadorWindow
from core.page_organizer_engine import MultiOrganizerJob, MultiOrganizerResult
print('OK — todos los módulos importan correctamente')
"
```

- [ ] **Step 2: Suite completa final**

```
python -m pytest tests/ -v --tb=short
```
Esperado: todos pasan (37+ tests)

- [ ] **Step 3: Commit final**

```bash
git add .
git commit -m "feat(organizador): rediseño completo — DocLanes, drag cross-lane, multi-output, caché bg"
```
