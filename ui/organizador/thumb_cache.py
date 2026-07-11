"""Thumbnail cache and background renderer for DocLane page strips."""
from __future__ import annotations

import threading
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QImage

from core.pdf_backend import PdfRenderDocument
from ui.common.pdf_render_utils import rendered_page_to_qimage


@dataclass(frozen=True)
class ThumbnailKey:
    source_path: str
    page_index: int
    rotation_deg: int
    width: int


class ThumbnailCache:
    """Thread-safe LRU cache for page thumbnails."""

    def __init__(self, max_size: int = 200) -> None:
        self._cache: OrderedDict[ThumbnailKey, QImage] = OrderedDict()
        self._max_size = max_size
        self._lock = threading.Lock()

    def get(self, key: ThumbnailKey) -> Optional[QImage]:
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def put(self, key: ThumbnailKey, image: QImage) -> None:
        with self._lock:
            self._cache[key] = image
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
) -> Optional[QImage]:
    """Render one PDF page to a QImage. Returns None on any error.

    QImage is thread-safe; callers in the GUI thread must convert to QPixmap.
    """
    try:
        with PdfRenderDocument(source_path) as doc:
            page = doc.page_info(page_index)
            width = max(1.0, page.width_pt)
            scale = target_w / width
            rendered = doc.render_page(
                page_index,
                scale=scale,
                rotation=rotation_deg,
            )
            return rendered_page_to_qimage(rendered)
    except Exception:
        return None


class _ThumbRequest:
    __slots__ = (
        "lane_id",
        "page_id",
        "source_path",
        "page_index",
        "rotation_deg",
        "width",
        "generation",
    )

    def __init__(
        self,
        lane_id: str,
        page_id: str,
        source_path: str,
        page_index: int,
        rotation_deg: int,
        width: int,
        generation: int,
    ) -> None:
        self.lane_id = lane_id
        self.page_id = page_id
        self.source_path = source_path
        self.page_index = page_index
        self.rotation_deg = rotation_deg
        self.width = width
        self.generation = generation


class ThumbnailWorker(QObject):
    """Background worker that renders thumbnails and emits them via signal."""

    thumb_ready = Signal(str, str, int, object)  # lane_id, page_id, rotation_deg, QImage

    def __init__(self, cache: ThumbnailCache, parent=None) -> None:
        super().__init__(parent)
        self._cache = cache
        self._queue: deque[_ThumbRequest] = deque()
        self._lock = threading.Lock()
        self._running = True
        self._generation = 0
        self._latest_generation: dict[tuple[str, str], int] = {}

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
        rotation_deg = int(rotation_deg) % 360
        key = ThumbnailKey(source_path, page_index, rotation_deg, width)
        cached = self._cache.get(key)
        if cached is not None:
            self.thumb_ready.emit(lane_id, page_id, rotation_deg, cached)
            return
        with self._lock:
            # Re-check after acquiring queue lock — background run() may have filled cache
            cached = self._cache.get(key)
            if cached is not None:
                self.thumb_ready.emit(lane_id, page_id, rotation_deg, cached)
                return
            identity = (lane_id, page_id)
            self._generation += 1
            generation = self._generation
            self._latest_generation[identity] = generation
            self._queue = deque(
                req
                for req in self._queue
                if (req.lane_id, req.page_id) != identity
            )
            self._queue.append(
                _ThumbRequest(
                    lane_id,
                    page_id,
                    source_path,
                    page_index,
                    rotation_deg,
                    width,
                    generation,
                )
            )

    def stop(self) -> None:
        self._running = False
        with self._lock:
            self._queue.clear()
            self._latest_generation.clear()

    def discard_lane(self, lane_id: str) -> None:
        """Drop queued/stale thumbnail work for a lane that is being destroyed."""
        with self._lock:
            self._queue = deque(req for req in self._queue if req.lane_id != lane_id)
            stale = [key for key in self._latest_generation if key[0] == lane_id]
            for key in stale:
                del self._latest_generation[key]

    def pending_count(self) -> int:
        """Return queued thumbnail requests. Intended for diagnostics/tests."""
        with self._lock:
            return len(self._queue)

    def run(self) -> None:
        """Main loop — runs in a QThread. Processes one request every 20 ms."""
        while self._running:
            req: Optional[_ThumbRequest] = None
            with self._lock:
                if self._queue:
                    req = self._queue.popleft()
            if req is None:
                QThread.msleep(20)
                continue
            key = ThumbnailKey(req.source_path, req.page_index, req.rotation_deg, req.width)
            with self._lock:
                if self._latest_generation.get((req.lane_id, req.page_id)) != req.generation:
                    continue
            qimage = render_page_thumb(req.source_path, req.page_index, req.rotation_deg, req.width)
            if qimage is not None:
                self._cache.put(key, qimage)
                with self._lock:
                    if self._latest_generation.get((req.lane_id, req.page_id)) != req.generation:
                        continue
                self.thumb_ready.emit(req.lane_id, req.page_id, req.rotation_deg, qimage)
