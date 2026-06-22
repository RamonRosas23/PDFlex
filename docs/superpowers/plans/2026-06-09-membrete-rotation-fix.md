# Membrete Engine: Corrección Robusta de Rotación PDF

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corregir el bug de rotación en `membrete_engine.py` donde páginas con `/Rotate=90/180/270` (PDFs escaneados tipo dúplex, documentos con orientación mixta) aparecen transpuestas o al revés al membretar.

**Architecture:** El bug está en `show_pdf_page()` de PyMuPDF 1.27, que calcula el scale con `page.rect` (rotation-aware) pero aplica ese scale sobre las coordenadas del MediaBox (pre-rotación), ignorando `/Rotate`. La solución agrega un helper `_place_page()` que para `rotation=0` usa `show_pdf_page` (vectorial, sin cambio), y para `rotation≠0` renderiza con `get_pixmap()` (que sí aplica `/Rotate` correctamente) e inserta con `insert_image()` en el rect ya calculado. No se cambia ninguna otra herramienta — todas las demás ya manejan rotación correctamente.

**Tech Stack:** PyMuPDF (fitz) ≥1.24, Python 3.11+, unittest, pytest

---

## Mapa de archivos

| Archivo | Acción | Responsabilidad del cambio |
|---|---|---|
| `core/membrete_engine.py` | **Modificar** | Agregar constante `_RENDER_DPI`, helper `_place_page()`, actualizar 2 líneas en `_process_job()` |
| `tests/test_membrete_engine_rotation.py` | **Crear** | Tests TDD para rotaciones 0/90/180/270 y documento mixto |

Ningún otro archivo se toca.

---

## Task 1: Tests TDD para rotaciones (deben FALLAR antes del fix)

**Files:**
- Create: `tests/test_membrete_engine_rotation.py`

> Estos tests validan que el contenido membretado:
> - (a) quede dentro de los bounds de la página (sin overflow)
> - (b) tenga la relación de aspecto correcta para su orientación de display
>
> El test _no_ verifica contenido de píxeles — solo geometría, que es lo que el bug rompe.

- [ ] **Step 1: Crear el archivo de tests**

```python
# tests/test_membrete_engine_rotation.py
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
    page.draw_rect(fitz.Rect(0, 0, width, 80), color=(0.2, 0.4, 0.8), fill=(0.2, 0.4, 0.8))
    page.draw_rect(fitz.Rect(0, height - 60, width, height), color=(0.2, 0.4, 0.8), fill=(0.2, 0.4, 0.8))
    page.insert_text((20, 50), "MEMBRETE OFICIAL", fontsize=18, color=(1, 1, 1))
    doc.save(str(path))
    doc.close()
    return path


def _make_source_pdf(path: Path, mediabox_w: float, mediabox_h: float, rotation: int) -> Path:
    """Crea un PDF con MediaBox dado y /Rotate aplicado.

    Ejemplo para PDF escaneado landscape con display portrait:
        mediabox_w=842, mediabox_h=595, rotation=90
    """
    doc = fitz.open()
    page = doc.new_page(width=mediabox_w, height=mediabox_h)
    # Marca de orientación: texto en esquina superior-izquierda del MediaBox
    page.insert_text((20, 40), f"ROT={rotation}", fontsize=24, color=(1, 0, 0))
    page.draw_rect(fitz.Rect(0, 0, 80, 80), color=(1, 0, 0))
    doc.save(str(path))
    doc.close()

    # Aplicar rotación si corresponde
    if rotation != 0:
        doc2 = fitz.open(str(path))
        doc2[0].set_rotation(rotation)
        doc2.save(str(path))
        doc2.close()
    return path


def _get_content_image_bbox(out_doc: fitz.Document, page_idx: int = 0) -> fitz.Rect | None:
    """Devuelve el bbox de la imagen de contenido (la más pequeña del par lh+content).

    Cuando rotation=0, show_pdf_page no inserta imágenes → devuelve None.
    """
    page = out_doc[page_idx]
    images = page.get_image_info(hashes=False)
    if not images:
        return None
    # La imagen de contenido es la de menor área (el membrete rasterizado ocupa la página completa)
    images_sorted = sorted(images, key=lambda i: (i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]))
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
        """Página sin rotación: output tiene exactamente 1 página dentro de bounds."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            src = _make_source_pdf(tmp / "src.pdf", mediabox_w=595, mediabox_h=842, rotation=0)
            out = self._run_membrete(tmp, src)
            try:
                self.assertEqual(out.page_count, 1)
                p = out[0]
                # La página output tiene dimensiones del membrete (595×842)
                self.assertAlmostEqual(p.rect.width, 595.0, delta=1.0)
                self.assertAlmostEqual(p.rect.height, 842.0, delta=1.0)
            finally:
                out.close()

    # ------------------------------------------------------------------ #
    #  rotation=90 — caso principal: PDF escaneado landscape → display portrait
    # ------------------------------------------------------------------ #

    def test_rotation_90_content_within_page_bounds(self) -> None:
        """Páginas con /Rotate=90 deben quedar dentro de los bounds de la página de salida.

        Caso real: PDF escaneado con MediaBox landscape (842×595) y /Rotate=90
        para display portrait. Sin el fix, show_pdf_page produce overflow de
        ~191 pt más allá del borde derecho de la página (595 pt).
        """
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            # MediaBox landscape (842×595) + /Rotate=90 → display portrait (595×842)
            src = _make_source_pdf(tmp / "src.pdf", mediabox_w=842, mediabox_h=595, rotation=90)

            # Verificar que el PDF source tiene la rotación correcta
            check = fitz.open(str(src))
            self.assertEqual(check[0].rotation, 90)
            self.assertAlmostEqual(check[0].rect.width, 595.0, delta=1.0)   # display portrait
            self.assertAlmostEqual(check[0].rect.height, 842.0, delta=1.0)
            check.close()

            out = self._run_membrete(tmp, src)
            try:
                self.assertEqual(out.page_count, 1)
                p = out[0]
                page_w = p.rect.width   # 595
                page_h = p.rect.height  # 842

                bbox = _get_content_image_bbox(out)
                self.assertIsNotNone(bbox, "Se esperaba imagen de contenido en la página")
                assert bbox is not None  # para type checker

                # Sin overflow
                self.assertLessEqual(bbox.x1, page_w + 1.0,
                    f"Overflow derecho: bbox.x1={bbox.x1:.1f} > page_w={page_w:.1f}")
                self.assertLessEqual(bbox.y1, page_h + 1.0,
                    f"Overflow inferior: bbox.y1={bbox.y1:.1f} > page_h={page_h:.1f}")
                self.assertGreaterEqual(bbox.x0, -1.0)
                self.assertGreaterEqual(bbox.y0, -1.0)

                # Relación de aspecto: el contenido (display portrait 595×842)
                # debe aparecer más alto que ancho dentro de la zona segura
                content_w = bbox.x1 - bbox.x0
                content_h = bbox.y1 - bbox.y0
                self.assertGreater(content_h, content_w,
                    f"Contenido debería ser portrait (h>w), got w={content_w:.1f} h={content_h:.1f}")
            finally:
                out.close()

    # ------------------------------------------------------------------ #
    #  rotation=180 — contenido al revés
    # ------------------------------------------------------------------ #

    def test_rotation_180_content_within_page_bounds(self) -> None:
        """Páginas con /Rotate=180: contenido debe quedar dentro de bounds."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            # MediaBox portrait (595×842) + /Rotate=180 → display portrait (595×842), al revés
            src = _make_source_pdf(tmp / "src.pdf", mediabox_w=595, mediabox_h=842, rotation=180)

            check = fitz.open(str(src))
            self.assertEqual(check[0].rotation, 180)
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

                # Relación de aspecto portrait conservada
                content_w = bbox.x1 - bbox.x0
                content_h = bbox.y1 - bbox.y0
                self.assertGreater(content_h, content_w)
            finally:
                out.close()

    # ------------------------------------------------------------------ #
    #  rotation=270 — espejo de 90
    # ------------------------------------------------------------------ #

    def test_rotation_270_content_within_page_bounds(self) -> None:
        """Páginas con /Rotate=270: no overflow y aspecto portrait."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            # MediaBox landscape (842×595) + /Rotate=270 → display portrait (595×842)
            src = _make_source_pdf(tmp / "src.pdf", mediabox_w=842, mediabox_h=595, rotation=270)

            check = fitz.open(str(src))
            self.assertEqual(check[0].rotation, 270)
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
        """Documento con rotaciones mixtas: todas las páginas dentro de bounds."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)

            # Crear PDF de 4 páginas con rotaciones distintas
            mixed_path = tmp / "mixed.pdf"
            doc = fitz.open()
            configs = [
                (595, 842, 0),    # portrait normal
                (842, 595, 90),   # landscape → portrait
                (595, 842, 180),  # portrait al revés
                (842, 595, 270),  # landscape → portrait (otro sentido)
            ]
            for mw, mh, rot in configs:
                page = doc.new_page(width=mw, height=mh)
                page.insert_text((20, 40), f"ROT={rot}", fontsize=20, color=(1, 0, 0))
            doc.save(str(mixed_path))
            doc.close()

            # Aplicar rotaciones
            doc2 = fitz.open(str(mixed_path))
            for i, (_, _, rot) in enumerate(configs):
                doc2[i].set_rotation(rot)
            doc2.save(str(mixed_path))
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

                    imgs = p.get_image_info(hashes=False)
                    for img in imgs:
                        b = img["bbox"]
                        self.assertLessEqual(b[2], pw + 1.0,
                            f"Página {pg_idx}: overflow derecho x1={b[2]:.1f} > pw={pw:.1f}")
                        self.assertLessEqual(b[3], ph + 1.0,
                            f"Página {pg_idx}: overflow inferior y1={b[3]:.1f} > ph={ph:.1f}")
            finally:
                out.close()

    # ------------------------------------------------------------------ #
    #  Membrete con rotación (raro pero posible)
    # ------------------------------------------------------------------ #

    def test_rotated_letterhead_produces_correct_output(self) -> None:
        """Membrete con /Rotate=90 debe producir página con dimensiones correctas."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)

            # Membrete landscape (842×595) + /Rotate=90 → display portrait (595×842)
            lh_path = tmp / "lh_rotated.pdf"
            doc = fitz.open()
            page = doc.new_page(width=842, height=595)
            page.draw_rect(fitz.Rect(0, 0, 842, 60), color=(0, 0.6, 0), fill=(0, 0.6, 0))
            doc.save(str(lh_path))
            doc.close()
            doc2 = fitz.open(str(lh_path))
            doc2[0].set_rotation(90)
            doc2.save(str(lh_path))
            doc2.close()

            src_path = _make_source_pdf(tmp / "src.pdf", mediabox_w=595, mediabox_h=842, rotation=0)
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
                # El output debe tener las dimensiones de DISPLAY del membrete
                self.assertAlmostEqual(p.rect.width, 595.0, delta=1.0)
                self.assertAlmostEqual(p.rect.height, 842.0, delta=1.0)
            finally:
                out.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Ejecutar tests para verificar que FALLAN (confirmar que el bug existe)**

```
cd C:\Desarrollo\CREATIVO\PDFlex
python -m pytest tests/test_membrete_engine_rotation.py -v
```

Salida esperada (los tests deben FALLAR antes del fix):
```
FAILED tests/test_membrete_engine_rotation.py::TestMembreteEngineRotation::test_rotation_90_content_within_page_bounds
FAILED tests/test_membrete_engine_rotation.py::TestMembreteEngineRotation::test_rotation_180_content_within_page_bounds
FAILED tests/test_membrete_engine_rotation.py::TestMembreteEngineRotation::test_rotation_270_content_within_page_bounds
FAILED tests/test_membrete_engine_rotation.py::TestMembreteEngineRotation::test_mixed_rotations_all_pages_within_bounds
FAILED tests/test_membrete_engine_rotation.py::TestMembreteEngineRotation::test_rotated_letterhead_produces_correct_output
PASSED tests/test_membrete_engine_rotation.py::TestMembreteEngineRotation::test_rotation_0_produces_one_page_within_bounds
```

> **Nota:** Si `test_rotation_0` falla también, hay algo más roto. `test_rotation_0` es el baseline y debería pasar siempre.

- [ ] **Step 3: Commit de los tests (código de test antes de implementación)**

```bash
git add tests/test_membrete_engine_rotation.py
git commit -m "test: add rotation regression tests for membrete engine (red phase TDD)"
```

---

## Task 2: Implementar el fix en `core/membrete_engine.py`

**Files:**
- Modify: `core/membrete_engine.py`

**Diagnóstico exacto del bug:**

Para un PDF con MediaBox landscape (842×595) y `/Rotate=90`:
- `page.rect` → (0, 0, 595, 842) — dimensiones de DISPLAY ✓
- `_fit_rect(safe, 595, 842)` calcula target portrait correcto
- `show_pdf_page(target, src, page_idx)` — IGNORA `/Rotate`:
  - Calcula scale = min(target.w/595, target.h/842) ≈ 0.742 (correcto)
  - Pero aplica: `MediaBox.w × scale = 842 × 0.742 = 625 pt` (INCORRECTO, debería ser ~454)
  - Resultado: imagen de 716×454 landscape con 191 pt de overflow

**La solución:**
`page.get_pixmap()` sí aplica `/Rotate` al renderizar. El pixmap resultante tiene
dimensiones `page.rect × scale` (portrait para este caso). Insertarlo con `insert_image(target)`
coloca el contenido correctamente orientado dentro del área ya calculada.

- [ ] **Step 1: Reemplazar el módulo completo**

Reemplazar `core/membrete_engine.py` con el siguiente contenido (los cambios son:
líneas 1-18 del docstring actualizado, constante `_RENDER_DPI`, función `_place_page()`,
y 2 líneas en `_process_job`):

```python
"""Motor de membretado masivo de PDFs.

Para cada documento de entrada, crea un nuevo PDF donde cada página es:
  1. Una copia de la hoja membretada (siempre la primera página del membrete).
  2. El contenido de la página original superpuesto dentro de la zona segura,
     escalado con relación de aspecto conservada y centrado.

La superposición utiliza _place_page():
  - rotation=0: fitz.Page.show_pdf_page() — copia vectorial, calidad perfecta.
  - rotation≠0: get_pixmap() + insert_image() a _RENDER_DPI — necesario porque
    show_pdf_page() en PyMuPDF 1.27 ignora /Rotate al calcular la posición del
    contenido, produciendo overflow y transposición de dimensiones.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import fitz

from .margin_detector import MembreteMargins


# ====================================================================== #
#  Tipos de datos
# ====================================================================== #

@dataclass
class MembreteJob:
    """Un documento a membretar."""
    pdf_path: str
    output_path: str


@dataclass
class MembreteJobResult:
    """Resultado de un MembreteJob. Compatible con GenericPdfViewer."""
    job: MembreteJob
    output_path: str = ""
    success: bool = True
    error: str = ""
    page_count: int = 0


# ====================================================================== #
#  Constantes
# ====================================================================== #

# DPI para rasterizar páginas con /Rotate≠0 vía get_pixmap().
# 150 DPI produce ~1275×2008 px para una página A4 portrait, adecuado para
# impresión de oficina y documentos legales.
_RENDER_DPI: float = 150.0


# ====================================================================== #
#  Motor
# ====================================================================== #

class MembreteEngine:
    """Aplica un membrete a cada página de los documentos indicados."""

    def run_batch(
        self,
        jobs: List[MembreteJob],
        letterhead_path: str,
        margins: MembreteMargins,
        progress: Optional[Callable[[int, int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> List[MembreteJobResult]:
        try:
            lh_doc = fitz.open(letterhead_path)
        except Exception as e:
            raise RuntimeError(f"No se pudo abrir el membrete: {e}")

        lh_page = lh_doc[0]
        lh_w = lh_page.rect.width   # dimensiones de DISPLAY (rotation-aware)
        lh_h = lh_page.rect.height

        # Zona segura (donde va el contenido del documento)
        safe = fitz.Rect(
            margins.left_pt,
            margins.top_pt,
            lh_w - margins.right_pt,
            lh_h - margins.bottom_pt,
        )

        results: List[MembreteJobResult] = []
        total = len(jobs)

        try:
            for i, job in enumerate(jobs):
                if should_cancel and should_cancel():
                    break
                if progress:
                    progress(i, total, f"Membretando: {Path(job.pdf_path).name}")
                result = self._process_job(
                    job,
                    lh_doc,
                    lh_w,
                    lh_h,
                    safe,
                    should_cancel=should_cancel,
                )
                results.append(result)
        finally:
            lh_doc.close()

        if progress and not (should_cancel and should_cancel()):
            progress(total, total, "Membretado completado")

        return results

    # ------------------------------------------------------------------ #

    def _process_job(
        self,
        job: MembreteJob,
        lh_doc: fitz.Document,
        lh_w: float,
        lh_h: float,
        safe: fitz.Rect,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> MembreteJobResult:
        try:
            src = fitz.open(job.pdf_path)
        except Exception as e:
            return MembreteJobResult(job=job, output_path="", success=False, error=str(e))

        out = fitz.open()

        try:
            for page_idx in range(src.page_count):
                if should_cancel and should_cancel():
                    raise _CancelledError()

                new_page = out.new_page(width=lh_w, height=lh_h)

                # 1. Fondo: copiar membrete completo
                _place_page(new_page, lh_doc, 0, new_page.rect)

                # 2. Superponer página del documento en la zona segura
                src_page = src[page_idx]
                target = _fit_rect(safe, src_page.rect.width, src_page.rect.height)
                _place_page(new_page, src, page_idx, target)

            out_path = Path(job.output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out.save(str(out_path), garbage=4, deflate=True)
            n_pages = src.page_count

        except _CancelledError:
            src.close()
            out.close()
            return MembreteJobResult(
                job=job,
                output_path="",
                success=False,
                error="Operación cancelada.",
            )
        except Exception as e:
            src.close()
            out.close()
            return MembreteJobResult(job=job, output_path="", success=False, error=str(e))
        finally:
            try:
                src.close()
                out.close()
            except Exception:
                pass

        return MembreteJobResult(
            job=job,
            output_path=job.output_path,
            success=True,
            page_count=n_pages,
        )


# ====================================================================== #
#  Utilidades geométricas y de renderizado
# ====================================================================== #

def _fit_rect(container: fitz.Rect, src_w: float, src_h: float) -> fitz.Rect:
    """Devuelve el rect que encaja src_w × src_h dentro de container
    conservando la relación de aspecto y centrando el resultado."""
    if src_w <= 0 or src_h <= 0:
        return container
    cw = container.width
    ch = container.height
    scale = min(cw / src_w, ch / src_h)
    fw = src_w * scale
    fh = src_h * scale
    x0 = container.x0 + (cw - fw) / 2
    y0 = container.y0 + (ch - fh) / 2
    return fitz.Rect(x0, y0, x0 + fw, y0 + fh)


def _place_page(
    dest_page: fitz.Page,
    src_doc: fitz.Document,
    page_idx: int,
    target: fitz.Rect,
    render_dpi: float = _RENDER_DPI,
) -> None:
    """Coloca src_doc[page_idx] en dest_page dentro de target.

    Para páginas con /Rotate=0 usa show_pdf_page (vectorial, calidad máxima).
    Para páginas con /Rotate≠0 renderiza a pixmap vía get_pixmap(), que sí
    aplica correctamente /Rotate, y luego inserta la imagen con insert_image().

    El bug de PyMuPDF 1.27 que justifica este helper:
      show_pdf_page() calcula el scale usando page.rect (rotation-aware) pero
      aplica ese scale sobre las coordenadas del MediaBox (pre-rotación). Para
      /Rotate=90/270 esto produce dimensiones transpuestas con overflow.
    """
    src_page = src_doc[page_idx]
    if src_page.rotation == 0:
        dest_page.show_pdf_page(target, src_doc, page_idx)
        return

    # Páginas rotadas: renderizar con orientación correcta.
    # get_pixmap() aplica /Rotate; el pixmap tiene dimensiones de page.rect.
    scale = render_dpi / 72.0
    mat = fitz.Matrix(scale, scale)
    pm = src_page.get_pixmap(matrix=mat, alpha=False)
    try:
        dest_page.insert_image(target, pixmap=pm)
    finally:
        del pm  # liberar memoria inmediatamente


class _CancelledError(Exception):
    pass
```

- [ ] **Step 2: Ejecutar los tests nuevos — deben pasar TODOS**

```
cd C:\Desarrollo\CREATIVO\PDFlex
python -m pytest tests/test_membrete_engine_rotation.py -v
```

Salida esperada:
```
PASSED tests/test_membrete_engine_rotation.py::TestMembreteEngineRotation::test_rotation_0_produces_one_page_within_bounds
PASSED tests/test_membrete_engine_rotation.py::TestMembreteEngineRotation::test_rotation_90_content_within_page_bounds
PASSED tests/test_membrete_engine_rotation.py::TestMembreteEngineRotation::test_rotation_180_content_within_page_bounds
PASSED tests/test_membrete_engine_rotation.py::TestMembreteEngineRotation::test_rotation_270_content_within_page_bounds
PASSED tests/test_membrete_engine_rotation.py::TestMembreteEngineRotation::test_mixed_rotations_all_pages_within_bounds
PASSED tests/test_membrete_engine_rotation.py::TestMembreteEngineRotation::test_rotated_letterhead_produces_correct_output

6 passed in X.XXs
```

- [ ] **Step 3: Ejecutar la suite completa (regresión)**

```
cd C:\Desarrollo\CREATIVO\PDFlex
python -m pytest tests/ -v --ignore=tests/test_membretado_window.py
```

> `test_membretado_window.py` requiere Qt offscreen y puede ser lento; se puede ejecutar
> por separado si se desea.

Salida esperada: todos los tests existentes siguen pasando.

- [ ] **Step 4: Commit final**

```bash
git add core/membrete_engine.py
git commit -m "fix: correct PDF rotation handling in membrete engine

show_pdf_page() in PyMuPDF 1.27 ignores /Rotate when computing content
placement coordinates, causing overflow and transposed dimensions for
scanned PDFs (e.g., landscape MediaBox + /Rotate=90).

Add _place_page() helper: for rotation=0 keeps show_pdf_page (vector
quality); for rotation≠0 uses get_pixmap()+insert_image() at 150 DPI,
which correctly applies /Rotate.

Affects letterhead placement and source page placement in _process_job.
All other tools (foleador, watermark, signature, organizer) already handle
rotation correctly via derotation_matrix or insert_pdf."
```

---

## Self-Review

### Spec coverage

| Requisito | Task que lo implementa |
|---|---|
| Corregir rotaciones 90/180/270 | Task 2 — `_place_page()` |
| No romper rotación=0 (vectorial) | Task 2 — rama `if rotation == 0` |
| Membrete con rotación | Task 1 test + Task 2 — `_place_page` para membrete |
| Documento con rotaciones mixtas | Task 1 `test_mixed_rotations_all_pages_within_bounds` |
| No afectar otras herramientas | Confirmado en análisis previo; no se cambia ningún otro archivo |
| TDD (tests antes del fix) | Task 1 antes de Task 2 |

### Placeholder scan

Sin TBD, sin "implement later", sin referencias a funciones no definidas.

### Type consistency

- `_place_page(dest_page, src_doc, page_idx, target, render_dpi)` — definida en Task 2, usada en Task 2 (`_process_job`)
- `_fit_rect(container, src_w, src_h)` — sin cambios, misma firma
- `_RENDER_DPI: float = 150.0` — definida en Task 2, usada como default en `_place_page`
- Helpers de tests: `_make_letterhead`, `_make_source_pdf`, `_get_content_image_bbox` — todos en Task 1

Todo consistente.
