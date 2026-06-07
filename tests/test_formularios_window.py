from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PyQt6.QtWidgets import QApplication, QComboBox, QLineEdit, QPlainTextEdit

from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from ui.formularios.window import FormulariosWindow


class FormulariosWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_loads_fields_and_builds_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_form_pdf(Path(tmp) / "form.pdf")
            window = FormulariosWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                window._load_fields()

                self.assertEqual(len(window._fields), 2)
                name_control = window._field_controls["nombre"]
                check_control = window._field_controls["acepto"]
                self.assertIsInstance(name_control, QLineEdit)
                self.assertIsInstance(check_control, QComboBox)
                name_control.setText("Maria")
                check_control.setCurrentIndex(1)

                jobs = window._build_jobs()

                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].pdf_path, str(pdf_path))
                self.assertEqual(jobs[0].values["nombre"], "Maria")
                self.assertNotEqual(jobs[0].values["acepto"], "Off")
                self.assertTrue(jobs[0].options.flatten)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_forms_for_pdfs(self) -> None:
        tool = get_tool("formularios")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Formularios PDF")
        self.assertIn(".pdf", tool.input_extensions)

    def test_required_multiline_field_uses_large_editor_and_blocks_empty_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_required_multiline_form_pdf(Path(tmp) / "form.pdf")
            window = FormulariosWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                window._load_fields()

                comments = window._field_controls["comentarios"]
                self.assertIsInstance(comments, QPlainTextEdit)
                self.assertIn("requeridos", window._validate_ready())

                comments.setPlainText("Revision completada")
                self.assertIsNone(window._validate_ready())
            finally:
                window.deleteLater()
                self.app.processEvents()

    @staticmethod
    def _make_form_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        text = fitz.Widget()
        text.field_name = "nombre"
        text.field_label = "Nombre"
        text.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        text.rect = fitz.Rect(60, 40, 220, 65)
        text.field_value = ""
        page.add_widget(text)

        check = fitz.Widget()
        check.field_name = "acepto"
        check.field_label = "Acepto"
        check.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
        check.rect = fitz.Rect(60, 90, 80, 110)
        check.field_value = False
        page.add_widget(check)

        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _make_required_multiline_form_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=320, height=220)
        comments = fitz.Widget()
        comments.field_name = "comentarios"
        comments.field_label = "Comentarios"
        comments.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        comments.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE | fitz.PDF_FIELD_IS_REQUIRED
        comments.rect = fitz.Rect(50, 40, 270, 125)
        comments.field_value = ""
        page.add_widget(comments)

        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
