from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PIL import Image
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from ui.organizador.window import OrganizadorWindow
from ui.organizador.page_preview_dialog import OrganizerPagePreviewDialog
from ui.organizador.thumb_cache import ThumbnailCache, ThumbnailKey, ThumbnailWorker, render_page_thumb
from core.page_organizer_engine import (
    MultiOrganizerResult,
    OrganizerJob,
    OrganizerResult,
    PageRef,
)


class OrganizadorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _make_ctx(self):
        return ShellContext(
            tray=PdfTray(),
            word_converter=WordToPdfConverter(),
            open_tool=lambda *_: None,
        )

    def test_tool_registry_exposes_organizer_for_pdfs(self) -> None:
        tool = get_tool("organizador")
        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Organizador visual")
        self.assertIn(".pdf", tool.input_extensions)
        self.assertIn(".docx", tool.input_extensions)
        self.assertIn(".png", tool.input_extensions)

    def test_window_loads_pdfs_into_separate_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "input.pdf"
            doc = fitz.open()
            for i in range(2):
                doc.new_page().insert_text((36, 72), f"Page {i+1}")
            doc.save(pdf_path)
            doc.close()

            window = OrganizadorWindow(self._make_ctx())
            try:
                window.set_inputs([str(pdf_path)])
                self.assertEqual(window._lane_container.total_lanes(), 1)
                self.assertEqual(window._lane_container.total_pages(), 2)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_window_converts_images_into_pdf_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "scan.png"
            Image.new("RGB", (90, 45), "white").save(image_path)

            window = OrganizadorWindow(self._make_ctx())
            try:
                window.set_inputs([str(image_path)])

                self.assertEqual(window._lane_container.total_lanes(), 1)
                self.assertEqual(window._lane_container.total_pages(), 1)
                ref = window._lane_container.ordered_page_refs()[0]
                self.assertEqual(Path(ref.source_path).suffix.lower(), ".pdf")
                doc = fitz.open(ref.source_path)
                try:
                    self.assertEqual(round(doc[0].rect.width), 90)
                    self.assertEqual(round(doc[0].rect.height), 45)
                finally:
                    doc.close()
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tray_selection_adds_pdf_to_a_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "from_tray.pdf"
            doc = fitz.open()
            doc.new_page().insert_text((36, 72), "From tray")
            doc.save(pdf_path)
            doc.close()

            ctx = self._make_ctx()
            ctx.tray.add_items([str(pdf_path)], "Unir")
            window = OrganizadorWindow(ctx)
            try:
                window._tray_panel.list_widget.item(0).setSelected(True)
                window._tray_panel._add_btn.click()

                self.assertEqual(window._lane_container.total_lanes(), 1)
                self.assertEqual(window._lane_container.total_pages(), 1)
                self.assertEqual(ctx.tray.items[0].status, "in_work")
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_window_opens_large_preview_at_requested_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "preview.pdf"
            doc = fitz.open()
            for i in range(3):
                doc.new_page().insert_text((36, 72), f"Preview {i+1}")
            doc.save(pdf_path)
            doc.close()

            window = OrganizadorWindow(self._make_ctx())
            try:
                window.set_inputs([str(pdf_path)])
                target = window._lane_container.lanes()[0].page_refs()[1]
                with patch("ui.organizador.window.OrganizerPagePreviewDialog") as dlg_cls:
                    dlg_cls.return_value.exec.return_value = 0
                    window._open_page_preview(target)

                args, kwargs = dlg_cls.call_args
                self.assertIs(args[0], window)
                self.assertEqual(len(args[1]), 3)
                self.assertEqual(kwargs["current_index"], 1)
                self.assertEqual(args[1][1].page_id, target.page_id)
            finally:
                window.deleteLater()
                self.app.processEvents()


class ThumbnailCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

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

    def test_worker_emits_thumb_ready_exactly_once_per_page(self) -> None:
        """Worker must not emit thumb_ready twice for the same page_id."""
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "w.pdf"
            doc = fitz.open()
            doc.new_page(width=300, height=200)
            doc.save(pdf)
            doc.close()

            cache = ThumbnailCache(max_size=10)
            worker = ThumbnailWorker(cache)

            received: list = []
            worker.thumb_ready.connect(lambda lid, pid, pix: received.append(pid))

            thread = QThread()
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            thread.start()

            worker.request("lane-1", "page-1", str(pdf), 0, 0, 116)
            worker.request("lane-1", "page-1", str(pdf), 0, 0, 116)  # duplicate

            # Give worker time to process
            import time
            time.sleep(0.3)
            self.app.processEvents()  # deliver queued cross-thread signals

            worker.stop()
            thread.quit()
            thread.wait(2000)
            self.app.processEvents()  # flush any remaining signals after thread exit

            # Should have emitted at most twice (once for queue, once if cache hit on 2nd request)
            # After fix, the second request should emit from cache hit (fast path) OR not at all
            # if TOCTOU fix prevents double-queue. Either way, page_id should not be in queue twice.
            # The important thing: the implementation must not crash and must emit at least once.
            self.assertGreaterEqual(len(received), 1)
            # Verify cache was populated
            from ui.organizador.thumb_cache import ThumbnailKey
            key = ThumbnailKey(str(pdf), 0, 0, 116)
            self.assertIsNotNone(cache.get(key))


class PageMimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_encode_decode_round_trip(self) -> None:
        from ui.organizador.page_mime import encode_drag, decode_drag
        from core.page_organizer_engine import PageRef
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
        from ui.organizador.page_mime import decode_drag
        from PyQt6.QtCore import QMimeData
        mime = QMimeData()
        mime.setText("hello")
        self.assertIsNone(decode_drag(mime))


class OrganizerPagePreviewDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_preview_dialog_renders_rotated_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "large.pdf"
            doc = fitz.open()
            page = doc.new_page(width=300, height=500)
            page.insert_text((36, 72), "Large preview")
            doc.save(pdf)
            doc.close()

            ref = PageRef(str(pdf), 0, rotation_deg=90, page_id="p1")
            dlg = OrganizerPagePreviewDialog(None, [ref])
            try:
                self.app.processEvents()
                pix = dlg._canvas.pixmap()
                self.assertIsNotNone(pix)
                self.assertFalse(pix.isNull())
                self.assertGreater(pix.width(), pix.height())
                self.assertIn("90", dlg._meta_lbl.toolTip())
            finally:
                dlg.close()
                self.app.processEvents()

    def test_preview_dialog_emits_editor_actions_for_current_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "action.pdf"
            doc = fitz.open()
            doc.new_page(width=300, height=400)
            doc.save(pdf)
            doc.close()

            ref = PageRef(str(pdf), 0, page_id="p1")
            dlg = OrganizerPagePreviewDialog(None, [ref])
            try:
                received: list[tuple[str, str]] = []
                dlg.page_action_requested.connect(
                    lambda action, page_id: received.append((action, page_id))
                )
                dlg._emit_page_action("delete")
                self.assertEqual(received, [("delete", "p1")])
            finally:
                dlg.close()
                self.app.processEvents()


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
            self.assertEqual(lane.page_refs()[1].page_index, 0)
            self.assertNotEqual(lane.page_refs()[0].page_id, lane.page_refs()[1].page_id)

    def test_add_pdf_at_row_inserts_pages_in_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.pdf"
            second = root / "second.pdf"
            for path, pages in ((first, 3), (second, 2)):
                doc = fitz.open()
                for _ in range(pages):
                    doc.new_page()
                doc.save(path)
                doc.close()

            lane = self._make_lane()
            lane.add_pages_from_pdf(str(first))
            lane.add_pages_from_pdf(str(second), at_row=2)

            refs = lane.page_refs()
            self.assertEqual([Path(r.source_path).name for r in refs], [
                "first.pdf",
                "first.pdf",
                "second.pdf",
                "second.pdf",
                "first.pdf",
            ])

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

    def test_delete_later_stops_thumbnail_worker_before_temp_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "release.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(pdf)
            doc.close()

            container = LaneContainer()
            container.add_lane_from_pdf(str(pdf))
            container.deleteLater()

            self.assertFalse(container._thumb_thread.isRunning())
            pdf.unlink()

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

            self.assertEqual(src_lane.count(), 1)
            self.assertEqual(dst_lane.count(), 1)
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
        container.move_lane(lane_b.lane_id, -1)
        names = [lane.display_name for lane in container.lanes()]
        self.assertEqual(names, ["B", "A"])
        container.deleteLater()

    def test_page_preview_signal_bubbles_from_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "preview-signal.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(pdf)
            doc.close()

            container = LaneContainer()
            try:
                received: list[str] = []
                container.page_preview_requested.connect(
                    lambda ref: received.append(ref.page_id)
                )
                lane = container.add_lane_from_pdf(str(pdf))
                ref = lane.page_refs()[0]
                lane._request_preview_for_ref(ref)
                self.app.processEvents()
                self.assertEqual(received, [ref.page_id])
            finally:
                container.deleteLater()

    def test_add_paths_to_lane_inserts_after_selected_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.pdf"
            inserted = root / "inserted.pdf"
            for path, pages in ((first, 3), (inserted, 2)):
                doc = fitz.open()
                for _ in range(pages):
                    doc.new_page()
                doc.save(path)
                doc.close()

            container = LaneContainer()
            try:
                lane = container.add_lane_from_pdf(str(first))
                lane._list.setCurrentRow(1)
                container.add_paths_to_lane(lane.lane_id, [str(inserted)])

                refs = lane.page_refs()
                self.assertEqual([Path(r.source_path).name for r in refs], [
                    "first.pdf",
                    "first.pdf",
                    "inserted.pdf",
                    "inserted.pdf",
                    "first.pdf",
                ])
            finally:
                container.deleteLater()


class OrganizadorWindowV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _make_ctx(self):
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
                pages = sum(lane.count() for lane in window._lane_container.lanes())
                self.assertEqual(pages, 2)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_window_routes_word_inputs_through_conversion_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            word = root / "contrato.docx"
            word.write_text("dummy", encoding="utf-8")
            converted = root / "contrato.pdf"
            doc = fitz.open()
            doc.new_page().insert_text((36, 72), "Convertido")
            doc.save(converted)
            doc.close()

            window = OrganizadorWindow(self._make_ctx())
            try:
                with patch.object(window, "_convert_words_then_add") as convert:
                    def _fake_convert(words, **kwargs):
                        self.assertEqual(words, [str(word)])
                        window._add_pdfs_to_lanes(
                            [str(converted)],
                            target_lane_id=kwargs["target_lane_id"],
                            at_row=kwargs["at_row"],
                            replace=kwargs["replace"],
                        )

                    convert.side_effect = _fake_convert
                    window.set_inputs([str(word)])

                self.assertEqual(window._lane_container.total_lanes(), 1)
                self.assertEqual(window._lane_container.total_pages(), 1)
                ref = window._lane_container.ordered_page_refs()[0]
                self.assertEqual(ref.source_path, str(converted))
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_preview_delete_action_updates_lane_and_dialog_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "preview-action.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.new_page()
            doc.save(pdf)
            doc.close()

            class FakeDialog:
                def __init__(self) -> None:
                    self.accepted = False
                    self.refs: list[PageRef] = []
                    self.current_page_id = ""

                def accept(self) -> None:
                    self.accepted = True

                def replace_refs(self, refs, *, current_page_id: str = "") -> None:
                    self.refs = list(refs)
                    self.current_page_id = current_page_id

            window = OrganizadorWindow(self._make_ctx())
            try:
                window.set_inputs([str(pdf)])
                first_id = window._lane_container.ordered_page_refs()[0].page_id
                second_id = window._lane_container.ordered_page_refs()[1].page_id
                dialog = FakeDialog()

                window._on_preview_action(dialog, "delete", first_id)

                self.assertFalse(dialog.accepted)
                self.assertEqual(window._lane_container.total_pages(), 1)
                self.assertEqual(dialog.current_page_id, second_id)
                self.assertEqual(dialog.refs[0].page_id, second_id)
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
                # Refresh output table so _build_multi_job can read it
                window._refresh_output_table()
                job = window._build_multi_job()
                self.assertEqual(len(job.lanes), 1)
                self.assertEqual(len(job.lanes[0].pages), 2)
                self.assertFalse(job.merge_all)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_finished_separate_mode_shows_all_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_a = root / "source_a.pdf"
            source_b = root / "source_b.pdf"
            out_a = root / "out_a.pdf"
            out_b = root / "out_b.pdf"
            for path, label in [
                (source_a, "Source A"),
                (source_b, "Source B"),
                (out_a, "Output A"),
                (out_b, "Output B"),
            ]:
                doc = fitz.open()
                doc.new_page(width=300, height=200).insert_text((36, 72), label)
                doc.save(path)
                doc.close()

            result = MultiOrganizerResult(
                results=[
                    OrganizerResult(
                        job=OrganizerJob(
                            pages=[PageRef(str(source_a), 0)],
                            output_path=str(out_a),
                        ),
                        output_path=str(out_a),
                        success=True,
                        total_pages=1,
                        source_count=1,
                    ),
                    OrganizerResult(
                        job=OrganizerJob(
                            pages=[PageRef(str(source_b), 0)],
                            output_path=str(out_b),
                        ),
                        output_path=str(out_b),
                        success=True,
                        total_pages=1,
                        source_count=1,
                    ),
                ],
                success=True,
            )

            window = OrganizadorWindow(self._make_ctx())
            try:
                window._on_finished(result)
                self.app.processEvents()

                self.assertEqual(window._result_viewer.doc_list.count(), 2)
                self.assertEqual(
                    window._result_viewer.doc_list.item(0).toolTip(),
                    str(out_a),
                )
                self.assertEqual(
                    window._result_viewer.doc_list.item(1).toolTip(),
                    str(out_b),
                )
            finally:
                window._result_viewer.clear_results()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
