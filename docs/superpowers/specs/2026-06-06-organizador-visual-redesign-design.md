# Organizador Visual de PDF — Rediseño Completo

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reemplazar la cuadrícula plana mezclada por un sistema de filas (DocLanes) — una por documento — con drag & drop entre filas, exportación flexible (individual o fusionada), caché de miniaturas y atajo de teclado completo.

**Architecture:** Arquitectura de widgets apilados: `LaneContainer` (QScrollArea vertical) contiene N `DocLane` (header + QListWidget horizontal). El drag cross-lane usa MIME personalizado. El motor recibe `MultiOrganizerJob` con N sub-jobs. Un `ThumbnailWorker` rellena el caché en background.

**Tech Stack:** PyQt6, PyMuPDF (fitz), Pillow, dataclasses, json, threading via QThread

---

## 1. Problema actual

- Todas las páginas de todos los PDFs se mezclan en una sola `QListWidget` — no hay separación visual por documento.
- No es posible ver qué páginas pertenecen a qué PDF al trabajar con múltiples documentos.
- Solo existe un PDF de salida; no se puede exportar por documento.
- No hay caché de miniaturas: re-renderiza en cada operación.
- Sin atajos de teclado completos, sin menú contextual, sin copiar/pegar cross-doc.

---

## 2. Modelo de datos

### PageRef (sin cambios)
```python
@dataclass(frozen=True)
class PageRef:
    source_path: str
    page_index: int
    rotation_deg: int = 0
    page_id: str = ""
```

### MultiOrganizerJob (nuevo)
```python
@dataclass
class MultiOrganizerJob:
    lanes: List[OrganizerJob]   # one per DocLane, in visual order
    merge_all: bool = False     # if True, concatenate all lanes into one PDF
```

### LaneState (en memoria, en LaneContainer)
```python
@dataclass
class LaneState:
    lane_id: str          # uuid hex
    display_name: str     # editable name shown in header
    source_path: str      # original PDF path or "" for blank lanes
    color: QColor         # accent color from palette
    pages: List[PageRef]  # ordered list of pages
    collapsed: bool = False
```

---

## 3. Archivos nuevos y modificados

### Nuevos
| Archivo | Responsabilidad |
|---|---|
| `ui/organizador/lane_widget.py` | `DocLane` — header colapsable + QListWidget horizontal |
| `ui/organizador/lane_container.py` | `LaneContainer` — apila N DocLanes, gestiona drag de lanes, botones globales |
| `ui/organizador/thumb_cache.py` | `ThumbnailCache` (LRU) + `ThumbnailWorker` (QThread) |
| `ui/organizador/page_mime.py` | Serialización/deserialización MIME `application/x-pdflex-pageref` |

### Modificados
| Archivo | Qué cambia |
|---|---|
| `ui/organizador/window.py` | Reemplaza `PageGridCard` por `LaneContainer`; actualiza paso 02 con tabla de exportación; actualiza paso 03 con multi-resultado |
| `core/page_organizer_engine.py` | Agrega `MultiOrganizerJob` y `run_multi_job()` |
| `tests/test_organizador_window.py` | Actualiza tests existentes + agrega tests cross-lane y multi-output |

---

## 4. DocLane (`ui/organizador/lane_widget.py`)

### Header (40 px)
```
▐ ↑↓  [nombre_doc]    N págs    [+ Agregar]  [⊗ Vaciar]  [▼]
```
- Franja de color izquierda 4 px (`self._color`)
- Botones `↑` `↓` para mover el lane hacia arriba/abajo (emiten `reorder_requested(lane_id, ±1)`)
- `QLabel` con nombre editable al doble clic: se convierte en `QLineEdit` inline; Enter = confirmar, Escape = cancelar
- Badge de páginas: `"N pág"` / `"N págs"`
- Botón `+` → abre selector de PDFs, agrega sus páginas al final del lane
- Botón `⊗` → vacía el lane (pide confirmación si >0 páginas)
- Botón `▼`/`▶` → colapsa/expande el strip

### Strip de miniaturas
- `QListWidget`, ViewMode=IconMode, Flow=LeftToRight, Wrapping=False
- Scroll horizontal, sin scroll vertical
- Height fija: 206 px (thumbnail 150 + label + padding)
- `setDragDropMode(DragDrop)` + `setDefaultDropAction(MoveAction)`
- Acepta drops externos (cross-lane): detecta MIME `application/x-pdflex-pageref`
- Emite `lane_drag_started(lane_id, selected_refs)` al iniciar drag
- `dragEnterEvent`: si es MIME cross-lane → highlight borde teal 2px + fondo sutil
- `dragLeaveEvent`: restaura borde normal
- `dropEvent`: deserializa MIME → move o copy según `ctrl_held`

### Señales públicas
```python
pages_changed = pyqtSignal(str)          # lane_id
lane_delete_requested = pyqtSignal(str)  # lane_id
reorder_requested = pyqtSignal(str, int) # lane_id, direction (+1/-1)
```

### Menú contextual (click derecho en miniatura)
```
Rotar →
Rotar ←
──────────
Duplicar
──────────
Mover a ▶  [lista de nombres de otros lanes]
Copiar a ▶ [lista de nombres de otros lanes]
──────────
Eliminar
```

---

## 5. LaneContainer (`ui/organizador/lane_container.py`)

### Layout
```
QScrollArea (vertical)
  └─ QWidget (container)
       ├─ DocLane 0
       ├─ DocLane 1
       ├─ ...
       ├─ DocLane N-1
       └─ QFrame (bottom_bar)
            ├─ QPushButton "＋ Nuevo documento vacío"
            └─ QPushButton "＋ Agregar PDFs"
```

### Reordenar lanes
- Los botones `↑`/`↓` del header de cada `DocLane` emiten `reorder_requested(lane_id, ±1)`.
- `LaneContainer` recibe la señal y llama `_rebuild_layout()`: quita y re-agrega los widgets en el nuevo orden.
- `_lanes: List[DocLane]` — la lista es la fuente de verdad del orden.

### Cross-lane drag (coordinator)
- `DocLane.dropEvent` deserializa MIME, detecta que `source_lane_id != self._lane_id`, y emite `cross_lane_drop_received(source_lane_id, self._lane_id, refs, ctrl_held)`.
- `LaneContainer` recibe esa señal y llama `_on_cross_lane_drop(source_id, target_id, refs, ctrl_held)`:
  - Si `ctrl_held=False`: quita refs de source, inserta en target
  - Si `ctrl_held=True`: inserta copia en target, deja source intacto
- Los `page_id` de las copias se regeneran para evitar duplicados.

### Señales públicas
```python
layout_changed = pyqtSignal()   # any lane added/removed/reordered
```

### API
```python
def add_lane_from_pdf(self, path: str) -> DocLane
def add_blank_lane(self, name: str = "") -> DocLane
def remove_lane(self, lane_id: str) -> None
def move_lane(self, lane_id: str, direction: int) -> None
def lanes(self) -> List[DocLane]
def all_page_refs(self) -> List[Tuple[str, List[PageRef]]]  # (lane_id, refs)
def lane_states(self) -> List[LaneState]
```

---

## 6. ThumbnailCache (`ui/organizador/thumb_cache.py`)

### Cache LRU
```python
class ThumbnailCache:
    def __init__(self, max_size: int = 200)
    def get(self, key: ThumbnailKey) -> Optional[QPixmap]
    def put(self, key: ThumbnailKey, pixmap: QPixmap) -> None
    def invalidate_path(self, path: str) -> None

@dataclass(frozen=True)
class ThumbnailKey:
    source_path: str
    page_index: int
    rotation_deg: int
    width: int
```

### Worker background
```python
class ThumbnailWorker(QObject):
    thumb_ready = pyqtSignal(str, str, object)   # lane_id, page_id, QPixmap

    def request(self, lane_id: str, page_id: str, ref: PageRef, width: int) -> None
    def run(self) -> None   # procesa cola de requests
```

Cada `DocLane` al agregar páginas:
1. Crea ítems con placeholder pixmap (ícono gris)
2. Envía requests al worker
3. Al recibir `thumb_ready` actualiza el ítem correspondiente

---

## 7. MIME (`ui/organizador/page_mime.py`)

```python
MIME_TYPE = "application/x-pdflex-pageref"

def encode_drag(lane_id: str, refs: List[PageRef]) -> QMimeData
def decode_drag(mime: QMimeData) -> Optional[Tuple[str, List[PageRef]]]
    # returns (source_lane_id, refs) or None if not our MIME
```

JSON payload:
```json
{
  "source_lane_id": "abc123",
  "refs": [
    {"source_path": "...", "page_index": 2, "rotation_deg": 0, "page_id": "x-3-abc"}
  ]
}
```

`ctrl_held` no se guarda en MIME — se lee en `dropEvent` desde `QApplication.keyboardModifiers()`.

---

## 8. Motor multi-output (`core/page_organizer_engine.py`)

```python
@dataclass
class MultiOrganizerJob:
    lanes: List[OrganizerJob]
    merge_all: bool = False

@dataclass
class MultiOrganizerResult:
    results: List[OrganizerResult]
    merged_output_path: str = ""
    success: bool = True
    error: str = ""
```

```python
class PageOrganizerEngine:
    def run_multi_job(
        self,
        job: MultiOrganizerJob,
        *,
        progress: Callable | None = None,
        should_cancel: Callable | None = None,
    ) -> MultiOrganizerResult:
        ...
```

Si `merge_all=False`: ejecuta cada `OrganizerJob` por separado y devuelve `results` con N entradas.
Si `merge_all=True`: construye una lista plana de todos los `PageRef` de todos los lanes (en orden) y genera un solo PDF. `results` tendrá un único `OrganizerResult`.

---

## 9. OrganizadorWindow — cambios en pasos

### Paso 01 (Páginas)
- Reemplaza `PageGridCard` por `LaneContainer`
- El header ahora muestra: total páginas · total docs · N lanes
- Desaparece el checkbox "solo seleccionadas" del paso 01 (ahora cada lane es independiente)

### Paso 02 (Procesar)
Tabla de lanes reemplaza el campo de nombre único:
```
┌──────────────────────────────────────────────────┐
│ Doc                 │ Págs │ Nombre de salida     │
│ contrato.pdf        │  5   │ [contrato_org.pdf  ] │
│ expediente.pdf      │  3   │ [expediente_org.pdf] │
│ nuevo_doc           │  2   │ [nuevo_doc.pdf     ] │
└──────────────────────────────────────────────────┘
  ☐ Fusionar en un solo PDF: [nombre_merged.pdf    ]
```
- QTableWidget con columnas: Nombre | Páginas | Archivo de salida (QLineEdit en celda)
- Al marcar fusionar: deshabilita columna "Archivo de salida", activa campo de nombre único

### Paso 03 (Resultados)
- Si exportación separada: viewer con selector de resultado (un PDF por lane)
- Si merged: viewer único

---

## 10. Colores de lanes (paleta)

```python
LANE_COLORS = [
    QColor(94, 106, 210),   # índigo
    QColor(56, 178, 172),   # teal
    QColor(236, 135, 72),   # naranja
    QColor(168, 85, 247),   # violeta
    QColor(239, 68, 68),    # rojo
    QColor(34, 197, 94),    # verde
    QColor(234, 179, 8),    # amarillo
    QColor(236, 72, 153),   # rosa
]
```

---

## 11. Tests a implementar

| Test | Archivo |
|---|---|
| `test_add_pdf_creates_lane_with_correct_page_count` | `test_organizador_window.py` |
| `test_blank_lane_creation` | `test_organizador_window.py` |
| `test_cross_lane_move_removes_from_source` | `test_organizador_window.py` |
| `test_cross_lane_copy_keeps_source_intact` | `test_organizador_window.py` |
| `test_lane_reorder_changes_export_order` | `test_organizador_window.py` |
| `test_multi_output_generates_n_pdfs` | `test_organizador_window.py` |
| `test_merge_output_generates_single_pdf` | `test_organizador_window.py` |
| `test_thumbnail_cache_hit_avoids_rerender` | `test_organizador_window.py` |
| `test_run_multi_job_separate` | `test_page_organizer_engine.py` |
| `test_run_multi_job_merged` | `test_page_organizer_engine.py` |

---

## 12. Restricciones y no-metas

- No se reimplementa el visor de resultados — se reutiliza `GenericPdfViewer`
- No hay zoom de miniaturas en tiempo real (tamaño fijo 116 px)
- No hay historial de deshacer (Ctrl+Z) — scope futuro
- No se toca el resto de herramientas de PDFlex
