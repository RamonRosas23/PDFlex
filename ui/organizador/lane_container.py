"""LaneContainer — manages N DocLanes stacked vertically with undo support."""
from __future__ import annotations

import uuid
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import List, Tuple

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from ui.common.tool_scaffold import RunnerThread
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from core.page_organizer_engine import PageRef
from core.media_conversion import DOCUMENT_IMPORT_FILTER
from ui.common.file_dialogs import get_open_file_names
from ui.common.icons import set_button_icon
from ui.organizador.lane_widget import LANE_COLORS, DocLane
from ui.organizador.thumb_cache import ThumbnailCache, ThumbnailWorker

PDF_WORD_FILTER = DOCUMENT_IMPORT_FILTER
_MAX_UNDO = 50


class LaneContainer(QWidget):
    """Scroll vertical con N DocLanes, portapapeles y pila de deshacer."""

    layout_changed = pyqtSignal()
    page_preview_requested = pyqtSignal(object)
    files_add_requested = pyqtSignal(list, object, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lanes: List[DocLane] = []
        self._undo_stack: deque = deque(maxlen=_MAX_UNDO)

        self._cache = ThumbnailCache(max_size=300)
        self._worker = ThumbnailWorker(self._cache)
        self._thumb_thread = RunnerThread(self._worker.run, self)
        self._worker_stopped = False
        self._thumb_thread.start()

        self._build()
        self.destroyed.connect(self._stop_worker)

    # ── Construcción ──────────────────────────────────────────────────────

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

        pdf_btn = QPushButton("＋ Agregar archivos")
        pdf_btn.setProperty("class", "Primary")
        set_button_icon(pdf_btn, "plus", size=13)
        pdf_btn.clicked.connect(self._on_add_pdfs)
        h.addWidget(pdf_btn)
        h.addStretch()
        return bar

    # ── API pública ───────────────────────────────────────────────────────

    def lanes(self) -> List[DocLane]:
        return list(self._lanes)

    def add_lane_from_pdf(self, path: str) -> DocLane:
        self._take_snapshot()
        name = Path(path).name
        lane = self._create_lane(name)
        lane.add_pages_from_pdf(path)
        return lane

    def add_blank_lane(self, name: str = "") -> DocLane:
        self._take_snapshot()
        display = name or f"Documento {len(self._lanes) + 1}"
        return self._create_lane(display)

    def remove_lane(self, lane_id: str) -> None:
        idx = self._index_of(lane_id)
        if idx < 0:
            return
        self._take_snapshot()
        lane = self._lanes.pop(idx)
        self._container_layout.removeWidget(lane)
        lane.teardown()
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
        self._take_snapshot()
        self._lanes.insert(new_idx, self._lanes.pop(idx))
        self._rebuild_layout()
        self.layout_changed.emit()

    def add_paths(self, paths: List[str]) -> None:
        valid = [p for p in paths if p.lower().endswith(".pdf") and Path(p).is_file()]
        if not valid:
            return
        self._take_snapshot()
        for path in valid:
            lane = self._create_lane(Path(path).name)
            lane.add_pages_from_pdf(path, _record=False)

    def add_paths_to_lane(
        self,
        lane_id: str,
        paths: List[str],
        *,
        at_row: int = -1,
    ) -> list[str]:
        lane = next((l for l in self._lanes if l.lane_id == lane_id), None)
        valid = [p for p in paths if p.lower().endswith(".pdf") and Path(p).is_file()]
        if lane is None or not valid:
            return []

        self._take_snapshot()
        insert_at = at_row if at_row >= 0 else lane.insert_row_after_selection()
        inserted_ids: list[str] = []
        for path in valid:
            ids = lane.add_pages_from_pdf(
                path,
                at_row=insert_at,
                _record=False,
                select_new=False,
            )
            inserted_ids.extend(ids)
            insert_at += len(ids)
        if inserted_ids:
            lane.select_page_id(inserted_ids[-1])
        self.layout_changed.emit()
        return inserted_ids

    def all_lane_states(self) -> List[Tuple[str, str, List[PageRef]]]:
        return [(lane.lane_id, lane.display_name, lane.page_refs()) for lane in self._lanes]

    def ordered_page_refs(self) -> List[PageRef]:
        refs: List[PageRef] = []
        for lane in self._lanes:
            refs.extend(lane.page_refs())
        return refs

    def total_pages(self) -> int:
        return sum(lane.count() for lane in self._lanes)

    def total_lanes(self) -> int:
        return len(self._lanes)

    def clear(self) -> None:
        self._take_snapshot()
        for lane in list(self._lanes):
            self._container_layout.removeWidget(lane)
            lane.teardown()
            lane.deleteLater()
        self._lanes.clear()
        self.layout_changed.emit()

    def apply_page_action(self, page_id: str, action: str) -> str:
        lane = self._lane_for_page_id(page_id)
        if lane is None:
            return ""
        if action == "rotate_cw":
            lane.rotate_page_id(page_id, 90)
            return page_id
        if action == "rotate_ccw":
            lane.rotate_page_id(page_id, -90)
            return page_id
        if action == "duplicate":
            return lane.duplicate_page_id(page_id) or page_id
        if action == "delete":
            row = lane.row_for_page_id(page_id)
            next_id = lane.page_id_at_row(row + 1) or lane.page_id_at_row(row - 1)
            lane.remove_page_id(page_id)
            return next_id
        if action == "trim_lane":
            lane.keep_only_page_id(page_id)
            return page_id
        return page_id

    # ── Undo ──────────────────────────────────────────────────────────────

    def _take_snapshot(self) -> None:
        """Captura estado completo para permitir deshacer."""
        snapshot = [
            (lane.lane_id, lane.display_name, list(lane.page_refs()))
            for lane in self._lanes
        ]
        self._undo_stack.append(snapshot)

    def undo(self) -> None:
        """Restaura el estado anterior de la pila de deshacer."""
        if not self._undo_stack:
            return
        # Recordar qué lane tenía foco para restaurarlo después
        focused_id: str | None = None
        for lane in self._lanes:
            if lane._list.hasFocus():
                focused_id = lane.lane_id
                break
        snapshot = self._undo_stack.pop()
        self._restore_snapshot(snapshot, focused_id)

    def _restore_snapshot(self, snapshot: list, restore_focus_id: str | None = None) -> None:
        """Reconstruye lanes desde un snapshot guardado."""
        for lane in list(self._lanes):
            lane.set_before_mutation_cb(None)
            self._container_layout.removeWidget(lane)
            lane.teardown()
            lane.deleteLater()
        self._lanes.clear()

        for (lane_id, name, refs) in snapshot:
            lane = self._create_lane_with_id(lane_id, name)
            lane.restore_refs(refs)

        self._refresh_siblings()
        self.layout_changed.emit()

        # Restaurar foco al lane que lo tenía antes del undo (o al primero)
        if self._lanes:
            target = next(
                (l for l in self._lanes if l.lane_id == restore_focus_id),
                self._lanes[0],
            )
            target._list.setFocus()

    # ── Cross-lane drag coordinator ───────────────────────────────────────

    def _on_cross_lane_drop(
        self,
        src_lane_id: str,
        dst_lane_id: str,
        refs: List[PageRef],
        ctrl_held: bool,
        at_row: int = -1,
    ) -> None:
        dst = next((l for l in self._lanes if l.lane_id == dst_lane_id), None)
        src = next((l for l in self._lanes if l.lane_id == src_lane_id), None)
        if dst is None:
            return

        self._take_snapshot()

        def _clone(ref: PageRef) -> PageRef:
            stem = Path(ref.source_path).stem
            return replace(ref, page_id=f"{stem}-{ref.page_index+1}-{uuid.uuid4().hex[:8]}")

        for i, ref in enumerate(refs):
            cloned = _clone(ref)
            insert_pos = None if at_row < 0 else (at_row + i)
            dst.add_page_ref(cloned, at_row=insert_pos)

        if not ctrl_held and src is not None:
            page_ids = {r.page_id for r in refs}
            src.remove_by_page_ids(page_ids, _record=False)

    # ── Helpers de creación ───────────────────────────────────────────────

    def _create_lane(self, display_name: str) -> DocLane:
        lane_id = uuid.uuid4().hex[:12]
        return self._create_lane_with_id(lane_id, display_name)

    def _create_lane_with_id(self, lane_id: str, display_name: str) -> DocLane:
        color = LANE_COLORS[len(self._lanes) % len(LANE_COLORS)]
        lane = DocLane(lane_id, display_name, color, self._cache, self._worker)
        lane.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lane.pages_changed.connect(lambda _: self.layout_changed.emit())
        lane.lane_delete_requested.connect(self.remove_lane)
        lane.reorder_requested.connect(self.move_lane)
        lane.cross_lane_drop_received.connect(self._on_cross_lane_drop)
        lane.page_preview_requested.connect(self.page_preview_requested)
        lane.files_add_requested.connect(self._on_lane_files_add_requested)
        lane.set_before_mutation_cb(self._take_snapshot)

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

    def _lane_for_page_id(self, page_id: str) -> DocLane | None:
        for lane in self._lanes:
            if lane.row_for_page_id(page_id) >= 0:
                return lane
        return None

    def _on_lane_files_add_requested(
        self,
        lane_id: str,
        paths: List[str],
        at_row: int,
    ) -> None:
        self.files_add_requested.emit(paths, lane_id, at_row)

    # ── Botones del bottom bar ────────────────────────────────────────────

    def _on_add_blank(self) -> None:
        self.add_blank_lane()

    def _on_add_pdfs(self) -> None:
        files, _ = get_open_file_names(
            self.window(),
            "Agregar PDF, Word o imágenes",
            "",
            PDF_WORD_FILTER,
        )
        if files:
            self.files_add_requested.emit(files, None, -1)

    def _stop_worker(self) -> None:
        if self._worker_stopped:
            return
        self._worker_stopped = True
        self._worker.stop()
        if self._thumb_thread.isRunning():
            self._thumb_thread.wait(2000)

    def deleteLater(self) -> None:
        """Detiene miniaturas antes de diferir la destrucción del widget."""
        self._stop_worker()
        super().deleteLater()
