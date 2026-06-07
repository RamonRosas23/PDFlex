from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PIL import Image, ImageDraw, ImageStat
from PyQt6.QtWidgets import QApplication

from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from ui.imgs_a_pdf.window import (
    ImgsAPdfWindow,
    ImgsToPdfWorker,
    ScanProcessingOptions,
    crop_light_borders,
    enhance_document_contrast,
    preprocess_document_image,
)


class ScannerProcessingTests(unittest.TestCase):
    def test_crop_light_borders_trims_document_margin(self) -> None:
        image = Image.new("RGB", (260, 180), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((64, 44, 196, 136), fill=(230, 230, 230))
        draw.text((90, 84), "DOC", fill="black")

        cropped = crop_light_borders(image, threshold=245, padding=4)

        self.assertLess(cropped.width, image.width)
        self.assertLess(cropped.height, image.height)
        self.assertGreater(cropped.width, 80)

    def test_high_contrast_profile_returns_grayscale_document_image(self) -> None:
        image = Image.new("RGB", (160, 100), (236, 232, 218))
        draw = ImageDraw.Draw(image)
        draw.text((24, 42), "Texto tenue", fill=(108, 104, 96))

        processed = preprocess_document_image(
            image,
            ScanProcessingOptions(
                enabled=True,
                crop_borders=False,
                deskew=False,
                enhance_contrast=True,
                grayscale=True,
            ),
        )

        self.assertEqual(processed.mode, "RGB")
        channels = ImageStat.Stat(processed).mean
        self.assertAlmostEqual(channels[0], channels[1], delta=1.0)
        self.assertAlmostEqual(channels[1], channels[2], delta=1.0)

    def test_enhance_document_contrast_keeps_dimensions(self) -> None:
        image = Image.new("RGB", (120, 80), (225, 225, 225))
        draw = ImageDraw.Draw(image)
        draw.rectangle((24, 24, 96, 56), outline=(130, 130, 130), width=2)

        enhanced = enhance_document_contrast(image)

        self.assertEqual(enhanced.size, image.size)
        self.assertEqual(enhanced.mode, "RGB")


class ImgsAPdfWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_worker_generates_pdf_with_scan_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = self._make_scan_photo(root / "scan.png")
            output = root / "salida.pdf"

            worker = ImgsToPdfWorker(
                image_paths=[str(image_path)],
                output_path=str(output),
                page_size_key="A4  (210 × 297 mm)",
                orientation="Vertical",
                margin_mm=8.0,
                fit_mode="Ajustar (mantener proporción)",
                auto_rotate=True,
                one_per_page=True,
                dpi=96,
                scan_options=ScanProcessingOptions(
                    enabled=True,
                    crop_borders=True,
                    deskew=False,
                    enhance_contrast=True,
                    grayscale=False,
                ),
            )
            results = []
            errors = []
            worker.finished.connect(lambda result: results.append(result))
            worker.error.connect(lambda msg: errors.append(msg))

            worker.run()

            self.assertFalse(errors)
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].success)
            self.assertTrue(output.exists())
            doc = fitz.open(str(output))
            try:
                self.assertEqual(doc.page_count, 1)
            finally:
                doc.close()

    def test_window_exposes_scan_profile_in_worker_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = self._make_scan_photo(Path(tmp) / "scan.png")
            window = ImgsAPdfWindow(
                ShellContext(
                    tray=PdfTray(),
                    word_converter=WordToPdfConverter(),
                    open_tool=lambda *_: None,
                )
            )
            try:
                window.set_inputs([str(image_path)])
                window._scan_profile_combo.setCurrentText("Foto de hoja")

                options = window._scan_options()

                self.assertTrue(options.enabled)
                self.assertTrue(options.crop_borders)
                self.assertTrue(options.deskew)
                self.assertTrue(options.enhance_contrast)
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_images_to_pdf_for_images(self) -> None:
        tool = get_tool("imgs_a_pdf")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Imágenes a PDF")
        self.assertIn(".png", tool.input_extensions)

    @staticmethod
    def _make_scan_photo(path: Path) -> Path:
        image = Image.new("RGB", (260, 180), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((52, 32, 208, 148), fill=(238, 238, 230), outline=(210, 210, 205))
        draw.text((82, 82), "Documento", fill=(50, 50, 50))
        image.save(path)
        return path


if __name__ == "__main__":
    unittest.main()
