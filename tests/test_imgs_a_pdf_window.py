from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw, ImageStat
from reportlab.pdfgen.canvas import Canvas
from PySide6.QtWidgets import QApplication

from shell.context import ShellContext
from shell.tool_registry import get_tool
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter
from core.pdf_backend import PdfRenderDocument
from ui.imgs_a_pdf.window import (
    ImgsAPdfWindow,
    ImgsToPdfWorker,
    ScanProcessingOptions,
    _image_detail,
    crop_light_borders,
    enhance_document_contrast,
    ImageListCard,
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
            with PdfRenderDocument(output) as document:
                self.assertEqual(document.page_count, 1)

    def test_worker_flattens_transparent_sources_on_white_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "transparent.png"
            image = Image.new("RGBA", (80, 40), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rectangle((20, 10, 60, 30), fill=(0, 0, 0, 255))
            image.save(image_path)
            output = root / "salida.pdf"

            worker = ImgsToPdfWorker(
                image_paths=[str(image_path)],
                output_path=str(output),
                page_size_key="Adaptado a la imagen",
                orientation="Vertical",
                margin_mm=0.0,
                fit_mode="Ajustar (mantener proporción)",
                auto_rotate=True,
                one_per_page=True,
                dpi=72,
                scan_options=ScanProcessingOptions(),
            )
            results = []
            errors = []
            worker.finished.connect(lambda result: results.append(result))
            worker.error.connect(lambda msg: errors.append(msg))

            worker.run()

            self.assertFalse(errors)
            self.assertTrue(results and results[0].success)
            with PdfRenderDocument(output) as document:
                rendered = document.render_page(0, scale=1).to_pil()
                self.assertEqual(rendered.size, (80, 40))
                self.assertEqual(rendered.getpixel((0, 0)), (255, 255, 255))

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

    def test_image_rows_show_dimensions_and_run_button_requires_images(self) -> None:
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
                self.assertFalse(window._run_btn.isEnabled())

                window.set_inputs([str(image_path)])
                self.app.processEvents()

                self.assertTrue(window._run_btn.isEnabled())
                item_text = window._img_card.list_widget.item(0).text()
                self.assertIn("260 x 180 px", item_text)
                self.assertIn("B", item_text)
                self.assertIn("260 x 180 px", _image_detail(str(image_path)))
            finally:
                window.deleteLater()
                self.app.processEvents()

    def test_image_list_card_converts_pdf_pages_to_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = root / "doc.pdf"
            self._make_blank_pdf(pdf_path)

            card = ImageListCard()
            try:
                card.add_paths([str(pdf_path)])
                self.app.processEvents()

                self.assertEqual(card.count(), 1)
                output = Path(card.paths()[0])
                self.assertEqual(output.suffix.lower(), ".png")
                with Image.open(output) as image:
                    self.assertEqual(image.size, (300, 150))
            finally:
                card.deleteLater()
                self.app.processEvents()

    def test_image_list_card_uses_drop_zone_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = self._make_scan_photo(Path(tmp) / "scan.png")
            card = ImageListCard()
            try:
                self.assertEqual(card._empty_w.objectName(), "DropZone")
                self.assertEqual(card._content_stack.currentWidget(), card._empty_w)

                card.add_paths([str(image_path)])
                self.app.processEvents()

                self.assertEqual(card._content_stack.currentWidget(), card.list_widget)
            finally:
                card.deleteLater()
                self.app.processEvents()

    def test_image_list_card_preserves_input_order_across_pdf_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_image = root / "10-first.png"
            second_image = root / "01-second.png"
            Image.new("RGB", (80, 40), "blue").save(first_image)
            Image.new("RGB", (70, 35), "white").save(second_image)

            pdf_path = root / "02-middle.pdf"
            self._make_blank_pdf(pdf_path)

            card = ImageListCard()
            try:
                card.add_paths([str(first_image), str(pdf_path), str(second_image)])
                self.app.processEvents()

                paths = card.paths()
                self.assertEqual(paths[0], str(first_image))
                self.assertEqual(Path(paths[1]).stem, "02-middle_p001")
                self.assertEqual(paths[2], str(second_image))
            finally:
                card.deleteLater()
                self.app.processEvents()

    def test_tool_registry_exposes_images_to_pdf_for_images(self) -> None:
        tool = get_tool("imgs_a_pdf")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.title, "Imágenes a PDF")
        self.assertIn(".png", tool.input_extensions)
        self.assertIn(".pdf", tool.input_extensions)
        self.assertIn(".docx", tool.input_extensions)

    @staticmethod
    def _make_scan_photo(path: Path) -> Path:
        image = Image.new("RGB", (260, 180), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((52, 32, 208, 148), fill=(238, 238, 230), outline=(210, 210, 205))
        draw.text((82, 82), "Documento", fill=(50, 50, 50))
        image.save(path)
        return path

    @staticmethod
    def _make_blank_pdf(path: Path) -> Path:
        canvas = Canvas(str(path), pagesize=(72, 36))
        canvas.showPage()
        canvas.save()
        return path


if __name__ == "__main__":
    unittest.main()
