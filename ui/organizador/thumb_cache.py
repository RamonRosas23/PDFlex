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
