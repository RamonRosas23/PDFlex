from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pikepdf
from reportlab.pdfgen.canvas import Canvas

from core.pdf_backend import PdfRenderDocument
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
            with self.assertRaises(pikepdf.PasswordError):
                pikepdf.Pdf.open(output, password="mal")
            with pikepdf.Pdf.open(output, password="abrir123") as encrypted:
                self.assertTrue(encrypted.is_encrypted)
                self.assertEqual(encrypted.encryption.R, 6)
                self.assertEqual(encrypted.encryption.bits, 256)
                self.assertTrue(encrypted.allow.print_lowres)
                self.assertFalse(encrypted.allow.extract)
                self.assertFalse(encrypted.allow.modify_other)
            with PdfRenderDocument(output, password="abrir123") as protected:
                self.assertIn("Documento protegido", protected.extract_text(0))

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
            with PdfRenderDocument(output) as protected:
                self.assertIn("Documento protegido", protected.extract_text(0))

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
        permissions = permissions_mask(
            ProtectOptions(
                owner_password="dueno123",
                allow_print=True,
                allow_high_quality_print=True,
                allow_copy=True,
                allow_modify=False,
                allow_accessibility=True,
            )
        )

        self.assertTrue(permissions.print_lowres)
        self.assertTrue(permissions.print_highres)
        self.assertTrue(permissions.extract)
        self.assertFalse(permissions.modify_other)
        self.assertTrue(permissions.accessibility)

    @staticmethod
    def _make_pdf(path: Path) -> Path:
        canvas = Canvas(str(path), pagesize=(300, 200))
        canvas.drawString(36, 128, "Documento protegido")
        canvas.showPage()
        canvas.save()
        return path


if __name__ == "__main__":
    unittest.main()
