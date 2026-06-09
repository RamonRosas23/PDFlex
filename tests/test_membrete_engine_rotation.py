"""Tests de regresión de rotación para MembreteEngine.

Verifica que páginas con /Rotate=0/90/180/270 se membretean
con orientación y dimensiones correctas (sin overflow, aspect ratio OK).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from core.margin_detector import MembreteMargins
from core.membrete_engine import MembreteEngine, MembreteJob


# ================================================================== #
#  Helpers
# ================================================================== #

def _make_letterhead(path: Path, width: float = 595.0, height: float = 842.0) -> Path:
    """Crea un membrete A4 portrait sin rotación."""
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    # Encabezado y pie claramente diferenciados
    page.draw_rect(
        fitz.Rect(0, 0, width, 80),
        color=(0.2, 0.4, 0.8),
        fill=(0.2, 0.4, 0.8),
    )
    page.draw_rect(
        fitz.Rect(0, height - 60, width, height),
        color=(0.2, 0.4, 0.8),
        fill=(0.2, 0.4, 0.8),
    )
    page.insert_text((20, 50), "MEMBRETE OFICIAL", fontsize=18, color=(1, 1, 1))
    doc.save(str(path))
    doc.close()
    return path


def _make_source_pdf(
    path: Path,
    mediabox_w: float,
    mediabox_h: float,
    rotation: int,
) -> Path:
    """Crea un PDF con MediaBox dado y /Rotate aplicado.

    Ejemplo para PDF escaneado landscape con display portrait:
        mediabox_w=842, mediabox_h=595, rotation=90
    """
    doc = fitz.open()
    page = doc.new_page(width=mediabox_w, height=mediabox_h)
    page.insert_text((20, 40), f"ROT={rotation}", fontsize=24, color=(1, 0, 0))
    page.draw_rect(fitz.Rect(0, 0, 80, 80), color=(1, 0, 0))
    doc.save(str(path))
    doc.close()

    if rotation != 0:
        # saveIncr() es obligatorio al guardar sobre el mismo archivo en PyMuPDF
        doc2 = fitz.open(str(path))
        try:
            doc2[0].set_rotation(rotation)
            doc2.saveIncr()
        finally:
            doc2.close()
    return path


def _get_content_image_bbox(
    out_doc: fitz.Document, page_idx: int = 0
) -> fitz.Rect | None:
    """Devuelve el bbox de la imagen de contenido (la más pequeña del par lh+content).

    Cuando rotation=0, show_pdf_page no inserta imágenes → devuelve None.
    """
    page = out_doc[page_idx]
    images = page.get_image_info(hashes=False)
    if not images:
        return None
    # La imagen de contenido es la de menor área
    images_sorted = sorted(
        images,
        key=lambda i: (i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]),
    )
    b = images_sorted[0]["bbox"]
    return fitz.Rect(b[0], b[1], b[2], b[3])


_MARGINS = MembreteMargins(top_pt=80.0, bottom_pt=60.0, left_pt=18.0, right_pt=18.0)


# ================================================================== #
#  Tests
# ================================================================== #

class TestMembreteEngineRotation(unittest.TestCase):

    def _run_membrete(self, tmp: Path, src_path: Path) -> fitz.Document:
        """Ejecuta el motor y retorna el documento de salida abierto."""
        lh_path = _make_letterhead(tmp / "lh.pdf")
        out_path = tmp / "out.pdf"
        engine = MembreteEngine()
        results = engine.run_batch(
            [MembreteJob(pdf_path=str(src_path), output_path=str(out_path))],
            str(lh_path),
            _MARGINS,
        )
        self.assertTrue(results[0].success, f"run_batch failed: {results[0].error}")
        return fitz.open(str(out_path))

    # ------------------------------------------------------------------ #
    #  rotation=0 — baseline, sin cambio en comportamiento
    # ------------------------------------------------------------------ #

    def test_rotation_0_produces_one_page_within_bounds(self) -> None:
        """Página sin rotación: output tiene 1 página con dimensiones del membrete."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            src = _make_source_pdf(
                tmp / "src.pdf", mediabox_w=595, mediabox_h=842, rotation=0
            )
            out = self._run_membrete(tmp, src)
            try:
                self.assertEqual(out.page_count, 1)
                p = out[0]
                self.assertAlmostEqual(p.rect.width, 595.0, delta=1.0)
                self.assertAlmostEqual(p.rect.height, 842.0, delta=1.0)
            finally:
                out.close()

    # ------------------------------------------------------------------ #
    #  rotation=90 — caso principal: PDF escaneado landscape → display portrait
    # ------------------------------------------------------------------ #

    def test_rotation_90_content_within_page_bounds(self) -> None:
        """Páginas con /Rotate=90 no deben generar overflow en la página de salida.

        Caso real: PDF escaneado con MediaBox landscape (842×595) + /Rotate=90
        → display portrait (595×842). Sin el fix, show_pdf_page produce ~191 pt
        de overflow más allá del borde derecho.
        """
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            # MediaBox landscape (842×595) + /Rotate=90 → display portrait (595×842)
            src = _make_source_pdf(
                tmp / "src.pdf", mediabox_w=842, mediabox_h=595, rotation=90
            )

            # Verificar que el PDF source tiene la rotación correcta
            check = fitz.open(str(src))
            try:
                self.assertEqual(check[0].rotation, 90)
                self.assertAlmostEqual(check[0].rect.width, 595.0, delta=1.0)
                self.assertAlmostEqual(check[0].rect.height, 842.0, delta=1.0)
            finally:
                check.close()

            out = self._run_membrete(tmp, src)
            try:
                self.assertEqual(out.page_count, 1)
                p = out[0]
                page_w = p.rect.width   # 595
                page_h = p.rect.height  # 842

                bbox = _get_content_image_bbox(out)
                self.assertIsNotNone(bbox, "Se esperaba imagen de contenido en la página")
                assert bbox is not None

                # Sin overflow
                self.assertLessEqual(
                    bbox.x1, page_w + 1.0,
                    f"Overflow derecho: bbox.x1={bbox.x1:.1f} > page_w={page_w:.1f}",
                )
                self.assertLessEqual(
                    bbox.y1, page_h + 1.0,
                    f"Overflow inferior: bbox.y1={bbox.y1:.1f} > page_h={page_h:.1f}",
                )
                self.assertGreaterEqual(bbox.x0, -1.0)
                self.assertGreaterEqual(bbox.y0, -1.0)

                # Relación de aspecto: display portrait → contenido más alto que ancho
                content_w = bbox.x1 - bbox.x0
                content_h = bbox.y1 - bbox.y0
                self.assertGreater(
                    content_h, content_w,
                    f"Contenido debería ser portrait (h>w), "
                    f"got w={content_w:.1f} h={content_h:.1f}",
                )
            finally:
                out.close()

    # ------------------------------------------------------------------ #
    #  rotation=180 — contenido invertido (al revés)
    # ------------------------------------------------------------------ #

    def test_rotation_180_content_within_page_bounds(self) -> None:
        """Páginas con /Rotate=180: contenido dentro de bounds, aspecto conservado."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            # MediaBox portrait (595×842) + /Rotate=180 → display portrait (595×842)
            src = _make_source_pdf(
                tmp / "src.pdf", mediabox_w=595, mediabox_h=842, rotation=180
            )

            check = fitz.open(str(src))
            try:
                self.assertEqual(check[0].rotation, 180)
            finally:
                check.close()

            out = self._run_membrete(tmp, src)
            try:
                self.assertEqual(out.page_count, 1)
                p = out[0]
                page_w = p.rect.width
                page_h = p.rect.height

                bbox = _get_content_image_bbox(out)
                self.assertIsNotNone(bbox)
                assert bbox is not None

                self.assertLessEqual(bbox.x1, page_w + 1.0)
                self.assertLessEqual(bbox.y1, page_h + 1.0)
                self.assertGreaterEqual(bbox.x0, -1.0)
                self.assertGreaterEqual(bbox.y0, -1.0)

                # Aspecto portrait conservado
                content_w = bbox.x1 - bbox.x0
                content_h = bbox.y1 - bbox.y0
                self.assertGreater(content_h, content_w)
            finally:
                out.close()

    # ------------------------------------------------------------------ #
    #  rotation=270 — espejo de 90
    # ------------------------------------------------------------------ #

    def test_rotation_270_content_within_page_bounds(self) -> None:
        """Páginas con /Rotate=270: no overflow, aspecto portrait."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            # MediaBox landscape (842×595) + /Rotate=270 → display portrait (595×842)
            src = _make_source_pdf(
                tmp / "src.pdf", mediabox_w=842, mediabox_h=595, rotation=270
            )

            check = fitz.open(str(src))
            try:
                self.assertEqual(check[0].rotation, 270)
            finally:
                check.close()

            out = self._run_membrete(tmp, src)
            try:
                p = out[0]
                page_w = p.rect.width
                page_h = p.rect.height

                bbox = _get_content_image_bbox(out)
                self.assertIsNotNone(bbox)
                assert bbox is not None

                self.assertLessEqual(bbox.x1, page_w + 1.0)
                self.assertLessEqual(bbox.y1, page_h + 1.0)

                content_w = bbox.x1 - bbox.x0
                content_h = bbox.y1 - bbox.y0
                self.assertGreater(content_h, content_w)
            finally:
                out.close()

    # ------------------------------------------------------------------ #
    #  Documento mixto: páginas con distintas rotaciones
    # ------------------------------------------------------------------ #

    def test_mixed_rotations_all_pages_within_bounds(self) -> None:
        """Documento con rotaciones 0/90/180/270: todas las páginas dentro de bounds."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)

            mixed_path = tmp / "mixed.pdf"
            configs = [
                (595, 842, 0),    # portrait normal
                (842, 595, 90),   # landscape MediaBox → display portrait
                (595, 842, 180),  # portrait al revés
                (842, 595, 270),  # landscape MediaBox → display portrait
            ]

            doc = fitz.open()
            for mw, mh, _ in configs:
                page = doc.new_page(width=mw, height=mh)
                page.insert_text((20, 40), "TEST", fontsize=20, color=(1, 0, 0))
            doc.save(str(mixed_path))
            doc.close()

            doc2 = fitz.open(str(mixed_path))
            try:
                for i, (_, _, rot) in enumerate(configs):
                    doc2[i].set_rotation(rot)
                doc2.saveIncr()
            finally:
                doc2.close()

            lh_path = _make_letterhead(tmp / "lh.pdf")
            out_path = tmp / "out.pdf"
            engine = MembreteEngine()
            results = engine.run_batch(
                [MembreteJob(pdf_path=str(mixed_path), output_path=str(out_path))],
                str(lh_path),
                _MARGINS,
            )
            self.assertTrue(results[0].success)
            self.assertEqual(results[0].page_count, 4)

            out = fitz.open(str(out_path))
            try:
                self.assertEqual(out.page_count, 4)
                for pg_idx in range(out.page_count):
                    p = out[pg_idx]
                    pw, ph = p.rect.width, p.rect.height
                    for img in p.get_image_info(hashes=False):
                        b = img["bbox"]
                        self.assertLessEqual(
                            b[2], pw + 1.0,
                            f"Pág {pg_idx}: overflow derecho x1={b[2]:.1f} > pw={pw:.1f}",
                        )
                        self.assertLessEqual(
                            b[3], ph + 1.0,
                            f"Pág {pg_idx}: overflow inferior y1={b[3]:.1f} > ph={ph:.1f}",
                        )
            finally:
                out.close()

    # ------------------------------------------------------------------ #
    #  Membrete con rotación (raro pero posible)
    # ------------------------------------------------------------------ #

    def test_rotated_letterhead_produces_correct_output(self) -> None:
        """Membrete con /Rotate=90 debe producir página con dimensiones de display."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)

            # Membrete landscape MediaBox (842×595) + /Rotate=90 → display portrait (595×842)
            lh_path = tmp / "lh_rotated.pdf"
            doc = fitz.open()
            page = doc.new_page(width=842, height=595)
            page.draw_rect(
                fitz.Rect(0, 0, 842, 60), color=(0, 0.6, 0), fill=(0, 0.6, 0)
            )
            doc.save(str(lh_path))
            doc.close()
            doc2 = fitz.open(str(lh_path))
            try:
                doc2[0].set_rotation(90)
                doc2.saveIncr()
            finally:
                doc2.close()

            src_path = _make_source_pdf(
                tmp / "src.pdf", mediabox_w=595, mediabox_h=842, rotation=0
            )
            out_path = tmp / "out.pdf"

            engine = MembreteEngine()
            results = engine.run_batch(
                [MembreteJob(pdf_path=str(src_path), output_path=str(out_path))],
                str(lh_path),
                _MARGINS,
            )
            self.assertTrue(results[0].success, results[0].error)

            out = fitz.open(str(out_path))
            try:
                p = out[0]
                # Output debe tener las dimensiones de DISPLAY del membrete
                self.assertAlmostEqual(p.rect.width, 595.0, delta=1.0)
                self.assertAlmostEqual(p.rect.height, 842.0, delta=1.0)
            finally:
                out.close()


if __name__ == "__main__":
    unittest.main()
