from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz

from core.page_organizer_engine import (
    OrganizerJob,
    PageOrganizerEngine,
    PageRef,
)
from core.page_organizer_engine import MultiOrganizerJob, MultiOrganizerResult


class PageOrganizerEngineTests(unittest.TestCase):
    def test_reorders_duplicates_and_rotates_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_a = self._make_pdf(root / "a.pdf", ["A1", "A2"])
            pdf_b = self._make_pdf(root / "b.pdf", ["B1", "B2"])
            output = root / "out" / "organizado.pdf"

            result = PageOrganizerEngine().run_job(
                OrganizerJob(
                    pages=[
                        PageRef(str(pdf_b), 1),
                        PageRef(str(pdf_a), 0, rotation_deg=90),
                        PageRef(str(pdf_a), 0),
                    ],
                    output_path=str(output),
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.total_pages, 3)
            self.assertTrue(output.exists())

            doc = fitz.open(output)
            try:
                self.assertIn("B2", doc[0].get_text())
                self.assertIn("A1", doc[1].get_text())
                self.assertIn("A1", doc[2].get_text())
                self.assertEqual(doc[1].rotation, 90)
                self.assertEqual(doc[2].rotation, 0)
            finally:
                doc.close()

    def test_empty_job_returns_controlled_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = PageOrganizerEngine().run_job(
                OrganizerJob(pages=[], output_path=str(Path(tmp) / "out.pdf"))
            )

            self.assertFalse(result.success)
            self.assertIn("No hay paginas", result.error)

    @staticmethod
    def _make_pdf(path: Path, labels: list[str]) -> Path:
        doc = fitz.open()
        for label in labels:
            page = doc.new_page(width=300, height=200)
            page.insert_text((36, 72), label)
        doc.save(path)
        doc.close()
        return path


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

    def test_run_multi_job_cancel_stops_early(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_a = self._make_pdf(root / "a.pdf", ["A1"])
            pdf_b = self._make_pdf(root / "b.pdf", ["B1"])
            pdf_c = self._make_pdf(root / "c.pdf", ["C1"])
            out_a = root / "out" / "a.pdf"
            out_b = root / "out" / "b.pdf"
            out_c = root / "out" / "c.pdf"

            call_count = [0]

            def should_cancel():
                call_count[0] += 1
                # Cancel before the second lane starts
                return call_count[0] > 1

            job = MultiOrganizerJob(
                lanes=[
                    OrganizerJob(pages=[PageRef(str(pdf_a), 0)], output_path=str(out_a)),
                    OrganizerJob(pages=[PageRef(str(pdf_b), 0)], output_path=str(out_b)),
                    OrganizerJob(pages=[PageRef(str(pdf_c), 0)], output_path=str(out_c)),
                ],
                merge_all=False,
            )
            result = PageOrganizerEngine().run_multi_job(job, should_cancel=should_cancel)

            self.assertFalse(result.success)
            self.assertIn("cancelad", result.error.lower())
            # Only the first lane ran before cancel
            self.assertLess(len(result.results), 3)

    @staticmethod
    def _make_pdf(path: Path, labels: list[str]) -> Path:
        doc = fitz.open()
        for label in labels:
            page = doc.new_page(width=300, height=200)
            page.insert_text((36, 72), label)
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
