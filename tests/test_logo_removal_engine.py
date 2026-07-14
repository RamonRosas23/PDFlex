from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image, ImageDraw, ImageFilter, ImageStat

from core.logo_removal_engine import (
    LogoRemovalEngine,
    LogoRemovalJob,
    LogoRemovalOptions,
    parse_page_selection,
)
import core.logo_removal_engine as logo_removal_engine


class LogoRemovalEngineTests(unittest.TestCase):
    def test_embedded_logo_is_removed_everywhere_and_text_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = self._make_logo(root / "logo.png")
            source = root / "input.pdf"
            output = root / "out" / "input_sin_logos.pdf"

            doc = fitz.open()
            for index in range(2):
                page = doc.new_page(width=500, height=700)
                page.insert_text((42, 120), f"TEXTO CONSERVADO {index + 1}")
                page.insert_image(
                    fitz.Rect(320, 28, 462, 90),
                    filename=str(logo),
                )
            doc.save(source)
            doc.close()

            result = LogoRemovalEngine().run_job(
                LogoRemovalJob(
                    str(source),
                    str(output),
                    [str(logo)],
                    LogoRemovalOptions(detection_mode="hybrid", similarity=0.84),
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.match_count, 2)
            self.assertEqual(result.embedded_matches, 2)
            self.assertEqual(result.pages_changed, 2)

            cleaned = fitz.open(output)
            try:
                for index, page in enumerate(cleaned):
                    self.assertIn(f"TEXTO CONSERVADO {index + 1}", page.get_text())
                    self.assertEqual(page.get_images(full=True), [])
            finally:
                cleaned.close()

    def test_png_jpg_and_webp_references_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for suffix in (".png", ".jpg", ".webp"):
                with self.subTest(suffix=suffix):
                    logo = self._make_logo(root / f"logo{suffix}", transparent=suffix == ".png")
                    embedded = root / f"embedded_{suffix[1:]}.png"
                    with Image.open(logo) as logo_image:
                        logo_image.convert("RGBA").save(embedded)
                    source = root / f"input_{suffix[1:]}.pdf"
                    output = root / "out" / f"output_{suffix[1:]}.pdf"
                    doc = fitz.open()
                    page = doc.new_page(width=420, height=300)
                    page.insert_image(
                        fitz.Rect(230, 30, 370, 88),
                        filename=str(embedded),
                    )
                    doc.save(source)
                    doc.close()

                    result = LogoRemovalEngine().run_job(
                        LogoRemovalJob(
                            str(source),
                            str(output),
                            [str(logo)],
                            LogoRemovalOptions(detection_mode="embedded", similarity=0.82),
                        )
                    )

                    self.assertTrue(result.success, result.error)
                    self.assertEqual(result.match_count, 1)

    def test_visual_detection_finds_logo_inside_scanned_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = self._make_logo(root / "logo.webp", transparent=False)
            scan = Image.new("RGB", (1000, 1400), "white")
            draw = ImageDraw.Draw(scan)
            draw.text((80, 220), "DOCUMENTO ESCANEADO", fill="black")
            with Image.open(logo) as logo_image:
                placed = logo_image.convert("RGB").resize((210, 90), Image.Resampling.LANCZOS)
            scan.paste(placed, (690, 60))
            scan_path = root / "scan.jpg"
            scan.save(scan_path, quality=88)

            source = root / "scan.pdf"
            output = root / "out" / "scan_sin_logo.pdf"
            doc = fitz.open()
            page = doc.new_page(width=500, height=700)
            page.insert_image(page.rect, filename=str(scan_path))
            doc.save(source)
            doc.close()

            result = LogoRemovalEngine().run_job(
                LogoRemovalJob(
                    str(source),
                    str(output),
                    [str(logo)],
                    LogoRemovalOptions(
                        detection_mode="visual",
                        similarity=0.70,
                        min_width_pct=10,
                        max_width_pct=30,
                        render_dpi=120,
                    ),
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.match_count, 1)
            self.assertEqual(result.visual_matches, 1)

            cleaned = fitz.open(output)
            try:
                pix = cleaned[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
                rendered = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                sample = rendered.crop((345, 30, 450, 75))
                average = ImageStat.Stat(sample).mean
                self.assertGreater(min(average), 235)
            finally:
                cleaned.close()

    def test_visual_detection_tolerates_resize_blur_compression_and_margin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = self._make_logo(root / "logo.jpg", transparent=False)
            with Image.open(logo) as logo_image:
                occurrence = logo_image.convert("RGB").resize(
                    (285, 114),
                    Image.Resampling.LANCZOS,
                )
            occurrence = occurrence.filter(ImageFilter.GaussianBlur(1.35))
            framed = Image.new("RGB", (390, 190), "white")
            framed.paste(occurrence, (52, 38))
            scan = Image.new("RGB", (1200, 1600), "white")
            ImageDraw.Draw(scan).text((80, 280), "DOCUMENTO ESCANEADO", fill="black")
            scan.paste(framed, (690, 90))
            scan_path = root / "scan_compressed.jpg"
            scan.save(scan_path, quality=76)

            source = root / "input.pdf"
            output = root / "output.pdf"
            doc = fitz.open()
            page = doc.new_page(width=600, height=800)
            page.insert_image(page.rect, filename=str(scan_path))
            doc.save(source)
            doc.close()

            result = LogoRemovalEngine().run_job(
                LogoRemovalJob(
                    str(source),
                    str(output),
                    [str(logo)],
                    LogoRemovalOptions(
                        detection_mode="visual",
                        min_width_pct=8,
                        max_width_pct=32,
                    ),
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.visual_matches, 1)

    def test_embedded_detection_ignores_uniform_internal_margin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = self._make_logo(root / "logo.jpg", transparent=False)
            with Image.open(logo) as logo_image:
                occurrence = logo_image.convert("RGB").resize(
                    (270, 108),
                    Image.Resampling.LANCZOS,
                )
            occurrence = occurrence.filter(ImageFilter.GaussianBlur(0.7))
            framed = Image.new("RGB", (450, 210), "white")
            framed.paste(occurrence, (90, 51))
            embedded = root / "logo_with_margin.jpg"
            framed.save(embedded, quality=74)

            source = root / "input.pdf"
            output = root / "output.pdf"
            doc = fitz.open()
            page = doc.new_page(width=500, height=700)
            page.insert_text((40, 180), "TEXTO CONSERVADO")
            page.insert_image(fitz.Rect(245, 24, 470, 129), filename=str(embedded))
            doc.save(source)
            doc.close()

            result = LogoRemovalEngine().run_job(
                LogoRemovalJob(
                    str(source),
                    str(output),
                    [str(logo)],
                    LogoRemovalOptions(detection_mode="embedded"),
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.embedded_matches, 1)
            cleaned = fitz.open(output)
            try:
                self.assertIn("TEXTO CONSERVADO", cleaned[0].get_text())
                self.assertEqual(cleaned[0].get_images(full=True), [])
            finally:
                cleaned.close()

    def test_custom_page_scope_only_changes_selected_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = self._make_logo(root / "logo.png")
            source = root / "pages.pdf"
            output = root / "out" / "pages_sin_logo.pdf"
            doc = fitz.open()
            for _ in range(3):
                page = doc.new_page(width=360, height=260)
                page.insert_image(fitz.Rect(210, 20, 330, 72), filename=str(logo))
            doc.save(source)
            doc.close()

            result = LogoRemovalEngine().run_job(
                LogoRemovalJob(
                    str(source),
                    str(output),
                    [str(logo)],
                    LogoRemovalOptions(
                        detection_mode="embedded",
                        page_scope="custom",
                        custom_pages="2",
                    ),
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.match_count, 1)
            cleaned = fitz.open(output)
            try:
                self.assertEqual(len(cleaned[0].get_images(full=True)), 1)
                self.assertEqual(len(cleaned[1].get_images(full=True)), 0)
                self.assertEqual(len(cleaned[2].get_images(full=True)), 1)
            finally:
                cleaned.close()

    def test_rotated_page_uses_native_image_coordinates_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = self._make_logo(root / "logo.png")
            source = root / "rotated.pdf"
            output = root / "out" / "rotated_sin_logo.pdf"
            doc = fitz.open()
            page = doc.new_page(width=400, height=300)
            page.insert_text((32, 120), "TEXTO CONSERVADO")
            page.insert_image(fitz.Rect(250, 20, 360, 64), filename=str(logo))
            page.set_rotation(90)
            doc.save(source)
            doc.close()

            result = LogoRemovalEngine().run_job(
                LogoRemovalJob(
                    str(source),
                    str(output),
                    [str(logo)],
                    LogoRemovalOptions(detection_mode="embedded"),
                )
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.match_count, 1)
            cleaned = fitz.open(output)
            try:
                self.assertIn("TEXTO CONSERVADO", cleaned[0].get_text())
                self.assertEqual(cleaned[0].get_images(full=True), [])
            finally:
                cleaned.close()

    def test_hybrid_mode_keeps_working_without_opencv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = self._make_logo(root / "logo.png")
            source = root / "input.pdf"
            output = root / "out" / "input_sin_logo.pdf"
            doc = fitz.open()
            page = doc.new_page(width=360, height=260)
            page.insert_text((30, 100), "TEXTO CONSERVADO")
            page.insert_image(fitz.Rect(210, 20, 330, 68), filename=str(logo))
            doc.save(source)
            doc.close()

            with patch.object(logo_removal_engine, "cv2", None):
                result = LogoRemovalEngine().run_job(
                    LogoRemovalJob(
                        str(source),
                        str(output),
                        [str(logo)],
                        LogoRemovalOptions(detection_mode="hybrid"),
                    )
                )

            self.assertTrue(result.success, result.error)
            self.assertTrue(output.exists())
            self.assertEqual(result.embedded_matches, 1)

    def test_failed_result_keeps_target_name_and_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = self._make_logo(root / "logo.png")
            output = root / "out" / "resultado.pdf"
            result = LogoRemovalEngine().run_job(
                LogoRemovalJob(
                    str(root / "missing.pdf"),
                    str(output),
                    [str(logo)],
                )
            )

            self.assertFalse(result.success)
            self.assertEqual(result.output_path, str(output))
            self.assertIn("no existe", result.error.lower())

    def test_page_selection_parser(self) -> None:
        self.assertEqual(parse_page_selection("all", "", 4), [0, 1, 2, 3])
        self.assertEqual(parse_page_selection("first", "", 4), [0])
        self.assertEqual(parse_page_selection("custom", "1, 3-4", 4), [0, 2, 3])
        self.assertEqual(parse_page_selection("custom", "2-", 4), [1, 2, 3])

    @staticmethod
    def _make_logo(path: Path, *, transparent: bool = True) -> Path:
        background = (255, 255, 255, 0) if transparent else (255, 255, 255, 255)
        image = Image.new("RGBA", (180, 72), background)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (4, 4, 176, 68),
            radius=10,
            fill=(18, 120, 196, 255),
        )
        draw.ellipse((18, 14, 66, 62), fill=(246, 196, 28, 255))
        draw.rectangle((82, 25, 158, 47), fill=(255, 255, 255, 255))
        if path.suffix.lower() in {".jpg", ".jpeg"}:
            image.convert("RGB").save(path, quality=94)
        elif path.suffix.lower() == ".webp":
            image.convert("RGB").save(path, format="WEBP", quality=94)
        else:
            image.save(path)
        return path


if __name__ == "__main__":
    unittest.main()
