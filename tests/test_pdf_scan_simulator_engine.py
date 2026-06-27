from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
import numpy as np
from PIL import Image, ImageDraw

from core.pdf_scan_simulator_engine import (
    PdfScanSimulatorEngine,
    ScanSimulationJob,
    config_for_preset,
    simulate_scan_image,
)


class PdfScanSimulatorEngineTests(unittest.TestCase):
    def test_simulate_scan_image_is_deterministic_by_seed_source_and_page(self) -> None:
        img = Image.new("RGB", (240, 320), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle((30, 50, 210, 260), outline="black", width=2)
        draw.text((44, 90), "PDFlex scan", fill="black")

        cfg = replace(config_for_preset("office"), dpi=96, seed=1234)
        a = simulate_scan_image(img, cfg, source_id="doc-a", page_index=0)
        b = simulate_scan_image(img, cfg, source_id="doc-a", page_index=0)
        c = simulate_scan_image(img, cfg, source_id="doc-a", page_index=1)

        self.assertEqual(a.tobytes(), b.tobytes())
        self.assertNotEqual(a.tobytes(), c.tobytes())

    def test_pages_in_same_run_share_scanner_signature(self) -> None:
        img = Image.new("RGB", (240, 320), "white")
        draw = ImageDraw.Draw(img)
        for y in range(60, 260, 28):
            draw.line((36, y, 204, y), fill="black", width=1)
        cfg = replace(config_for_preset("office"), dpi=96, seed=5678)

        page_a = simulate_scan_image(img, cfg, source_id="same-run", page_index=0)
        page_b = simulate_scan_image(img, cfg, source_id="same-run", page_index=1)

        self.assertNotEqual(page_a.tobytes(), page_b.tobytes())
        a_profile = np.asarray(page_a.convert("L"), dtype=np.float32).mean(axis=1)
        b_profile = np.asarray(page_b.convert("L"), dtype=np.float32).mean(axis=1)
        corr = float(np.corrcoef(a_profile, b_profile)[0, 1])
        self.assertGreater(corr, 0.72)

    def test_pages_in_same_run_keep_similar_sheet_placement(self) -> None:
        img = Image.new("RGB", (280, 360), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle((24, 24, 256, 336), outline="black", width=2)
        for y in range(70, 280, 32):
            draw.line((48, y, 232, y), fill="black", width=1)
        cfg = replace(config_for_preset("office"), dpi=96, seed=9876)

        page_a = simulate_scan_image(img, cfg, source_id="placement-run", page_index=0)
        page_b = simulate_scan_image(img, cfg, source_id="placement-run", page_index=1)

        bbox_a = _dark_bbox(page_a)
        bbox_b = _dark_bbox(page_b)
        max_delta = max(abs(a - b) for a, b in zip(bbox_a, bbox_b))
        self.assertLessEqual(max_delta, 5)

    def test_simulation_fallback_works_without_opencv(self) -> None:
        img = Image.new("RGB", (160, 220), "white")
        draw = ImageDraw.Draw(img)
        draw.text((28, 80), "Fallback", fill="black")
        cfg = replace(config_for_preset("clean"), dpi=96, seed=22)

        with patch("core.pdf_scan_simulator_engine.cv2", None):
            out = simulate_scan_image(img, cfg, source_id="fallback", page_index=0)

        self.assertEqual(out.size, img.size)
        self.assertEqual(out.mode, "RGB")

    def test_run_job_creates_readable_scanned_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "source.pdf", pages=1)
            output = root / "source_escaneado.pdf"
            cfg = replace(config_for_preset("clean"), dpi=96, seed=77)

            result = PdfScanSimulatorEngine().run_job(
                ScanSimulationJob(str(source), str(output)),
                cfg,
            )

            self.assertTrue(result.success, result.error)
            self.assertTrue(output.exists())
            self.assertEqual(result.page_count, 1)
            self.assertGreater(result.output_bytes, 0)

            with fitz.open(str(source)) as original, fitz.open(str(output)) as scanned:
                self.assertEqual(scanned.page_count, 1)
                self.assertAlmostEqual(scanned[0].rect.width, original[0].rect.width, places=2)
                self.assertAlmostEqual(scanned[0].rect.height, original[0].rect.height, places=2)
                self.assertGreaterEqual(len(scanned[0].get_images(full=True)), 1)

                src_pixels = _render_page_array(original, 0)
                out_pixels = _render_page_array(scanned, 0)
                self.assertEqual(src_pixels.shape, out_pixels.shape)
                mean_delta = np.abs(
                    src_pixels.astype(np.int16) - out_pixels.astype(np.int16)
                ).mean()
                self.assertGreater(mean_delta, 1.0)

    def test_page_range_selects_only_requested_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "source.pdf", pages=3)
            output = root / "range.pdf"
            cfg = replace(config_for_preset("clean"), dpi=96, page_range="2-final")

            result = PdfScanSimulatorEngine().run_job(
                ScanSimulationJob(str(source), str(output)),
                cfg,
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.page_count, 2)
            with fitz.open(str(output)) as doc:
                self.assertEqual(doc.page_count, 2)

    @staticmethod
    def _make_pdf(path: Path, pages: int) -> Path:
        doc = fitz.open()
        for index in range(pages):
            page = doc.new_page(width=220, height=300)
            page.insert_text((32, 52), f"Pagina {index + 1}", fontsize=13)
            page.draw_rect(fitz.Rect(28, 78, 190, 160), color=(0, 0, 0), width=0.8)
            page.insert_text((38, 112), "Documento de prueba", fontsize=10)
        doc.save(path)
        doc.close()
        return path


def _render_page_array(doc: fitz.Document, page_index: int) -> np.ndarray:
    pix = doc[page_index].get_pixmap(dpi=72, colorspace=fitz.csRGB, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n)).copy()


def _dark_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    gray = np.asarray(image.convert("L"), dtype=np.uint8)
    mask = gray < 232
    ys, xs = np.where(mask)
    if len(xs) == 0 or len(ys) == 0:
        return (0, 0, 0, 0)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


if __name__ == "__main__":
    unittest.main()
