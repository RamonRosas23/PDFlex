# PDFlex — Rediseño Premium Completo (Evolutionary Premium)

**Fecha:** 2026-06-06
**Enfoque:** A — Evolutionary Premium (upgrade quirúrgico, no reescritura)
**Alcance:** 21 herramientas + launcher + componentes shared + features transversales
**Estado del spec:** COMPLETO — Secciones 1-6 aprobadas y committeadas

---

## Contexto del proyecto

PDFlex es una suite de 21 herramientas PDF desktop (PyQt6 + PyMuPDF + Tesseract) para
GRUPO OCMX. Arquitectura: `PipelineWindow` base con sidebar de pasos + `QStackedWidget`
de contenido. Tema dark actual inspirado en Linear/Vercel (#0A0A0B). 21 herramientas
con accent color propio. Componentes shared: `DocumentsCard`, `ProcessStep`,
`GenericPdfViewer`, `ImageResultsViewer`, `SendToToolButton`.

---

## Decisiones de diseño clave

- **Enfoque:** Evolutionary Premium — no reescribir lo que funciona, upgradear con cirugía
- **Capas:** Primero sistema base (tema, animaciones, shared components, launcher),
  luego mejoras por herramienta que heredan el sistema automáticamente
- **Visual:** Ultra-refined dark + glassmorphism selectivo (solo modals/overlays) +
  luminous borders + SVG icons + micro-animaciones 150-300ms
- **Features nuevas:** Command palette (Ctrl+K), presets por herramienta, historial
  de sesión ampliado (drawer), atajos de teclado globales, preferencias
- **Animaciones:** `QPropertyAnimation` para transiciones, shimmer en progress,
  success celebration, stagger en listas, spring easing para popups

---

## Sección 1: Sistema de Diseño Visual

### Paleta de color

```python
COLORS = {
    # Backgrounds (más profundos que los actuales)
    "bg":             "#050507",   # era #0A0A0B
    "surface":        "#0D0D10",   # era #111114
    "surface_2":      "#131318",   # era #16161A
    "surface_3":      "#1A1A21",   # era #1C1C21
    "surface_4":      "#20202A",   # NUEVO — para modals/overlays

    # Borders
    "border":         "#1E1E28",   # era #26262C (más sutil)
    "border_strong":  "#2A2A38",   # era #33333B
    # border_focus = per-tool accent (se mantiene)

    # Glassmorphism (command palette, modals, tray drawer)
    "glass_bg":       "rgba(13,13,16, 0.92)",
    "glass_border":   "rgba(255,255,255,0.07)",

    # Texto (más jerarquía)
    "text":           "#F0F1F3",   # era #ECEDEE, ligeramente más cálido
    "text_muted":     "#8A8FA0",   # era #9094A0
    "text_dim":       "#52566A",   # era #6B6F7A
    "text_faint":     "#383B4A",   # NUEVO — placeholders

    # Semánticos (sin cambio)
    "success":        "#3BD37C",
    "warning":        "#F5A623",
    "danger":         "#E5484D",
    "scroll_handle":  "#2A2A38",
}
```

Los accents de herramienta se mantienen. Se añaden variantes `_glow`:
`rgba(accent, 0.15)` como `QGraphicsDropShadowEffect` en botones Primary activos.

### Escala tipográfica

| Elemento          | Actual        | Nuevo                      |
|-------------------|---------------|----------------------------|
| Page title        | 21px / 700    | 26px / 800 / -0.8px ls     |
| Section header    | —             | 13px / 700 / +1.2px uppercase |
| Card title        | 13px / 600    | 14px / 700 / -0.1px ls     |
| Body              | 13px          | 13px (sin cambio)          |
| Small/hint        | 12px          | 12px (sin cambio)          |
| Mono              | 12px          | 12px (sin cambio)          |
| Stat value        | 24px / 600    | 28px / 700 / -1px ls       |
| Status bar        | —             | 11px / 400 / text_dim      |

Line-height: 1.6 en párrafos de ayuda.

### Sistema de iconos SVG

Reemplazar los iconos de letra generada (círculo con letra) por SVG Lucide
semánticos renderizados en `QLabel` con tint del accent de cada herramienta.

Nueva función: `make_tool_icon_svg(tool_id: str, accent: str, size: int) -> QPixmap`

Mapping herramienta → icono Lucide:
```
firmador       → pen-tool
foleador       → hash
separador      → scissors
unir           → layers
membretado     → layout-template
organizador    → grid-3x3
compresor      → minimize-2
marca_agua     → droplets
redactor       → eye-off
protector      → lock
formularios    → file-text
comparador     → git-compare
reparador      → wrench
word_a_pdf     → file-type-2
pdf_to_word    → file-text (variante)
pdf_to_imgs    → image
imgs_a_pdf     → images
extraer_imgs   → image-down
quitar_fondo   → layers (con opacidad)
ocr            → scan-text
clasificador   → tags
```

### Sistema de animaciones — ui/common/animations.py

Nueva clase `AnimationHelper` con los siguientes helpers:

```python
class AnimationHelper:
    @staticmethod
    def fade_in(widget, duration=200, curve=OutCubic): ...
    
    @staticmethod
    def slide_in(widget, direction="right", duration=220): ...
    
    @staticmethod
    def scale_press(widget, scale=0.97, duration=120): ...
    
    @staticmethod
    def success_check(widget, duration=400): ...  # dibuja check animado
    
    @staticmethod
    def stagger_list(items, delay=25, duration=180): ...
    
    @staticmethod
    def count_up(label, target_value, duration=400): ...
    
    @staticmethod
    def shimmer_progress(progress_bar): ...  # QTimer-based shimmer
```

Timings:
- Micro-interacciones (hover, press): 120-160ms
- Transiciones entre secciones: 220ms, OutCubic
- Popups y overlays: 180ms apertura, 140ms cierre
- Celebraciones (success): 280-400ms, OutBack para "pop"
- Count-up de estadísticas: 400ms, OutQuart
- Stagger entre list items: 25ms delay, 180ms por item

Respeta `QAccessibility` — toggle en preferencias para desactivar animaciones.

### Efectos especiales

**Glow en botones Primary:**
```python
effect = QGraphicsDropShadowEffect()
effect.setBlurRadius(20)
effect.setColor(QColor(*hex_to_rgb(accent), 89))  # 0.35 alpha
effect.setOffset(0, 0)
btn.setGraphicsEffect(effect)
```

**Glassmorphism** (solo command palette, modals, tray drawer):
- Background: `rgba(13,13,16, 0.92)`
- Border: `rgba(255,255,255,0.07)`
- Efecto blur del fondo: capturar `QPixmap.grabWidget()` de la ventana subyacente,
  aplicar `QGraphicsBlurEffect(radius=14)` sobre ese pixmap y renderizarlo como
  fondo del overlay. PyQt6 no tiene backdrop-filter nativo; esta es la aproximación
  correcta: blur sobre snapshot, no sobre el widget en vivo.

**Bordes luminosos en sidebar step activo:**
```css
#SidebarStepActive {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(accent, 0.08), stop:1 transparent);
    border-left: 2px solid accent;
}
```

---

## Sección 2: Launcher rediseñado

### Layout general

Two-column layout:
- **Columna izquierda:** 280px fija — identidad + filtros + recientes
- **Columna derecha:** flexible — grid de herramientas

### Panel izquierdo

Estructura:
```
┌─────────────────────────┐
│  PDFlex  (28px/800)     │
│  Herramientas PDF  (dim)│
├─────────────────────────┤
│  🔍 Buscar... (Ctrl+K)  │
├─────────────────────────┤
│  RECIENTES              │
│  > Compresor       ●    │
│  > Firmador        ●    │
│  > Marca de Agua   ●    │
├─────────────────────────┤
│  SECCIONES              │
│  ○ Todas                │
│  ○ Esenciales           │
│  ○ Preparar             │
│  ○ Conversión           │
├─────────────────────────┤
│  [Herramientas: 23]     │
│  v1.x.x · GRUPO OCMX   │
└─────────────────────────┘
```

- Recientes: últimas 5 herramientas usadas (de `ToolUsageStore`)
- Tooltip en recientes: último archivo procesado + timestamp relativo
- Secciones actúan como filtro con fade animation en el grid derecho

### Grid de herramientas

- Cards de **96px** (de 82px actual)
- Mínimo **240px** de ancho por card
- Grid responsivo: 3 o 4 columnas según ancho de ventana
- SVG icon 40px en accent, título 15px/700 accent, tagline 12px dim

**Hover de card:**
- border → `rgba(accent, 0.5)`
- box-shadow → `0 0 16px rgba(accent, 0.12)`
- Flecha `→` aparece a la derecha con fade-in 160ms
- Elevación de 1px

**Click de card:**
- Scale micro: `1.0 → 0.98` en 80ms antes de navegar

### Command Palette (Ctrl+K)

`QDialog` frameless, 600px ancho, centrado:
- Input de búsqueda con fuzzy matching (título > tagline > descripción)
- Categorías: Herramientas / Acciones globales / Acciones contextuales / Recientes / Config
- Resaltado de caracteres coincidentes en bold + accent
- Animación: scale `0.94→1.0` + fade, 180ms OutCubic
- Fondo glassmorphism

### Atajos globales en launcher

| Shortcut  | Acción                         |
|-----------|--------------------------------|
| `Ctrl+K`  | Command palette                |
| `Ctrl+1`…`9` | Herramienta reciente #1-9   |
| `/`       | Focus en búsqueda              |
| `Esc`     | Volver al launcher             |
| `Ctrl+,`  | Preferencias                   |

---

## Sección 3: PipelineWindow — Sidebar, Navegación y Transiciones

### Header del sidebar

```
[SVG icon 32px]
Comprimir PDF           (17px / 800, accent)
Reduce peso...          (11px dim, wordwrap)
────────────────────────
████████░░░░  Paso 2 de 4   (progress bar 3px + texto)
```

Progress bar de pasos: `QProgressBar` 3px, accent color, animada con
`QPropertyAnimation` en `value`, 200ms.

### Estados de pasos en sidebar

```
○  01  Documentos    ← pendiente: badge gris, texto dim
✓  01  Documentos    ← completado: badge accent tenue + check SVG
◉  02  Perfil        ← activo: badge accent sólido, glow lateral
   03  Procesar      ← futuro: dim
```

Transición entre estados: `QPropertyAnimation` en opacidad + color interpolado.
"Completado" se marca automáticamente al avanzar paso.

Hint de shortcuts visible en hover sobre sidebar:
```
⌨  Alt+1…4 para navegar   (fade in/out en enter/leave)
```

### Transiciones entre pasos

Slide animado (no corte seco):
- Avanzar → slide izquierda (entrante desde derecha)
- Retroceder → slide derecha (entrante desde izquierda)
- 220ms, QEasingCurve.OutCubic

Implementación: captura de pixmap del widget saliente + posicionamiento
del entrante fuera del frame + animación simultánea de ambos.

### Barra de navegación fija

`QFrame` 64px alto, `border-top: 1px border`, fijo en la base de cada página:
```
[← Nombre paso anterior]              [Nombre paso siguiente →]
```
- Retroceso: Ghost + arrow-left + texto del paso anterior
- Avance: Primary + arrow-right + texto del paso siguiente
- Botón Primary: micro-animación scale `1.0 → 0.97 → 1.0` en click, 120ms
- Botón Primary deshabilitado si docs vacíos + tooltip explicativo

### Empty states

Por contexto:
- Sin docs (inicio): folder-open + "Arrastra archivos aquí" + `Ctrl+O`
- Cancelado: X icon + "Cancelado" + botón "Reintentar"
- Error: alert-triangle rojo + mensaje específico + acción
- Sin válidos: info + mensaje específico

Iconos en SVG del accent de la herramienta (no genérico azul).

### Mini status bar

24px en base del content area:
```
3 documentos · Perfil: Equilibrado · Listo para procesar
⟳ Comprimiendo 2/3...          (durante proceso)
✓ 3 PDFs · 42% reducción       (completado)
```
Texto `text_dim`, 11px. Actualizado dinámicamente.

---

## Sección 4: Shared Components

### DocumentsCard — mejoras

**Toolbar:**
```
[+ Agregar]  [↓ Bandeja]         3 docs · 4.2 MB  [≡ ▾]
```
- Solo "Agregar" es Primary
- Menú `[≡]`: Vaciar, Quitar selección, Ordenar por nombre/tamaño/fecha
- Conteo + tamaño total en tiempo real

**Lista de documentos:**
- Miniaturas: **80×104px** (de 64×82px)
- Metadata por item: nombre + tamaño + páginas + tipo (leído en background)
- Botones inline en hover: `×` quitar, `↑↓` reordenar
- Animación de entrada: fade + translateY 6px, stagger 25ms
- Animación de salida: fade-out + translateY -6px + colapso de espacio

**Drop zone:**
1. Normal: folder icon + "Arrastra aquí o `Ctrl+O`"
2. Drag sobre zona: border accent sólido + bg `rgba(accent, 0.06)` +
   bounce del icono (scale 1.0→1.12→1.0, loop)
3. Drop: flash `rgba(accent, 0.15)` 300ms

### ProcessStep — mejoras

**Summary cards:**
```
┌──────────┐ ┌──────────┐ ┌──────────┐
│ 3        │ │ 4.2 MB   │ │Equilib.  │
│documentos│ │  entrada │ │  perfil  │
└──────────┘ └──────────┘ └──────────┘
```
Valores animados con count-up al aparecer la sección (400ms OutQuart).

**Durante procesamiento:**
- Progress bar 8px con shimmer (QTimer 50ms, gradiente desplazado)
- Nombre del archivo actual procesándose
- Tiempo transcurrido + estimación restante
- Botón Cancelar estilo Danger con icono square

**Completado:**
- Check SVG animado: círculo se dibuja (stroke progress 0→1) + checkmark
- Estadísticas: entrada → salida → reducción %
- Botones: "Ver resultados →" + "Nueva sesión"
- Duración total: 400ms, OutBack para el "pop"

### GenericPdfViewer — mejoras

**Lista de resultados:**
- Miniaturas 80×104px
- Badge de resultado: verde (reducción), amarillo (neutro), rojo (empeoró)
- Acciones inline por doc: Abrir, Guardar, → Herramienta

**Preview:**
- Toolbar: `[−] 100% [+] [Ajustar] [Página 1/8 ▾]`
- Zoom con Ctrl+Scroll
- Navegación con ← → PgUp PgDn
- Botón "Abrir en explorador" con external-link

**Acciones globales:**
```
[↓ Guardar todos]  [→ Enviar a...]  [↺ Nueva sesión]
```

### ImageResultsViewer — mejoras

- Toggle: vista galería (grid) ↔ vista lista
- Galería: click → preview full-screen en overlay
- Agrupación por PDF fuente con headers colapsables

---

## Sección 5: Features Transversales

### Command Palette — shell/command_palette.py

```python
@dataclass
class Command:
    id: str
    title: str
    subtitle: str
    category: str        # "tool" | "action" | "recent" | "config"
    accent: str
    icon: str            # nombre lucide
    shortcut: str        # display only
    action: Callable
```

Categorías:
- **Herramientas:** 23 comandos para abrir cada herramienta
- **Acciones globales:** Nueva sesión, Guardar todo, Abrir explorador
- **Acciones contextuales:** cambian según herramienta activa (Procesar, Cancelar)
- **Recientes:** últimos 5 archivos procesados + "Abrir con..."
- **Configuración:** Preferencias, Sufijo, Atajos

UX: fuzzy search, resaltado bold+accent, ↑↓ navegar, Enter ejecutar, Esc cerrar.
Glassmorphism. Animación scale `0.94→1.0` + fade, 180ms OutCubic.

### Sistema de Presets — shell/presets.py

Persistencia: `~/.pdflex/presets/<tool_id>.json`

UI en sección de configuración de cada herramienta:
```
PRESET  [Correo OCMX ▾]  [+ Guardar actual]  [⋯]
```
- Dropdown: presets guardados + "Sin preset (manual)"
- Guardar: diálogo inline con campo nombre, Enter confirma
- Menú ⋯: Renombrar, Eliminar, Exportar JSON, Importar
- Aplicar preset: flash sutil en controles afectados (border accent 400ms fade)

Presets pre-cargados por herramienta:
| Herramienta  | Presets                                    |
|--------------|--------------------------------------------|
| Compresor    | "Correo OCMX", "Archivo", "Web"            |
| Marca Agua   | "Confidencial", "Borrador", "Copia", "Pagado", "Recibido" |
| Protector    | "Solo lectura", "Sin impresión", "Máxima restricción" |
| Foleador     | "FOLIO-0001", "01/N", "Página 1 de N"     |
| Firmador     | "Esquina inf. derecha", "Centro pie"       |

### Session History Drawer — shell/session_history.py

```python
@dataclass
class HistoryEntry:
    id: str
    tool_id: str
    tool_name: str
    timestamp: datetime
    output_paths: list[str]

class SessionHistory:
    _entries: list[HistoryEntry]
    changed = pyqtSignal()
```

Drawer deslizable desde la derecha (240px ancho):
- Agrupado por ejecución con timestamp relativo
- Cada grupo: herramienta + archivos + acciones (Guardar todo, → Tool)
- Animación: slide-in desde derecha 240ms OutCubic
- Overlay `rgba(0,0,0,0.3)` en contenido principal al abrir

### Atajos de teclado globales

Registrados en `ShellWindow` con `QShortcut`:

| Shortcut          | Acción                               |
|-------------------|--------------------------------------|
| `Ctrl+K`          | Command palette                      |
| `Ctrl+O`          | Agregar archivos                     |
| `Ctrl+R`          | Procesar / Re-procesar               |
| `Ctrl+S`          | Guardar todos los resultados         |
| `Ctrl+W`          | Volver al launcher                   |
| `Ctrl+H`          | Abrir/cerrar historial drawer        |
| `Ctrl+,`          | Preferencias                         |
| `Ctrl+1`…`9`      | Herramientas recientes #1-9          |
| `Escape`          | Cancelar / cerrar palette / volver   |
| `Alt+1`…`9`       | Navegar a paso #1-9 de herramienta   |
| `Ctrl+Shift+N`    | Nueva sesión en herramienta activa   |

### Preferencias — shell/preferences_dialog.py

`QDialog` modal con sidebar de secciones:
- **General:** sufijo de salida, carpeta temporal, animaciones toggle
- **Apariencia:** densidad de UI (compacto/normal), tamaño de miniaturas
- **Atajos:** tabla editable de shortcuts
- **Avanzado:** OCR threads, temp cleanup, logs

---

## Sección 6: Mejoras por Herramienta

*Base: lectura completa de cada window.py y engine. Solo se propone lo que NO existe hoy.*
*Las mejoras del sistema base (Secciones 1-5) aplican automáticamente a todas.*

---

### 01 — Clasificador OCR

Gaps reales: no hay edición de resultados antes de aplicar, sin exportación de mapeo, sin
código de color por confianza, sin historial de plantillas.

- **Tabla editable pre-aplicación** — antes de renombrar, mostrar tabla: archivo original
  → nombre sugerido → campo editable. Confirmar todo o fila por fila.
- **Código de color de confianza** — verde/amarillo/rojo en cada fila según nivel de
  confianza. Las filas rojas requieren revisión antes de aplicar.
- **Exportar CSV del mapeo** — genera `clasificacion_YYYY-MM-DD.csv`: archivo_original,
  nombre_sugerido, tipo, confianza, rfc, fecha detectada.
- **Historial de plantillas** — últimas 5 plantillas de nombre usadas disponibles como
  dropdown para reutilizar.

---

### 02 — Compresor

Gaps reales: solo 3 perfiles fijos, sin estimación previa, sin comparativa visual.

- **Perfil personalizado** — cuarta opción "Personalizado": sliders de DPI (50–300) y
  calidad JPEG (10–100%) editables directamente.
- **Estimación de reducción esperada** — al seleccionar perfil, analizar el PDF y mostrar
  "Estimado: ~X MB → ~Y MB (~Z% menos)" antes de procesar.
- **Barra antes/después en resultados** — por cada documento: barra horizontal solapada
  (gris=original, acento=comprimido) con tamaños anotados. Más visual que solo números.

---

### 03 — Comparador

Gaps reales: no hay vista simultánea de ambos PDFs, sin filtro de páginas iguales,
sin score por página expuesto en UI.

- **Vista lado a lado** — panel dividido 50/50 con el PDF base izquierda y revisado
  derecha, sincronizados en scroll, diferencias resaltadas en ambos paneles.
- **Filtrar solo páginas con cambios** — toggle: oculta páginas idénticas en la lista
  de resultados, muestra solo las modificadas.
- **Score de similitud por página** — porcentaje junto a cada página en la lista
  (el engine ya lo calcula, falta exponerlo en la UI).

---

### 04 — Extraer Imágenes

Gaps reales: filtro de formato no existe en UI, sin galería exploratoria previa,
sin patrón de nombre configurable. (Tamaño mínimo ya existe.)

- **Filtro por formato** — checkboxes PNG / JPG / Cualquiera. El engine extrae ambos;
  falta filtro en UI.
- **Galería exploratoria previa** — botón "Ver imágenes encontradas": escanea PDFs y
  muestra galería con dimensiones y formato de cada imagen. El usuario desmarca las que
  no quiere antes de extraer.
- **Patrón de nombre de salida** — campo: `{pdf}_{pagina}_{n}` (default), con variables
  documentadas en tooltip.

---

### 05 — Firmador Masivo

Gaps reales: preview siempre del primer documento, sin rotación base fija,
el intervalo de páginas es global (no por firma individual).
(Librería de firmas, variación, canvas multi-firma, drag ya existen.)

- **Selector de documento para preview** — dropdown o lista para elegir sobre cuál PDF
  del lote se visualiza el canvas. Hoy siempre muestra el primero.
- **Ángulo base fijo de firma** — control de "ángulo base" (ej. -15°) sobre el que se
  aplica la variación aleatoria existente. Hoy solo existe la variación, no una
  inclinación intencional base.
- **Intervalo de páginas por firma** — cada entrada de firma en la lista puede tener su
  propio intervalo de páginas (ej. firma A en pp. 1-3, firma B en última).

---

### 06 — Foleador

Gaps reales: sin alineación configurable del texto en el placeholder, sin numeración
romana, sin modo espejo para doble cara.
(Fuente, color, bold, italic, tamaño, número inicial, paso ya existen.)

- **Alineación del número** — botones izquierda/centro/derecha dentro del placeholder.
  Actualmente siempre centrado.
- **Numeración romana** — variable `{n:roman}` en el patrón (I, II, III…).
  Implementar en `folio_format.py`.
- **Modo espejo (doble cara)** — toggle: páginas impares a la derecha, pares a la
  izquierda. Para documentos impresos a doble cara.

---

### 07 — Formularios PDF

Gaps reales: sin relleno por lote desde CSV, sin reutilización de valores frecuentes.

- **Relleno por lote desde CSV/Excel** — modo lote: importar CSV donde cada fila = un
  formulario resultado. Paso de mapeo columna→campo. Genera N PDFs, uno por fila.
- **Valores frecuentes por campo** — botón [★] junto a cada campo de texto: lista los
  últimos 5 valores usados en ese campo (persistidos en JSON local). Evita reescribir
  empresa, RFC, etc.

---

### 08 — Imágenes a PDF

Gaps reales: sin corrección de perspectiva (dewarp), sin estimación del PDF resultante.
(Deskew, crop bordes, enhance contraste, tamaño página, márgenes, presets ya existen.)

- **Corrección de perspectiva (dewarp)** — detectar y corregir distorsión trapezoidal
  en fotos tomadas con cámara inclinada. Más que deskew: corrige la perspectiva.
  Usando OpenCV `getPerspectiveTransform`.
- **Estimación del PDF resultante** — mostrar antes de procesar: "~X páginas, ~Y MB
  estimado" según resolución y formato elegidos.

---

### 09 — Marca de Agua

Gaps reales: texto usa fuente fija (sin selector), sin modo mosaico, sin múltiples sellos.
(9 posiciones, rotación, opacidad, presets, rango de páginas ya existen.)

- **Selector de fuente para texto** — `QFontComboBox` para elegir la fuente del sello.
  Actualmente Helvetica fijo. Documentos corporativos requieren la fuente del branding.
- **Modo mosaico/filigrana** — repetir el sello en cuadrícula por toda la página.
  Controles: espaciado H y V. Ideal para "BORRADOR" o "CONFIDENCIAL" en todo el fondo.
- **Múltiples capas de sello** — lista de hasta 3 sellos independientes con reordenamiento.
  Ejemplo: texto "CONFIDENCIAL" + logo corporativo aplicados simultáneamente.

---

### 10 — Membretado

Gaps reales: sin regla primera página / resto, sin escala del membrete, sin preview
lado a lado. (Librería de membretes, detección de márgenes, sliders de margen ya existen.)

- **Regla primera página / resto** — toggle con selector independiente de membrete para
  portada vs. páginas siguientes. Caso muy común: portada sin membrete o con membrete
  diferente al resto del documento.
- **Escala del membrete** — slider 50–100%: reduce el membrete si ocupa demasiado.
  Actualmente siempre llena la página completa.
- **Preview lado a lado** — dos paneles sincronizados: página sin membrete | con membrete.
  Valida antes de procesar el lote completo.

---

### 11 — OCR de PDF

Gaps reales: sin búsqueda en el texto transcrito, el panel de texto no es editable,
sin exportación a PDF con capa de texto.
(Idiomas, DPI, estrategias, TextResultsViewer con estadísticas ya existen.)

- **Búsqueda en transcripción** — campo de búsqueda en Resultados que resalta matches
  en el TextResultsViewer. Verificar que nombre/número fue reconocido correctamente
  antes de exportar.
- **Edición en línea del texto transcrito** — hacer editable el panel de texto para
  corregir errores de OCR (siglas, nombres propios) antes de guardar el DOCX.
- **Exportar PDF con capa de texto** — generar PDF con texto OCR como capa invisible
  (text-behind-image). El PDF sigue visualmente igual pero es buscable/copiable
  en cualquier lector PDF.

---

### 12 — Organizador Visual

Gaps reales: sin rotación de página en la UI, sin duplicar página, sin preview del resultado.
(Drag & drop multi-lane, merge toggle, nombres por lane ya existen.)

- **Botones de rotación en miniaturas** — ícono de rotación 90° CW / CCW en hover
  sobre cada thumbnail. Actualmente no hay forma de rotar páginas en el organizador.
- **Duplicar página** — botón o `Ctrl+D` sobre página seleccionada para crear copia
  en la misma lane.
- **Preview del resultado final** — botón "Vista previa" que genera PDF temporal de
  baja resolución para revisar orden y rotaciones antes de confirmar el proceso.

---

### 13 — PDF a Imágenes

Gaps reales: sin modo escala de grises / B&N, sin estimación de peso total.
(DPI, formato PNG/JPG/WebP, rango de páginas, modo panorámico ya existen.)

- **Modo de color** — selector: RGB (actual) / Escala de grises / Blanco y negro
  (umbral 0–255 configurable). Grises reduce peso considerablemente para escaneados.
- **Estimación de peso total** — al cambiar DPI o formato: "~X imágenes, ~Y MB en total"
  calculado antes de procesar.

---

### 14 — PDF a Word

Gaps reales: sin vista previa del contenido antes de exportar, sin opción TXT adicional.
(Idioma, precisión, DPI, OCR fallback, preservación de texto nativo ya existen.)

- **Vista del texto extraído antes de exportar** — panel de previsualización del
  contenido en la sección Procesar: el texto que irá al DOCX visible antes de generarlo
  para decidir si continuar o ajustar opciones.
- **Exportar TXT adicional** — checkbox "También generar TXT plano" junto al DOCX.
  Para quien necesita el texto sin estructura de Word.

---

### 15 — Protector

Gaps reales: sin modo desproteger, sin generador de contraseña.
(AES-256, contraseña apertura/propietario, 8 permisos granulares ya existen.)

- **Modo desproteger** — pestaña o toggle "Quitar contraseña": introduce la contraseña
  actual de un PDF protegido y genera copia sin cifrado. La funcionalidad opuesta que hoy falta.
- **Generador de contraseña segura** — botón [Generar] junto al campo: crea password
  aleatorio fuerte (12+ chars, mayúsculas + dígitos + símbolos) con opción de copiar
  al portapapeles.

---

### 16 — Quitar Fondo

Gaps reales: sin selector de color manual, sin comparativa antes/después en la sección
de ajustes. (Slider de tolerancia, ImageResultsViewer con comparison_mode ya existen.)

- **Selector de color a eliminar** — cuentagotas sobre el preview de la imagen para
  seleccionar exactamente qué color eliminar. El modo automático existente falla en
  fondos con variación; este modo lo resuelve.
- **Vista antes/después con divisor** — slider vertical sobre el preview en la sección
  Ajustes (antes de procesar): arrastra para comparar original vs sin fondo en tiempo real
  mientras ajustas la tolerancia.

---

### 17 — Reparador

Gaps reales: sin diagnóstico previo que oriente al perfil, sin recuperación parcial.
(3 perfiles de normalización con opciones configurables ya existen.)

- **Diagnóstico previo** — botón "Analizar" al cargar: reporta problemas detectados
  (xrefs rotas, streams inválidos, páginas inaccesibles) y recomienda qué perfil usar.
  Hoy el usuario elige perfil sin información sobre qué está mal.
- **Extracción de páginas legibles** — si no se puede reparar completamente, opción
  "Extraer páginas recuperables": genera PDF solo con las páginas que sí se pudieron leer.

---

### 18 — Separador

Gaps reales: sin miniaturas del rango activo, sin detección de separadores automáticos,
sin exportar como ZIP. (Rangos editables, "N partes iguales", "1 pág/archivo" ya existen.)

- **Miniaturas del rango activo** — panel lateral que muestra thumbnails de las páginas
  incluidas en el rango seleccionado/activo. Confirmar visualmente sin contar páginas.
- **Detectar páginas en blanco como separadores** — botón "Dividir en páginas en blanco":
  analiza el PDF y propone rangos automáticamente usando páginas vacías como cortes.
  Muy común en expedientes escaneados.
- **Empaquetar en ZIP** — opción de salida: generar `.zip` con todos los fragmentos.
  Facilita compartir el resultado como archivo único.

---

### 19 — Unir PDFs

Gaps reales: sin portada automática, sin página divisoria con título, sin numeración en
salida. (Nombre de salida, página en blanco entre docs, bookmarks ya existen.)

- **Portada automática** — checkbox: primera página generada con título editable, fecha
  y lista de documentos incluidos. Renderizada con PyMuPDF.
- **Página divisoria con título** — en lugar de (o además de) página en blanco, insertar
  página de transición con el nombre del documento siguiente centrado.
- **Numeración automática en salida** — checkbox: añadir foliado al PDF unificado
  usando el FoleadorEngine internamente. Posición y formato configurables.

---

### 20 — Word a PDF

Gaps reales: sin fallback a LibreOffice, sin thumbnails inline en resultados.
(Conversión COM, detección de Office, WordListCard ya existen.)

- **Fallback a LibreOffice** — detectar si LibreOffice está instalado y ofrecerlo si
  Word no está disponible. El diálogo "Office no encontrado" pasa de bloqueante a
  "¿Usar LibreOffice como alternativa?".
- **Thumbnails en lista de resultados** — miniatura de primera página por documento
  generado (igual que otras herramientas). Actualmente solo hay visor general.

---

### 21 — Redactor

Gaps reales: sin auto-detección de patrones, sin "buscar y redactar", sin undo,
sin reutilización de zonas. (Canvas de dibujo, redacción real PyMuPDF, limpiar página ya existen.)

- **Buscar y redactar texto** — campo de búsqueda: el texto escrito se marca
  automáticamente en todas sus ocurrencias en todas las páginas. Evita dibujar
  rectángulos sobre texto repetido.
- **Auto-detección de patrones** — botón "Detectar automáticamente": busca y propone
  zonas para emails, teléfonos, RFC/CURP, importes. Zonas sugeridas en color diferente;
  el usuario aprueba o descarta cada una.
- **Undo/redo** — Ctrl+Z / Ctrl+Y para deshacer zonas dibujadas. Hoy un trazo erróneo
  obliga a "Limpiar página" y empezar de cero.
- **Plantilla de zonas reutilizable** — exportar coordenadas de redacción como JSON para
  aplicar las mismas zonas a otros PDFs del mismo tipo (formularios recurrentes, contratos tipo).

---

## Librerías nuevas a considerar

- No se requieren librerías de terceros adicionales para el redesign visual
- `QGraphicsDropShadowEffect`, `QGraphicsBlurEffect`, `QPropertyAnimation`,
  `QEasingCurve` — todo nativo PyQt6
- Para animaciones de path SVG en el check de success: `QPainterPath` + `QPropertyAnimation`
- Para glassmorphism: `QGraphicsBlurEffect` + `QFrame` con alpha
- JSON para presets: módulo `json` estándar

---

## Anti-patterns a evitar (ui-ux-pro-max guidelines)

- No emojis como iconos — solo SVG (ya aplicado)
- No scale transforms que muevan layout — solo opacity + translate
- No animaciones > 300ms en micro-interacciones
- No glassmorphism en componentes base — solo modals/overlays
- Texto body mínimo 13px, contraste 4.5:1 mínimo
- Focus states visibles en todos los interactivos
- cursor-pointer en todos los elementos clickeables
- `prefers-reduced-motion` respetado vía toggle en preferencias

---

*Spec escrito el 2026-06-06. Última actualización: Secciones 1-6 completas.*
*Próximo paso: self-review del spec, aprobación del usuario, invocar writing-plans.*
