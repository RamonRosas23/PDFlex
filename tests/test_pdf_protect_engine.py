from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz

from core.pdf_protect_engine import (
    PdfProtectEngine,
    ProtectJob,
    ProtectOptions,
    permissions_mask,
)


class PdfProtectEngineTests(unittest.TestCase):
    def test_open_password_encrypts_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "input.pdf")
            output = root / "out" / "input_protegido.pdf"
            options = ProtectOptions(
                open_password="abrir123",
                owner_password="dueno123",
                allow_print=True,
                allow_copy=False,
                allow_modify=False,
            )

            result = PdfProtectEngine().run_job(
                ProtectJob(str(source), str(output), options)
            )

            self.assertTrue(result.success, result.error)
            self.assertTrue(output.exists())
            protected = fitz.open(output)
            try:
                self.assertTrue(protected.needs_pass)
                self.assertEqual(protected.authenticate("mal"), 0)
                self.assertGreater(protected.authenticate("abrir123"), 0)
                self.assertIn("Documento protegido", protected[0].get_text())
            finally:
                protected.close()

    def test_owner_password_can_restrict_permissions_without_open_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "input.pdf")
            output = root / "out" / "input_protegido.pdf"
            options = ProtectOptions(
                open_password="",
                owner_password="dueno123",
                allow_print=False,
                allow_copy=False,
                allow_modify=False,
            )

            result = PdfProtectEngine().run_job(
                ProtectJob(str(source), str(output), options)
            )

            self.assertTrue(result.success, result.error)
            protected = fitz.open(output)
            try:
                self.assertFalse(bool(protected.needs_pass))
                self.assertIn("Documento protegido", protected[0].get_text())
            finally:
                protected.close()

    def test_requires_some_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "input.pdf")
            output = root / "out" / "input_protegido.pdf"

            result = PdfProtectEngine().run_job(
                ProtectJob(str(source), str(output), ProtectOptions(open_password="", owner_password=""))
            )

            self.assertFalse(result.success)
            self.assertIn("contrasena", result.error.lower())

    def test_permissions_mask_uses_selected_flags(self) -> None:
        mask = permissions_mask(
            ProtectOptions(
                owner_password="dueno123",
                allow_print=True,
                allow_high_quality_print=True,
                allow_copy=True,
                allow_modify=False,
                allow_accessibility=True,
            )
        )

        self.assertTrue(mask & fitz.PDF_PERM_PRINT)
        self.assertTrue(mask & fitz.PDF_PERM_PRINT_HQ)
        self.assertTrue(mask & fitz.PDF_PERM_COPY)
        self.assertFalse(mask & fitz.PDF_PERM_MODIFY)
        self.assertTrue(mask & fitz.PDF_PERM_ACCESSIBILITY)

    @staticmethod
    def _make_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((36, 72), "Documento protegido")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
