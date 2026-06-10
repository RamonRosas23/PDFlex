# PDFlex Studio — Fase 0 (Spike de Riesgo) + Fase 1 Núcleo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir y validar el núcleo sin-UI de PDFlex Studio: geometría/derotación a prueba de balas (prueba reina), modelo de elementos/reglas/capas, historial undo, motores de texto e imagen, exportador verificado con respaldo, y proyecto editable `.flexproj`.

**Architecture:** Motor 100 % libre de Qt en `core/editor/` (igual que los engines existentes de la suite). Toda inserción pasa por `CoordinateMapper` (derotación centralizada). Exportador como caja negra validada releyendo el PDF generado. Spec: `docs/superpowers/specs/2026-06-09-pdflex-studio-editor-pdf-design.md`.

**Tech Stack:** Python 3.11+, PyMuPDF (fitz) ≥1.24, Pillow ≥10, pytest. Sin dependencias nuevas en esta parte (fontTools llega en Fase 2).

**Alcance de ESTE plan:** Fase 0 (Tasks 1–6) + Fase 1 núcleo (Tasks 7–16). La UI (canvas QGraphicsScene, paneles, EditorWindow, registro en launcher) va en el plan "Parte 2 — UI", que se escribe cuando este plan pase su gate. Razón: `shell/launcher.py` tiene cambios WIP sin commitear del usuario; no se toca ningún archivo existente en este plan — **solo archivos nuevos**.

**Decisión registrada (desviación del spec §10.4):** `HistoryStack` se implementa en Python puro (sin `QUndoStack`) — el spec ya exigía que `history/` no importe Qt (§5.3); la fachada Qt era redundante. El spec se actualiza en la Task 11.

**Convenciones:**
- Rama: `feature/pdflex-studio` (creada en Task 0; el working tree del usuario tiene WIP sin commitear que NO se toca ni se commitea).
- Commits: convencionales en inglés (patrón del repo: `feat:`, `test:`, `fix:`) + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Cada commit añade SOLO archivos de este plan (`git add` con rutas explícitas, nunca `git add -A`).
- Tests: `python -m pytest tests/editor/ -v` (subdirectorio nuevo con su propio `conftest.py`).
- Tolerancia de la prueba reina: ≤ 0.5 pt para formas/imágenes (ruta pura de coordenadas); el texto valida contención en caja + dirección de escritura (las métricas de fuente impiden igualdad exacta).

---

## Parte A — FASE 0: Spike de riesgo

### Task 0: Rama y verificación del entorno

**Files:** ninguno (solo comandos).

- [x] **Step 0.1: Crear rama de feature**

```bash
git checkout -b feature/pdflex-studio
```

Expected: `Switched to a new branch 'feature/pdflex-studio'` (el WIP del usuario permanece intacto en el working tree).

- [x] **Step 0.2: Verificar versión de PyMuPDF (≥1.24 para insert_htmlbox)**

```bash
python -c "import fitz; print(fitz.pymupdf_version)"
```

Expected: `1.24.x` o superior. Si fuera menor: detenerse y reportar (requirements.txt ya exige ≥1.24, sería un entorno desactualizado → `pip install -U PyMuPDF`).

- [x] **Step 0.3: Verificar que pytest corre en el repo**

```bash
python -m pytest tests/test_smoke_tools.py -x -q --no-header
```

Expected: tests existentes pasan (o al menos colectan y corren). Anotar el patrón de fixtures Qt que usa el repo para reutilizarlo en Task 6.

---

### Task 1: Fixtures de PDFs con rotación y tamaños mixtos

**Files:**
- Create: `tests/editor/__init__.py` (vacío)
- Create: `tests/editor/conftest.py`
- Create: `tests/editor/test_fixtures.py`

- [x] **Step 1.1: Escribir el test de sanidad de los fixtures (falla: conftest no existe)**

`tests/editor/test_fixtures.py`:

```python
"""Sanidad de los fixtures: los PDFs generados tienen la rotación y tamaños esperados."""
import fitz
import pytest


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_pdf_has_rotation(make_pdf, rotation):
    path = make_pdf(rotations=[rotation])
    with fitz.open(path) as doc:
        page = doc[0]
        assert page.rotation == rotation
        # A4: 595x842. Con /Rotate 90/270 el rect display transpone dimensiones.
        if rotation in (90, 270):
            assert round(page.rect.width) == 842 and round(page.rect.height) == 595
        else:
            assert round(page.rect.width) == 595 and round(page.rect.height) == 842


def test_mixed_sizes_pdf(make_pdf):
    path = make_pdf(sizes=[(595, 842), (612, 1008), (420, 595)])  # A4, oficio, A5
    with fitz.open(path) as doc:
        assert doc.page_count == 3
        assert round(doc[1].rect.width) == 612 and round(doc[1].rect.height) == 1008
```

- [x] **Step 1.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_fixtures.py -v`
Expected: ERROR `fixture 'make_pdf' not found`.

- [x] **Step 1.3: Implementar el conftest con la fábrica de PDFs**

`tests/editor/conftest.py`:

```python
"""Fixtures compartidos del editor: fábrica de PDFs sintéticos con rotación/tamaños."""
from __future__ import annotations
from pathlib import Path

import fitz
import pytest


@pytest.fixture
def make_pdf(tmp_path):
    """Fábrica: crea un PDF en tmp con páginas controladas.

    make_pdf(rotations=[0, 90])            → 2 páginas A4 con /Rotate 0 y 90
    make_pdf(sizes=[(595,842),(612,1008)]) → 2 páginas de esos tamaños, /Rotate 0
    make_pdf(rotations=[90], with_text=True) → página con texto nativo de referencia
    """
    counter = {"n": 0}

    def _make(rotations=None, sizes=None, with_text=False) -> Path:
        rotations = rotations if rotations is not None else [0]
        sizes = sizes if sizes is not None else [(595.0, 842.0)] * len(rotations)
        if len(rotations) == 1 and len(sizes) > 1:
            rotations = rotations * len(sizes)
        counter["n"] += 1
        path = tmp_path / f"fixture_{counter['n']}.pdf"
        doc = fitz.open()
        for rot, (w, h) in zip(rotations, sizes):
            page = doc.new_page(width=w, height=h)
            if with_text:
                page.insert_text(fitz.Point(72, 72), "texto nativo de referencia",
                                 fontsize=11, fontname="helv")
            page.set_rotation(rot)
        doc.save(str(path))
        doc.close()
        return path

    return _make
```

`tests/editor/__init__.py`: archivo vacío.

- [x] **Step 1.4: Correr y verificar que pasa**

Run: `python -m pytest tests/editor/test_fixtures.py -v`
Expected: 5 PASS.

- [x] **Step 1.5: Commit**

```bash
git add tests/editor/__init__.py tests/editor/conftest.py tests/editor/test_fixtures.py
git commit -m "test(studio): add rotation/mixed-size PDF fixture factory for editor tests"
```

---

### Task 2: `PageGeometry` + `CoordinateMapper` (derotación centralizada)

**Files:**
- Create: `core/editor/__init__.py` (vacío)
- Create: `core/editor/geometry.py`
- Create: `tests/editor/test_geometry.py`

- [x] **Step 2.1: Escribir tests que fallan**

`tests/editor/test_geometry.py`:

```python
"""Geometría: round-trip display↔inserción en las 4 rotaciones, anclas y unidades."""
import fitz
import pytest

from core.editor.geometry import PageGeometry, display_rect_to_insertion, mm_to_pt, pt_to_mm


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_display_to_insertion_roundtrip(make_pdf, rotation):
    """rect_display → inserción → (rotation_matrix) → rect_display: identidad ≤1e-3 pt."""
    path = make_pdf(rotations=[rotation])
    with fitz.open(path) as doc:
        page = doc[0]
        geo = PageGeometry.from_page(0, page)
        rect_display = fitz.Rect(100, 150, 300, 250)
        rect_ins = display_rect_to_insertion(rect_display, geo)
        # Volver al espacio display con la matriz de rotación capturada
        back = rect_ins * fitz.Matrix(*geo.rotation_matrix)
        back.normalize()
        for got, want in zip(tuple(back), tuple(rect_display)):
            assert got == pytest.approx(want, abs=1e-3)


def test_rotation_0_is_identity(make_pdf):
    path = make_pdf(rotations=[0])
    with fitz.open(path) as doc:
        geo = PageGeometry.from_page(0, doc[0])
        r = fitz.Rect(10, 20, 30, 40)
        assert tuple(display_rect_to_insertion(r, geo)) == pytest.approx(tuple(r))


def test_page_geometry_captures_display_dims(make_pdf):
    path = make_pdf(rotations=[90])
    with fitz.open(path) as doc:
        geo = PageGeometry.from_page(0, doc[0])
        assert round(geo.width_pt) == 842 and round(geo.height_pt) == 595
        assert geo.rotation == 90


def test_units():
    assert mm_to_pt(25.4) == pytest.approx(72.0)
    assert pt_to_mm(72.0) == pytest.approx(25.4)
```

- [x] **Step 2.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_geometry.py -v`
Expected: ERROR `ModuleNotFoundError: No module named 'core.editor'`.

- [x] **Step 2.3: Implementar `geometry.py`**

`core/editor/geometry.py`:

```python
"""Espacios de coordenadas de PDFlex Studio.

Espacio canónico del modelo: "display" — puntos PDF tras aplicar /Rotate,
origen sup-izq, Y hacia abajo (lo que reportan fitz.Page.rect y get_text()).

Las funciones insert_*() de PyMuPDF interpretan rectángulos en el sistema NO
rotado de la página. Este módulo centraliza esa conversión: NADIE más en el
código multiplica por derotation_matrix (lección del bug de membrete_engine).
"""
from __future__ import annotations
from dataclasses import dataclass

import fitz

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0


def mm_to_pt(mm: float) -> float:
    return mm * PT_PER_INCH / MM_PER_INCH


def pt_to_mm(pt: float) -> float:
    return pt * MM_PER_INCH / PT_PER_INCH


Matrix6 = tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class PageGeometry:
    """Geometría inmutable de una página, capturada UNA vez desde fitz.

    Se captura al abrir el documento; el resto del motor trabaja con estos
    valores puros sin tocar fitz (regla de hilos del spec §5.3).
    """
    index: int
    width_pt: float          # dimensiones DISPLAY (rotation-aware)
    height_pt: float
    rotation: int            # 0 | 90 | 180 | 270
    derotation_matrix: Matrix6
    rotation_matrix: Matrix6

    @classmethod
    def from_page(cls, index: int, page: fitz.Page) -> "PageGeometry":
        return cls(
            index=index,
            width_pt=page.rect.width,
            height_pt=page.rect.height,
            rotation=page.rotation % 360,
            derotation_matrix=tuple(page.derotation_matrix),
            rotation_matrix=tuple(page.rotation_matrix),
        )


def display_rect_to_insertion(rect: fitz.Rect, geo: PageGeometry) -> fitz.Rect:
    """Convierte un rect en espacio display al espacio que esperan insert_*()."""
    out = fitz.Rect(rect) * fitz.Matrix(*geo.derotation_matrix)
    out.normalize()
    return out


def display_point_to_insertion(pt: fitz.Point, geo: PageGeometry) -> fitz.Point:
    return fitz.Point(pt) * fitz.Matrix(*geo.derotation_matrix)
```

`core/editor/__init__.py`: vacío.

- [x] **Step 2.4: Correr y verificar que pasa**

Run: `python -m pytest tests/editor/test_geometry.py -v`
Expected: 7 PASS.

- [x] **Step 2.5: Commit**

```bash
git add core/editor/__init__.py core/editor/geometry.py tests/editor/test_geometry.py
git commit -m "feat(studio): PageGeometry + centralized display-to-insertion derotation"
```

---

### Task 3: Prueba reina — formas y texto en las 4 rotaciones

**Files:**
- Create: `tests/editor/test_export_roundtrip.py`
- Create: `core/editor/export/__init__.py` (vacío)
- Create: `core/editor/export/primitives.py` (primitivas de inserción usadas luego por el Exporter)

- [x] **Step 3.1: Tests que fallan — rect estricto ≤0.5 pt y texto contenido + horizontal**

`tests/editor/test_export_roundtrip.py`:

```python
"""PRUEBA REINA (gate de Fase 0): lo insertado queda EXACTAMENTE donde se pidió,
en las 4 rotaciones, verificado releyendo el PDF generado."""
import fitz
import pytest

from core.editor.geometry import PageGeometry
from core.editor.export.primitives import stamp_rect, stamp_text

TARGET = fitz.Rect(120.0, 180.0, 320.0, 260.0)  # display space
ROTATIONS = [0, 90, 180, 270]


def _roundtrip(make_pdf, rotation, stamp_fn):
    src = make_pdf(rotations=[rotation])
    out = src.with_name(f"out_{rotation}.pdf")
    with fitz.open(src) as doc:
        geo = PageGeometry.from_page(0, doc[0])
        stamp_fn(doc[0], geo)
        doc.save(str(out))
    return out


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_rect_lands_exactly_where_placed(make_pdf, rotation):
    out = _roundtrip(make_pdf, rotation,
                     lambda page, geo: stamp_rect(page, geo, TARGET,
                                                  fill=(1, 0, 0), opacity=0.5))
    with fitz.open(out) as doc:
        drawings = doc[0].get_drawings()
        assert len(drawings) == 1
        got = drawings[0]["rect"]  # get_drawings reporta en espacio display
        for g, w in zip(tuple(got), tuple(TARGET)):
            assert g == pytest.approx(w, abs=0.5), f"/Rotate={rotation}: {got} vs {TARGET}"


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_text_lands_inside_box_and_reads_horizontal(make_pdf, rotation):
    out = _roundtrip(make_pdf, rotation,
                     lambda page, geo: stamp_text(page, geo, TARGET, "PDFlex Studio",
                                                  fontsize=14))
    with fitz.open(out) as doc:
        d = doc[0].get_text("dict")
        spans = [s for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]]
        assert len(spans) >= 1
        span = spans[0]
        assert span["text"].strip() == "PDFlex Studio"
        # Contenido dentro de la caja pedida (+1 pt de holgura por métricas de fuente)
        box = fitz.Rect(span["bbox"])
        assert fitz.Rect(TARGET) + (-1, -1, 1, 1) | box == fitz.Rect(TARGET) + (-1, -1, 1, 1), \
            f"/Rotate={rotation}: bbox {box} fuera de {TARGET}"
        # El texto se LEE horizontal en pantalla (dirección de escritura compensada)
        line = [l for b in d["blocks"] for l in b.get("lines", [])][0]
        assert line["dir"] == pytest.approx((1.0, 0.0), abs=1e-6), \
            f"/Rotate={rotation}: dir={line['dir']} — rotación no compensada"
```

- [x] **Step 3.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_export_roundtrip.py -v`
Expected: ERROR `No module named 'core.editor.export'`.

- [x] **Step 3.3: Implementar las primitivas de inserción**

`core/editor/export/primitives.py`:

```python
"""Primitivas de inserción rotación-seguras. ÚNICO lugar que llama insert_*/draw_*.

Reglas:
  - Reciben rects en espacio DISPLAY y PageGeometry; derotan internamente.
  - Texto: rotate=geo.rotation compensa /Rotate para que el texto se lea
    horizontal en pantalla (receta documentada de PyMuPDF para páginas rotadas).
"""
from __future__ import annotations

import fitz

from core.editor.geometry import PageGeometry, display_rect_to_insertion

RGB = tuple[float, float, float]


def stamp_rect(page: fitz.Page, geo: PageGeometry, rect_display: fitz.Rect,
               *, fill: RGB, opacity: float = 1.0) -> None:
    """Rectángulo relleno (base de whiteout/formas; y vara de medir del gate)."""
    rect = display_rect_to_insertion(rect_display, geo)
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(fill=fill, fill_opacity=opacity, color=None)
    shape.commit(overlay=True)


def stamp_text(page: fitz.Page, geo: PageGeometry, rect_display: fitz.Rect,
               text: str, *, fontsize: float = 12.0, fontname: str = "helv",
               color: RGB = (0, 0, 0), opacity: float = 1.0,
               align: int = fitz.TEXT_ALIGN_LEFT) -> float:
    """Texto plano en caja. Retorna el sobrante de insert_textbox (<0 = no cupo)."""
    rect = display_rect_to_insertion(rect_display, geo)
    return page.insert_textbox(
        rect, text,
        fontsize=fontsize, fontname=fontname, color=color,
        fill_opacity=opacity, align=align,
        rotate=geo.rotation,
    )
```

`core/editor/export/__init__.py`: vacío.

- [x] **Step 3.4: Correr y verificar que pasa — ESTE ES EL GATE**

Run: `python -m pytest tests/editor/test_export_roundtrip.py -v`
Expected: 8 PASS. Si los de 90/270 fallan por transposición: el bug está en la dirección de la matriz (usar `derotation_matrix`, no `rotation_matrix`) o en `rotate=` (debe ser `geo.rotation`, sin negar). No avanzar hasta verde.

- [x] **Step 3.5: Commit**

```bash
git add core/editor/export/__init__.py core/editor/export/primitives.py tests/editor/test_export_roundtrip.py
git commit -m "feat(studio): rotation-safe stamp primitives pass the 4-rotation gate test"
```

---

### Task 4: Prueba reina — imágenes (posición + orientación visual)

**Files:**
- Modify: `core/editor/export/primitives.py` (añadir `stamp_image`)
- Modify: `tests/editor/test_export_roundtrip.py` (añadir tests de imagen)
- Modify: `tests/editor/conftest.py` (añadir fixture `probe_png`)

- [x] **Step 4.1: Fixture de imagen-sonda + tests que fallan**

Añadir a `tests/editor/conftest.py`:

```python
@pytest.fixture(scope="session")
def probe_png() -> bytes:
    """PNG 80x80 asimétrico: cuadrante sup-izq ROJO, resto AZUL.

    Permite verificar orientación visual tras el round-trip: si la imagen
    quedó rotada por error, el rojo aparece en otra esquina.
    """
    from PIL import Image
    img = Image.new("RGB", (80, 80), (0, 0, 255))
    for x in range(40):
        for y in range(40):
            img.putpixel((x, y), (255, 0, 0))
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

Añadir a `tests/editor/test_export_roundtrip.py`:

```python
from core.editor.export.primitives import stamp_image

SQUARE = fitz.Rect(150.0, 200.0, 230.0, 280.0)  # cuadrado: la sonda no se deforma


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_image_lands_exactly_where_placed(make_pdf, probe_png, rotation):
    out = _roundtrip(make_pdf, rotation,
                     lambda page, geo: stamp_image(page, geo, SQUARE, probe_png))
    with fitz.open(out) as doc:
        infos = doc[0].get_image_info()
        assert len(infos) == 1
        got = fitz.Rect(infos[0]["bbox"])  # display space
        for g, w in zip(tuple(got), tuple(SQUARE)):
            assert g == pytest.approx(w, abs=0.5), f"/Rotate={rotation}: {got} vs {SQUARE}"


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_image_orientation_is_upright(make_pdf, probe_png, rotation):
    """El cuadrante rojo debe verse arriba-izquierda EN PANTALLA en toda rotación."""
    out = _roundtrip(make_pdf, rotation,
                     lambda page, geo: stamp_image(page, geo, SQUARE, probe_png))
    with fitz.open(out) as doc:
        pix = doc[0].get_pixmap(clip=SQUARE, matrix=fitz.Matrix(2, 2))
        w, h = pix.width, pix.height

        def rgb_at(fx: float, fy: float):
            x, y = int(w * fx), int(h * fy)
            return pix.pixel(x, y)

        r = rgb_at(0.25, 0.25)   # centro del cuadrante sup-izq → debe ser rojo
        b = rgb_at(0.75, 0.75)   # cuadrante inf-der → debe ser azul
        assert r[0] > 180 and r[2] < 80, f"/Rotate={rotation}: sup-izq no es rojo: {r}"
        assert b[2] > 180 and b[0] < 80, f"/Rotate={rotation}: inf-der no es azul: {b}"
```

- [x] **Step 4.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_export_roundtrip.py -k image -v`
Expected: ImportError `cannot import name 'stamp_image'`.

- [x] **Step 4.3: Implementar `stamp_image`**

Añadir a `core/editor/export/primitives.py`:

```python
def stamp_image(page: fitz.Page, geo: PageGeometry, rect_display: fitz.Rect,
                image_bytes: bytes) -> None:
    """Imagen en caja display. rotate=geo.rotation mantiene la imagen 'derecha'
    en pantalla sobre páginas con /Rotate (misma compensación que el texto).
    keep_proportion=False: el frame del elemento ya trae la proporción deseada;
    la política de aspecto vive en el modelo, no aquí.
    """
    rect = display_rect_to_insertion(rect_display, geo)
    page.insert_image(rect, stream=image_bytes,
                      rotate=geo.rotation, keep_proportion=False, overlay=True)
```

- [x] **Step 4.4: Correr TODO el archivo y verificar verde**

Run: `python -m pytest tests/editor/test_export_roundtrip.py -v`
Expected: 16 PASS. Si la orientación falla en 90/270 con posición correcta: el signo de `rotate=` en `insert_image` va invertido respecto a `insert_textbox` en la versión instalada → probar `rotate=(360 - geo.rotation) % 360` SOLO en `stamp_image` y dejar comentario con la versión de PyMuPDF que lo exigió. El test de orientación existe exactamente para fijar esto empíricamente.

- [x] **Step 4.5: Commit**

```bash
git add core/editor/export/primitives.py tests/editor/test_export_roundtrip.py tests/editor/conftest.py
git commit -m "feat(studio): rotation-safe image stamping with visual orientation probe test"
```

---

### Task 5: Rotación libre de elementos (texto con morph, imagen vía XObject)

**Files:**
- Modify: `core/editor/export/primitives.py` (parámetro `angle_deg` en texto; `stamp_image_rotated`)
- Modify: `tests/editor/test_export_roundtrip.py`

- [x] **Step 5.1: Tests que fallan**

Añadir a `tests/editor/test_export_roundtrip.py`:

```python
from core.editor.export.primitives import stamp_image_rotated


@pytest.mark.parametrize("rotation", [0, 90])
def test_free_angle_text_direction(make_pdf, rotation):
    """Texto a 30° sobre página normal y rotada: dir ≈ (cos30, -sin30) en display."""
    import math
    out = _roundtrip(make_pdf, rotation,
                     lambda page, geo: stamp_text(page, geo, TARGET, "Girado",
                                                  fontsize=14, angle_deg=30.0))
    with fitz.open(out) as doc:
        d = doc[0].get_text("dict")
        lines = [l for b in d["blocks"] for l in b.get("lines", [])]
        assert lines, "no se encontró el texto rotado"
        dx, dy = lines[0]["dir"]
        # fitz mide dir en espacio display con Y hacia abajo → 30° antihorario
        # visual = (cos30, -sin30)
        assert dx == pytest.approx(math.cos(math.radians(30)), abs=0.02)
        assert dy == pytest.approx(-math.sin(math.radians(30)), abs=0.02)


@pytest.mark.parametrize("rotation", [0, 90])
def test_free_angle_image_center_stays_put(make_pdf, probe_png, rotation):
    """Imagen a 45°: el centro del bbox resultante coincide con el centro pedido."""
    out = _roundtrip(make_pdf, rotation,
                     lambda page, geo: stamp_image_rotated(page, geo, SQUARE,
                                                           probe_png, angle_deg=45.0))
    with fitz.open(out) as doc:
        # Rotación libre → XObject; get_image_info da el bbox envolvente
        infos = doc[0].get_image_info()
        assert len(infos) == 1
        got = fitz.Rect(infos[0]["bbox"])
        cx, cy = (got.x0 + got.x1) / 2, (got.y0 + got.y1) / 2
        assert cx == pytest.approx((SQUARE.x0 + SQUARE.x1) / 2, abs=0.8)
        assert cy == pytest.approx((SQUARE.y0 + SQUARE.y1) / 2, abs=0.8)
```

- [x] **Step 5.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_export_roundtrip.py -k free_angle -v`
Expected: ImportError (`stamp_image_rotated`) / TypeError (`angle_deg`).

- [x] **Step 5.3: Implementar rotación libre**

Modificar `stamp_text` en `core/editor/export/primitives.py` — nueva firma y cuerpo:

```python
def stamp_text(page: fitz.Page, geo: PageGeometry, rect_display: fitz.Rect,
               text: str, *, fontsize: float = 12.0, fontname: str = "helv",
               color: RGB = (0, 0, 0), opacity: float = 1.0,
               align: int = fitz.TEXT_ALIGN_LEFT, angle_deg: float = 0.0) -> float:
    """Texto plano en caja, con ángulo libre opcional alrededor del centro.

    angle_deg gira en sentido antihorario VISUAL (espacio display). El morph de
    PyMuPDF opera en espacio no-rotado: el pivote se deroda y el ángulo se aplica
    tal cual (la composición con rotate=geo.rotation ya compensa la página).
    """
    rect = display_rect_to_insertion(rect_display, geo)
    morph = None
    if angle_deg:
        pivot = (rect.tl + rect.br) / 2
        morph = (pivot, fitz.Matrix(angle_deg))
    return page.insert_textbox(
        rect, text,
        fontsize=fontsize, fontname=fontname, color=color,
        fill_opacity=opacity, align=align,
        rotate=geo.rotation, morph=morph,
    )


def stamp_image_rotated(page: fitz.Page, geo: PageGeometry, rect_display: fitz.Rect,
                        image_bytes: bytes, *, angle_deg: float) -> None:
    """Imagen con ángulo libre: se envuelve como XObject (doc de 1 página en
    memoria) y se muestra con show_pdf_page(rotate=ángulo) — vectorial, sin
    resampleo (spec §21-6). El ángulo de show_pdf_page rota alrededor del
    centro del rect destino, que es la semántica del editor."""
    src = fitz.open()
    pix_rect = fitz.Rect(0, 0, rect_display.width, rect_display.height)
    src_page = src.new_page(width=pix_rect.width, height=pix_rect.height)
    src_page.insert_image(pix_rect, stream=image_bytes, keep_proportion=False)
    rect = display_rect_to_insertion(rect_display, geo)
    # Compensación de página + ángulo del usuario en una sola rotación efectiva
    effective = (angle_deg + geo.rotation) % 360
    page.show_pdf_page(rect, src, 0, rotate=effective)
    src.close()
```

- [x] **Step 5.4: Correr archivo completo**

Run: `python -m pytest tests/editor/test_export_roundtrip.py -v`
Expected: 20 PASS. Nota empírica esperable: el signo del ángulo en `morph`/`show_pdf_page` (horario vs antihorario) se fija con estos tests; si `dir` sale `(cos, +sin)`, negar el ángulo en el morph y documentarlo en el docstring.

- [x] **Step 5.5: Commit**

```bash
git add core/editor/export/primitives.py tests/editor/test_export_roundtrip.py
git commit -m "feat(studio): free-angle text (morph) and image (XObject) stamping"
```

---

### Task 6: RenderService (hilo dedicado + caché LRU + cancelación por generación)

**Files:**
- Create: `core/editor/render/__init__.py` (vacío)
- Create: `core/editor/render/pixmap_cache.py`
- Create: `core/editor/render/render_service.py`
- Create: `tests/editor/test_render_service.py`

Nota: el RenderService usa QThread/señales (frontera core/UI, igual que `BaseWorker`). El caché es Python puro. Antes de escribir el test, mirar cómo crean `QApplication` los tests existentes (`tests/test_*_window.py`) y replicar el mecanismo (fixture local si el repo no expone uno global).

- [x] **Step 6.1: Test del caché LRU (puro) que falla**

`tests/editor/test_render_service.py`:

```python
"""Caché LRU por presupuesto de bytes + RenderService con cancelación por generación."""
import fitz
import pytest

from core.editor.render.pixmap_cache import ByteBudgetLRU


def test_lru_evicts_by_byte_budget():
    cache = ByteBudgetLRU(budget_bytes=100)
    cache.put("a", object(), size_bytes=40)
    cache.put("b", object(), size_bytes=40)
    assert cache.get("a") is not None          # 'a' queda como más reciente
    cache.put("c", object(), size_bytes=40)    # presupuesto: expulsa 'b' (LRU)
    assert cache.get("b") is None
    assert cache.get("a") is not None and cache.get("c") is not None
    assert cache.used_bytes <= 100


def test_lru_rejects_oversized_item_without_breaking():
    cache = ByteBudgetLRU(budget_bytes=10)
    cache.put("big", object(), size_bytes=50)  # no cabe: no se almacena
    assert cache.get("big") is None
    assert cache.used_bytes == 0
```

- [x] **Step 6.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_render_service.py -v`
Expected: ModuleNotFoundError.

- [x] **Step 6.3: Implementar `ByteBudgetLRU`**

`core/editor/render/pixmap_cache.py`:

```python
"""LRU con presupuesto en bytes para pixmaps de página (spec §20)."""
from __future__ import annotations
from collections import OrderedDict
from typing import Any, Hashable


class ByteBudgetLRU:
    def __init__(self, budget_bytes: int) -> None:
        self._budget = budget_bytes
        self._items: OrderedDict[Hashable, tuple[Any, int]] = OrderedDict()
        self.used_bytes = 0

    def get(self, key: Hashable):
        entry = self._items.get(key)
        if entry is None:
            return None
        self._items.move_to_end(key)
        return entry[0]

    def put(self, key: Hashable, value: Any, size_bytes: int) -> None:
        if size_bytes > self._budget:
            return  # nunca cabrá; no desalojar todo por gusto
        if key in self._items:
            self.used_bytes -= self._items.pop(key)[1]
        while self.used_bytes + size_bytes > self._budget and self._items:
            _, (_, sz) = self._items.popitem(last=False)
            self.used_bytes -= sz
        self._items[key] = (value, size_bytes)
        self.used_bytes += size_bytes

    def clear(self) -> None:
        self._items.clear()
        self.used_bytes = 0
```

- [x] **Step 6.4: Correr tests del caché**

Run: `python -m pytest tests/editor/test_render_service.py -v`
Expected: 2 PASS.

- [x] **Step 6.5: Test del servicio (Qt) que falla**

Añadir a `tests/editor/test_render_service.py` (ajustar la fixture de QApplication al patrón real del repo encontrado en Task 0.3):

```python
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _wait_for(app, predicate, timeout_ms=5000):
    from PyQt6.QtCore import QElapsedTimer
    t = QElapsedTimer(); t.start()
    while not predicate():
        app.processEvents()
        if t.elapsed() > timeout_ms:
            raise TimeoutError("render no llegó a tiempo")


def test_render_service_delivers_pixmap(qapp, make_pdf):
    from core.editor.render.render_service import RenderService
    path = make_pdf(rotations=[0, 90])
    svc = RenderService(str(path))
    got = []
    svc.pixmap_ready.connect(lambda page, scale, gen, img: got.append((page, scale, img)))
    svc.start()
    try:
        svc.request_page(page=1, scale=1.5)
        _wait_for(qapp, lambda: len(got) == 1)
        page, scale, img = got[0]
        assert page == 1 and scale == 1.5
        # página /Rotate=90 → display 842x595 pt → a 1.5x ≈ 1263x892 px
        assert abs(img.width() - round(842 * 1.5)) <= 2
        assert abs(img.height() - round(595 * 1.5)) <= 2
    finally:
        svc.stop()


def test_render_service_generation_cancels_stale(qapp, make_pdf):
    from core.editor.render.render_service import RenderService
    path = make_pdf(rotations=[0] * 12)
    svc = RenderService(str(path))
    got = []
    svc.pixmap_ready.connect(lambda page, scale, gen, img: got.append(gen))
    svc.start()
    try:
        for p in range(12):
            svc.request_page(page=p, scale=2.0)   # generación 1 (zoom viejo)
        svc.bump_generation()                      # usuario cambió el zoom
        svc.request_page(page=0, scale=3.0)        # generación 2
        _wait_for(qapp, lambda: 2 in got)
        svc.drain()                                # procesa lo que quede en vuelo
        stale = [g for g in got if g == 1]
        assert len(stale) <= 2, f"se entregaron {len(stale)} renders obsoletos"
    finally:
        svc.stop()
```

- [x] **Step 6.6: Implementar `RenderService`**

`core/editor/render/render_service.py`:

```python
"""Hilo de render dedicado: ÚNICO dueño del fitz.Document de lectura (spec §5.3).

La UI pide (página, escala) y recibe pixmap_ready(page, scale, generation, QImage).
bump_generation() invalida lo encolado (cambio de zoom): los trabajos con
generación vieja se descartan antes de renderizar — nunca se desperdicia un
render que ya nadie quiere (riesgo histórico de freezes de la suite).
"""
from __future__ import annotations

import queue
import threading

import fitz
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QImage

from .pixmap_cache import ByteBudgetLRU

_SENTINEL = None


class RenderService(QObject):
    pixmap_ready = pyqtSignal(int, float, int, QImage)   # page, scale, generation, image
    render_failed = pyqtSignal(int, str)                  # page, error

    def __init__(self, pdf_path: str, cache_budget_mb: int = 384) -> None:
        super().__init__()
        self._path = pdf_path
        self._queue: "queue.Queue" = queue.Queue()
        self._generation = 0
        self._gen_lock = threading.Lock()
        self._cache = ByteBudgetLRU(cache_budget_mb * 1024 * 1024)
        self._thread: threading.Thread | None = None

    # ── API (hilo de UI) ────────────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="StudioRender", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._queue.put(_SENTINEL)
        if self._thread is not None:
            self._thread.join(timeout=10)

    def bump_generation(self) -> int:
        with self._gen_lock:
            self._generation += 1
            return self._generation

    def request_page(self, page: int, scale: float) -> None:
        with self._gen_lock:
            gen = self._generation
        cached = self._cache.get((page, round(scale, 3)))
        if cached is not None:
            self.pixmap_ready.emit(page, scale, gen, cached)
            return
        self._queue.put((gen, page, scale))

    def drain(self) -> None:
        """Bloquea hasta vaciar la cola (solo para tests)."""
        self._queue.join()

    # ── Hilo de render (único dueño del fitz.Document) ──────────────
    def _run(self) -> None:
        doc = fitz.open(self._path)
        try:
            while True:
                item = self._queue.get()
                if item is _SENTINEL:
                    self._queue.task_done()
                    return
                gen, page_idx, scale = item
                try:
                    with self._gen_lock:
                        current = self._generation
                    if gen < current:
                        continue  # obsoleto: descartar sin renderizar
                    pix = doc[page_idx].get_pixmap(matrix=fitz.Matrix(scale, scale),
                                                   alpha=False)
                    img = QImage(pix.samples, pix.width, pix.height,
                                 pix.stride, QImage.Format.Format_RGB888).copy()
                    self._cache.put((page_idx, round(scale, 3)), img,
                                    img.sizeInBytes())
                    self.pixmap_ready.emit(page_idx, scale, gen, img)
                except Exception as exc:           # noqa: BLE001 — se reporta a UI
                    self.render_failed.emit(page_idx, str(exc))
                finally:
                    self._queue.task_done()
        finally:
            doc.close()
```

`core/editor/render/__init__.py`: vacío.

- [x] **Step 6.7: Correr todo y commit**

Run: `python -m pytest tests/editor/ -v`
Expected: todo verde (≈26 PASS).

```bash
git add core/editor/render/ tests/editor/test_render_service.py
git commit -m "feat(studio): dedicated render thread with byte-budget LRU and generation cancel"
```

**🚦 GATE DE FASE 0 COMPLETO** — posición exacta ≤0.5 pt en 4 rotaciones (formas e imágenes), texto compensado y contenido, rotación libre, render asíncrono cancelable.

---

## Parte B — FASE 1 NÚCLEO (sin UI)

### Task 7: Modelo — `Frame`, `Placement`, `Anchor` y elementos serializables

**Files:**
- Create: `core/editor/model/__init__.py` (vacío)
- Create: `core/editor/model/placement.py`
- Create: `core/editor/model/elements.py`
- Create: `tests/editor/test_model.py`

- [x] **Step 7.1: Tests que fallan**

`tests/editor/test_model.py`:

```python
"""Modelo de elementos: defaults, serialización round-trip y resolución de anclas."""
import pytest

from core.editor.model.placement import Anchor, Frame, Placement, resolve_frame
from core.editor.model.elements import TextElement, ImageElement, element_from_dict


def _a4():
    from core.editor.geometry import PageGeometry
    return PageGeometry(index=0, width_pt=595.0, height_pt=842.0, rotation=0,
                        derotation_matrix=(1, 0, 0, 1, 0, 0),
                        rotation_matrix=(1, 0, 0, 1, 0, 0))


def _oficio():
    from core.editor.geometry import PageGeometry
    return PageGeometry(index=1, width_pt=612.0, height_pt=1008.0, rotation=0,
                        derotation_matrix=(1, 0, 0, 1, 0, 0),
                        rotation_matrix=(1, 0, 0, 1, 0, 0))


def test_absolute_placement_is_identity():
    f = Frame(x=100, y=200, w=150, h=40)
    p = Placement(mode="absolute")
    assert resolve_frame(f, p, _a4()) == f


def test_anchor_bottom_right_adapts_to_page_size():
    f = Frame(x=0, y=0, w=100, h=30)
    p = Placement(mode="anchor", anchor=Anchor.BOTTOM_RIGHT, dx_pt=-20, dy_pt=-15)
    fa = resolve_frame(f, p, _a4())
    fo = resolve_frame(f, p, _oficio())
    # El frame queda pegado a la esquina inf-der menos el offset, en AMBAS páginas
    assert fa.x == pytest.approx(595 - 100 - 20) and fa.y == pytest.approx(842 - 30 - 15)
    assert fo.x == pytest.approx(612 - 100 - 20) and fo.y == pytest.approx(1008 - 30 - 15)


def test_normalized_placement_scales_like_foleador():
    # Centro al 50%,25% de la página y tamaño 30%x5% de la referencia A4
    f = Frame(x=0, y=0, w=0, h=0)
    p = Placement(mode="normalized", cx_norm=0.5, cy_norm=0.25,
                  w_norm=0.3, h_norm=0.05, ref_page_w_pt=595, ref_page_h_pt=842)
    fo = resolve_frame(f, p, _oficio())
    assert fo.w == pytest.approx(612 * 0.3)
    assert fo.h == pytest.approx(1008 * 0.05)
    assert fo.x + fo.w / 2 == pytest.approx(612 * 0.5)
    assert fo.y + fo.h / 2 == pytest.approx(1008 * 0.25)


def test_text_element_serialization_roundtrip():
    el = TextElement(text="CONFIDENCIAL", font_size=24.0, color=(0.9, 0.1, 0.1),
                     frame=Frame(x=10, y=20, w=300, h=50), opacity=0.5,
                     align="center", rotation_deg=30.0, layer_id="marcas")
    data = el.to_dict()
    back = element_from_dict(data)
    assert isinstance(back, TextElement)
    assert back == el


def test_image_element_serialization_roundtrip():
    el = ImageElement(asset_id="ab12" * 16, frame=Frame(x=5, y=6, w=80, h=80),
                      crop=(0.1, 0.1, 0.9, 0.9), keep_aspect=False, flip_h=True)
    assert element_from_dict(el.to_dict()) == el


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="kind"):
        element_from_dict({"kind": "hologram", "schema": 1})
```

- [x] **Step 7.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_model.py -v`
Expected: ModuleNotFoundError.

- [x] **Step 7.3: Implementar `placement.py`**

`core/editor/model/placement.py`:

```python
"""Frame (caja en pt display) y Placement (cómo se resuelve por página).

Tres modos (spec §12):
  absolute   — el frame es literal (elementos colocados a mano en UNA página)
  anchor     — 9 anclas + offset en pt (encabezados/pies/folios en reglas)
  normalized — centro y tamaño como fracción de página de referencia
               (marcas de agua; patrón probado del foleador)
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Literal

from core.editor.geometry import PageGeometry


class Anchor(str, Enum):
    TOP_LEFT = "top-left";       TOP_CENTER = "top-center";       TOP_RIGHT = "top-right"
    MIDDLE_LEFT = "middle-left"; CENTER = "center";               MIDDLE_RIGHT = "middle-right"
    BOTTOM_LEFT = "bottom-left"; BOTTOM_CENTER = "bottom-center"; BOTTOM_RIGHT = "bottom-right"


@dataclass(frozen=True)
class Frame:
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


@dataclass(frozen=True)
class Placement:
    mode: Literal["absolute", "anchor", "normalized"] = "absolute"
    # anchor:
    anchor: Anchor = Anchor.TOP_LEFT
    dx_pt: float = 0.0
    dy_pt: float = 0.0
    # normalized:
    cx_norm: float = 0.5
    cy_norm: float = 0.5
    w_norm: float = 0.0
    h_norm: float = 0.0
    ref_page_w_pt: float = 595.0
    ref_page_h_pt: float = 842.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["anchor"] = self.anchor.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Placement":
        d = dict(d)
        d["anchor"] = Anchor(d.get("anchor", Anchor.TOP_LEFT.value))
        return cls(**d)


def resolve_frame(frame: Frame, placement: Placement, geo: PageGeometry) -> Frame:
    """Frame efectivo del elemento en UNA página concreta (display space)."""
    if placement.mode == "absolute":
        return frame

    if placement.mode == "normalized":
        w = geo.width_pt * placement.w_norm
        h = geo.height_pt * placement.h_norm
        cx = geo.width_pt * placement.cx_norm
        cy = geo.height_pt * placement.cy_norm
        return Frame(x=cx - w / 2, y=cy - h / 2, w=w, h=h)

    # anchor: el frame conserva su tamaño; la posición se calcula contra la página
    w, h = frame.w, frame.h
    col = {"left": 0.0, "center": 0.5, "right": 1.0}
    row = {"top": 0.0, "middle": 0.5, "bottom": 1.0}
    v, hz = placement.anchor.value.split("-") if "-" in placement.anchor.value else ("middle", "center")
    if placement.anchor is Anchor.CENTER:
        v, hz = "middle", "center"
    x = (geo.width_pt - w) * col[hz] + placement.dx_pt
    y = (geo.height_pt - h) * row[v] + placement.dy_pt
    return Frame(x=x, y=y, w=w, h=h)
```

- [x] **Step 7.4: Implementar `elements.py`**

`core/editor/model/elements.py`:

```python
"""Elementos del editor: dataclasses serializables, sin Qt y sin fitz.

Serialización: to_dict()/element_from_dict() con campo "schema" para
migraciones futuras (spec §17). Las imágenes referencian assets por hash
SHA-256 (el binario vive en el AssetStore del proyecto, Task 15).
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field, asdict
from typing import Literal

from .placement import Frame, Placement

SCHEMA_VERSION = 1
RGB = tuple[float, float, float]


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class _Base:
    id: str = field(default_factory=_new_id)
    frame: Frame = field(default_factory=Frame)
    placement: Placement = field(default_factory=Placement)
    rotation_deg: float = 0.0
    opacity: float = 1.0
    locked: bool = False
    hidden: bool = False
    layer_id: str = "general"
    z: int = 0


@dataclass(frozen=True)
class TextElement(_Base):
    kind: str = field(default="text", init=False)
    text: str = ""
    font_family: str = "helv"            # MVP: helv|tiro|cour (catálogo foleador)
    font_size: float = 12.0
    bold: bool = False
    italic: bool = False
    color: RGB = (0.0, 0.0, 0.0)
    align: Literal["left", "center", "right", "justify"] = "left"
    line_height: float = 1.2
    box_fill: RGB | None = None
    box_fill_opacity: float = 1.0
    variables_enabled: bool = False

    def to_dict(self) -> dict:
        return _serialize(self)


@dataclass(frozen=True)
class ImageElement(_Base):
    kind: str = field(default="image", init=False)
    asset_id: str = ""
    crop: tuple[float, float, float, float] | None = None   # l,t,r,b en fracciones
    keep_aspect: bool = True
    flip_h: bool = False
    flip_v: bool = False

    def to_dict(self) -> dict:
        return _serialize(self)


_KINDS = {"text": TextElement, "image": ImageElement}


def _serialize(el) -> dict:
    d = asdict(el)
    d["schema"] = SCHEMA_VERSION
    d["frame"] = asdict(el.frame)
    d["placement"] = el.placement.to_dict()
    if d.get("crop") is not None:
        d["crop"] = list(el.crop)
    return d


def element_from_dict(d: dict):
    d = dict(d)
    d.pop("schema", None)
    kind = d.pop("kind", None)
    cls = _KINDS.get(kind)
    if cls is None:
        raise ValueError(f"kind de elemento desconocido: {kind!r}")
    d["frame"] = Frame(**d["frame"])
    d["placement"] = Placement.from_dict(d["placement"])
    if d.get("color") is not None:
        d["color"] = tuple(d["color"])
    if d.get("box_fill") is not None:
        d["box_fill"] = tuple(d["box_fill"])
    if d.get("crop") is not None:
        d["crop"] = tuple(d["crop"])
    return cls(**d)
```

`core/editor/model/__init__.py`: vacío.

- [x] **Step 7.5: Correr y commitear**

Run: `python -m pytest tests/editor/test_model.py -v`
Expected: 7 PASS.

```bash
git add core/editor/model/ tests/editor/test_model.py
git commit -m "feat(studio): element model with absolute/anchor/normalized placement"
```

---

### Task 8: `PageTarget` — objetivo de páginas con parser "1-5,9,12-"

**Files:**
- Create: `core/editor/model/page_target.py`
- Create: `tests/editor/test_page_target.py`

- [x] **Step 8.1: Tests que fallan**

`tests/editor/test_page_target.py`:

```python
"""PageTarget: todas/actual/pares/impares/spec con rangos abiertos y comas."""
import pytest

from core.editor.model.page_target import PageTarget, parse_pages_spec


def test_parse_simple_and_ranges():
    assert parse_pages_spec("1-3,7,10-12", total=20) == [1, 2, 3, 7, 10, 11, 12]


def test_parse_open_ended_and_dedup_sorted():
    assert parse_pages_spec("18-,5,5,1-2", total=20) == [1, 2, 5, 18, 19, 20]


def test_parse_clamps_and_validates():
    assert parse_pages_spec("0-2", total=5) == [1, 2]      # clamp inferior
    assert parse_pages_spec("4-99", total=5) == [4, 5]     # clamp superior
    with pytest.raises(ValueError, match="vacío"):
        parse_pages_spec("", total=5)
    with pytest.raises(ValueError, match="inválido"):
        parse_pages_spec("abc", total=5)
    with pytest.raises(ValueError, match="inválido"):
        parse_pages_spec("5-3", total=10)                  # rango invertido


@pytest.mark.parametrize("mode,expected", [
    ("all", [1, 2, 3, 4, 5]),
    ("even", [2, 4]),
    ("odd", [1, 3, 5]),
])
def test_modes(mode, expected):
    assert PageTarget(mode=mode).resolve(total=5) == expected


def test_current_mode_uses_given_page():
    assert PageTarget(mode="current").resolve(total=9, current_page=4) == [4]


def test_pages_mode_uses_spec():
    t = PageTarget(mode="pages", spec="2,4-5")
    assert t.resolve(total=10) == [2, 4, 5]
    assert t.to_dict() == {"mode": "pages", "spec": "2,4-5"}
    assert PageTarget.from_dict(t.to_dict()) == t
```

- [x] **Step 8.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_page_target.py -v`
Expected: ModuleNotFoundError.

- [x] **Step 8.3: Implementar**

`core/editor/model/page_target.py`:

```python
"""Objetivo de páginas para reglas y aplicación masiva (spec §10.2).

Sintaxis de spec: "1-5,9,12-"  (rangos cerrados, páginas sueltas, rango abierto
al final del documento). 1-based, como todo lo visible al usuario en la suite
(mismo criterio que core/split_ranges.py del Separador).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

_ERR_EMPTY = "El objetivo de páginas está vacío. Ejemplos: 1-5,9,12-"
_ERR_BAD = "Tramo inválido: {part!r}. Usa números (5), rangos (3-8) o abiertos (12-)"


def parse_pages_spec(spec: str, total: int) -> list[int]:
    """Parsea la spec → lista 1-based ordenada y sin duplicados, recortada a [1,total]."""
    spec = (spec or "").strip()
    if not spec:
        raise ValueError(_ERR_EMPTY)
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if part.endswith("-"):
                start = int(part[:-1])
                end = total
            elif "-" in part:
                a, b = part.split("-", 1)
                start, end = int(a), int(b)
            else:
                start = end = int(part)
        except ValueError:
            raise ValueError(_ERR_BAD.format(part=part)) from None
        if start > end:
            raise ValueError(_ERR_BAD.format(part=part))
        start, end = max(1, start), min(total, end)
        pages.update(range(start, end + 1))
    return sorted(pages)


@dataclass(frozen=True)
class PageTarget:
    mode: Literal["all", "current", "pages", "even", "odd"] = "all"
    spec: str = ""

    def resolve(self, total: int, current_page: int = 1) -> list[int]:
        if self.mode == "all":
            return list(range(1, total + 1))
        if self.mode == "current":
            return [current_page]
        if self.mode == "even":
            return list(range(2, total + 1, 2))
        if self.mode == "odd":
            return list(range(1, total + 1, 2))
        return parse_pages_spec(self.spec, total)

    def to_dict(self) -> dict:
        return {"mode": self.mode, "spec": self.spec}

    @classmethod
    def from_dict(cls, d: dict) -> "PageTarget":
        return cls(mode=d.get("mode", "all"), spec=d.get("spec", ""))
```

- [x] **Step 8.4: Correr y commitear**

Run: `python -m pytest tests/editor/test_page_target.py -v`
Expected: 9 PASS.

```bash
git add core/editor/model/page_target.py tests/editor/test_page_target.py
git commit -m "feat(studio): PageTarget with open-ended range spec parser"
```

---

### Task 9: Variables dinámicas `{pagina}`, `{total}`, `{fecha}`, `{hora}`, `{doc}`, `{n:05}`

**Files:**
- Create: `core/editor/model/variables.py`
- Create: `tests/editor/test_variables.py`

- [x] **Step 9.1: Tests que fallan**

`tests/editor/test_variables.py`:

```python
"""Variables dinámicas de texto. {n}/{total}/{doc} delegan en core.folio_format."""
from datetime import datetime

import pytest

from core.editor.model.variables import RenderContext, render_text


CTX = RenderContext(page=3, total=120, doc_name="contrato",
                    now=datetime(2026, 6, 9, 14, 30), folio_n=7)


def test_page_total_doc():
    assert render_text("Pág. {pagina} de {total}", CTX) == "Pág. 3 de 120"
    assert render_text("{doc}", CTX) == "contrato"


def test_folio_mask_delegates_to_folio_format():
    assert render_text("FOLIO-{n:05}", CTX) == "FOLIO-00007"


def test_date_time_default_and_custom_format():
    assert render_text("{fecha}", CTX) == "09/06/2026"
    assert render_text("{fecha:%Y-%m-%d}", CTX) == "2026-06-09"
    assert render_text("{hora}", CTX) == "14:30"


def test_unknown_tokens_left_intact():
    assert render_text("hola {desconocido} {pagina}", CTX) == "hola {desconocido} 3"


def test_no_variables_is_passthrough():
    assert render_text("texto plano", CTX) == "texto plano"
```

- [x] **Step 9.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_variables.py -v`
Expected: ModuleNotFoundError.

- [x] **Step 9.3: Implementar**

`core/editor/model/variables.py`:

```python
"""Variables dinámicas de PDFlex Studio (spec §16).

Extiende la sintaxis probada de core/folio_format ({n}, {n:05}, {total}, {doc})
con {pagina}, {fecha[:formato strftime]} y {hora}. Tokens desconocidos se dejan
intactos (el usuario los ve y corrige; no se lanza error en render).
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime

from core.folio_format import render as folio_render

_TOKEN = re.compile(r"\{(pagina|fecha|hora)(?::([^{}]+))?\}")


@dataclass(frozen=True)
class RenderContext:
    page: int                 # 1-based, página donde se renderiza la instancia
    total: int
    doc_name: str
    now: datetime
    folio_n: int = 1          # contador de folio (regla folio lo incrementa)


def render_text(template: str, ctx: RenderContext) -> str:
    if "{" not in template:
        return template

    def _replace(m: re.Match) -> str:
        name, fmt = m.group(1), m.group(2)
        if name == "pagina":
            return str(ctx.page)
        if name == "fecha":
            return ctx.now.strftime(fmt or "%d/%m/%Y")
        if name == "hora":
            return ctx.now.strftime(fmt or "%H:%M")
        return m.group(0)

    out = _TOKEN.sub(_replace, template)
    # {n}, {n:05}, {total}, {doc} — sintaxis y semántica exactas del foleador
    out = folio_render(out, n=ctx.folio_n, doc_name=ctx.doc_name, total_pages=ctx.total)
    return out
```

- [x] **Step 9.4: Correr y commitear**

Run: `python -m pytest tests/editor/test_variables.py -v`
Expected: 5 PASS.

```bash
git add core/editor/model/variables.py tests/editor/test_variables.py
git commit -m "feat(studio): dynamic text variables extending folio_format syntax"
```

---

### Task 10: Capas, reglas y `EditorDocument.resolved_elements()`

**Files:**
- Create: `core/editor/model/layers.py`
- Create: `core/editor/model/rules.py`
- Create: `core/editor/model/document_state.py`
- Create: `tests/editor/test_document_state.py`

- [x] **Step 10.1: Tests que fallan**

`tests/editor/test_document_state.py`:

```python
"""EditorDocument: resolución por página de elementos + reglas, orden z, capas."""
import pytest

from core.editor.geometry import PageGeometry
from core.editor.model.document_state import EditorDocument
from core.editor.model.elements import TextElement
from core.editor.model.layers import Layer
from core.editor.model.page_target import PageTarget
from core.editor.model.placement import Anchor, Frame, Placement
from core.editor.model.rules import PageRule


def _geo(i, w=595.0, h=842.0):
    return PageGeometry(index=i, width_pt=w, height_pt=h, rotation=0,
                        derotation_matrix=(1, 0, 0, 1, 0, 0),
                        rotation_matrix=(1, 0, 0, 1, 0, 0))


def _doc(n_pages=4) -> EditorDocument:
    return EditorDocument(source_path="x.pdf", source_sha256="0" * 64,
                          page_geometries=[_geo(i) for i in range(n_pages)])


def test_concrete_element_only_on_its_page():
    doc = _doc()
    el = TextElement(text="hola", frame=Frame(10, 10, 100, 20))
    doc.add_element(page=2, element=el)
    assert [r.element.id for r in doc.resolved_elements(2)] == [el.id]
    assert doc.resolved_elements(1) == []


def test_rule_materializes_on_target_pages_with_resolved_frame():
    doc = _doc(4)  # páginas 1..4
    rule = PageRule(
        element=TextElement(text="Pág. {pagina} de {total}", variables_enabled=True,
                            frame=Frame(0, 0, 120, 18),
                            placement=Placement(mode="anchor",
                                                anchor=Anchor.BOTTOM_CENTER, dy_pt=-10)),
        target=PageTarget(mode="odd"),
    )
    doc.add_rule(rule)
    r1 = doc.resolved_elements(1)
    assert len(r1) == 1 and r1[0].from_rule_id == rule.id
    assert r1[0].text == "Pág. 1 de 4"                  # variable sustituida
    assert r1[0].frame.y == pytest.approx(842 - 18 - 10)  # ancla resuelta
    assert doc.resolved_elements(2) == []                # página par: nada


def test_z_order_layer_then_element():
    doc = _doc(1)
    doc.layers.add(Layer(id="fondo", name="Fondo", z=0))
    doc.layers.add(Layer(id="frente", name="Frente", z=10))
    a = TextElement(text="a", layer_id="frente", z=1)
    b = TextElement(text="b", layer_id="fondo", z=99)   # z alto en capa baja
    c = TextElement(text="c", layer_id="frente", z=0)
    for el in (a, b, c):
        doc.add_element(page=1, element=el)
    order = [r.text for r in doc.resolved_elements(1)]
    assert order == ["b", "c", "a"]                     # capa manda; luego z


def test_hidden_layer_and_hidden_element_excluded():
    doc = _doc(1)
    doc.layers.add(Layer(id="oculta", name="Oculta", z=5, visible=False))
    doc.add_element(1, TextElement(text="invisible-capa", layer_id="oculta"))
    doc.add_element(1, TextElement(text="invisible-flag", hidden=True))
    doc.add_element(1, TextElement(text="visible"))
    assert [r.text for r in doc.resolved_elements(1)] == ["visible"]


def test_layer_opacity_multiplies_element_opacity():
    doc = _doc(1)
    doc.layers.add(Layer(id="suave", name="Suave", z=1, opacity=0.5))
    doc.add_element(1, TextElement(text="x", layer_id="suave", opacity=0.6))
    assert doc.resolved_elements(1)[0].effective_opacity == pytest.approx(0.3)


def test_default_layer_always_exists_and_is_protected():
    doc = _doc(1)
    assert doc.layers.get("general") is not None
    with pytest.raises(ValueError, match="protegida"):
        doc.layers.remove("general")
```

- [x] **Step 10.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_document_state.py -v`
Expected: ModuleNotFoundError.

- [x] **Step 10.3: Implementar `layers.py`**

`core/editor/model/layers.py`:

```python
"""Capas del editor (concepto del editor, no del PDF fuente — spec §10.2)."""
from __future__ import annotations
from dataclasses import dataclass, asdict, field

GENERAL_LAYER_ID = "general"


@dataclass
class Layer:
    id: str
    name: str
    z: int = 0
    visible: bool = True
    locked: bool = False
    opacity: float = 1.0
    export_as_ocg: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Layer":
        return cls(**d)


class LayerStack:
    """Siempre contiene la capa 'General' (no eliminable)."""

    def __init__(self) -> None:
        self._layers: dict[str, Layer] = {}
        self.add(Layer(id=GENERAL_LAYER_ID, name="General", z=0))

    def add(self, layer: Layer) -> None:
        self._layers[layer.id] = layer

    def get(self, layer_id: str) -> Layer | None:
        return self._layers.get(layer_id)

    def remove(self, layer_id: str) -> None:
        if layer_id == GENERAL_LAYER_ID:
            raise ValueError("La capa General está protegida y no puede eliminarse")
        self._layers.pop(layer_id, None)

    def all(self) -> list[Layer]:
        return sorted(self._layers.values(), key=lambda l: l.z)

    def to_dict(self) -> list[dict]:
        return [l.to_dict() for l in self.all()]

    @classmethod
    def from_dict(cls, items: list[dict]) -> "LayerStack":
        st = cls()
        for d in items:
            st.add(Layer.from_dict(d))
        return st
```

- [x] **Step 10.4: Implementar `rules.py`**

`core/editor/model/rules.py`:

```python
"""Reglas de página: UN elemento + UN objetivo → instancias fantasma (spec §10.3)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field

from .elements import element_from_dict
from .page_target import PageTarget


@dataclass(frozen=True)
class PageRule:
    element: object                       # ElementBase (Text/Image/…)
    target: PageTarget
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {"id": self.id, "element": self.element.to_dict(),
                "target": self.target.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "PageRule":
        return cls(id=d["id"], element=element_from_dict(d["element"]),
                   target=PageTarget.from_dict(d["target"]))
```

- [x] **Step 10.5: Implementar `document_state.py`**

`core/editor/model/document_state.py`:

```python
"""EditorDocument: estado completo del proyecto + resolución por página.

resolved_elements(page) es LA función que consumen el canvas y el exportador:
elementos concretos + instancias de reglas, con anclas resueltas al tamaño real
de la página, variables sustituidas, filtrado de ocultos y orden (z capa, z el.).
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from core.editor.geometry import PageGeometry
from .elements import TextElement
from .layers import LayerStack
from .model_types import ResolvedElement  # ver más abajo en este mismo step
from .placement import resolve_frame
from .rules import PageRule
from .variables import RenderContext, render_text


@dataclass
class EditorDocument:
    source_path: str
    source_sha256: str
    page_geometries: list[PageGeometry]
    layers: LayerStack = field(default_factory=LayerStack)
    elements_by_page: dict[int, list] = field(default_factory=dict)   # 1-based
    rules: list[PageRule] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.page_geometries)

    # ── mutaciones (las invocan los comandos del historial) ─────────
    def add_element(self, page: int, element) -> None:
        self.elements_by_page.setdefault(page, []).append(element)

    def remove_element(self, page: int, element_id: str) -> object | None:
        items = self.elements_by_page.get(page, [])
        for i, el in enumerate(items):
            if el.id == element_id:
                return items.pop(i)
        return None

    def add_rule(self, rule: PageRule) -> None:
        self.rules.append(rule)

    def remove_rule(self, rule_id: str) -> PageRule | None:
        for i, r in enumerate(self.rules):
            if r.id == rule_id:
                return self.rules.pop(i)
        return None

    # ── resolución ──────────────────────────────────────────────────
    def resolved_elements(self, page: int, now: datetime | None = None) -> list[ResolvedElement]:
        geo = self.page_geometries[page - 1]
        now = now or datetime.now()
        out: list[ResolvedElement] = []

        def _emit(el, from_rule_id: str | None) -> None:
            layer = self.layers.get(el.layer_id)
            if el.hidden or (layer is not None and not layer.visible):
                return
            frame = resolve_frame(el.frame, el.placement, geo)
            text = getattr(el, "text", None)
            if text is not None and getattr(el, "variables_enabled", False):
                ctx = RenderContext(page=page, total=self.page_count,
                                    doc_name=Path(self.source_path).stem,
                                    now=now, folio_n=page)
                text = render_text(text, ctx)
            layer_z = layer.z if layer is not None else 0
            layer_op = layer.opacity if layer is not None else 1.0
            out.append(ResolvedElement(
                element=el, frame=frame, text=text,
                effective_opacity=el.opacity * layer_op,
                layer_z=layer_z, from_rule_id=from_rule_id,
            ))

        for el in self.elements_by_page.get(page, []):
            _emit(el, None)
        for rule in self.rules:
            if page in rule.target.resolve(self.page_count, current_page=page):
                _emit(rule.element, rule.id)

        out.sort(key=lambda r: (r.layer_z, r.element.z))
        return out
```

Y `core/editor/model/model_types.py` (Create — añadirlo a **Files** de esta task):

```python
"""Tipos de salida de la resolución (separados para evitar import circular)."""
from __future__ import annotations
from dataclasses import dataclass

from .placement import Frame


@dataclass(frozen=True)
class ResolvedElement:
    """Instancia lista para pintar/exportar en UNA página concreta."""
    element: object
    frame: Frame
    effective_opacity: float
    layer_z: int
    text: str | None = None          # texto final con variables sustituidas
    from_rule_id: str | None = None  # None = elemento concreto

    @property
    def is_ghost(self) -> bool:
        return self.from_rule_id is not None
```

- [x] **Step 10.6: Correr y commitear**

Run: `python -m pytest tests/editor/test_document_state.py -v`
Expected: 7 PASS.

```bash
git add core/editor/model/layers.py core/editor/model/rules.py core/editor/model/document_state.py core/editor/model/model_types.py tests/editor/test_document_state.py
git commit -m "feat(studio): EditorDocument with layers, page rules and per-page resolution"
```

---

### Task 11: Historial — comandos undo/redo puros con merge y macro

**Files:**
- Create: `core/editor/history/__init__.py` (vacío)
- Create: `core/editor/history/commands.py`
- Create: `core/editor/history/stack.py`
- Create: `tests/editor/test_history.py`
- Modify: `docs/superpowers/specs/2026-06-09-pdflex-studio-editor-pdf-design.md` (línea de QUndoStack → pila pura)

- [x] **Step 11.1: Tests que fallan**

`tests/editor/test_history.py`:

```python
"""HistoryStack puro: undo/redo, merge de arrastres, macros, tope de pasos."""
import pytest

from core.editor.geometry import PageGeometry
from core.editor.history.commands import AddElement, MoveResize, RemoveElement
from core.editor.history.stack import HistoryStack, Macro
from core.editor.model.document_state import EditorDocument
from core.editor.model.elements import TextElement
from core.editor.model.placement import Frame


def _doc():
    geo = PageGeometry(index=0, width_pt=595, height_pt=842, rotation=0,
                       derotation_matrix=(1, 0, 0, 1, 0, 0),
                       rotation_matrix=(1, 0, 0, 1, 0, 0))
    return EditorDocument(source_path="x.pdf", source_sha256="0" * 64,
                          page_geometries=[geo])


def test_add_undo_redo():
    doc, h = _doc(), HistoryStack(limit=200)
    el = TextElement(text="hola")
    h.push(AddElement(doc, page=1, element=el))
    assert len(doc.resolved_elements(1)) == 1
    h.undo()
    assert doc.resolved_elements(1) == []
    h.redo()
    assert len(doc.resolved_elements(1)) == 1
    assert h.can_undo and not h.can_redo


def test_move_commands_merge_during_drag():
    doc, h = _doc(), HistoryStack()
    el = TextElement(text="x", frame=Frame(0, 0, 50, 20))
    h.push(AddElement(doc, page=1, element=el))
    # un arrastre = muchos micro-movimientos con el mismo merge_key
    for i in range(1, 11):
        h.push(MoveResize(doc, page=1, element_id=el.id,
                          new_frame=Frame(i * 5.0, i * 2.0, 50, 20),
                          merge_key=f"drag-{el.id}-1"))
    assert h.undo_count == 2              # Add + UN solo MoveResize fusionado
    h.undo()
    assert doc.resolved_elements(1)[0].frame == Frame(0, 0, 50, 20)


def test_macro_groups_as_single_step():
    doc, h = _doc(), HistoryStack()
    els = [TextElement(text=f"e{i}") for i in range(3)]
    with h.macro("Pegar 3 elementos"):
        for el in els:
            h.push(AddElement(doc, page=1, element=el))
    assert h.undo_count == 1
    h.undo()
    assert doc.resolved_elements(1) == []


def test_redo_cleared_on_new_command():
    doc, h = _doc(), HistoryStack()
    a, b = TextElement(text="a"), TextElement(text="b")
    h.push(AddElement(doc, page=1, element=a))
    h.undo()
    h.push(AddElement(doc, page=1, element=b))
    assert not h.can_redo


def test_limit_drops_oldest():
    doc, h = _doc(), HistoryStack(limit=3)
    for i in range(5):
        h.push(AddElement(doc, page=1, element=TextElement(text=str(i))))
    assert h.undo_count == 3


def test_remove_element_roundtrip():
    doc, h = _doc(), HistoryStack()
    el = TextElement(text="x")
    h.push(AddElement(doc, page=1, element=el))
    h.push(RemoveElement(doc, page=1, element_id=el.id))
    assert doc.resolved_elements(1) == []
    h.undo()
    assert [r.element.id for r in doc.resolved_elements(1)] == [el.id]
```

- [x] **Step 11.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_history.py -v`
Expected: ModuleNotFoundError.

- [x] **Step 11.3: Implementar comandos**

`core/editor/history/commands.py`:

```python
"""Comandos undoables. Guardan DELTAS, no snapshots (spec §20).

Los elementos son dataclasses frozen: 'mover' = reemplazar el objeto por una
copia con frame nuevo. El comando guarda referencias old/new — barato y exacto.
"""
from __future__ import annotations
from dataclasses import replace


class Command:
    """Interfaz: do()/undo(); merge_key opcional para fusionar arrastres."""
    text: str = ""
    merge_key: str | None = None

    def do(self) -> None: ...
    def undo(self) -> None: ...

    def merge_with(self, newer: "Command") -> bool:
        """Absorbe un comando más nuevo con el mismo merge_key. False = no fusiona."""
        return False


class AddElement(Command):
    def __init__(self, doc, page: int, element) -> None:
        self.text = "Agregar elemento"
        self._doc, self._page, self._element = doc, page, element

    def do(self) -> None:
        self._doc.add_element(self._page, self._element)

    def undo(self) -> None:
        self._doc.remove_element(self._page, self._element.id)


class RemoveElement(Command):
    def __init__(self, doc, page: int, element_id: str) -> None:
        self.text = "Eliminar elemento"
        self._doc, self._page, self._eid = doc, page, element_id
        self._removed = None

    def do(self) -> None:
        self._removed = self._doc.remove_element(self._page, self._eid)

    def undo(self) -> None:
        if self._removed is not None:
            self._doc.add_element(self._page, self._removed)


class MoveResize(Command):
    def __init__(self, doc, page: int, element_id: str, new_frame,
                 merge_key: str | None = None) -> None:
        self.text = "Mover/redimensionar"
        self.merge_key = merge_key
        self._doc, self._page, self._eid = doc, page, element_id
        self._new_frame = new_frame
        self._old_frame = None

    def _find(self):
        for el in self._doc.elements_by_page.get(self._page, []):
            if el.id == self._eid:
                return el
        return None

    def _swap(self, frame) -> None:
        items = self._doc.elements_by_page[self._page]
        for i, el in enumerate(items):
            if el.id == self._eid:
                items[i] = replace(el, frame=frame)
                return

    def do(self) -> None:
        el = self._find()
        if self._old_frame is None and el is not None:
            self._old_frame = el.frame
        self._swap(self._new_frame)

    def undo(self) -> None:
        self._swap(self._old_frame)

    def merge_with(self, newer: "Command") -> bool:
        if isinstance(newer, MoveResize) and newer._eid == self._eid:
            self._new_frame = newer._new_frame
            self._swap(self._new_frame)   # newer ya hizo do(); estado consistente
            return True
        return False


class SetElementAttrs(Command):
    """Cambio de estilo/atributos: opacity, color, font_size, text, etc."""

    def __init__(self, doc, page: int, element_id: str,
                 merge_key: str | None = None, **attrs) -> None:
        self.text = "Cambiar propiedades"
        self.merge_key = merge_key
        self._doc, self._page, self._eid, self._attrs = doc, page, element_id, attrs
        self._old: dict | None = None

    def do(self) -> None:
        items = self._doc.elements_by_page[self._page]
        for i, el in enumerate(items):
            if el.id == self._eid:
                if self._old is None:
                    self._old = {k: getattr(el, k) for k in self._attrs}
                items[i] = replace(el, **self._attrs)
                return

    def undo(self) -> None:
        items = self._doc.elements_by_page[self._page]
        for i, el in enumerate(items):
            if el.id == self._eid:
                items[i] = replace(el, **(self._old or {}))
                return

    def merge_with(self, newer: "Command") -> bool:
        if isinstance(newer, SetElementAttrs) and newer._eid == self._eid \
                and set(newer._attrs) == set(self._attrs):
            self._attrs = newer._attrs
            return True
        return False
```

- [x] **Step 11.4: Implementar la pila**

`core/editor/history/stack.py`:

```python
"""Pila undo/redo pura (sin Qt — decisión registrada en el plan, spec §10.4)."""
from __future__ import annotations
from contextlib import contextmanager


class Macro:
    """Agrupa comandos hijos como UN paso."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.merge_key = None
        self.children: list = []

    def do(self) -> None:
        for c in self.children:
            c.do()

    def undo(self) -> None:
        for c in reversed(self.children):
            c.undo()

    def merge_with(self, newer) -> bool:
        return False


class HistoryStack:
    def __init__(self, limit: int = 200) -> None:
        self._limit = limit
        self._undo: list = []
        self._redo: list = []
        self._macro: Macro | None = None

    # ── push / macro ────────────────────────────────────────────────
    def push(self, cmd) -> None:
        cmd.do()
        self._redo.clear()
        if self._macro is not None:
            self._macro.children.append(cmd)
            return
        if (self._undo and cmd.merge_key
                and self._undo[-1].merge_key == cmd.merge_key
                and self._undo[-1].merge_with(cmd)):
            return
        self._undo.append(cmd)
        if len(self._undo) > self._limit:
            self._undo.pop(0)

    @contextmanager
    def macro(self, text: str):
        self._macro = Macro(text)
        try:
            yield self._macro
        finally:
            macro, self._macro = self._macro, None
            if macro.children:
                self._redo.clear()
                self._undo.append(macro)
                if len(self._undo) > self._limit:
                    self._undo.pop(0)

    # ── undo / redo ─────────────────────────────────────────────────
    def undo(self) -> None:
        if self._undo:
            cmd = self._undo.pop()
            cmd.undo()
            self._redo.append(cmd)

    def redo(self) -> None:
        if self._redo:
            cmd = self._redo.pop()
            cmd.do()
            self._undo.append(cmd)

    @property
    def can_undo(self) -> bool: return bool(self._undo)
    @property
    def can_redo(self) -> bool: return bool(self._redo)
    @property
    def undo_count(self) -> int: return len(self._undo)
```

- [x] **Step 11.5: Actualizar el spec (decisión QUndoStack → pila pura)**

En `docs/superpowers/specs/2026-06-09-pdflex-studio-editor-pdf-design.md`, reemplazar la línea:

`class HistoryStack:                  # fachada sobre QUndoStack`

por:

`class HistoryStack:                  # pila undo/redo pura (sin Qt; decisión Task 11 del plan)`

y en la tabla §6, fila 12, reemplazar `Patrón Command sobre QUndoStack` por `Patrón Command sobre pila propia sin Qt`.

- [x] **Step 11.6: Correr y commitear**

Run: `python -m pytest tests/editor/test_history.py -v`
Expected: 6 PASS.

```bash
git add core/editor/history/ tests/editor/test_history.py docs/superpowers/specs/2026-06-09-pdflex-studio-editor-pdf-design.md
git commit -m "feat(studio): pure-python undo stack with drag merge and macros"
```

---

### Task 12: `image_engine` — normalización RGBA, opacidad, recorte, volteos

**Files:**
- Create: `core/editor/image_engine.py`
- Create: `tests/editor/test_image_engine.py`

- [x] **Step 12.1: Tests que fallan**

`tests/editor/test_image_engine.py`:

```python
"""Normalización de imágenes: WebP/JPG/PNG → PNG RGBA con ops horneadas."""
import io

import pytest
from PIL import Image

from core.editor.image_engine import prepare_image_bytes


def _png(mode="RGB", size=(40, 40), color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="PNG")
    return buf.getvalue()


def _webp_with_alpha() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (40, 40), (0, 255, 0, 128)).save(buf, format="WEBP")
    return buf.getvalue()


def test_webp_alpha_normalizes_to_png_rgba():
    out = prepare_image_bytes(_webp_with_alpha())
    img = Image.open(io.BytesIO(out))
    assert img.format == "PNG" and img.mode == "RGBA"
    assert img.getpixel((5, 5))[3] == 128          # alfa preservado


def test_opacity_bakes_into_alpha():
    out = prepare_image_bytes(_png(), opacity=0.5)
    img = Image.open(io.BytesIO(out))
    assert img.mode == "RGBA"
    assert img.getpixel((5, 5))[3] == pytest.approx(127, abs=2)


def test_crop_fractions():
    out = prepare_image_bytes(_png(size=(100, 200)), crop=(0.25, 0.10, 0.75, 0.90))
    img = Image.open(io.BytesIO(out))
    assert img.size == (50, 160)


def test_flips():
    src = Image.new("RGB", (2, 1)); src.putpixel((0, 0), (255, 0, 0)); src.putpixel((1, 0), (0, 0, 255))
    buf = io.BytesIO(); src.save(buf, format="PNG")
    out = prepare_image_bytes(buf.getvalue(), flip_h=True)
    img = Image.open(io.BytesIO(out))
    assert img.getpixel((0, 0))[:3] == (0, 0, 255)  # rojo y azul intercambiados


def test_invalid_bytes_raise_value_error():
    with pytest.raises(ValueError, match="imagen"):
        prepare_image_bytes(b"not an image")
```

- [x] **Step 12.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_image_engine.py -v`
Expected: ModuleNotFoundError.

- [x] **Step 12.3: Implementar**

`core/editor/image_engine.py`:

```python
"""Preparación de imágenes para inserción (spec §6-6, §21-5, §21-12).

Pipeline: bytes (PNG/JPG/WebP/...) → PIL → [crop fracciones] → [flips] →
[opacidad horneada en alfa] → PNG RGBA bytes listos para insert_image.
La rotación NO se hornea aquí: es vectorial vía XObject (primitives).
"""
from __future__ import annotations
import io

from PIL import Image, UnidentifiedImageError

CropBox = tuple[float, float, float, float]   # l, t, r, b en fracciones [0,1]


def prepare_image_bytes(data: bytes, *, opacity: float = 1.0,
                        crop: CropBox | None = None,
                        flip_h: bool = False, flip_v: bool = False) -> bytes:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"No es una imagen válida: {exc}") from exc

    img = img.convert("RGBA")

    if crop is not None:
        w, h = img.size
        l, t, r, b = crop
        box = (round(w * l), round(h * t), round(w * r), round(h * b))
        if box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError(f"Recorte de imagen inválido: {crop}")
        img = img.crop(box)

    if flip_h:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if flip_v:
        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    if opacity < 1.0:
        alpha = img.getchannel("A").point(lambda a: round(a * max(0.0, opacity)))
        img.putalpha(alpha)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
```

- [x] **Step 12.4: Correr y commitear**

Run: `python -m pytest tests/editor/test_image_engine.py -v`
Expected: 5 PASS.

```bash
git add core/editor/image_engine.py tests/editor/test_image_engine.py
git commit -m "feat(studio): image normalization engine (webp/alpha/crop/opacity/flips)"
```

---

### Task 13: `text_engine` — estilos → primitivas (catálogo base-14 del foleador)

**Files:**
- Create: `core/editor/text_engine.py`
- Create: `tests/editor/test_text_engine.py`

- [x] **Step 13.1: Tests que fallan**

`tests/editor/test_text_engine.py`:

```python
"""Resolución de estilo de texto a parámetros de primitiva."""
import fitz
import pytest

from core.editor.model.elements import TextElement
from core.editor.text_engine import resolve_font, alignment_flag


def test_font_variants_match_foleador_map():
    assert resolve_font("helv", bold=False, italic=False) == "helv"
    assert resolve_font("helv", bold=True, italic=False) == "hebo"
    assert resolve_font("tiro", bold=True, italic=True) == "tibi"
    assert resolve_font("cour", bold=False, italic=True) == "coit"


def test_unknown_family_falls_back_to_helv():
    assert resolve_font("comic-sans", bold=False, italic=False) == "helv"
    assert resolve_font("comic-sans", bold=True, italic=False) == "hebo"


def test_alignment_flags():
    assert alignment_flag("left") == fitz.TEXT_ALIGN_LEFT
    assert alignment_flag("center") == fitz.TEXT_ALIGN_CENTER
    assert alignment_flag("right") == fitz.TEXT_ALIGN_RIGHT
    assert alignment_flag("justify") == fitz.TEXT_ALIGN_JUSTIFY
```

- [x] **Step 13.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_text_engine.py -v`
Expected: ModuleNotFoundError.

- [x] **Step 13.3: Implementar**

`core/editor/text_engine.py`:

```python
"""Estilo de texto → parámetros de primitivas.

MVP: catálogo base-14 (helv/tiro/cour + variantes), EXACTAMENTE el mapa probado
de core/foleador_engine._FONT_VARIANTS — consistencia visual con el Foleador.
Fase 2 añade fuentes embebidas OFL + sistema (fontTools) sin tocar este contrato.
"""
from __future__ import annotations

import fitz

_FONT_VARIANTS: dict[tuple[str, bool, bool], str] = {
    ("helv", False, False): "helv", ("helv", True, False): "hebo",
    ("helv", False, True): "heit", ("helv", True, True): "hebi",
    ("tiro", False, False): "tiro", ("tiro", True, False): "tibo",
    ("tiro", False, True): "tiit", ("tiro", True, True): "tibi",
    ("cour", False, False): "cour", ("cour", True, False): "cobo",
    ("cour", False, True): "coit", ("cour", True, True): "cobi",
}

_ALIGN = {
    "left": fitz.TEXT_ALIGN_LEFT, "center": fitz.TEXT_ALIGN_CENTER,
    "right": fitz.TEXT_ALIGN_RIGHT, "justify": fitz.TEXT_ALIGN_JUSTIFY,
}


def resolve_font(family: str, *, bold: bool, italic: bool) -> str:
    base = family if (family, False, False) in _FONT_VARIANTS else "helv"
    return _FONT_VARIANTS[(base, bold, italic)]


def alignment_flag(align: str) -> int:
    return _ALIGN.get(align, fitz.TEXT_ALIGN_LEFT)
```

- [x] **Step 13.4: Correr y commitear**

Run: `python -m pytest tests/editor/test_text_engine.py -v`
Expected: 3 PASS.

```bash
git add core/editor/text_engine.py tests/editor/test_text_engine.py
git commit -m "feat(studio): text style resolution reusing foleador base-14 font map"
```

---

### Task 14: `Exporter` + `Verifier` + `BackupManager` (exportación segura completa)

**Files:**
- Create: `core/editor/export/exporter.py`
- Create: `core/editor/export/verifier.py`
- Create: `core/editor/export/backup.py`
- Create: `tests/editor/test_exporter.py`

- [x] **Step 14.1: Tests que fallan**

`tests/editor/test_exporter.py`:

```python
"""Exportador end-to-end: documento+reglas → PDF nuevo verificado, original intacto."""
import hashlib

import fitz
import pytest

from core.editor.export.exporter import ExportOptions, Exporter
from core.editor.geometry import PageGeometry
from core.editor.model.document_state import EditorDocument
from core.editor.model.elements import ImageElement, TextElement
from core.editor.model.layers import Layer
from core.editor.model.page_target import PageTarget
from core.editor.model.placement import Anchor, Frame, Placement
from core.editor.model.rules import PageRule


def _build_doc(pdf_path) -> EditorDocument:
    with fitz.open(pdf_path) as d:
        geos = [PageGeometry.from_page(i, d[i]) for i in range(d.page_count)]
    sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    return EditorDocument(source_path=str(pdf_path), source_sha256=sha,
                          page_geometries=geos)


def test_export_concrete_text_and_rule_on_odd_pages(make_pdf, tmp_path):
    src = make_pdf(rotations=[0, 90, 0, 270])
    doc = _build_doc(src)
    doc.add_element(2, TextElement(text="SOLO PÁG 2", font_size=18,
                                   frame=Frame(80, 100, 250, 40)))
    doc.add_rule(PageRule(
        element=TextElement(text="Pág. {pagina} de {total}", variables_enabled=True,
                            frame=Frame(0, 0, 140, 16), font_size=9,
                            placement=Placement(mode="anchor",
                                                anchor=Anchor.BOTTOM_CENTER, dy_pt=-12)),
        target=PageTarget(mode="odd")))
    out = tmp_path / "salida.pdf"
    src_bytes = src.read_bytes()

    result = Exporter().export(doc, out, ExportOptions())

    assert result.success, result.error
    assert src.read_bytes() == src_bytes          # original INTACTO byte a byte
    with fitz.open(out) as d:
        assert d.page_count == 4
        assert "SOLO PÁG 2" in d[1].get_text()
        assert "Pág. 1 de 4" in d[0].get_text()
        assert "Pág. 3 de 4" in d[2].get_text()   # página /Rotate=0
        assert "SOLO PÁG 2" not in d[0].get_text()
        assert "Pág. 2" not in d[1].get_text()    # regla es solo impares


def test_export_image_element(make_pdf, probe_png, tmp_path):
    src = make_pdf(rotations=[90])
    doc = _build_doc(src)
    doc.assets = {"img1": probe_png}              # AssetResolver simple (dict)
    doc.add_element(1, ImageElement(asset_id="img1", frame=Frame(100, 120, 80, 80)))
    out = tmp_path / "img.pdf"
    result = Exporter().export(doc, out, ExportOptions())
    assert result.success
    with fitz.open(out) as d:
        infos = d[0].get_image_info()
        assert len(infos) == 1
        got = fitz.Rect(infos[0]["bbox"])
        assert got.x0 == pytest.approx(100, abs=0.5) and got.y0 == pytest.approx(120, abs=0.5)


def test_hidden_layer_not_exported(make_pdf, tmp_path):
    src = make_pdf()
    doc = _build_doc(src)
    doc.layers.add(Layer(id="oculta", name="Oculta", z=1, visible=False))
    doc.add_element(1, TextElement(text="NO DEBE SALIR", layer_id="oculta"))
    out = tmp_path / "capas.pdf"
    assert Exporter().export(doc, out, ExportOptions()).success
    with fitz.open(out) as d:
        assert "NO DEBE SALIR" not in d[0].get_text()


def test_backup_created_when_overwriting(make_pdf, tmp_path):
    src = make_pdf()
    doc = _build_doc(src)
    doc.add_element(1, TextElement(text="v2"))
    out = tmp_path / "salida.pdf"
    out.write_bytes(b"%PDF-1.4 contenido previo")
    result = Exporter().export(doc, out, ExportOptions())
    assert result.success
    backups = list((tmp_path / "respaldo").glob("salida*.pdf"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"%PDF-1.4 contenido previo"


def test_progress_and_cancel(make_pdf, tmp_path):
    src = make_pdf(rotations=[0] * 6)
    doc = _build_doc(src)
    calls = []
    result = Exporter().export(doc, tmp_path / "c.pdf", ExportOptions(),
                               progress=lambda c, t, m: calls.append((c, t)),
                               should_cancel=lambda: len(calls) >= 3)
    assert not result.success and "cancel" in result.error.lower()
    assert not (tmp_path / "c.pdf").exists()      # cancelado → no deja basura


def test_verifier_rejects_corrupt_output(tmp_path):
    from core.editor.export.verifier import verify_pdf
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"garbage")
    ok, msg = verify_pdf(bad, expected_pages=1)
    assert not ok and msg
```

- [x] **Step 14.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_exporter.py -v`
Expected: ImportError.

- [x] **Step 14.3: Implementar `backup.py` y `verifier.py`**

`core/editor/export/backup.py`:

```python
"""Respaldo del archivo destino antes de sobrescribir (spec §15)."""
from __future__ import annotations
import shutil
from datetime import datetime
from pathlib import Path


def backup_existing(target: Path) -> Path | None:
    """Si target existe, lo copia a <dir>/respaldo/<stem>_<timestamp>.pdf."""
    if not target.exists():
        return None
    backup_dir = target.parent / "respaldo"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"{target.stem}_{stamp}{target.suffix}"
    shutil.copy2(target, dest)
    return dest
```

`core/editor/export/verifier.py`:

```python
"""Verificación post-exportación: el PDF debe reabrirse y renderizar (spec §15)."""
from __future__ import annotations
from pathlib import Path

import fitz


def verify_pdf(path: Path, expected_pages: int) -> tuple[bool, str]:
    try:
        if path.stat().st_size == 0:
            return False, "El archivo exportado está vacío"
        with fitz.open(str(path)) as doc:
            if doc.page_count != expected_pages:
                return False, (f"Páginas esperadas {expected_pages}, "
                               f"obtenidas {doc.page_count}")
            # Render de muestra: primera, última y una del medio
            for idx in sorted({0, doc.page_count // 2, doc.page_count - 1}):
                doc[idx].get_pixmap(matrix=fitz.Matrix(0.4, 0.4))
        return True, ""
    except Exception as exc:                      # noqa: BLE001 — se reporta
        return False, f"El PDF exportado no es válido: {exc}"
```

- [x] **Step 14.4: Implementar `exporter.py`**

`core/editor/export/exporter.py`:

```python
"""Exportador: EditorDocument → PDF nuevo. NUNCA toca el original (spec §15).

Flujo: abrir copia del fuente → por página: resolved_elements() → primitivas
rotación-seguras → guardar a temporal → verificar → respaldo del destino si
existe → os.replace atómico. Contrato de progreso idéntico a los engines de
la suite: progress(current, total, msg) + should_cancel().
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import fitz

from core.editor.geometry import PageGeometry
from core.editor.image_engine import prepare_image_bytes
from core.editor.model.document_state import EditorDocument
from core.editor.model.model_types import ResolvedElement
from core.editor.text_engine import alignment_flag, resolve_font
from .backup import backup_existing
from .primitives import stamp_image, stamp_image_rotated, stamp_rect, stamp_text
from .verifier import verify_pdf


@dataclass(frozen=True)
class ExportOptions:
    garbage: int = 3
    deflate: bool = True


@dataclass
class ExportResult:
    output_path: str = ""
    success: bool = False
    error: str = ""
    page_count: int = 0
    warnings: list[str] = field(default_factory=list)


class Exporter:
    def export(self, doc: EditorDocument, output_path: Path,
               options: ExportOptions,
               progress: Callable[[int, int, str], None] | None = None,
               should_cancel: Callable[[], bool] | None = None) -> ExportResult:
        output_path = Path(output_path)
        result = ExportResult(output_path=str(output_path))
        tmp = output_path.with_suffix(".tmp.pdf")
        total = doc.page_count
        try:
            with fitz.open(doc.source_path) as pdf:
                for page_no in range(1, total + 1):
                    if should_cancel and should_cancel():
                        result.error = "Exportación cancelada por el usuario"
                        return result
                    if progress:
                        progress(page_no - 1, total, f"Exportando página {page_no}")
                    page = pdf[page_no - 1]
                    geo = doc.page_geometries[page_no - 1]
                    for res in doc.resolved_elements(page_no):
                        self._stamp(page, geo, res, doc, result)
                pdf.save(str(tmp), garbage=options.garbage, deflate=options.deflate)

            ok, msg = verify_pdf(tmp, expected_pages=total)
            if not ok:
                result.error = f"Verificación fallida: {msg}"
                return result
            backup_existing(output_path)
            os.replace(tmp, output_path)
            result.success = True
            result.page_count = total
            if progress:
                progress(total, total, "Exportación completada")
            return result
        except Exception as exc:                  # noqa: BLE001 — se reporta
            result.error = f"Error al exportar: {exc}"
            return result
        finally:
            if tmp.exists() and not result.success:
                try:
                    tmp.unlink()
                except OSError:
                    pass

    # ------------------------------------------------------------------
    def _stamp(self, page: fitz.Page, geo: PageGeometry, res: ResolvedElement,
               doc: EditorDocument, result: ExportResult) -> None:
        el = res.element
        rect = fitz.Rect(res.frame.x, res.frame.y,
                         res.frame.x + res.frame.w, res.frame.y + res.frame.h)
        if el.kind == "text":
            if el.box_fill is not None:
                stamp_rect(page, geo, rect, fill=el.box_fill,
                           opacity=el.box_fill_opacity * res.effective_opacity)
            leftover = stamp_text(
                page, geo, rect, res.text if res.text is not None else el.text,
                fontsize=el.font_size,
                fontname=resolve_font(el.font_family, bold=el.bold, italic=el.italic),
                color=el.color, opacity=res.effective_opacity,
                align=alignment_flag(el.align), angle_deg=el.rotation_deg)
            if leftover < 0:
                result.warnings.append(
                    f"Página {geo.index + 1}: el texto {el.id[:8]} no cupo completo "
                    f"en su caja (faltaron {-leftover:.0f} pt)")
        elif el.kind == "image":
            data = doc.assets[el.asset_id]
            data = prepare_image_bytes(data, opacity=res.effective_opacity,
                                       crop=el.crop, flip_h=el.flip_h,
                                       flip_v=el.flip_v)
            if el.rotation_deg:
                stamp_image_rotated(page, geo, rect, data, angle_deg=el.rotation_deg)
            else:
                stamp_image(page, geo, rect, data)
```

Nota: `EditorDocument` necesita el atributo `assets: dict[str, bytes]` — añadir a `document_state.py` el campo `assets: dict[str, bytes] = field(default_factory=dict)` (el AssetStore del proyecto lo poblará en Task 15).

- [x] **Step 14.5: Correr y commitear**

Run: `python -m pytest tests/editor/test_exporter.py tests/editor/ -v`
Expected: exporter 6 PASS y TODO el resto sigue verde.

```bash
git add core/editor/export/ core/editor/model/document_state.py tests/editor/test_exporter.py
git commit -m "feat(studio): verified atomic exporter with backup, progress and cancel"
```

---

### Task 15: Proyecto `.flexproj` — guardar/cargar con assets y autosave

**Files:**
- Create: `core/editor/project/__init__.py` (vacío)
- Create: `core/editor/project/format.py`
- Create: `core/editor/project/autosave.py`
- Create: `tests/editor/test_project_roundtrip.py`

- [x] **Step 15.1: Tests que fallan**

`tests/editor/test_project_roundtrip.py`:

```python
"""Proyecto .flexproj: zip con manifest/elementos/reglas/capas/assets; round-trip total."""
import zipfile

import pytest

from core.editor.project.format import ProjectStore, SCHEMA_VERSION
from core.editor.geometry import PageGeometry
from core.editor.model.document_state import EditorDocument
from core.editor.model.elements import ImageElement, TextElement
from core.editor.model.layers import Layer
from core.editor.model.page_target import PageTarget
from core.editor.model.placement import Frame
from core.editor.model.rules import PageRule


def _doc(src="x.pdf"):
    geo = PageGeometry(index=0, width_pt=595, height_pt=842, rotation=0,
                       derotation_matrix=(1, 0, 0, 1, 0, 0),
                       rotation_matrix=(1, 0, 0, 1, 0, 0))
    return EditorDocument(source_path=src, source_sha256="a" * 64,
                          page_geometries=[geo])


def test_save_load_roundtrip(tmp_path):
    doc = _doc()
    doc.layers.add(Layer(id="sellos", name="Sellos", z=5, opacity=0.8))
    doc.assets["i1"] = b"\x89PNG fake-bytes"
    doc.add_element(1, TextElement(text="hola {pagina}", variables_enabled=True,
                                   frame=Frame(1, 2, 3, 4), layer_id="sellos"))
    doc.add_element(1, ImageElement(asset_id="i1", frame=Frame(9, 9, 50, 50)))
    doc.add_rule(PageRule(element=TextElement(text="regla"),
                          target=PageTarget(mode="even")))
    path = tmp_path / "proyecto.flexproj"

    ProjectStore().save(doc, path)
    loaded = ProjectStore().load(path)

    assert loaded.source_path == doc.source_path
    assert loaded.source_sha256 == doc.source_sha256
    assert len(loaded.page_geometries) == 1
    assert loaded.page_geometries[0].rotation_matrix == (1, 0, 0, 1, 0, 0)
    assert loaded.assets["i1"] == b"\x89PNG fake-bytes"
    els = loaded.elements_by_page[1]
    assert els[0] == doc.elements_by_page[1][0]
    assert els[1] == doc.elements_by_page[1][1]
    assert loaded.rules[0] == doc.rules[0]
    assert loaded.layers.get("sellos").opacity == 0.8


def test_flexproj_is_valid_zip_with_manifest(tmp_path):
    path = tmp_path / "p.flexproj"
    ProjectStore().save(_doc(), path)
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        assert {"manifest.json", "document.json", "elements.json",
                "rules.json", "layers.json"} <= names
        import json
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["schema_version"] == SCHEMA_VERSION


def test_load_rejects_newer_schema(tmp_path):
    import json, shutil
    path = tmp_path / "p.flexproj"
    ProjectStore().save(_doc(), path)
    # Reescribir el manifest con una versión futura
    bumped = tmp_path / "b.flexproj"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(bumped, "w") as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item == "manifest.json":
                m = json.loads(data); m["schema_version"] = 999
                data = json.dumps(m).encode()
            zout.writestr(item, data)
    with pytest.raises(ValueError, match="versión"):
        ProjectStore().load(bumped)


def test_atomic_save_never_leaves_partial_file(tmp_path):
    """Guardar sobre un proyecto existente: si todo va bien, el contenido es nuevo;
    el archivo nunca existe en estado intermedio (se escribe a .tmp y se renombra)."""
    path = tmp_path / "p.flexproj"
    ProjectStore().save(_doc("uno.pdf"), path)
    ProjectStore().save(_doc("dos.pdf"), path)
    assert ProjectStore().load(path).source_path == "dos.pdf"
    assert not list(tmp_path.glob("*.tmp*"))
```

- [x] **Step 15.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_project_roundtrip.py -v`
Expected: ModuleNotFoundError.

- [x] **Step 15.3: Implementar `format.py`**

`core/editor/project/format.py`:

```python
"""Formato .flexproj (spec §17): zip con manifest + JSON + assets binarios."""
from __future__ import annotations
import json
import os
import zipfile
from dataclasses import asdict
from pathlib import Path

from core.editor.geometry import PageGeometry
from core.editor.model.document_state import EditorDocument
from core.editor.model.elements import element_from_dict
from core.editor.model.layers import LayerStack
from core.editor.model.rules import PageRule

SCHEMA_VERSION = 1


class ProjectStore:
    def save(self, doc: EditorDocument, path: Path) -> None:
        path = Path(path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps({
                "schema_version": SCHEMA_VERSION, "app": "PDFlex Studio"}))
            z.writestr("document.json", json.dumps({
                "source_path": doc.source_path,
                "source_sha256": doc.source_sha256,
                "pages": [asdict(g) for g in doc.page_geometries]}))
            z.writestr("elements.json", json.dumps({
                str(page): [el.to_dict() for el in els]
                for page, els in doc.elements_by_page.items()}))
            z.writestr("rules.json", json.dumps([r.to_dict() for r in doc.rules]))
            z.writestr("layers.json", json.dumps(doc.layers.to_dict()))
            for asset_id, data in doc.assets.items():
                z.writestr(f"assets/{asset_id}", data)
        os.replace(tmp, path)

    def load(self, path: Path) -> EditorDocument:
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read("manifest.json"))
            version = manifest.get("schema_version", 0)
            if version > SCHEMA_VERSION:
                raise ValueError(
                    f"El proyecto usa una versión más nueva ({version}) que esta "
                    f"instalación de PDFlex ({SCHEMA_VERSION}). Actualiza PDFlex.")
            docd = json.loads(z.read("document.json"))
            geos = [PageGeometry(**{**g, "derotation_matrix": tuple(g["derotation_matrix"]),
                                    "rotation_matrix": tuple(g["rotation_matrix"])})
                    for g in docd["pages"]]
            doc = EditorDocument(source_path=docd["source_path"],
                                 source_sha256=docd["source_sha256"],
                                 page_geometries=geos,
                                 layers=LayerStack.from_dict(json.loads(z.read("layers.json"))))
            for page_str, els in json.loads(z.read("elements.json")).items():
                for d in els:
                    doc.add_element(int(page_str), element_from_dict(d))
            doc.rules = [PageRule.from_dict(d) for d in json.loads(z.read("rules.json"))]
            for name in z.namelist():
                if name.startswith("assets/") and not name.endswith("/"):
                    doc.assets[name.split("/", 1)[1]] = z.read(name)
        return doc
```

- [x] **Step 15.4: Implementar `autosave.py`**

`core/editor/project/autosave.py`:

```python
"""Autosave: escritura periódica atómica en %APPDATA%/PDFlex/autosave (spec §15).

Sin Qt: quien lo usa (EditorWindow, plan Parte 2) llama maybe_autosave() desde
un QTimer. Aquí solo vive la política (intervalo, destino, limpieza)."""
from __future__ import annotations
import os
import time
from pathlib import Path

from .format import ProjectStore


def autosave_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home())) / "PDFlex" / "autosave"
    base.mkdir(parents=True, exist_ok=True)
    return base


class Autosaver:
    def __init__(self, interval_s: float = 90.0, directory: Path | None = None) -> None:
        self._interval = interval_s
        self._dir = directory or autosave_dir()
        self._last_save = 0.0
        self._dirty = False

    def mark_dirty(self) -> None:
        self._dirty = True

    def autosave_path(self, doc) -> Path:
        return self._dir / f"{doc.source_sha256[:16]}.flexproj"

    def maybe_autosave(self, doc) -> Path | None:
        """Guarda si hay cambios y pasó el intervalo. Retorna la ruta si guardó."""
        if not self._dirty or (time.monotonic() - self._last_save) < self._interval:
            return None
        path = self.autosave_path(doc)
        ProjectStore().save(doc, path)
        self._last_save = time.monotonic()
        self._dirty = False
        return path

    def discard(self, doc) -> None:
        """Al cerrar limpiamente se elimina el autosave (ya no hay nada que recuperar)."""
        p = self.autosave_path(doc)
        if p.exists():
            p.unlink()

    def pending_recoveries(self) -> list[Path]:
        return sorted(self._dir.glob("*.flexproj"))
```

Añadir test a `tests/editor/test_project_roundtrip.py`:

```python
def test_autosaver_respects_dirty_and_interval(tmp_path):
    from core.editor.project.autosave import Autosaver
    doc = _doc()
    saver = Autosaver(interval_s=0.0, directory=tmp_path)
    assert saver.maybe_autosave(doc) is None          # sin cambios → no guarda
    saver.mark_dirty()
    p = saver.maybe_autosave(doc)
    assert p is not None and p.exists()
    assert saver.maybe_autosave(doc) is None          # ya no está dirty
    saver.mark_dirty()
    saver.discard(doc)
    assert saver.pending_recoveries() == []
```

- [x] **Step 15.5: Correr y commitear**

Run: `python -m pytest tests/editor/test_project_roundtrip.py -v`
Expected: 5 PASS.

```bash
git add core/editor/project/ tests/editor/test_project_roundtrip.py
git commit -m "feat(studio): .flexproj project format with atomic save and autosave policy"
```

---

### Task 16: `validation.py` — chequeos al abrir (password, daño, firmas, resumen)

**Files:**
- Create: `core/editor/validation.py`
- Create: `tests/editor/test_validation.py`

- [x] **Step 16.1: Tests que fallan**

`tests/editor/test_validation.py`:

```python
"""Validación al abrir: cifrado, daño reparado, firmas digitales, resumen de páginas."""
import fitz
import pytest

from core.editor.validation import OpenReport, inspect_pdf


def test_clean_pdf_report(make_pdf):
    path = make_pdf(rotations=[0, 90], with_text=True)
    rep = inspect_pdf(path)
    assert rep.ok and not rep.needs_password
    assert rep.page_count == 2
    assert rep.rotated_pages == [2]            # 1-based
    assert rep.scanned_pages == []             # tiene texto nativo
    assert not rep.has_signatures


def test_scanned_pages_detected(make_pdf):
    path = make_pdf(rotations=[0])             # sin texto
    rep = inspect_pdf(path)
    assert rep.scanned_pages == [1]


def test_encrypted_pdf_needs_password(make_pdf, tmp_path):
    src = make_pdf()
    enc = tmp_path / "enc.pdf"
    with fitz.open(src) as doc:
        doc.save(str(enc), encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw="own", user_pw="usr")
    rep = inspect_pdf(enc)
    assert rep.needs_password and not rep.ok
    rep2 = inspect_pdf(enc, password="usr")
    assert rep2.ok and not rep2.needs_password


def test_signature_fields_detected(make_pdf):
    src = make_pdf()
    with fitz.open(src) as doc:
        page = doc[0]
        w = fitz.Widget()
        w.field_name = "firma1"
        w.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE
        w.rect = fitz.Rect(50, 50, 200, 100)
        page.add_widget(w)
        out = src.with_name("signed.pdf")
        doc.save(str(out))
    rep = inspect_pdf(out)
    assert rep.has_signatures


def test_missing_file_reports_error(tmp_path):
    rep = inspect_pdf(tmp_path / "no_existe.pdf")
    assert not rep.ok and rep.error
```

- [x] **Step 16.2: Correr y verificar que falla**

Run: `python -m pytest tests/editor/test_validation.py -v`
Expected: ModuleNotFoundError.

- [x] **Step 16.3: Implementar**

`core/editor/validation.py`:

```python
"""Inspección al abrir un PDF en el Studio (spec §15).

Produce un OpenReport con todo lo que la UI necesita para avisar al usuario:
contraseña, daño reparado al vuelo, firmas digitales (se invalidarían al
editar), páginas rotadas y páginas sin texto nativo (candidatas a OCR).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

import fitz


@dataclass
class OpenReport:
    ok: bool = False
    error: str = ""
    needs_password: bool = False
    was_repaired: bool = False
    has_signatures: bool = False
    page_count: int = 0
    rotated_pages: list[int] = field(default_factory=list)    # 1-based
    scanned_pages: list[int] = field(default_factory=list)    # 1-based, sin texto
    mixed_sizes: bool = False


def inspect_pdf(path: Path, password: str | None = None) -> OpenReport:
    rep = OpenReport()
    try:
        doc = fitz.open(str(path))
    except Exception as exc:                      # noqa: BLE001 — se reporta
        rep.error = f"No se pudo abrir el PDF: {exc}"
        return rep
    try:
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                rep.needs_password = True
                rep.error = "El PDF está protegido con contraseña"
                return rep
        rep.was_repaired = bool(getattr(doc, "is_repaired", False))
        rep.page_count = doc.page_count

        sizes: set[tuple[int, int]] = set()
        for i, page in enumerate(doc, start=1):
            if page.rotation % 360 != 0:
                rep.rotated_pages.append(i)
            sizes.add((round(page.rect.width), round(page.rect.height)))
            if not page.get_text("words"):
                rep.scanned_pages.append(i)
        rep.mixed_sizes = len(sizes) > 1

        # Firmas digitales: campos widget de tipo firma en cualquier página
        for page in doc:
            for w in page.widgets() or []:
                if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    rep.has_signatures = True
                    break
            if rep.has_signatures:
                break

        rep.ok = True
        return rep
    finally:
        doc.close()
```

- [x] **Step 16.4: Correr TODO el suite del editor y commitear**

Run: `python -m pytest tests/editor/ -v`
Expected: TODO verde (≈60 tests).

```bash
git add core/editor/validation.py tests/editor/test_validation.py
git commit -m "feat(studio): open-time PDF inspection (password, repair, signatures, scan/rotation summary)"
```

---

## Cierre del plan

- [x] **Final 1: Suite completa del repo en verde**

Run: `python -m pytest tests/ -q`
Expected: todos los tests del repo (existentes + editor) pasan. Los tests existentes NO deben verse afectados (este plan no modificó ningún archivo previo).

- [x] **Final 2: Actualizar el plan con casillas marcadas y estado**

Marcar checkboxes completados en este archivo y commitear:

```bash
git add docs/superpowers/plans/2026-06-09-pdflex-studio-fase0-nucleo.md
git commit -m "docs(studio): phase 0 + core phase 1 plan executed"
```

- [x] **Final 3: Gate de decisión**

Con el gate verde, escribir el plan **Parte 2 — UI** (canvas QGraphicsScene, paneles, EditorWindow, registro en launcher cuando el WIP del usuario esté commiteado) siguiendo el spec §18.

## Self-review del plan (ejecutado al escribirlo)

1. **Cobertura del spec (Fase 0 + Fase 1 núcleo):** geometría/derotación ✔ (T2), prueba reina 4 rotaciones ✔ (T3-T4), rotación libre ✔ (T5), render asíncrono+caché+cancelación ✔ (T6), modelo+anclas+normalizado ✔ (T7), targets ✔ (T8), variables ✔ (T9), capas+reglas+resolución ✔ (T10), historial ✔ (T11), imágenes ✔ (T12), texto ✔ (T13), exportador+verificación+respaldo+atomicidad+cancelación ✔ (T14), proyecto+autosave ✔ (T15), validación al abrir ✔ (T16). Diferidos a planes siguientes (registrado): UI completa, OCR bridge, plantillas store, contenido existente, OCG (necesita capa UI para tener sentido).
2. **Placeholders:** ninguno — todo step de código incluye el código.
3. **Consistencia de tipos:** `PageGeometry` (T2) consumido igual en T3-T16; `Frame/Placement` (T7) en T10-T15; `resolved_elements()` (T10) consumido por Exporter (T14); `doc.assets` introducido en T14 y persistido en T15; firmas `progress/should_cancel` idénticas al contrato de la suite.


---

## Registro de ejecución (2026-06-09) — PLAN COMPLETADO

**Resultado:** 16/16 tareas en verde. Suite completa del repo: **324 passed** (73 nuevos del editor + 251 existentes sin regresión). Rama `feature/pdflex-studio`, solo archivos nuevos.

### Desviaciones empíricas respecto al plan (todas demostradas por sondas + tests por píxeles)

1. **Contrato de coordenadas PyMuPDF 1.27 (Tasks 2-4):** el plan asumía la receta clásica "derotar + rotate=página" con verificación vía `get_drawings`/`get_image_info`/`get_text`. Las sondas demostraron que (a) TODAS las APIs de inserción operan en espacio sin rotar (la derotación quedó como chokepoint único `geometry.insertion_rect`), (b) texto E imagen necesitan `rotate=page.rotation` para quedar derechos en pantalla, y (c) **las APIs de extracción reportan en espacio sin rotar** (eco del input), por lo que la prueba reina se endureció a verificación POR PÍXELES RENDERIZADOS (escáner numpy, 0.5 pt de resolución). El spec §12.4/§13/§21-1 quedó actualizado.
2. **Rotación libre de imágenes (Task 5):** se descartó `show_pdf_page`/XObject (ignora `/Rotate` — precedente del membrete — y su semántica fit-inside no es la de un canvas). Implementado con pre-rotación PIL (`expand=True`) + `stamp_image` probado. Convención de producto: ángulo positivo = horario (paridad Qt).
3. **`insert_textbox` exige alto mínimo ≈ fontsize×1.68** (sondeado: 23.5 pt para 14 pt); si no cabe, omite silenciosamente y retorna déficit. El Exporter lo convierte en warning y el test del gate exige `leftover >= 0`.
4. **`mixed_sizes` (Task 16):** el par (w,h) display se normaliza ordenado — `/Rotate` transpone el display pero el papel físico es el mismo.
5. **RenderService (Task 6):** un solo lock para generación+caché (el caché se comparte entre hilos); el hit de caché emite síncrono; la generación inicia en 0.
6. **Historial (Task 11):** pila pura sin QUndoStack, registrado también en spec §10.4 y tabla §6.

### Siguiente paso

Plan **Parte 2 — UI** (canvas QGraphicsScene, paneles, EditorWindow, registro en launcher) según spec §18, sobre este núcleo ya validado.
