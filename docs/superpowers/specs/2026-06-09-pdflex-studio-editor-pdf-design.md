# PDFlex Studio — Editor Visual Avanzado de PDF (Propuesta Técnica Completa)

**Fecha:** 2026-06-09
**Estado:** Propuesta — pendiente de aprobación
**Autor:** Diseño técnico asistido (brainstorming + recon del codebase PDFlex)

---

## 1. Nombre sugerido

**PDFlex Studio** — el editor insignia de la suite PDFlex.

- Producto/herramienta: **PDFlex Studio** (en el launcher: "Studio — Editor visual").
- Paquete del motor: `core/editor/` (codename interno: **flexcanvas**).
- Formato de proyecto: **`.flexproj`** · Formato de plantilla: **`.flextpl`**.

Alternativas consideradas: *PDFlex Canvas* (suena a herramienta de dibujo), *PDFlex Editor Pro* (genérico). "Studio" comunica un espacio de trabajo profesional y diferencia esta herramienta de las herramientas-pipeline existentes (membretado, foleador, etc.).

## 2. Objetivo

Crear un **editor visual de superposición (overlay) de nivel profesional** para PDF: colocar y manipular texto, cuadros de texto, imágenes, sellos, firmas, marcas de agua, folios y formas sobre cualquier PDF — con selección, arrastre, redimensionamiento, rotación, opacidad, capas, panel de propiedades, aplicación masiva por páginas, plantillas reutilizables, proyectos editables y exportación sin pérdida de calidad — sin dañar jamás el documento original.

El editor **no pretende ser un reemplazo de Adobe Acrobat para re-maquetar PDFs** (reflow completo de párrafos). Su fortaleza es la **superposición precisa y masiva** + edición puntual de contenido existente cuando el PDF lo permite. Esta distinción de alcance es deliberada y es lo que hace viable un producto estable en Python.

## 3. Alcance

### Incluido (versión profesional)

1. Insertar texto editable sobre el PDF (clic-para-escribir, estilo Sejda).
2. Cuadros de texto movibles, redimensionables, rotables, con edición inline WYSIWYG.
3. Estilo completo de texto: fuente, tamaño, color, opacidad, alineación (izq/centro/der/justificado), rotación libre, interlineado, negrita/itálica/subrayado, fondo opcional del cuadro.
4. Imágenes PNG/JPG/WebP con transparencia alfa.
5. Mover, escalar (con/sin proporción), rotar libremente, recortar y cambiar opacidad de imágenes.
6. Aplicación por objetivo de páginas: página actual, lista ("1,3,9"), rangos ("5-12", "20-"), pares, impares, todas — y combinaciones ("1-5,9,12-").
7. Encabezados, pies de página, marcas de agua, sellos, firmas y folios como **reglas por página** (ver §10.3) con variables dinámicas.
8. Capas editables (visibilidad, bloqueo, orden z, opacidad de capa) + exportación opcional como OCG (capas PDF reales).
9. Proyectos editables `.flexproj` con autosave y recuperación ante crash.
10. Exportación a PDF nuevo, atómica, verificada, con respaldo automático — el original nunca se modifica.
11. Calidad máxima: overlay vectorial por defecto; rasterizado sólo como fallback explícito.
12. Soporte de PDFs escaneados, pesados (1000+ páginas / 500+ MB), páginas rotadas (/Rotate 90/180/270), tamaños mixtos por página.
13. OCR integrado (Tesseract embebido ya presente en la suite): hacer PDF buscable (capa de texto invisible) y asistir edición sobre escaneos.
14. Edición de texto existente **en modo "reemplazo en caja"** (sin reflow) cuando el PDF tiene texto nativo.
15. Detección, ocultamiento, reemplazo y reposicionamiento de imágenes existentes (con advertencias cuando el recurso es compartido entre páginas).
16. Deshacer/rehacer ilimitado-acotado, copiar/pegar/duplicar, bloquear, ocultar, eliminar, multi-selección, alinear/distribuir.
17. Plantillas reutilizables (`.flextpl`) para textos, logos, marcas de agua, sellos, firmas y configuraciones de página, con galería.
18. Validación al abrir, reparación (motor existente), respaldo automático antes de guardar.

### Excluido explícitamente (no-objetivos)

- Reflow tipográfico de párrafos existentes (re-maquetado estilo Acrobat "Edit PDF" completo).
- Edición de contenido vectorial existente (paths) más allá de cubrir/ocultar.
- Firmas digitales criptográficas nuevas (PAdES) — el Firmador existente cubre firma visual; firma criptográfica queda como integración futura.
- Editor de formularios AcroForm (ya existe `ui/formularios`).
- Colaboración multi-usuario / nube.

## 4. Análisis competitivo

| Producto | Qué hace bien | Qué adoptamos |
|---|---|---|
| **Adobe Acrobat Pro** | Edición in-place con reflow; encabezados/pies con presets + rangos + pares/impares; numeración Bates; sellos dinámicos con variables; panel de capas OCG; Preflight; Actions (lotes) | Sistema de encabezado/pie/marca de agua como **reglas con objetivo de páginas y presets**; sellos dinámicos con variables; panel de capas; verificación tipo preflight ligera |
| **Foxit PDF Editor** | Herramienta "máquina de escribir" (clic y teclear); galería de sellos organizada; UX de cinta clara | Modo clic-para-escribir; galería de sellos/plantillas con categorías |
| **PDF-XChange Editor** | Precisión numérica de colocación (X/Y/W/H editables); rendimiento sobresaliente con PDFs enormes; loupe/pan | Panel de propiedades con coordenadas numéricas en pt/mm; arquitectura de render por demanda con caché agresivo |
| **Sejda** | Simplicidad: clic en cualquier parte → texto; detección de fuente aproximada al editar líneas existentes; UX de rangos simple | Edición de texto existente por línea con "reemplazo en caja"; selector de rangos simple |
| **PDFescape** | Técnica whiteout (cubrir + reescribir) honesta y robusta | Whiteout como herramienta explícita y como fallback de edición sobre escaneos |
| **Smallpdf / iLovePDF** | Wizards directos, fricción cero | Defaults sensatos; insertar con un clic y ajustar después |
| **PDF24** | Toolbox offline gratuito, sellos por lote | Funcionamiento 100 % offline (ya es ADN de PDFlex); aplicar plantilla a N documentos en lote |

**Síntesis:** ninguno de los productos web (Sejda/Smallpdf/iLovePDF) ofrece reglas masivas por página con precisión de escritorio, y los de escritorio (Acrobat/Foxit/XChange) no ofrecen plantillas + lote con la sencillez de PDFlex. El nicho de PDFlex Studio: **precisión de escritorio + aplicación masiva + plantillas de la organización**.

## 5. Decisiones de arquitectura

### 5.1 Integración con la suite (decisión)

**PDFlex Studio se construye como herramienta de la suite**, registrada en el catálogo `TOOLS` de `shell/launcher.py`, pero **no** usa `PipelineWindow` (el scaffold de pasos 01→02→03 no aplica a un editor de documento): tiene su propia `EditorWindow` centrada en canvas. Reutiliza íntegramente: `ui/styles.py` (tokens), `ui/common/icons.py`, `ui/common/dialogs.py`, `ui/common/file_dialogs.py`, `ui/common/base_worker.py`, `ui/common/save_utils.py`, `ui/common/animations.py`, `core/crash_handler.py`, `core/output_naming.py` / `core/output_paths.py`, y la integración `send_to_tool` (recibir PDFs desde otras herramientas y enviar el resultado a Compresor/Protector/etc.).

El motor (`core/editor/`) queda **100 % libre de Qt** (igual que los engines existentes), lo que permite empaquetarlo a futuro como producto standalone o CLI de lotes sin tocar la UI.

### 5.2 Enfoques evaluados para el lienzo de edición

| Enfoque | Pros | Contras | Veredicto |
|---|---|---|---|
| **A. Widgets superpuestos sobre `GenericPdfViewer`** (QLabel/QWidget hijos sobre el canvas actual) | Reusa el visor existente; rápido de prototipar | Sin rotación de elementos, z-order frágil, hit-testing manual, sin escena coordinada, colapsa con cientos de elementos | ❌ Rechazado |
| **B. `QGraphicsScene` / `QGraphicsView`** (escena vectorial de Qt) | Selección, transformaciones, z-order, rubber-band, hit-testing, LOD y coordenadas flotantes **nativos**; es el framework con el que se construyen editores en Qt; rendimiento probado con miles de ítems | Curva de aprendizaje; hay que disciplinar el mapeo de coordenadas | ✅ **Elegido** |
| **C. Motor de pintado propio sobre QWidget** (paintEvent + input manual) | Control absoluto | Reimplementar selección/transformación/z/snapping = meses de trabajo sin valor diferencial | ❌ Rechazado |

### 5.3 Vista de arquitectura (capas)

```
┌─────────────────────────── ui/studio (PyQt6) ───────────────────────────┐
│ EditorWindow                                                            │
│ ├─ Toolbar (insertar/zoom/undo/guardar/exportar)                        │
│ ├─ ThumbnailPanel (páginas)      ├─ CanvasView (QGraphicsView+reglas)   │
│ ├─ PropertiesPanel (contextual)  ├─ LayersPanel  ├─ ApplyPanel (masivo) │
│ └─ Dialogs (exportar, OCR, recorte, plantillas)                         │
└───────────────▲──────────────────────────────▲──────────────────────────┘
                │ señales Qt / comandos        │ pixmaps listos (señal)
┌───────────────┴───────────────┐  ┌───────────┴──────────────────────────┐
│ core/editor (sin Qt*)         │  │ RenderService (hilo dedicado fitz)   │
│ ├─ model (elementos/capas/    │  │ ├─ cola con prioridad (visible 1º)   │
│ │   reglas/targets/variables) │  │ ├─ PixmapCache LRU (presupuesto MB)  │
│ ├─ geometry (CoordinateMapper)│  │ └─ tiles para zoom alto              │
│ ├─ history (comandos undo)    │  └──────────────────────────────────────┘
│ ├─ text_engine / image_engine │
│ ├─ content_edit (existente)   │   Reutilizados de la suite:
│ ├─ ocr_bridge → core/ocr_*    │   ocr_engine, pdf_repair_engine,
│ ├─ templates  ├─ project      │   signature_engine, sig_processing,
│ ├─ export (exporter/verifier/ │   background_removal_engine,
│ │   backup)  └─ validation    │   folio_format, split_ranges,
└───────────────────────────────┘   pdf_analyzer, output_naming/paths
```

\* `core/editor/model` y `history` no importan Qt. El `RenderService` y el `QUndoStack` viven en la frontera (infraestructura), igual que `BaseWorker` hoy.

**Regla de hilos (crítica con PyMuPDF):** PyMuPDF no es thread-safe. Cada hilo que necesita `fitz` abre **su propia instancia** de `fitz.Document` sobre el mismo archivo: el hilo de render tiene la suya (solo lectura), el worker de exportación abre la suya al exportar, el hilo de UI **nunca** toca `fitz`. Es el mismo patrón ya validado en los engines de la suite vía `BaseWorker`.

## 6. Módulos del motor (los 12 solicitados)

| # | Módulo | Paquete | Responsabilidad |
|---|---|---|---|
| 1 | **Renderizado PDF** | `core/editor/render/` | Hilo dedicado con `fitz.Document` propio; cola priorizada (página visible → vecinas → miniaturas); caché LRU de pixmaps con presupuesto de memoria; render por tiles a zoom > 200 %; cancelación de trabajos obsoletos |
| 2 | **Edición visual** | `ui/studio/canvas/` | `QGraphicsScene` por documento; ítems por página y por elemento; manijas de transformación; rubber-band; guías inteligentes; snapping |
| 3 | **Coordenadas** | `core/editor/geometry.py` | `CoordinateMapper`: conversiones escena↔display-pt↔coords-de-inserción (derotación); anclas; normalización entre tamaños de página |
| 4 | **Capas** | `core/editor/model/layers.py` | Capas con nombre, z, visibilidad, bloqueo, opacidad; mapeo opcional a OCG en exportación |
| 5 | **Texto** | `core/editor/text_engine.py` | Medición y render de texto (estilos, interlineado, alineación); resolución de fuentes (catálogo embebido + sistema); inserción vía `insert_htmlbox`/`insert_textbox` |
| 6 | **Imágenes** | `core/editor/image_engine.py` | Normalización PNG/JPG/WebP→RGBA (Pillow); recorte; opacidad horneada en alfa; rotación libre vía XObject (`show_pdf_page`) |
| 7 | **OCR** | `core/editor/ocr_bridge.py` | Puente al `core/ocr_engine.py` existente; capa de texto invisible (PDF buscable); OCR de región para asistir edición de escaneos |
| 8 | **Plantillas** | `core/editor/templates/` | Esquema JSON versionado; galería con categorías; variables dinámicas; import/export `.flextpl` (zip con assets) |
| 9 | **Guardado/exportación** | `core/editor/export/` | `Exporter` (overlay vectorial / raster fallback), `Verifier` (reabre y valida), `BackupManager` (respaldo previo), escritura atómica |
| 10 | **Proyecto editable** | `core/editor/project/` | Formato `.flexproj` (zip: manifest + elements + assets); autosave con timer; recuperación post-crash |
| 11 | **Validación y reparación** | `core/editor/validation.py` | Al abrir: chequeo fitz, password, resumen del `pdf_analyzer` (rotaciones/tamaños), detección de firmas digitales existentes; reparación delegada a `pdf_repair_engine` |
| 12 | **Historial** | `core/editor/history/` | Patrón Command sobre `QUndoStack`; coalescencia de arrastres; macro-comandos para aplicación masiva; tope configurable (default 200 pasos) |

## 7. Mapeo de las 18 funciones obligatorias

| Función | Módulos | Viabilidad técnica |
|---|---|---|
| 1. Texto editable sobre PDF | 2, 5 | ✅ Directa |
| 2. Cuadros de texto movibles/redimensionables | 2 | ✅ Directa (QGraphicsItem) |
| 3. Fuente/tamaño/color/opacidad/alineación/rotación/interlineado/estilo | 5 | ✅ `insert_htmlbox` (PyMuPDF ≥1.24, ya requerido) cubre todo con CSS |
| 4. Imágenes PNG/JPG/WebP con transparencia | 6 | ✅ Pillow normaliza; alfa soportado por `insert_image` |
| 5. Mover/escalar/rotar/recortar/opacidad de imágenes | 2, 6 | ✅ Rotación libre vía XObject; recorte con Pillow al exportar |
| 6. Aplicar a página/varias/rangos/pares/impares/todas | 3, 9, §10.3 | ✅ `PageTarget` + parser extendido de `split_ranges` |
| 7. Encabezados/pies/marcas de agua/sellos/firmas/folios | 5–8, §10.3 | ✅ Reglas por página + `folio_format` + `watermark_engine` presets + `sig_processing` |
| 8. Capas editables | 4 | ✅ Capas de editor; OCG opcional al exportar |
| 9. Proyectos editables | 10 | ✅ `.flexproj` |
| 10. Exportar sin dañar el original | 9 | ✅ Siempre archivo nuevo + verificación + respaldo |
| 11. Máxima calidad visual | 1, 9 | ✅ Overlay vectorial por defecto |
| 12. Escaneados/pesados/rotados/tamaños mixtos/muchas páginas | 1, 3, §13 | ✅ Diseñado para ello (ver rendimiento y rotación) |
| 13. OCR para buscable/parcialmente editable | 7 | ✅ Tesseract ya embebido en la suite |
| 14. Editar texto existente cuando el PDF lo permita | `content_edit` | ⚠️ **Parcial por diseño**: reemplazo en caja (redacción + reinserción), sin reflow; fuente aproximada si la original no es extraíble |
| 15. Detectar/mover/reemplazar/ocultar imágenes existentes | `content_edit` | ⚠️ **Posible con caveats**: `get_image_info(xrefs)` + `delete_image`/`replace_image`; advertir si el xref es compartido entre páginas |
| 16. Undo/redo/copiar/pegar/duplicar/bloquear/ocultar/eliminar | 12, 2 | ✅ Directa |
| 17. Plantillas reutilizables | 8 | ✅ Directa |
| 18. Validación/reparación/respaldo automático | 11, 9 | ✅ Reutiliza `pdf_repair_engine` |

## 8. Librerías recomendadas

| Librería | Versión | Rol | Justificación |
|---|---|---|---|
| **PyMuPDF (fitz)** | ≥ 1.24 *(ya en requirements)* | Render, inserción, OCR, OCG, reparación | Ya es el corazón de la suite; `insert_htmlbox`, `derotation_matrix`, `get_textpage_ocr`, `add_ocg`, `subset_fonts` cubren todas las necesidades |
| **PyQt6** | ≥ 6.6 *(ya en requirements)* | UI, QGraphicsScene/View, QUndoStack | La suite ya es PyQt6 (el enunciado permitía PySide6 **o** PyQt6; cambiar de binding sería un costo sin beneficio) |
| **Pillow** | ≥ 10 *(ya)* | Normalización de imágenes, recorte, opacidad→alfa, WebP | Ya presente |
| **numpy** | ≥ 1.24 *(ya)* | Muestreo de color de fondo (whiteout inteligente), métricas OCR | Ya presente |
| **fontTools** | ≥ 4.50 *(nueva, pura-Python)* | Inspección de TTF/OTF del sistema: nombre real, flag `fsType` (permiso de embebido), subsetting auxiliar | Necesaria para ofrecer fuentes del sistema con embebido legal y fiable |
| Fuentes embebidas (assets) | — | Inter, Noto Sans/Serif, DejaVu Sans/Serif/Mono (licencias OFL) | Catálogo curado que garantiza WYSIWYG y embebido legal en cualquier máquina |

**Descartadas y por qué:** `pikepdf` (la reparación/saneo ya la resuelve `pdf_repair_engine` con fitz; añadir un segundo motor PDF duplica superficie de bugs y peso del instalador); `pdfplumber/reportlab` (solapan con fitz); `ocrmypdf` (arrastra Ghostscript; el OCR de la suite ya funciona con Tesseract embebido); `QML/Qt Quick` (la suite es Widgets).

## 9. Estructura de carpetas

```
core/editor/
├── __init__.py
├── model/
│   ├── elements.py        # ElementBase, TextElement, ImageElement, ShapeElement,
│   │                      #   StampElement, SignatureElement, WatermarkElement, FolioElement
│   ├── layers.py          # Layer, LayerStack
│   ├── placement.py       # Frame, Anchor (9 puntos), PlacementMode (absoluto|ancla|normalizado)
│   ├── page_target.py     # PageTarget (todas|actual|rangos|pares|impares|lista) + parser
│   ├── rules.py           # PageRule (elemento + target) → instancias fantasma
│   ├── document_state.py  # EditorDocument: páginas, elementos, reglas, capas, dirty flags
│   └── variables.py       # {pagina},{total},{fecha},{hora},{doc},{contador:…} (extiende folio_format)
├── geometry.py            # CoordinateMapper (escena↔display↔inserción, derotación, anclas)
├── render/
│   ├── render_service.py  # hilo dedicado + cola priorizada + cancelación
│   ├── pixmap_cache.py    # LRU por (página, bucket_zoom[, tile]) con presupuesto en MB
│   └── tiles.py           # subdivisión para zoom > 200 %
├── text_engine.py         # estilos→HTML/CSS para insert_htmlbox; fallback insert_textbox
├── image_engine.py        # normalización RGBA, recorte, opacidad, rotación libre (XObject)
├── fonts.py               # FontCatalog: embebidas + sistema (fontTools: fsType, ruta TTF)
├── content_edit.py        # texto existente (redact+reinsert) e imágenes existentes (xref ops)
├── ocr_bridge.py          # capa invisible buscable + OCR de región (usa core/ocr_engine)
├── templates/
│   ├── schema.py          # esquema JSON versionado + migraciones
│   └── store.py           # galería en %APPDATA%/PDFlex/templates, import/export .flextpl
├── project/
│   ├── format.py          # .flexproj (zip): manifest, elements, assets dedup por hash
│   ├── autosave.py        # timer + escritura atómica en %APPDATA%/PDFlex/autosave
│   └── recovery.py        # detección de autosaves huérfanos al iniciar
├── export/
│   ├── exporter.py        # overlay vectorial; raster fallback por página (patrón membrete)
│   ├── verifier.py        # reabre el PDF exportado, valida páginas y render de muestra
│   └── backup.py          # respaldo del destino si existe + del proyecto antes de guardar
├── history/
│   ├── commands.py        # Add/Remove/Move/Resize/Rotate/Style/Layer/MassApply (macro)
│   └── stack.py           # fachada sobre QUndoStack, coalescencia, tope de pasos
└── validation.py          # chequeos al abrir (password, daño, firmas digitales, resumen analyzer)

ui/studio/
├── __init__.py
├── window.py              # EditorWindow (layout, docks, menús, atajos)
├── toolbar.py             # herramientas de inserción, zoom, undo, guardar, exportar
├── canvas/
│   ├── scene.py           # EditorScene: páginas en columna, fondo, guías
│   ├── view.py            # EditorView: zoom (rueda+Ctrl), pan (espacio), DPR-aware
│   ├── page_item.py       # PageItem: pixmap por bucket de zoom, placeholder mientras carga
│   ├── element_items.py   # TextItem (edición inline), ImageItem, ShapeItem, GhostItem (reglas)
│   ├── handles.py         # manijas de resize/rotación, cursores, restricciones (Shift=proporción)
│   ├── guides.py          # guías inteligentes: centro/márgenes/bordes de otros elementos
│   └── rulers.py          # reglas pt/mm acopladas al viewport + indicador de cursor
├── panels/
│   ├── properties.py      # X/Y/W/H/rotación/opacidad numéricos (pt/mm) + estilo contextual
│   ├── layers_panel.py    # árbol de capas: visibilidad, candado, opacidad, reordenar
│   ├── pages_panel.py     # miniaturas virtualizadas (patrón organizador/thumb_cache)
│   ├── apply_panel.py     # objetivo de páginas (todas/rango/pares/impares) + vista previa de alcance
│   └── templates_panel.py # galería de plantillas con categorías y búsqueda
└── dialogs/
    ├── export_dialog.py   # destino (output_paths), modo vectorial/raster, OCG, OCR buscable
    ├── crop_dialog.py     # recorte de imagen con preview
    └── ocr_region_dialog.py

tests/editor/
├── fixtures/              # PDFs: rotado 90/180/270, tamaños mixtos, escaneado, cifrado, firmado
├── test_geometry.py       # round-trip de coordenadas en las 4 rotaciones (la prueba reina)
├── test_model.py, test_history.py, test_page_target.py, test_variables.py
├── test_text_engine.py, test_image_engine.py, test_fonts.py
├── test_exporter.py       # exporta y re-extrae posición real con get_text("dict")/get_image_info
├── test_project_roundtrip.py, test_templates.py, test_content_edit.py
└── test_studio_window.py  # smoke UI (patrón de los tests de ventana existentes)
```

## 10. Modelo de datos y clases principales

### 10.1 Elementos

```python
class ElementKind(Enum):
    TEXT, IMAGE, SHAPE, STAMP, SIGNATURE, WATERMARK, FOLIO = auto(), ...

@dataclass
class Frame:
    x: float; y: float          # pt, espacio display de la página (origen sup-izq)
    w: float; h: float          # pt
    rotation_deg: float = 0.0   # libre, alrededor del centro del frame

@dataclass
class Placement:
    mode: Literal["absolute", "anchor", "normalized"] = "absolute"
    anchor: Anchor = Anchor.TOP_LEFT      # 9 puntos (patrón watermark_engine.POSITIONS)
    dx_pt: float = 0.0; dy_pt: float = 0.0
    # normalized: frame relativo a página de referencia (patrón foleador x_norm/y_norm)
    ref_page_w_pt: float = 595.0; ref_page_h_pt: float = 842.0

@dataclass
class ElementBase:
    id: str                      # uuid4
    kind: ElementKind
    frame: Frame
    placement: Placement
    opacity: float = 1.0
    locked: bool = False
    hidden: bool = False
    layer_id: str = "default"
    z: int = 0

@dataclass
class TextElement(ElementBase):
    runs: list[TextRun]          # tramos con overrides puntuales (negrita en una palabra,
                                 #   otro color, etc.); heredan del estilo base del elemento
    align: Literal["left","center","right","justify"] = "left"
    line_height: float = 1.2
    font_family: str = "Inter"; font_size: float = 12.0
    color: RGBColor = (0,0,0); bold=False; italic=False; underline=False
    box_fill: RGBColor | None = None; box_fill_opacity: float = 1.0
    variables_enabled: bool = False   # habilita {pagina},{fecha},{n:05}…

@dataclass
class ImageElement(ElementBase):
    asset_id: str                # hash SHA-256 del binario en el almacén de assets
    crop: tuple[float,float,float,float] | None = None   # fracciones 0-1 (l,t,r,b)
    keep_aspect: bool = True; flip_h: bool = False; flip_v: bool = False
```

`StampElement`, `SignatureElement`, `WatermarkElement` y `FolioElement` son especializaciones delgadas (composición de texto/imagen + defaults de su categoría + presets — los de marca de agua se importan de `core/watermark_engine.PRESETS`; las firmas pasan por `background_removal_engine` para fondo transparente, como ya hace el Firmador).

### 10.2 Documento, capas y objetivo de páginas

```python
@dataclass
class Layer:
    id: str; name: str; z: int
    visible: bool = True; locked: bool = False; opacity: float = 1.0
    export_as_ocg: bool = False

@dataclass
class PageTarget:
    mode: Literal["all","current","pages","even","odd"] = "all"
    spec: str = ""               # "1-5,9,12-" — parser extiende core/split_ranges
    def resolve(self, total: int) -> list[int]: ...

@dataclass
class PageRule:
    """Encabezado/pie/marca de agua/folio definidos UNA vez, aplicados a un target.
    En el canvas se ven como instancias fantasma editables desde cualquier página."""
    id: str
    element: ElementBase
    target: PageTarget

class EditorDocument:
    """Estado completo del proyecto: fuente PDF + elementos + reglas + capas."""
    source_path: Path; source_sha256: str
    page_geometries: list[PageGeometry]    # w,h,rotation por página (del pdf_analyzer)
    elements_by_page: dict[int, list[ElementBase]]
    rules: list[PageRule]
    layers: LayerStack
    def resolved_elements(self, page: int) -> list[ResolvedElement]:
        """Elementos concretos + instancias de reglas, con variables sustituidas
        y placement resuelto al tamaño real de ESA página."""
```

**Manejo de capas (consolidado):** las capas son un concepto del **editor** (no existen en el PDF fuente). Todo elemento pertenece a exactamente una capa; el orden de pintado es `(z de capa, z del elemento)`. Siempre existe una capa "General" no eliminable. Operaciones del panel (crear, renombrar, reordenar, fusionar, eliminar-con-reubicación) son comandos undoables. `visible=False` excluye la capa del render del canvas **y de la exportación** (con aviso en el diálogo de exportar: "2 capas ocultas no se incluirán"); `locked=True` bloquea selección/edición de sus elementos; `opacity` de capa se multiplica con la del elemento. Al exportar, las capas marcadas `export_as_ocg=True` se crean con `doc.add_ocg(nombre)` y sus elementos se insertan con `oc=xref` — capas PDF reales conmutables en Acrobat/visores compatibles; el resto se aplana (default universal, §21-13).

### 10.3 Concepto clave: elementos concretos vs. reglas

Las herramientas profesionales (Acrobat headers/footers, watermarks) no copian N objetos: definen **una regla** con un objetivo de páginas. PDFlex Studio adopta esto:

- **Elemento concreto**: vive en una página específica (arrastrado a la página 7, queda en la 7).
- **Regla de página** (`PageRule`): se define una vez (p. ej. folio `{n:05}` en esquina superior derecha, páginas impares) y el canvas muestra **instancias fantasma** en cada página del target. Editar cualquier instancia edita la regla; una instancia puede "desprenderse" (override) y volverse elemento concreto de esa página.
- "Aplicar a varias páginas" desde el panel masivo convierte el elemento seleccionado en regla (macro-comando undoable de un solo paso).

Esto da aplicación masiva sin explosión de memoria (1 regla ≠ 1000 objetos) y edición centralizada.

### 10.4 Clases de infraestructura

```python
class CoordinateMapper:      # core/editor/geometry.py — pura, sin Qt
    def scene_to_page(self, pt: Point, page: int) -> Point      # display pt
    def page_to_scene(self, pt: Point, page: int) -> Point
    def display_rect_to_insertion(self, r: Rect, page_geo: PageGeometry) -> Rect
        # r * derotation_matrix  → coords que esperan insert_*() en páginas /Rotate≠0
    def text_rotate_for_page(self, element_deg: float, page_geo) -> tuple[int, Matrix|None]
        # descompone en rotate= (múltiplos de 90 que compensa la página) + morph (ángulo libre)

class RenderService(QObject):        # frontera core/UI
    request = ...                    # (page, scale_bucket, tile, priority)
    pixmap_ready = pyqtSignal(int, float, object, QPixmap)
    # Hilo propio con SU fitz.Document. Descarta trabajos obsoletos (generación de zoom).

class Exporter:                      # core/editor/export/exporter.py
    def export(self, doc: EditorDocument, out: Path, opts: ExportOptions,
               progress, should_cancel) -> ExportResult
    # por página: resolved_elements → texto (htmlbox/textbox) e imágenes (insert_image
    # o XObject rotado) en coords de inserción; firma de progreso idéntica a engines actuales

class ProjectStore:                  # .flexproj
    def save(self, doc: EditorDocument, path: Path) -> None     # atómico: tmp + os.replace
    def load(self, path: Path) -> EditorDocument                # con migración de esquema
    # zip: manifest.json (schema_version, app_version), document.json (ref+sha256, modo
    # vínculo|embebido), elements.json, layers.json, rules.json, assets/<sha256>.png|jpg

class HistoryStack:                  # fachada sobre QUndoStack
    # comandos con merge (arrastre = 1 paso), macros (masivo = 1 paso), tope 200
```

## 11. Flujo de trabajo (usuario y datos)

**Usuario:** Abrir PDF (o `.flexproj`, o recibido vía `send_to_tool`) → validación + resumen (§15) → el canvas muestra página 1 + miniaturas → inserta elementos (clic en herramienta → clic/arrastre en página) → ajusta con mouse o panel de propiedades → opcionalmente convierte en regla masiva (panel Aplicar) → guarda proyecto (`Ctrl+S`, autosave de fondo cada 90 s) → exporta (`Ctrl+E`): diálogo con destino (convenciones `output_paths`), modo vectorial/raster, OCG sí/no, OCR buscable sí/no → barra de progreso cancelable → verificación → visor de resultado (componente existente) con "Abrir en explorador" y "Enviar a otra herramienta".

**Datos:** input del mouse → `EditorView` → ítem QGraphics → comando en `HistoryStack` → muta `EditorDocument` → señal de cambio → ítems re-sincronizan + autosave marca dirty. Exportación: `EditorDocument` → `Exporter` (worker `BaseWorker`, su propio fitz) → `Verifier` → `ExportResult` (mismo contrato `output_path/success/error` que consume `GenericPdfViewer`).

## 12. Manejo de coordenadas (diseño detallado)

Espacios definidos (un solo documento de verdad, `geometry.py`):

1. **Espacio display de página** (unidad canónica del modelo): puntos PDF (1/72"), origen arriba-izquierda, eje Y hacia abajo, **después** de aplicar /Rotate — es exactamente lo que `fitz.Page.rect` y `get_text()` reportan, y lo que el usuario ve.
2. **Espacio de escena Qt:** 1 unidad de escena = 1 pt display. Las páginas se apilan en columna con separación fija; `scene_to_page` solo resta el offset de la página. El zoom es transformación de la **vista**, nunca de la escena → las coordenadas del modelo no dependen del zoom.
3. **Espacio de píxeles de render:** `escala = zoom × devicePixelRatio`; el pixmap se genera con `fitz.Matrix(escala, escala)` y se marca con `setDevicePixelRatio` para nitidez en pantallas HiDPI/escalado fraccional de Windows.
4. **Espacio de inserción PyMuPDF:** *(verdad empírica FINAL — sondas 1-3 del 2026-06-09 sobre PyMuPDF 1.27.2.3, demostrada por píxeles renderizados en la prueba reina de Fase 0)* `insert_textbox`, `Shape.draw_*` e `insert_image` interpretan TODOS el rect en el sistema **no rotado**: conversión única `rect × derotation_matrix` encapsulada en `geometry.insertion_rect()`. Texto e imagen además orientan su contenido según la página sin rotar → las primitivas aplican `rotate=page.rotation` para que queden derechos en pantalla. **Trampa documentada:** las APIs de extracción (`get_text`, `get_drawings`, `get_image_info`) reportan también en espacio sin rotar en 1.27 — parecen "eco" del input y NO sirven para verificar posición display; toda verificación de posición se hace **renderizando y midiendo píxeles** (helper numpy del gate). Si una versión futura cambia el contrato, la prueba reina falla y el fix vive en `insertion_rect()`, en ningún otro lado. `show_pdf_page` se verifica por separado en la Task 5 (membrete documentó que ignora `/Rotate`).

**Anclas y tamaños mixtos:** un elemento con `placement.mode="anchor"` guarda (ancla, dx, dy) — p. ej. `BOTTOM_RIGHT + (-20, -15)` pt; al resolverse contra cada página del target se recalcula contra el `page.rect` real. Con `mode="normalized"` se usa el patrón ya probado del foleador (centro y tamaño como fracción de página de referencia, escalando el fontsize por el lado mayor). Defaults: elementos concretos = `absolute`; reglas masivas = `anchor` (encabezados/pies/folios) o `normalized` (marcas de agua centradas).

**Entrada numérica:** el panel de propiedades muestra X/Y/W/H en pt o mm (selector de unidad, conversión 1 mm = 72/25.4 pt), con origen seleccionable (esquina sup-izq de página o margen). La barra de estado muestra coordenadas vivas del cursor en ambas unidades.

## 13. Manejo de páginas rotadas

- El render con `get_pixmap` ya entrega la página como se ve (rotación aplicada): el canvas no necesita lógica especial para mostrar.
- Toda inserción pasa por `geometry.insertion_rect` (chokepoint: derotación única — ver §12.4) y las primitivas de texto/imagen aplican `rotate=page.rotation` para enderezar el contenido en pantalla.
- El ángulo libre del usuario va en `morph=(centro, Matrix(ángulo))` / XObject, con semántica (signo, pivote) fijada empíricamente por los tests por píxeles de la Task 5.
- **Fallback raster por página** (herencia del membrete), con disparadores definidos: (a) **automático**, cuando la inserción vectorial sobre una página lanza excepción o el `Verifier` detecta que el contenido no quedó donde debía (round-trip de posición falla); (b) **manual**, vía opción "Aplanar páginas" del diálogo de exportación. En ambos casos se rasteriza **solo la página afectada** a DPI configurable (150 por defecto, 300 para impresión) y la decisión queda registrada por página en el reporte de exportación.
- **Tests de regresión obligatorios** (la suite ya tiene el patrón en los tests de rotación del membrete): fixtures /Rotate 0/90/180/270 × {texto, imagen, regla anclada}; tras exportar se reabre el PDF y se verifica con `get_text("dict")`/`get_image_info` que el contenido quedó a ≤0.5 pt de la posición esperada. **Esta prueba se escribe en la Fase 0, antes que el editor.**

## 14. Manejo de OCR

Reutiliza el motor híbrido existente (`core/ocr_engine.py`, Tesseract embebido en `assets/tessdata`, spa+eng, recuperación de rotación):

1. **PDF buscable (sandwich):** opción en exportación. Por página escaneada: `page.get_textpage_ocr(...)` → palabras con bbox → inserción de texto **invisible** (`render_mode=3`) alineado a cada bbox en el PDF de salida. El aspecto no cambia; el PDF se vuelve seleccionable/buscable. Progreso por página, cancelable (el OCR es lento: ~1-3 s/página — siempre en worker, jamás bloquea la UI; el freeze de OCR sin timeout ya está identificado como riesgo de la suite y aquí nace resuelto).
2. **Asistencia de edición sobre escaneos:** herramienta "Editar texto de escaneo": el usuario traza un rectángulo → OCR de región → se crea (a) parche de cobertura con color muestreado del fondo (mediana de bordes vía numpy, no blanco fijo) y (b) `TextElement` prellenado con el texto reconocido, fuente aproximada por altura de bbox. Es la técnica whiteout de PDFescape, automatizada.
3. **Detección automática:** al abrir, el resumen del analyzer marca páginas sin texto nativo ("escaneado") y la UI ofrece el flujo OCR contextualmente.

## 15. Validación, reparación y respaldo

**Al abrir:** ¿existe/legible? → ¿cifrado? (diálogo de contraseña; respeta permisos) → ¿`doc.is_repaired`? (avisar "PDF con daños, reparado al vuelo"; ofrecer pasarlo por `pdf_repair_engine` para normalizar) → ¿firmas digitales presentes? (detección vía campos /Sig; **advertencia clara**: "Este PDF tiene firmas digitales; cualquier edición las invalidará") → resumen `pdf_analyzer`: nº páginas, tamaños distintos, rotaciones, páginas escaneadas.

**Antes de exportar:** validar elementos (fuentes resolubles, assets presentes, targets dentro de rango); si el archivo destino existe → respaldo `nombre.bak.pdf` en subcarpeta `respaldo/` antes de reemplazar; escritura a archivo temporal + `os.replace` (atómico).

**Después de exportar:** `Verifier` reabre el resultado: nº de páginas correcto, render de muestra (primera/última/una del medio) sin excepción, tamaño > 0. Si falla, el original y el respaldo quedan intactos y se reporta el error con detalle (patrón `PdfRepairEngine` de verificación post-escritura).

**Proyecto:** autosave cada 90 s a `%APPDATA%/PDFlex/autosave/<hash>.flexproj` (atómico); al iniciar, `recovery.py` detecta autosaves huérfanos (crash) y ofrece restaurar — se integra con `core/crash_handler.py` existente.

## 16. Sistema de plantillas

- **Esquema:** JSON versionado (`schema.py` con migraciones) = lista de elementos/reglas serializados + assets referenciados por hash + metadatos (nombre, categoría, autor, fecha, miniatura PNG).
- **Categorías:** Membretes, Sellos, Firmas, Marcas de agua, Folios, Encabezados/Pies, Composiciones (varias piezas juntas — p. ej. "Juego oficio OCMX": logo + folio + pie legal).
- **Variables dinámicas** (`variables.py`, extiende la sintaxis ya probada de `folio_format`): `{n}`, `{n:05}`, `{total}`, `{doc}` (existentes) + `{pagina}`, `{fecha}`, `{fecha:%d/%m/%Y}`, `{hora}`, `{usuario}`. Se resuelven al exportar; en canvas se muestran con valores de ejemplo y borde punteado "dinámico".
- **Galería:** panel con búsqueda y vista previa; almacén en `%APPDATA%/PDFlex/templates/`; import/export `.flextpl` (zip) para compartir entre equipos de OCMX. `core/membrete_library.py` sirve de referencia de patrón (biblioteca de assets reutilizables ya existente en la suite).
- **Aplicación en lote (diferenciador):** "Aplicar plantilla a N documentos" — selector de archivos múltiple (componente `documents_step` existente) + plantilla + target → worker masivo. Es el puente natural con el ADN batch de PDFlex y queda para Fase 3.

## 17. Sistema de guardado y proyecto editable

**`.flexproj` = zip** con: `manifest.json` (versión de esquema y de app), `document.json` (ruta del PDF fuente + SHA-256 + modo `vínculo` o `embebido`), `elements.json` / `rules.json` / `layers.json`, `assets/<sha256>.<ext>` (imágenes deduplicadas), `thumb.png` (vista previa del proyecto).

- **Vínculo vs. embebido:** por defecto el proyecto **referencia** el PDF (proyectos ligeros); el usuario puede marcar "Empaquetar PDF en el proyecto" (portabilidad total). Al abrir un proyecto vinculado se verifica el SHA-256: si el PDF cambió o no está, diálogo de relocalización con advertencia.
- El historial de undo **no** se persiste (estándar de la industria; evita proyectos gigantes y esquemas frágiles).
- Guardado siempre atómico; "Guardar como" duplica assets; los proyectos recientes se listan en la pantalla inicial del Studio.

## 18. Interfaz de usuario

Layout `EditorWindow` (QMainWindow con docks, tokens de `ui/styles.py`, iconografía SVG y animaciones del rediseño premium):

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Toolbar: [Seleccionar][Texto][Imagen][Sello][Firma][Marca agua][Folio]   │
│          [Formas][Whiteout] | ↶ ↷ | zoom [- 100% +][Ajustar] | 💾 Exportar│
├─────────┬──────────────────────────────────────────────┬────────────────┤
│ Páginas │  Regla horizontal (pt/mm)                    │ Propiedades    │
│ (minia- │ ┌──────────────────────────────────────────┐ │  X 120.0 pt    │
│  turas  │R│                                          │ │  Y  85.5 pt    │
│  virtua-│e│         CANVAS (QGraphicsView)           │ │  W/H, ⟳ 0.0°   │
│  lizadas│g│   página actual + vecinas, guías         │ │  Opacidad 100% │
│  con nº │l│   inteligentes, manijas de selección     │ │  [estilo según │
│  y badge│a│                                          │ │   selección]   │
│  de     │ │                                          │ ├────────────────┤
│  reglas)│ └──────────────────────────────────────────┘ │ Capas          │
│         │  Status: pág 3/120 · X:142.3 Y:88.1 · A4 90° │ Aplicar a pág. │
└─────────┴──────────────────────────────────────────────┴────────────────┘
```

- **Visor central:** scroll continuo por páginas; zoom 25–800 % con Ctrl+rueda anclado al cursor; ajuste a ancho/página; pan con barra espaciadora; doble clic en texto = edición inline.
- **Miniaturas:** virtualizadas (solo se renderizan las visibles — patrón `thumb_cache` del organizador), badge cuando la página recibe reglas.
- **Panel de propiedades:** contextual (texto → tipografía completa; imagen → recorte/proporción/volteo; nada seleccionado → propiedades de página/documento). Spinboxes con unidades pt/mm, pasos finos con Shift.
- **Guías inteligentes:** snap (umbral 6 px de pantalla, se desactiva con Alt) a centros y márgenes de página y a bordes/centros de otros elementos; líneas de guía arrastrables desde las reglas; cuadrícula opcional.
- **Atajos:** estándar (Ctrl+Z/Y/C/V/D/S/E, Supr, flechas = 1 pt, Shift+flechas = 10 pt, Ctrl+G agrupar a capa); compatibles con el Command Palette (Ctrl+K) del rediseño premium.
- **Accesibilidad/idioma:** todo en español, consistente con la suite.

## 19. Edición de contenido existente (funciones 14-15, límites honestos)

**Texto existente:** `page.get_text("dict")` da spans con bbox, fuente, tamaño y color. Doble clic con la herramienta "Editar existente" sobre una línea → se crea una operación de **reemplazo en caja**: redacción del span original (`add_redact_annot` + `apply_redactions` con preservación de imágenes) + `TextElement` prellenado con el texto, fuente mapeada a la más cercana del catálogo (las fuentes embebidas del PDF rara vez son re-embebibles legal/técnicamente) y color/tamaño originales. Sin reflow: el texto editado vive en su caja (nivel Sejda, no nivel Acrobat — se comunica así en la UI). La redacción se aplica **solo al exportar**; en el canvas es no destructiva (parche + texto encima), por lo que sigue siendo undoable.

**Imágenes existentes:** herramienta "Contenido existente" lista `page.get_image_info(xrefs=True)` con resaltado de bbox al pasar el mouse. Acciones: **ocultar** (parche de cobertura no destructivo o `delete_image(xref)` al exportar), **reemplazar** (`replace_image(xref, …)`), **mover** (delete + reinsertar en nuevo rect). Caveat detectado y manejado: si el xref aparece en varias páginas (logos repetidos comparten stream), se advierte "esta imagen se usa en N páginas" y se ofrece elegir alcance (solo esta página → se duplica el stream primero; todas → operación directa).

## 20. Rendimiento y robustez (documentos grandes y escaneados)

| Riesgo | Estrategia |
|---|---|
| PDFs de 1000+ páginas | Ítems de página perezosos: solo se materializan pixmaps de viewport ± 2 páginas; el resto son rectángulos placeholder con tamaño conocido (geometrías precargadas del analyzer, baratas) |
| Escaneos pesados (50+ MB/página) | Presupuesto de caché LRU configurable (default 384 MB); render por tiles a zoom alto; tope de píxeles por render (patrón `_CANVAS_MAX_PX` del visor actual) |
| UI congelada (riesgo histórico de la suite) | `fitz` jamás en el hilo de UI; cola con prioridad y **cancelación por generación** (al cambiar de zoom, los renders en vuelo de la generación anterior se descartan); miniaturas a prioridad baja |
| Memoria de undo | Comandos guardan deltas (no snapshots); imágenes referenciadas por hash al almacén, nunca copiadas en comandos |
| Exportación de documentos enormes | Streaming página a página con `progress(current,total,msg)` y `should_cancel` (contrato exacto de los engines actuales); `doc.save(garbage=3, deflate=True)` + `subset_fonts()` |
| Zoom fraccional de Windows (125 %/150 %) | Render a píxeles físicos (`zoom × DPR`) + `setDevicePixelRatio`; ya hay precedente de manejo DPI en la suite |

## 21. Problemas técnicos previsibles y soluciones

| # | Problema | Solución de diseño |
|---|---|---|
| 1 | El contrato de coordenadas de `insert_*` ante /Rotate cambió entre versiones de PyMuPDF (bug ya sufrido en membrete; en 1.27 operan en espacio display) | Chokepoint único `display_rect_to_insertion` + prueba reina de 4 rotaciones que detecta cualquier cambio futuro de contrato |
| 2 | PyMuPDF no es thread-safe | Un `fitz.Document` por hilo; UI nunca toca fitz; render en hilo dedicado con cola |
| 3 | WYSIWYG: Qt y MuPDF no rasterizan texto idéntico (kerning/shaping) | Catálogo curado de fuentes embebidas (mismo TTF en pantalla y en PDF); tolerancia documentada ±1 px; botón "Vista fiel" que re-renderiza la página vía MuPDF con elementos horneados antes de exportar |
| 4 | Fuentes del sistema sin permiso de embebido (`fsType` restrictivo) | `fonts.py` inspecciona con fontTools; las restringidas se muestran con candado y no son seleccionables para exportar |
| 5 | Opacidad global de imagen no existe en `insert_image` | `image_engine` hornea opacidad en el canal alfa (Pillow) antes de insertar |
| 6 | Rotación libre de imágenes no soportada por `insert_image` (solo múltiplos de 90) | Envolver la imagen como XObject (doc de 1 página en memoria) + `show_pdf_page(rotate=ángulo)` — vectorial, sin resampleo |
| 7 | Texto con ángulo libre | `insert_htmlbox`/`insert_text` con `morph=(centro, Matrix(ángulo))` |
| 8 | Imagen existente con xref compartido entre páginas | Detección previa + diálogo de alcance + duplicación de stream cuando aplica (§19) |
| 9 | PDFs firmados digitalmente: editar invalida firmas | Detección al abrir + advertencia bloqueante con opción consciente de continuar (§15) |
| 10 | PDFs cifrados / con permisos | Flujo de contraseña al abrir; respeto de flags de permiso; mensajes claros |
| 11 | Autosave corrupto por crash a mitad de escritura | Escritura atómica (tmp + `os.replace`); el recovery valida el zip antes de ofrecerlo |
| 12 | WebP con alfa / modos exóticos (P, CMYK) | Pillow normaliza todo a RGBA/RGB en el ingreso al almacén de assets |
| 13 | OCG no visible en visores viejos | OCG es opt-in al exportar; default = contenido plano universal |
| 14 | `insert_htmlbox` requiere PyMuPDF ≥ 1.24 | Ya es el mínimo de `requirements.txt`; se fija además chequeo en arranque del Studio |
| 15 | Snapping lento con cientos de elementos por página | Índice espacial simple por página (listas ordenadas de bordes X/Y) recalculado on-change, no on-move |
| 16 | Proyecto vinculado cuyo PDF fuente cambió | SHA-256 en manifest + diálogo de relocalización/reconciliación (§17) |
| 17 | Empaquetado PyInstaller (fuentes nuevas + tessdata) | Mismo mecanismo de assets ya probado (`core/assets.py`, tessdata embebido); las fuentes OFL pesan ~6 MB |

## 22. Estrategia de pruebas

- **Núcleo sin UI primero:** geometría, modelo, targets, variables, historial, proyecto round-trip, exportador — pytest puro, sin Qt (rápidos, deterministas).
- **La prueba reina (Fase 0):** exportar elemento en página /Rotate 0/90/180/270 → reabrir → posición real extraída ≤ 0.5 pt de la esperada. Sin esto en verde no se construye UI.
- **Exportador como caja negra:** siempre se valida releyendo el PDF generado (`get_text("dict")`, `get_image_info`), nunca confiando en que "no lanzó excepción".
- **UI smoke** (patrón existente `test_*_window.py`): crear ventana, cargar fixture, insertar elemento, undo/redo, exportar a tmp.
- **Fixtures dedicados:** rotados, tamaños mixtos (carta+oficio+A5 en un doc), escaneado real, cifrado, con firma digital, malformado-reparable.
- TDD por módulo (disciplina ya usada en la suite: tests rojos del membrete antes del fix).

## 23. Plan de desarrollo por etapas

| Fase | Contenido | Duración | Gate de salida |
|---|---|---|---|
| **0 — Spike de riesgo** | `geometry.py` + `CoordinateMapper` + fixtures rotación + prueba reina de export round-trip; prototipo mínimo QGraphicsScene con 1 página y 1 rectángulo arrastrable; `RenderService` con cola y caché | 1 sem | Posición exacta ≤0.5 pt en las 4 rotaciones; canvas fluido con PDF de 500 págs |
| **1 — MVP** | Modelo + historial; texto e imagen completos (mover/resize/rotar/opacidad/estilos); panel propiedades; miniaturas; zoom/ajuste; marcas de agua (presets existentes); `PageTarget` + reglas fantasma básicas (todas/rango/pares/impares); exportación vectorial verificada con respaldo; proyecto `.flexproj` + autosave; registro en launcher | 3-4 sem | Demo: membrete+marca de agua+texto sobre PDF de 200 págs rotadas mixtas, export verificado, reabrir proyecto |
| **2 — Edición profesional** | Capas (panel + lock/hide/opacidad); sellos, firmas (con `background_removal_engine`) y folios (`folio_format`); formas básicas (línea/rect/elipse/flecha); whiteout; guías inteligentes + reglas + snapping; multi-selección, alinear/distribuir, copiar/pegar/duplicar; plantillas v1 con galería | 3 sem | Caso real OCMX: juego de sello+folio+firma aplicado masivamente y guardado como plantilla |
| **3 — Contenido existente + OCR + lote** | Edición de texto existente (reemplazo en caja); imágenes existentes (ocultar/reemplazar/mover con manejo de xref compartido); OCR buscable en export + OCR de región; variables dinámicas completas; aplicar plantilla a N documentos (lote); export OCG opcional | 3 sem | Escaneo → buscable + texto corregido por región; lote de 50 docs con plantilla sin supervisión |
| **4 — Endurecimiento y pulido premium** | Rendimiento 1000+ págs (perfilado real); pulido visual (tokens premium, animaciones, empty states); atajos completos + Command Palette; matriz QA (fixtures × funciones); integración crash_handler/updater; beta interna OCMX; documentación de usuario | 2 sem | Beta sin crashes en corpus real de OCMX; arranque del Studio < 2 s; export 500 págs < 60 s |

**Total: ~12-13 semanas** hasta versión profesional. Cada fase termina integrable (la suite sigue shippeable en todo momento; el Studio se registra con `enabled=False` en el catálogo hasta el gate de Fase 1).

## 24. MVP recomendado (entregable de la Fase 1)

El MVP ya es útil en producción para el caso de uso nº 1 de OCMX (estampar contenido sobre documentos oficiales):

1. Abrir PDF robusto (validación + rotaciones + tamaños mixtos).
2. Insertar/editar **texto** y **imágenes** con estilos completos, mover/resize/rotar/opacidad.
3. Marcas de agua con los presets existentes.
4. Aplicación masiva: todas/actual/rango/pares/impares con instancias fantasma.
5. Undo/redo completo; panel de propiedades numérico.
6. Exportación segura verificada + respaldo; proyecto editable con autosave.

Queda fuera del MVP (y está bien): capas UI, plantillas, OCR, edición de contenido existente, formas, lote multi-documento.

## 25. Versión profesional completa (definición de "terminado")

Todo lo del §3-incluido operando sobre el corpus real de OCMX con estos SLO: arranque < 2 s; primer render de página < 300 ms (caché tibio < 50 ms); 60 fps al arrastrar elementos; export vectorial de 500 páginas < 60 s; cero pérdida de datos ante crash (autosave + recovery); cero modificaciones al archivo original en cualquier ruta de código.

## 26. Supuestos y decisiones tomadas (para validar en revisión)

1. **PyQt6, no PySide6** — la suite entera es PyQt6; el enunciado aceptaba ambos.
2. **Herramienta de la suite, no app separada** — máxima reutilización; el motor queda desacoplado para un futuro standalone.
3. **Overlay-first con edición puntual de existente** — el reflow completo estilo Acrobat queda explícitamente fuera del alcance (es el único camino realista a un producto estable en Python).
4. **Sin dependencias PDF nuevas** (no pikepdf/reportlab); solo se añade `fontTools` + fuentes OFL.
5. **Reglas + instancias fantasma** como mecanismo de aplicación masiva (en lugar de duplicar objetos por página).
6. Nombre **PDFlex Studio** y extensiones `.flexproj`/`.flextpl`.
