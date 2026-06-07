from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PyQt6.QtWidgets import QApplication

from core.pdf_protect_engine import PdfProtectEngine, ProtectJob, ProtectOptions
from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from ui.common.pdf_viewer import GenericPdfViewer
from ui.protector.window import ProtectorWindow


class ProtectorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_loads_pdf_and_builds_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp) / "input.pdf")
            window = ProtectorWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window._docs_card.add_paths([str(pdf_path)])
                window._open_pw_edit.setText("abrir123")
                window._owner_pw_edit.setText("dueno123")
                window._allow_copy_chk.setChecked(True)

                jobs = window._build_jobs()

                self.assertEqual(window._docs_card.count(), 1)
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].options.open_password, "abrir123")
                self.assertEqual(jobs[0].options.owner_password, "dueno123")
                self.assertTrue(jobs[0].options.allow_copy)
                self.assertTrue(jobs[0].output_path.endswith(".pdf"))
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_result_viewer_authenticates_protected_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "input.pdf")
            output = root / "out" / "input_protegido.pdf"
            result = PdfProtectEngine().run_job(
                ProtectJob(
                    str(source),
                    str(output),
                    ProtectOptions(open_password="abrir123", owner_password="dueno123"),
                )
            )
            self.assertTrue(result.success, result.error)

            viewer = GenericPdfViewer("Protegidos")
            try:
                viewer.set_results([result])
                self.app.processEvents()

                self.assertIsNotNone(viewer._current_doc)
                self.assertIn("Documento protegido", viewer._current_doc[0].get_text())
            finally:
                viewer.clear_results()
                viewer.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_protector_for_pdfs(self) -> None:
        tool = get_tool("protector")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Proteger PDF")
        self.assertIn(".pdf", tool.input_extensions)

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
