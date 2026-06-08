# Spec: PdfFullViewDialog — Vista Completa de Resultados PDF

**Fecha:** 2026-06-08  
**Estado:** Aprobado  
**Archivo destino:** `ui/common/pdf_fullview_dialog.py`

---

## 1. Objetivo

Añadir a la etapa de resultados un botón **"Vista completa"** que abre un modal inmersivo para leer el PDF con máximo espacio. El modal permite navegar entre todos los documentos del lote y entre páginas, con zoom y controles de primera clase.

---

## 2. Puntos de integración

| Archivo | Cambio |
|---|---|
| `ui/common/pdf_viewer.py` | Botón "Vista completa" en `title_row`; llama `PdfFullViewDialog` |
| `ui/results_viewer.py` | Mismo botón; misma llamada |
| `ui/common/pdf_fullview_dialog.py` | Archivo nuevo — toda la lógica del modal |

El botón se habilita solo cuando hay un resultado exitoso seleccionado y se coloca entre los botones existentes ("Abrir PDF") y ("Abrir carpeta").

---

## 3. Estructura visual

```
┌──────────────────────────────────────────────────────────────────────┐
│ TOOLBAR (46px fija)                                                  │
│ [≡]│← [Doc 2/8] →│ resultado.pdf ···│− 100% + ⊡ □│Pág.[3]/24 ← →│✕│
├──────┬───────────────────────────────────────────────────────────────┤
│      │                                                               │
│ PAGE │                                                               │
│THUMBS│              PDF CANVAS (QScrollArea)                         │
│120px │                fondo #050507                                  │
│      │                                                               │
├──────┴───────────────────────────────────────────────────────────────┤
│  [● doc1.pdf]  [● doc2.pdf ▌activo]  [doc3.pdf]  [✗ doc4.pdf]      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. API pública

```python
class PdfFullViewDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        results: list,          # objetos con: output_path, success, error
        current_index: int,     # índice del doc a mostrar al abrir
    ) -> None: ...
```

Llamada desde los viewers:
```python
def _on_fullview(self) -> None:
    row = self.doc_list.currentRow()
    dlg = PdfFullViewDialog(self, results=self._results, current_index=row)
    dlg.exec()
```

---

## 5. Componentes internos

### 5.1 QDialog shell

- `FramelessWindowHint` + `WA_TranslucentBackground`
- Layout externo: `QVBoxLayout` con `contentsMargins(0,0,0,0)`, `background: rgba(0,0,0,0.65)` → backdrop oscuro
- Interior: `QFrame#FullViewShell` con `border-radius: 12px`, `background: #0D0D10`, `border: 1px solid #2A2A38`
- Tamaño: 92% del área disponible de pantalla, centrado
- `fade_in(dialog, 160ms)` al mostrar
- Draggable (misma implementación que `AppDialog`: `mousePressEvent` / `mouseMoveEvent`)
- `Esc` → `reject()`

### 5.2 Toolbar superior (46px)

Fila `QHBoxLayout` con `contentsMargins(10,0,10,0)`, `spacing=4`.  
Divisores verticales (`QFrame VLine`, 1px, `#2A2A38`) entre grupos.

Grupos de izquierda a derecha:

**G1 — Toggle sidebar**
- `IconBtn` 32×32, ícono `panel-left` (o `sidebar`/`layout`)
- Tooltip: "Mostrar/ocultar miniaturas"
- Al click: colapsa/expande el panel izquierdo animado (width 0 ↔ 120px, 180ms OutCubic)

**G2 — Navegación de documentos**
- `IconBtn` ← (doc anterior)
- `QLabel` `"Doc N / M"` estilo muted, `min-width: 70px`, centrado
- `IconBtn` → (doc siguiente)
- Los botones se deshabilitan en los extremos

**G3 — Nombre del archivo**
- `ElidedLabel` (de `result_ui.py`), `stretch=1`, color `text_muted`, `font-size: 12px`
- Muestra `Path(output_path).name` del doc activo

**G4 — Zoom**
- `IconBtn` `−` → zoom out
- `QLabel` `"100%"`, `min-width: 44px`, centrado, color muted
- `IconBtn` `+` → zoom in
- `IconBtn` `⊡` (`maximize`) → fit al ancho
- `IconBtn` `□` (`file-text`) → fit página completa

**G5 — Paginador**
- `QLabel` `"Pág."` color muted, `font-size: 12px`
- `QSpinBox` 54px ancho, sin botones, `editingFinished` → saltar página
- `QLabel` `"/ N"` color muted
- `IconBtn` `←` → página anterior
- `IconBtn` `→` → página siguiente

**G6 — Cerrar**
- `IconBtn` `✕` 32×32 → `reject()`

### 5.3 Panel izquierdo — Miniaturas de páginas

- `QListWidget` en `IconMode`, ancho 120px
- `IconSize(80, 103)`, `GridSize(100, 136)`, `Flow: TopToBottom`, sin wrap
- Scroll vertical, sin scroll horizontal
- Al seleccionar ítem → navega a esa página
- Thumbnails: mismo engine adaptativo (`fitz`, DPI calculado para que lado largo ≤ 140px)
- Visible por defecto; toggle desde G1

### 5.4 Canvas

- `QScrollArea` con `objectName("FullViewCanvas")`, `widgetResizable=False`, `AlignCenter`
- `QLabel` canvas interno, `background: transparent`
- Fondo del scroll: `#050507` (el más profundo de la paleta)
- Render: misma lógica de `_compute_dpi` + `fitz.Matrix` que en `GenericPdfViewer`
- `ZOOM_LEVELS = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 2.50, 3.00, 4.00]`
- Índice inicial de zoom: el que produce fit-ancho del viewport
- `Ctrl+Rueda` → zoom in/out
- `wheelEvent`: scroll normal por defecto; con Ctrl → zoom

### 5.5 Strip inferior — Documentos del lote

- `QScrollArea` horizontal, altura fija 52px, sin scroll vertical
- Interior: `QHBoxLayout` con chips por cada resultado, `spacing=6`, `contentsMargins(10,6,10,6)`
- **Chip normal (éxito):** `QFrame` 160×36px, `border-radius: 8px`, `background: surface_3`, `border: 1px solid border`; ícono verde 12px + nombre truncado 120px, cursor pointer
- **Chip error:** mismo pero ícono rojo y texto `text_muted`
- **Chip activo:** `border: 1.5px solid <accent_color>`, `background: surface_4`, texto `text` (blanco)
- Click en chip → `_load_doc(index)`
- El accent_color se inyecta como parámetro opcional (default: `COLORS["accent"]`)
- Scroll automático para mantener el chip activo visible (`scrollTo`)

---

## 6. Render y navegación

### Carga de documento

```python
def _load_doc(self, index: int) -> None:
    # Cierra doc fitz actual
    # Abre fitz.open(result.output_path)
    # Regenera thumbnails en QListWidget
    # Llama _render_current_page()
    # Actualiza toolbar: doc label, page spin, total label, nombre archivo
    # Scroll el chip activo al centro del strip
```

### Render de página

```python
def _render_current_page(self) -> None:
    # _compute_dpi() basado en viewport size y zoom_index
    # fitz Matrix → get_pixmap → PIL → QPixmap
    # canvas.setPixmap(pix), canvas.setFixedSize(pix.size())
    # _update_page_controls()
```

### Estado de controles

```python
def _update_page_controls(self) -> None:
    # page_spin range/value
    # page_total_lbl
    # prev/next page btn enabled
    # zoom label %
```

---

## 7. Atajos de teclado

| Tecla | Acción |
|---|---|
| `Esc` | Cerrar dialog |
| `←` / `→` | Doc anterior / siguiente |
| `Page Up` / `Page Down` | Página anterior / siguiente |
| `Ctrl + −` | Zoom out |
| `Ctrl + =` | Zoom in |
| `Ctrl + 0` | Fit al ancho |
| `Ctrl + Shift + 0` | Fit página completa |

Implementado en `keyPressEvent` del dialog.

---

## 8. Parámetro accent_color

`GenericPdfViewer` y `ResultsViewer` pueden pasar el accent color de la herramienta activa para que el chip activo del strip inferior use ese color. Parámetro opcional con default `COLORS["accent"]`.

---

## 9. Error handling

- Si `result.success` es `False` o `output_path` está vacío: el chip está deshabilitado para click y el modal no lo carga
- Si `fitz.open()` falla: canvas muestra mensaje de error centrado, controles deshabilitados
- Si el doc tiene 0 páginas: misma condición de error

---

## 10. Archivos a modificar

| Archivo | Cambio |
|---|---|
| `ui/common/pdf_fullview_dialog.py` | **Crear** — toda la implementación |
| `ui/common/pdf_viewer.py` | Añadir botón "Vista completa" en `title_row`, wiring a `PdfFullViewDialog` |
| `ui/results_viewer.py` | Mismo botón, mismo wiring |

No se modifica ningún otro archivo.
