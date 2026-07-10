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

    thumb_ready = Signal(str, str, object)  # lane_id, page_id, QImage (convert to QPixmap in GUI thread)

    def __init__(self, cache: ThumbnailCache, parent=None) -> None:
        super().__init__(parent)
        self._cache = cache
        self._queue: deque[_ThumbRequest] = deque()
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
            # Re-check after acquiring queue lock — background run() may have filled cache
            cached = self._cache.get(key)
            if cached is not None:
                self.thumb_ready.emit(lane_id, page_id, cached)
                return
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
                    req = self._queue.popleft()
            if req is None:
                QThread.msleep(20)
                continue
            key = ThumbnailKey(req.source_path, req.page_index, req.rotation_deg, req.width)
            qimage = render_page_thumb(req.source_path, req.page_index, req.rotation_deg, req.width)
            if qimage is not None:
                self._cache.put(key, qimage)
                self.thumb_ready.emit(req.lane_id, req.page_id, qimage)
