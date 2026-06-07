from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz

from core.document_classifier_engine import (
    ClassifierConfig,
    ClassifierJob,
    DEFAULT_RULES_TEXT,
    DocumentClassifierEngine,
    detect_fields,
    parse_classification_rules,
    render_filename_template,
)


class DocumentClassifierEngineTests(unittest.TestCase):
    def test_detects_fields_and_renames_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_invoice_pdf(root / "factura.pdf")
            out_dir = root / "out"
            config = ClassifierConfig(
                template="{tipo}_{cliente}_{rfc}_{fecha}_{folio}",
                rules_text=DEFAULT_RULES_TEXT,
                max_pages=1,
                use_ocr_fallback=False,
                add_tool_suffix=False,
            )

            result = DocumentClassifierEngine().run_job(
                ClassifierJob(str(source), str(out_dir), config)
            )

            self.assertTrue(result.success, result.error)
            self.assertTrue(Path(result.output_path).exists())
            name = Path(result.output_path).name
            self.assertIn("Factura", name)
            self.assertIn("ACME_SA_DE_CV", name)
            self.assertIn("AAA010101AAA", name)
            self.assertIn("2026-06-05", name)
            self.assertIn("F-12345", name)
            self.assertEqual(result.fields["tipo"], "Factura")

    def test_rule_parser_and_template_render(self) -> None:
        rules = parse_classification_rules("Orden=orden de compra, proveedor\n")
        fields = detect_fields(
            "Orden de compra\nProveedor: Norte SA\nFecha: 2026-06-05",
            "origen",
            rules,
        )

        self.assertEqual(fields["tipo"], "Orden")
        self.assertEqual(fields["fecha"], "2026-06-05")
        self.assertEqual(
            render_filename_template("{tipo}_{fecha}_{original}", fields, ClassifierConfig()),
            "Orden_2026-06-05_origen.pdf",
        )

    @staticmethod
    def _make_invoice_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=420, height=260)
        page.insert_text(
            (36, 54),
            "FACTURA\n"
            "Cliente: ACME SA DE CV\n"
            "RFC: AAA010101AAA\n"
            "Fecha: 05/06/2026\n"
            "Folio: F-12345\n"
            "Subtotal 100 Total 116 CFDI",
        )
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
