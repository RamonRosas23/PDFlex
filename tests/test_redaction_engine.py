from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz

from core.redaction_engine import (
    RedactionEngine,
    RedactionJob,
    RedactionRect,
)


class RedactionEngineTests(unittest.TestCase):
    def test_redaction_removes_text_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "input.pdf")
            output = root / "out" / "input_redactado.pdf"

            doc = fitz.open(source)
            try:
                secret_rect = doc[0].search_for("SECRETO")[0]
                rect = RedactionRect.from_page_rect(
                    0,
                    secret_rect + (-2, -2, 2, 2),
                    doc[0].rect.width,
                    doc[0].rect.height,
                )
            finally:
                doc.close()

            result = RedactionEngine().run_job(
                RedactionJob(str(source), str(output), [rect])
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.redaction_count, 1)
            self.assertTrue(output.exists())

            redacted = fitz.open(output)
            try:
                text = redacted[0].get_text()
                self.assertNotIn("SECRETO", text)
                self.assertIn("PUBLICO", text)
            finally:
                redacted.close()

    def test_requires_at_least_one_rect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "input.pdf")
            output = root / "out" / "input_redactado.pdf"

            result = RedactionEngine().run_job(
                RedactionJob(str(source), str(output), [])
            )

            self.assertFalse(result.success)
            self.assertIn("zona", result.error.lower())

    def test_rotated_page_uses_display_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "rotated.pdf", rotation=90)
            output = root / "out" / "rotated_redactado.pdf"

            doc = fitz.open(source)
            try:
                page = doc[0]
                native_rect = page.search_for("SECRETO")[0] + (-2, -2, 2, 2)
                display_rect = self._native_to_display_rect(page, native_rect)
                rect = RedactionRect.from_page_rect(
                    0,
                    display_rect,
                    page.rect.width,
                    page.rect.height,
                )
            finally:
                doc.close()

            result = RedactionEngine().run_job(
                RedactionJob(str(source), str(output), [rect])
            )

            self.assertTrue(result.success, result.error)
            redacted = fitz.open(output)
            try:
                text = redacted[0].get_text()
                self.assertNotIn("SECRETO", text)
                self.assertIn("PUBLICO", text)
            finally:
                redacted.close()

    @staticmethod
    def _make_pdf(path: Path, rotation: int = 0) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=420, height=260)
        page.insert_text((48, 96), "SECRETO")
        page.insert_text((180, 96), "PUBLICO")
        if rotation:
            page.set_rotation(rotation)
        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _native_to_display_rect(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
        if not int(page.rotation) % 360:
            return rect
        points = [
            fitz.Point(rect.x0, rect.y0) * page.rotation_matrix,
            fitz.Point(rect.x1, rect.y0) * page.rotation_matrix,
            fitz.Point(rect.x0, rect.y1) * page.rotation_matrix,
            fitz.Point(rect.x1, rect.y1) * page.rotation_matrix,
        ]
        return fitz.Rect(
            min(point.x for point in points),
            min(point.y for point in points),
            max(point.x for point in points),
            max(point.y for point in points),
        )


if __name__ == "__main__":
    unittest.main()
