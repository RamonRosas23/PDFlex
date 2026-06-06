"""LaneContainer — manages N DocLanes stacked vertically."""
from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path
from typing import List, Tuple

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

    layout_changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lanes: List[DocLane] = []

        self._cache = ThumbnailCache(max_size=300)
        self._worker = ThumbnailWorker(self._cache)
        self._thumb_thread = QThread(self)
        self._worker.moveToThread(self._thumb_thread)
        self._thumb_thread.started.connect(self._worker.run)
        self._thumb_thread.start()

        self._build()
        self.destroyed.connect(self._stop_worker)

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

        def _clone(ref: PageRef) -> PageRef:
            stem = Path(ref.source_path).stem
            return replace(ref, page_id=f"{stem}-{ref.page_index+1}-{uuid.uuid4().hex[:8]}")

        for ref in refs:
            dst.add_page_ref(_clone(ref))

        if not ctrl_held and src is not None:
            page_ids = {r.page_id for r in refs}
            src.remove_by_page_ids(page_ids)

    def _create_lane(self, display_name: str) -> DocLane:
        color = LANE_COLORS[len(self._lanes) % len(LANE_COLORS)]
        lane_id = uuid.uuid4().hex[:12]
        lane = DocLane(lane_id, display_name, color, self._cache, self._worker)
        lane.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lane.pages_changed.connect(lambda _: self.layout_changed.emit())
        lane.lane_delete_requested.connect(self.remove_lane)
        lane.reorder_requested.connect(self.move_lane)
        lane.cross_lane_drop_received.connect(self._on_cross_lane_drop)

        self._lanes.append(lane)
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
        for lane in self._lanes:
            self._container_layout.removeWidget(lane)
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
