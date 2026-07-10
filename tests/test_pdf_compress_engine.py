from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import core.pdf_compress_engine as compress_engine
from core.pdf_compress_engine import (
    CompressJob,
    CompressOptions,
    PdfCompressEngine,
    compress_job_to_dict,
    format_bytes,
    profile_for,
)
from core.pdf_compress_process import doc_rewrite_main, page_rewrite_main, run_request
from core.pdf_page_rules import PageCompressionRule


class PdfCompressEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_find_qpdf = compress_engine._find_qpdf
        self._original_find_ghostscript = compress_engine._find_ghostscript
        compress_engine._find_qpdf = lambda: None
        compress_engine._find_ghostscript = lambda: None

    def tearDown(self) -> None:
        compress_engine._find_qpdf = self._original_find_qpdf
        compress_engine._find_ghostscript = self._original_find_ghostscript

    def test_email_profile_reduces_image_heavy_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_image_pdf(root / "scan.pdf")
            output = root / "out" / "scan_comprimido.pdf"

            result = PdfCompressEngine().run_job(
                CompressJob(
                    pdf_path=str(source),
                    output_path=str(output),
                    profile_id="email",
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertTrue(output.exists())
            self.assertLess(result.output_bytes, result.input_bytes)
            self.assertGreater(result.reduction_pct, 20.0)
            self.assertIn("menos", result.meta_text)
            self.assertEqual(result.strategy, "imagenes optimizadas")
            self.assertGreater(result.validation_pages, 0)

    def test_small_pdf_does_not_grow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "simple.pdf")
            output = root / "out" / "simple_comprimido.pdf"

            result = PdfCompressEngine().run_job(
                CompressJob(
                    pdf_path=str(source),
                    output_path=str(output),
                    profile_id="balanced",
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertTrue(output.exists())
            self.assertLessEqual(result.output_bytes, result.input_bytes)

    def test_refuses_to_overwrite_source_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = self._make_text_pdf(Path(tmp) / "simple.pdf")

            result = PdfCompressEngine().run_job(
                CompressJob(
                    pdf_path=str(source),
                    output_path=str(source),
                    profile_id="balanced",
                )
            )

            self.assertFalse(result.success)
            self.assertIn("mismo archivo", result.error)

    def test_signed_pdf_is_copied_without_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "signed.pdf")
            output = root / "out" / "signed_comprimido.pdf"
            original_signature_flags = compress_engine._signature_flags
            compress_engine._signature_flags = lambda _doc: 1
            try:
                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="email",
                    )
                )
            finally:
                compress_engine._signature_flags = original_signature_flags

            self.assertTrue(result.success, result.error)
            self.assertTrue(output.exists())
            self.assertEqual(result.strategy, "original validado")
            self.assertIn("firmas", result.warning)
            self.assertEqual(result.output_bytes, result.input_bytes)

    def test_rejected_image_candidate_falls_back_to_safe_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_image_pdf(root / "scan.pdf")
            output = root / "out" / "scan_comprimido.pdf"
            original_compare = compress_engine._compare_visual_pages

            def fail_image_candidate(source_path, candidate_path, pages, profile):
                if "tmp-imagenes" in Path(candidate_path).name:
                    raise RuntimeError("diferencia visual simulada")
                return original_compare(source_path, candidate_path, pages, profile)

            compress_engine._compare_visual_pages = fail_image_candidate
            try:
                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="email",
                    )
                )
            finally:
                compress_engine._compare_visual_pages = original_compare

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "optimizacion segura")
            self.assertIn("modo seguro", result.warning)
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_image_candidate_skips_safe_rewrite_when_it_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_image_pdf(root / "scan.pdf")
            output = root / "out" / "scan_comprimido.pdf"
            original_write_safe = compress_engine._write_safe_candidate

            def fail_if_called(_source_path, _output_path):
                raise AssertionError("safe rewrite should not run")

            compress_engine._write_safe_candidate = fail_if_called
            try:
                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="email",
                    )
                )
            finally:
                compress_engine._write_safe_candidate = original_write_safe

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "imagenes optimizadas")
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_lossless_safe_candidate_skips_visual_render_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "simple.pdf")
            output = root / "out" / "simple_comprimido.pdf"
            original_compare = compress_engine._compare_visual_pages

            def fail_if_called(*_args, **_kwargs):
                raise AssertionError("lossless candidate should not render pages")

            compress_engine._compare_visual_pages = fail_if_called
            try:
                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="balanced",
                    )
                )
            finally:
                compress_engine._compare_visual_pages = original_compare

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "optimizacion segura")

    def test_qpdf_candidate_can_win_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_metadata_heavy_pdf(root / "metadata.pdf")
            output = root / "out" / "metadata_comprimido.pdf"
            original_write_qpdf = compress_engine._write_qpdf_candidate

            def fake_qpdf(source_path, output_path, _executable):
                doc = fitz.open(str(source_path))
                try:
                    doc.set_metadata({})
                    doc.save(
                        str(output_path),
                        garbage=4,
                        deflate=True,
                        use_objstms=1,
                        preserve_metadata=0,
                    )
                finally:
                    doc.close()

            compress_engine._find_qpdf = lambda: "qpdf"
            compress_engine._write_qpdf_candidate = fake_qpdf
            try:
                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="quality",
                    )
                )
            finally:
                compress_engine._write_qpdf_candidate = original_write_qpdf

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "qpdf estructural")
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_qpdf_mode_uses_visual_boost_for_image_heavy_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_metadata_heavy_pdf(root / "qpdf_visual.pdf")
            output = root / "out" / "qpdf_visual_comprimido.pdf"
            original_inspect = compress_engine._inspect_source
            original_find_qpdf = compress_engine._find_qpdf
            original_find_ghostscript = compress_engine._find_ghostscript
            original_write_qpdf = compress_engine._write_qpdf_candidate
            original_write_ghostscript = compress_engine._write_ghostscript_candidate

            def fail_qpdf_if_visual_boost_wins(*_args, **_kwargs):
                raise AssertionError("qpdf visual debe probar refuerzo antes de QPDF estructural")

            def fake_ghostscript(source_path, output_path, _profile, _executable):
                doc = fitz.open(str(source_path))
                try:
                    doc.set_metadata({})
                    doc.save(
                        str(output_path),
                        garbage=4,
                        deflate=True,
                        use_objstms=1,
                        preserve_metadata=0,
                    )
                finally:
                    doc.close()

            try:
                compress_engine._inspect_source = lambda *_: self._image_heavy_analysis()
                compress_engine._find_qpdf = lambda: "qpdf"
                compress_engine._find_ghostscript = lambda: "gs"
                compress_engine._write_qpdf_candidate = fail_qpdf_if_visual_boost_wins
                compress_engine._write_ghostscript_candidate = fake_ghostscript

                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="balanced",
                        options=CompressOptions(engine_mode="qpdf"),
                    )
                )
            finally:
                compress_engine._inspect_source = original_inspect
                compress_engine._find_qpdf = original_find_qpdf
                compress_engine._find_ghostscript = original_find_ghostscript
                compress_engine._write_qpdf_candidate = original_write_qpdf
                compress_engine._write_ghostscript_candidate = original_write_ghostscript

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "qpdf visual reforzado")
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_qpdf_mode_skips_visual_boost_for_already_optimized_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_metadata_heavy_pdf(root / "qpdf_optimized_image.pdf")
            output = root / "out" / "qpdf_optimized_image_comprimido.pdf"
            original_inspect = compress_engine._inspect_source
            original_find_qpdf = compress_engine._find_qpdf
            original_find_ghostscript = compress_engine._find_ghostscript
            original_write_qpdf = compress_engine._write_qpdf_candidate
            original_write_ghostscript = compress_engine._write_ghostscript_candidate

            def fail_ghostscript(*_args, **_kwargs):
                raise AssertionError("imagenes ya optimizadas no deben disparar refuerzo visual")

            def fake_qpdf(source_path, output_path, _executable):
                doc = fitz.open(str(source_path))
                try:
                    doc.set_metadata({})
                    doc.save(
                        str(output_path),
                        garbage=4,
                        deflate=True,
                        use_objstms=1,
                        preserve_metadata=0,
                    )
                finally:
                    doc.close()

            try:
                compress_engine._inspect_source = lambda *_: self._optimized_large_image_analysis()
                compress_engine._find_qpdf = lambda: "qpdf"
                compress_engine._find_ghostscript = lambda: "gs"
                compress_engine._write_qpdf_candidate = fake_qpdf
                compress_engine._write_ghostscript_candidate = fail_ghostscript

                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="balanced",
                        options=CompressOptions(engine_mode="qpdf"),
                    )
                )
            finally:
                compress_engine._inspect_source = original_inspect
                compress_engine._find_qpdf = original_find_qpdf
                compress_engine._find_ghostscript = original_find_ghostscript
                compress_engine._write_qpdf_candidate = original_write_qpdf
                compress_engine._write_ghostscript_candidate = original_write_ghostscript

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "qpdf estructural")
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_ghostscript_candidate_can_win_when_internal_rewrite_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_image_pdf(root / "scan.pdf")
            output = root / "out" / "scan_comprimido.pdf"
            original_write_image = compress_engine._write_image_candidate
            original_write_ghostscript = compress_engine._write_ghostscript_candidate

            def reject_internal_image(_source_path, _output_path, _profile):
                raise RuntimeError("rechazo interno simulado")

            def fake_ghostscript(source_path, output_path, profile, _executable):
                original_write_image(source_path, output_path, profile)

            compress_engine._find_ghostscript = lambda: "gs"
            compress_engine._write_image_candidate = reject_internal_image
            compress_engine._write_ghostscript_candidate = fake_ghostscript
            try:
                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="email",
                    )
                )
            finally:
                compress_engine._write_image_candidate = original_write_image
                compress_engine._write_ghostscript_candidate = original_write_ghostscript

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "ghostscript pdfwrite")
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_app_local_engines_are_detected_for_portable_installs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qpdf = root / "tools" / "qpdf" / "qpdf.exe"
            gs = root / "tools" / "ghostscript" / "bin" / "gswin64c.exe"
            qpdf.parent.mkdir(parents=True)
            gs.parent.mkdir(parents=True)
            qpdf.write_bytes(b"")
            gs.write_bytes(b"")

            original_roots = compress_engine._app_local_roots
            original_which = compress_engine.shutil.which
            compress_engine._find_qpdf = self._original_find_qpdf
            compress_engine._find_ghostscript = self._original_find_ghostscript
            compress_engine._app_local_roots = lambda: [root]
            compress_engine.shutil.which = lambda _name: None
            try:
                statuses = compress_engine.optional_engine_status()
            finally:
                compress_engine._app_local_roots = original_roots
                compress_engine.shutil.which = original_which

            self.assertEqual([status.label for status in statuses], ["QPDF", "Ghostscript"])
            self.assertTrue(all(status.available for status in statuses))
            self.assertTrue(all(status.source == "empaquetado" for status in statuses))

    def test_manual_qpdf_mode_requires_qpdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "simple.pdf")
            output = root / "out" / "simple_comprimido.pdf"

            result = PdfCompressEngine().run_job(
                CompressJob(
                    pdf_path=str(source),
                    output_path=str(output),
                    profile_id="balanced",
                    options=CompressOptions(engine_mode="qpdf"),
                )
            )

            self.assertFalse(result.success)
            self.assertIn("QPDF", result.error)

    def test_manual_fast_mode_requires_ghostscript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "simple.pdf")
            output = root / "out" / "simple_comprimido.pdf"

            result = PdfCompressEngine().run_job(
                CompressJob(
                    pdf_path=str(source),
                    output_path=str(output),
                    profile_id="balanced",
                    options=CompressOptions(engine_mode="fast"),
                )
            )

            self.assertFalse(result.success)
            self.assertIn("Ghostscript", result.error)

    def test_fast_mode_uses_fast_ghostscript_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_metadata_heavy_pdf(root / "fast.pdf")
            output = root / "out" / "fast_comprimido.pdf"
            original_inspect = compress_engine._inspect_source
            original_write_fast = compress_engine._write_ghostscript_fast_candidate

            def fake_fast(source_path, output_path, _executable):
                self._strip_metadata(source_path, output_path)

            try:
                compress_engine._inspect_source = lambda *_: self._image_heavy_analysis()
                compress_engine._find_ghostscript = lambda: "gs"
                compress_engine._write_ghostscript_fast_candidate = fake_fast

                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="balanced",
                        options=CompressOptions(engine_mode="fast"),
                    )
                )
            finally:
                compress_engine._inspect_source = original_inspect
                compress_engine._write_ghostscript_fast_candidate = original_write_fast

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "ghostscript rapido")
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_qpdf_command_allows_warning_exit_zero(self) -> None:
        captured: list[str] = []
        original_run_command = compress_engine._run_command

        def fake_run_command(command, _label, **_kwargs):
            captured.extend(command)

        compress_engine._run_command = fake_run_command
        try:
            compress_engine._write_qpdf_candidate(
                Path("entrada.pdf"),
                Path("salida.pdf"),
                "qpdf",
            )
        finally:
            compress_engine._run_command = original_run_command

        self.assertIn("--warning-exit-0", captured)

    def test_page_rules_require_page_aware_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "simple.pdf")
            output = root / "out" / "simple_comprimido.pdf"

            result = PdfCompressEngine().run_job(
                CompressJob(
                    pdf_path=str(source),
                    output_path=str(output),
                    profile_id="balanced",
                    options=CompressOptions(engine_mode="qpdf"),
                    page_rules=[PageCompressionRule("1", "exclude")],
                )
            )

            self.assertFalse(result.success)
            self.assertIn("reglas por pagina", result.error)

    def test_all_excluded_page_rules_copy_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "simple.pdf")
            output = root / "out" / "simple_comprimido.pdf"

            result = PdfCompressEngine().run_job(
                CompressJob(
                    pdf_path=str(source),
                    output_path=str(output),
                    profile_id="email",
                    page_rules=[PageCompressionRule("todo", "exclude")],
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "original conservado")
            self.assertEqual(result.pages_excluded, 1)
            self.assertEqual(result.pages_compressed, 0)
            self.assertIn("excluidas", result.warning)

    def test_page_rules_compress_only_allowed_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_multi_image_pdf(root / "scan.pdf")
            output = root / "out" / "scan_comprimido.pdf"

            result = PdfCompressEngine().run_job(
                CompressJob(
                    pdf_path=str(source),
                    output_path=str(output),
                    profile_id="email",
                    page_rules=[
                        PageCompressionRule("1", "exclude"),
                        PageCompressionRule("2", "email"),
                    ],
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "reglas por pagina")
            self.assertEqual(result.pages_excluded, 1)
            self.assertEqual(result.pages_compressed, 1)
            self.assertIn("regla", result.page_rule_summary)
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_page_rules_report_shared_images_between_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_shared_image_pdf(root / "shared.pdf")
            output = root / "out" / "shared_comprimido.pdf"

            result = PdfCompressEngine().run_job(
                CompressJob(
                    pdf_path=str(source),
                    output_path=str(output),
                    profile_id="email",
                    page_rules=[
                        PageCompressionRule("1", "exclude"),
                        PageCompressionRule("2", "email"),
                    ],
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "reglas por pagina")
            self.assertIn("imagen compartida", " ".join(result.rule_warnings))
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_risky_masked_images_skip_internal_rewrite_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "risky.pdf")
            output = root / "out" / "risky_comprimido.pdf"
            original_inspect = compress_engine._inspect_source
            original_write_image = compress_engine._write_image_candidate
            try:
                compress_engine._inspect_source = lambda *_: self._risky_image_analysis()

                def fail_if_called(*_args, **_kwargs):
                    raise AssertionError("rewrite_images no debe usarse con imagenes riesgosas")

                compress_engine._write_image_candidate = fail_if_called
                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="balanced",
                    )
                )
            finally:
                compress_engine._inspect_source = original_inspect
                compress_engine._write_image_candidate = original_write_image

            self.assertTrue(result.success, result.error)
            self.assertTrue(output.exists())
            self.assertNotEqual(result.strategy, "imagenes optimizadas")
            self.assertIn("imagenes con mascara", result.warning)

    def test_auto_prioritizes_ghostscript_for_masked_image_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_metadata_heavy_pdf(root / "risky_big.pdf")
            output = root / "out" / "risky_big_comprimido.pdf"
            original_inspect = compress_engine._inspect_source
            original_find_qpdf = compress_engine._find_qpdf
            original_find_ghostscript = compress_engine._find_ghostscript
            original_write_qpdf = compress_engine._write_qpdf_candidate
            original_write_safe = compress_engine._write_safe_candidate
            original_write_ghostscript = compress_engine._write_ghostscript_candidate

            def fail_if_called(*_args, **_kwargs):
                raise AssertionError("auto debe evitar candidatos lentos antes de Ghostscript")

            def fake_ghostscript(source_path, output_path, _profile, _executable):
                doc = fitz.open(str(source_path))
                try:
                    doc.set_metadata({})
                    doc.save(
                        str(output_path),
                        garbage=4,
                        deflate=True,
                        use_objstms=1,
                        preserve_metadata=0,
                    )
                finally:
                    doc.close()

            try:
                compress_engine._inspect_source = lambda *_: self._risky_image_analysis()
                compress_engine._find_qpdf = lambda: "qpdf"
                compress_engine._find_ghostscript = lambda: "gs"
                compress_engine._write_qpdf_candidate = fail_if_called
                compress_engine._write_safe_candidate = fail_if_called
                compress_engine._write_ghostscript_candidate = fake_ghostscript

                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="balanced",
                    )
                )
            finally:
                compress_engine._inspect_source = original_inspect
                compress_engine._find_qpdf = original_find_qpdf
                compress_engine._find_ghostscript = original_find_ghostscript
                compress_engine._write_qpdf_candidate = original_write_qpdf
                compress_engine._write_safe_candidate = original_write_safe
                compress_engine._write_ghostscript_candidate = original_write_ghostscript

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "ghostscript pdfwrite")
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_auto_prioritizes_ghostscript_for_full_page_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_metadata_heavy_pdf(root / "visual_big.pdf")
            output = root / "out" / "visual_big_comprimido.pdf"
            original_inspect = compress_engine._inspect_source
            original_find_qpdf = compress_engine._find_qpdf
            original_find_ghostscript = compress_engine._find_ghostscript
            original_write_qpdf = compress_engine._write_qpdf_candidate
            original_write_safe = compress_engine._write_safe_candidate
            original_write_image = compress_engine._write_image_candidate
            original_write_ghostscript = compress_engine._write_ghostscript_candidate

            def fail_if_called(*_args, **_kwargs):
                raise AssertionError("auto debe evitar rutas lentas si Ghostscript ya gano")

            def fake_ghostscript(source_path, output_path, _profile, _executable):
                doc = fitz.open(str(source_path))
                try:
                    doc.set_metadata({})
                    doc.save(
                        str(output_path),
                        garbage=4,
                        deflate=True,
                        use_objstms=1,
                        preserve_metadata=0,
                    )
                finally:
                    doc.close()

            try:
                compress_engine._inspect_source = lambda *_: self._image_heavy_analysis()
                compress_engine._find_qpdf = lambda: "qpdf"
                compress_engine._find_ghostscript = lambda: "gs"
                compress_engine._write_qpdf_candidate = fail_if_called
                compress_engine._write_safe_candidate = fail_if_called
                compress_engine._write_image_candidate = fail_if_called
                compress_engine._write_ghostscript_candidate = fake_ghostscript

                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="quality",
                    )
                )
            finally:
                compress_engine._inspect_source = original_inspect
                compress_engine._find_qpdf = original_find_qpdf
                compress_engine._find_ghostscript = original_find_ghostscript
                compress_engine._write_qpdf_candidate = original_write_qpdf
                compress_engine._write_safe_candidate = original_write_safe
                compress_engine._write_image_candidate = original_write_image
                compress_engine._write_ghostscript_candidate = original_write_ghostscript

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "ghostscript pdfwrite")
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_auto_accepts_fast_ghostscript_for_long_visual_workload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_metadata_heavy_pdf(root / "visual_long.pdf")
            output = root / "out" / "visual_long_comprimido.pdf"
            original_inspect = compress_engine._inspect_source
            original_write_fast = compress_engine._write_ghostscript_fast_candidate
            original_write_qpdf = compress_engine._write_qpdf_candidate
            original_write_image = compress_engine._write_image_candidate
            original_write_safe = compress_engine._write_safe_candidate
            original_write_ghostscript = compress_engine._write_ghostscript_candidate

            def fake_fast(source_path, output_path, _executable):
                self._strip_metadata(source_path, output_path)

            def fail_if_called(*_args, **_kwargs):
                raise AssertionError("auto debe aceptar el candidato rapido suficiente")

            try:
                compress_engine._inspect_source = lambda *_: self._long_visual_analysis()
                compress_engine._find_qpdf = lambda: "qpdf"
                compress_engine._find_ghostscript = lambda: "gs"
                compress_engine._write_ghostscript_fast_candidate = fake_fast
                compress_engine._write_qpdf_candidate = fail_if_called
                compress_engine._write_image_candidate = fail_if_called
                compress_engine._write_safe_candidate = fail_if_called
                compress_engine._write_ghostscript_candidate = fail_if_called

                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="balanced",
                    )
                )
            finally:
                compress_engine._inspect_source = original_inspect
                compress_engine._write_ghostscript_fast_candidate = original_write_fast
                compress_engine._write_qpdf_candidate = original_write_qpdf
                compress_engine._write_image_candidate = original_write_image
                compress_engine._write_safe_candidate = original_write_safe
                compress_engine._write_ghostscript_candidate = original_write_ghostscript

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "ghostscript rapido")
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_auto_skips_ghostscript_for_already_optimized_large_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "optimized_visual.pdf")
            output = root / "out" / "optimized_visual_comprimido.pdf"
            original_inspect = compress_engine._inspect_source
            original_find_ghostscript = compress_engine._find_ghostscript
            original_write_ghostscript = compress_engine._write_ghostscript_candidate

            def fail_ghostscript(*_args, **_kwargs):
                raise AssertionError("auto no debe gastar Ghostscript sin ganancia visual probable")

            try:
                compress_engine._inspect_source = lambda *_: self._optimized_large_image_analysis()
                compress_engine._find_ghostscript = lambda: "gs"
                compress_engine._write_ghostscript_candidate = fail_ghostscript

                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="balanced",
                    )
                )
            finally:
                compress_engine._inspect_source = original_inspect
                compress_engine._find_ghostscript = original_find_ghostscript
                compress_engine._write_ghostscript_candidate = original_write_ghostscript

            self.assertTrue(result.success, result.error)
            self.assertNotEqual(result.strategy, "ghostscript pdfwrite")

    def test_turbo_mode_uses_isolated_document_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_metadata_heavy_pdf(root / "turbo.pdf")
            output = root / "out" / "turbo_comprimido.pdf"
            original_write_turbo = compress_engine._write_isolated_image_candidate

            def fake_turbo(source_path, output_path, _profile):
                self._strip_metadata(source_path, output_path)

            compress_engine._write_isolated_image_candidate = fake_turbo
            try:
                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="balanced",
                        options=CompressOptions(engine_mode="turbo"),
                    )
                )
            finally:
                compress_engine._write_isolated_image_candidate = original_write_turbo

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "pymupdf turbo aislado")
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_pymupdf_mode_uses_pagewise_rewrite_for_masked_image_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_metadata_heavy_pdf(root / "risky_pagewise.pdf")
            output = root / "out" / "risky_pagewise_comprimido.pdf"
            original_inspect = compress_engine._inspect_source
            original_write_image = compress_engine._write_image_candidate
            original_write_pagewise = compress_engine._write_pagewise_image_candidate
            original_write_safe = compress_engine._write_safe_candidate

            def fail_direct_rewrite(*_args, **_kwargs):
                raise AssertionError("rewrite_images directo no debe usarse con mascaras")

            def fail_safe_if_called(*_args, **_kwargs):
                raise AssertionError("modo seguro no debe ganar si pagewise es util")

            def fake_pagewise(source_path, output_path, _profile):
                doc = fitz.open(str(source_path))
                try:
                    doc.set_metadata({})
                    doc.save(
                        str(output_path),
                        garbage=4,
                        deflate=True,
                        use_objstms=1,
                        preserve_metadata=0,
                    )
                finally:
                    doc.close()

            try:
                compress_engine._inspect_source = lambda *_: self._risky_image_analysis()
                compress_engine._write_image_candidate = fail_direct_rewrite
                compress_engine._write_pagewise_image_candidate = fake_pagewise
                compress_engine._write_safe_candidate = fail_safe_if_called

                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="balanced",
                        options=CompressOptions(engine_mode="pymupdf"),
                    )
                )
            finally:
                compress_engine._inspect_source = original_inspect
                compress_engine._write_image_candidate = original_write_image
                compress_engine._write_pagewise_image_candidate = original_write_pagewise
                compress_engine._write_safe_candidate = original_write_safe

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.strategy, "imagenes optimizadas por pagina")
            self.assertLess(result.output_bytes, result.input_bytes)

    def test_page_rules_with_risky_images_conserve_original_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "rules.pdf")
            output = root / "out" / "rules_comprimido.pdf"
            original_inspect = compress_engine._inspect_source
            original_write_rules = compress_engine._write_page_rules_candidate
            try:
                compress_engine._inspect_source = lambda *_: self._risky_image_analysis()

                def fail_if_called(*_args, **_kwargs):
                    raise AssertionError("reglas no deben recomprimir imagenes riesgosas")

                compress_engine._write_page_rules_candidate = fail_if_called
                result = PdfCompressEngine().run_job(
                    CompressJob(
                        pdf_path=str(source),
                        output_path=str(output),
                        profile_id="balanced",
                        page_rules=[PageCompressionRule("1", "email")],
                    )
                )
            finally:
                compress_engine._inspect_source = original_inspect
                compress_engine._write_page_rules_candidate = original_write_rules

            self.assertTrue(result.success, result.error)
            self.assertTrue(output.exists())
            self.assertEqual(result.strategy, "original conservado")
            self.assertIn("imagenes con mascara", result.warning)

    def test_custom_options_build_effective_profile(self) -> None:
        profile = compress_engine._effective_profile(
            profile_for("balanced"),
            CompressOptions(
                dpi_target=220,
                dpi_threshold=210,
                quality=55,
                set_to_gray=True,
                validation_level="strict",
            ),
        )

        self.assertEqual(profile.dpi_target, 220)
        self.assertGreater(profile.dpi_threshold, profile.dpi_target)
        self.assertEqual(profile.quality, 55)
        self.assertTrue(profile.set_to_gray)
        self.assertLess(profile.max_visual_mean_delta, profile_for("balanced").max_visual_mean_delta)

    def test_turbo_worker_profile_uses_aggressive_fast_parameters(self) -> None:
        profile = compress_engine._turbo_worker_profile(profile_for("quality"))

        self.assertEqual(profile.dpi_threshold, 130)
        self.assertEqual(profile.dpi_target, 110)
        self.assertEqual(profile.quality, 62)

    def test_candidate_is_rejected_if_links_are_lost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_link_pdf(root / "link.pdf")
            candidate = self._make_text_pdf(root / "plain.pdf")
            profile = profile_for("balanced")
            analysis = compress_engine._inspect_source(source, profile)

            with self.assertRaisesRegex(RuntimeError, "enlaces"):
                compress_engine._validate_candidate(
                    source,
                    candidate,
                    analysis,
                    [],
                    profile,
                    "candidato sin links",
                )

    def test_isolated_process_request_writes_progress_and_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_text_pdf(root / "simple.pdf")
            output = root / "out" / "simple_comprimido.pdf"
            request = root / "request.json"
            response = root / "response.json"
            events = root / "events.jsonl"
            cancel = root / "cancel.signal"
            job = CompressJob(
                pdf_path=str(source),
                output_path=str(output),
                profile_id="balanced",
            )

            request.write_text(
                json.dumps({"jobs": [compress_job_to_dict(job)]}, ensure_ascii=False),
                encoding="utf-8",
            )
            events.touch()

            exit_code = run_request(request, response, events, cancel)
            payload = json.loads(response.read_text(encoding="utf-8"))
            event_lines = events.read_text(encoding="utf-8").splitlines()

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(payload["results"][0]["success"], payload["results"][0]["error"])
            self.assertTrue(output.exists())
            self.assertTrue(any('"type": "progress"' in line for line in event_lines))
            self.assertTrue(any('"type": "result"' in line for line in event_lines))

    def test_page_rewrite_worker_writes_single_page_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_image_pdf(root / "scan.pdf")
            output = root / "page.pdf"

            exit_code = page_rewrite_main([
                "--page-source",
                str(source),
                "--page-output",
                str(output),
                "--page-index",
                "0",
                "--dpi-threshold",
                "180",
                "--dpi-target",
                "150",
                "--quality",
                "76",
            ])

            self.assertEqual(exit_code, 0)
            self.assertTrue(output.exists())
            doc = fitz.open(str(output))
            try:
                self.assertEqual(doc.page_count, 1)
            finally:
                doc.close()

    def test_doc_rewrite_worker_writes_document_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_image_pdf(root / "scan.pdf")
            output = root / "doc.pdf"

            exit_code = doc_rewrite_main([
                "--doc-source",
                str(source),
                "--doc-output",
                str(output),
                "--dpi-threshold",
                "180",
                "--dpi-target",
                "150",
                "--quality",
                "76",
            ])

            self.assertEqual(exit_code, 0)
            self.assertTrue(output.exists())
            doc = fitz.open(str(output))
            try:
                self.assertEqual(doc.page_count, 1)
            finally:
                doc.close()

    def test_unknown_profile_falls_back_to_balanced(self) -> None:
        self.assertEqual(profile_for("nope").id, "balanced")

    def test_format_bytes_is_human_readable(self) -> None:
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1536), "1.5 KB")

    @staticmethod
    def _risky_image_analysis():
        return compress_engine._PdfAnalysis(
            page_count=1,
            image_count=1,
            oversized_images=1,
            risky_images=1,
            image_pages=[0],
            large_image_pages=[0],
            oversized_pages=[0],
            risky_pages=[0],
        )

    @staticmethod
    def _image_heavy_analysis():
        return compress_engine._PdfAnalysis(
            page_count=1,
            image_count=1,
            oversized_images=0,
            risky_images=0,
            image_pages=[0],
            large_image_pages=[0],
            large_image_bytes=2_200_000,
            large_image_pixels=3_000_000,
        )

    @staticmethod
    def _optimized_large_image_analysis():
        return compress_engine._PdfAnalysis(
            page_count=1,
            image_count=1,
            oversized_images=0,
            risky_images=0,
            image_pages=[0],
            large_image_pages=[0],
            large_image_bytes=70_000,
            large_image_pixels=1_750_000,
        )

    @staticmethod
    def _long_visual_analysis():
        return compress_engine._PdfAnalysis(
            page_count=1,
            image_count=800,
            oversized_images=800,
            risky_images=0,
            image_pages=[0],
            large_image_pages=[0],
            large_image_bytes=32_000_000,
            large_image_pixels=130_000_000,
            oversized_pages=[0],
        )

    @staticmethod
    def _strip_metadata(source_path, output_path) -> None:
        doc = fitz.open(str(source_path))
        try:
            doc.set_metadata({})
            doc.save(
                str(output_path),
                garbage=4,
                deflate=True,
                use_objstms=1,
                preserve_metadata=0,
            )
        finally:
            doc.close()

    @staticmethod
    def _make_text_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((36, 72), "PDF pequeno")
        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _make_metadata_heavy_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((36, 72), "PDF pequeno")
        doc.set_metadata({"title": "X" * 800_000, "author": "PDFlex"})
        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _make_link_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((36, 72), "PDF pequeno")
        page.insert_link(
            {
                "kind": fitz.LINK_URI,
                "from": fitz.Rect(30, 45, 160, 90),
                "uri": "https://example.com",
            }
        )
        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _make_image_pdf(path: Path) -> Path:
        rng = np.random.default_rng(20260625)
        paper = rng.integers(242, 255, size=(1800, 1400, 1), dtype=np.uint8)
        image = Image.fromarray(np.repeat(paper, 3, axis=2), mode="RGB")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        for y in range(120, 1660, 95):
            draw.text(
                (120, y),
                "PDFlex documento escaneado - texto legible y lineas de control",
                fill=(24, 24, 24),
                font=font,
            )
            draw.line((120, y + 38, 1240, y + 38), fill=(82, 82, 82), width=3)
        png = path.with_suffix(".png")
        image.save(png, format="PNG")

        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        rect = fitz.Rect(36, 72, 576, 612)
        page.insert_image(rect, filename=str(png))
        doc.save(path)
        doc.close()
        return path

    @classmethod
    def _make_multi_image_pdf(cls, path: Path) -> Path:
        first_png = cls._make_scan_image(path.with_name("scan_page_1.png"), seed=1)
        second_png = cls._make_scan_image(path.with_name("scan_page_2.png"), seed=2)
        doc = fitz.open()
        for png in (first_png, second_png):
            page = doc.new_page(width=612, height=792)
            page.insert_image(fitz.Rect(36, 72, 576, 612), filename=str(png))
        doc.save(path)
        doc.close()
        return path

    @classmethod
    def _make_shared_image_pdf(cls, path: Path) -> Path:
        png = cls._make_scan_image(path.with_name("shared_scan.png"), seed=9)
        doc = fitz.open()
        for _ in range(2):
            page = doc.new_page(width=612, height=792)
            page.insert_image(fitz.Rect(36, 72, 576, 612), filename=str(png))
        doc.save(path)
        doc.close()
        return path

    @staticmethod
    def _make_scan_image(path: Path, *, seed: int) -> Path:
        rng = np.random.default_rng(20260625 + seed)
        paper = rng.integers(238, 255, size=(1900, 1500, 1), dtype=np.uint8)
        image = Image.fromarray(np.repeat(paper, 3, axis=2), mode="RGB")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        for y in range(110, 1780, 80):
            draw.text(
                (105, y),
                f"PDFlex pagina {seed} - tablas pequenas y texto de control",
                fill=(20, 20, 20),
                font=font,
            )
            draw.rectangle((105, y + 24, 1340, y + 48), outline=(80, 80, 80), width=2)
        image.save(path, format="PNG")
        return path


if __name__ == "__main__":
    unittest.main()
