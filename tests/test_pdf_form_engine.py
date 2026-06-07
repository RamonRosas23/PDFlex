from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz

from core.pdf_form_engine import (
    FormFillJob,
    FormFillOptions,
    PdfFormEngine,
    _checkbox_value,
    _radio_value,
)


class PdfFormEngineTests(unittest.TestCase):
    def test_detects_form_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = self._make_form_pdf(Path(tmp) / "form.pdf")

            fields = PdfFormEngine().inspect_fields(source)

            names = {field.name for field in fields}
            self.assertIn("nombre", names)
            self.assertIn("acepto", names)
            self.assertIn("tipo", names)

    def test_fills_and_flattens_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_form_pdf(root / "form.pdf")
            output = root / "out" / "form_aplanado.pdf"

            result = PdfFormEngine().run_job(
                FormFillJob(
                    pdf_path=str(source),
                    output_path=str(output),
                    values={
                        "nombre": "Juan Perez",
                        "acepto": "Yes",
                        "tipo": "Cliente",
                    },
                    options=FormFillOptions(flatten=True),
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertTrue(output.exists())
            self.assertTrue(result.flattened)
            self.assertEqual(result.filled_fields, 3)

            doc = fitz.open(output)
            try:
                self.assertFalse(bool(doc.is_form_pdf))
                self.assertEqual(list(doc[0].widgets() or []), [])
                text = "\n".join(page.get_text() for page in doc)
                self.assertIn("Juan Perez", text)
                self.assertIn("Cliente", text)
            finally:
                doc.close()

    def test_can_leave_form_editable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_form_pdf(root / "form.pdf")
            output = root / "out" / "form_editable.pdf"

            result = PdfFormEngine().run_job(
                FormFillJob(
                    pdf_path=str(source),
                    output_path=str(output),
                    values={"nombre": "Ana"},
                    options=FormFillOptions(flatten=False),
                )
            )

            self.assertTrue(result.success, result.error)
            doc = fitz.open(output)
            try:
                self.assertTrue(bool(doc.is_form_pdf))
                widgets = list(doc[0].widgets() or [])
                self.assertTrue(widgets)
                self.assertEqual(
                    next(widget for widget in widgets if widget.field_name == "nombre").field_value,
                    "Ana",
                )
            finally:
                doc.close()

    def test_pdf_without_fields_returns_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "simple.pdf")
            output = root / "out" / "simple.pdf"

            result = PdfFormEngine().run_job(
                FormFillJob(str(source), str(output), values={"nombre": "Ana"})
            )

            self.assertFalse(result.success)
            self.assertIn("formulario", result.error.lower())

    def test_button_values_accept_custom_on_states(self) -> None:
        self.assertEqual(_checkbox_value(_DummyButton("Aceptado"), "Aceptado"), "Aceptado")
        self.assertEqual(_checkbox_value(_DummyButton("Aceptado"), "si"), "Aceptado")
        self.assertEqual(_checkbox_value(_DummyButton("Aceptado"), "no"), "Off")

        self.assertEqual(_radio_value(_DummyButton("OpcionB"), "OpcionB"), "OpcionB")
        self.assertEqual(_radio_value(_DummyButton("OpcionB"), "OpcionA"), "Off")

    def test_inspect_marks_required_multiline_and_readonly_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = self._make_metadata_form_pdf(Path(tmp) / "metadata.pdf")

            fields = {field.name: field for field in PdfFormEngine().inspect_fields(source)}

            self.assertTrue(fields["comentarios"].required)
            self.assertTrue(fields["comentarios"].multiline)
            self.assertTrue(fields["comentarios"].supported)
            self.assertTrue(fields["folio"].read_only)
            self.assertFalse(fields["folio"].supported)

    @staticmethod
    def _make_form_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=360, height=240)
        page.insert_text((36, 38), "Nombre:")
        text = fitz.Widget()
        text.field_name = "nombre"
        text.field_label = "Nombre"
        text.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        text.rect = fitz.Rect(110, 22, 310, 50)
        text.field_value = ""
        page.add_widget(text)

        page.insert_text((36, 82), "Acepto:")
        check = fitz.Widget()
        check.field_name = "acepto"
        check.field_label = "Acepto"
        check.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
        check.rect = fitz.Rect(110, 68, 130, 88)
        check.field_value = False
        page.add_widget(check)

        page.insert_text((36, 126), "Tipo:")
        combo = fitz.Widget()
        combo.field_name = "tipo"
        combo.field_label = "Tipo"
        combo.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
        combo.rect = fitz.Rect(110, 108, 250, 136)
        combo.choice_values = ["Proveedor", "Cliente"]
        combo.field_value = "Proveedor"
        page.add_widget(combo)

        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _make_metadata_form_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=360, height=240)

        comments = fitz.Widget()
        comments.field_name = "comentarios"
        comments.field_label = "Comentarios"
        comments.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        comments.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE | fitz.PDF_FIELD_IS_REQUIRED
        comments.rect = fitz.Rect(90, 40, 310, 110)
        comments.field_value = ""
        page.add_widget(comments)

        folio = fitz.Widget()
        folio.field_name = "folio"
        folio.field_label = "Folio"
        folio.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        folio.field_flags = fitz.PDF_FIELD_IS_READ_ONLY
        folio.rect = fitz.Rect(90, 130, 220, 158)
        folio.field_value = "A-001"
        page.add_widget(folio)

        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _make_text_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((36, 72), "Sin formulario")
        doc.save(path)
        doc.close()
        return path


class _DummyButton:
    def __init__(self, state: str) -> None:
        self._state = state

    def on_state(self) -> str:
        return self._state


if __name__ == "__main__":
    unittest.main()
