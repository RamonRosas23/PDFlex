# Spec: Contextual Footer Buttons — Navbar como barra de acción por paso

**Fecha:** 2026-06-07
**Estado:** Aprobado

---

## Problema

En el scaffold actual, los pasos "Procesar" y "Resultados" tienen botones de acción (Ejecutar, Cancelar, Nueva sesión, Enviar a herramienta) embebidos dentro del contenido de la etapa. Esto crea dos zonas de acción separadas: la barra inferior de navegación (Anterior / Siguiente) y los botones dentro del paso. La experiencia es inconsistente y visualmente ruidosa.

---

## Objetivo

Consolidar TODAS las acciones en la barra inferior (`ToolNavBar`) del scaffold. Los pasos sin acción muestran solo los botones de navegación; los pasos con acción (Procesar, Resultados) reemplazan "Siguiente" con sus botones contextuales específicos.

---

## Diseño

### 1. Layout del navbar por paso

El navbar (56 px de altura, sin cambio) se comporta así según el paso activo:

```
Pasos sin acción (ej. Documentos, Perfil):
  [← Anterior]   [·····stretch·····]   [→ Siguiente: Procesar]

Paso Procesar:
  [← Anterior]   [·····stretch·····]   [■ Cancelar]  [▶ Comprimir PDFs]

Paso Resultados (último):
  [← Anterior]   [·····stretch·····]   [↗ Enviar a...]  [↺ Nueva sesión ●]
```

**Regla de visibilidad:**
- Si `_action_zone` tiene widgets → `_nav_next_btn` se oculta
- Si `_action_zone` está vacío → `_nav_next_btn` se muestra con texto descriptivo

### 2. Cambios en `PipelineWindow` (`ui/common/tool_scaffold.py`)

#### 2a. `_build_navbar()` — agregar `_action_zone`

El layout del navbar pasa de:
```
[Anterior] [stretch] [Siguiente]
```
a:
```
[Anterior] [stretch] [_action_zone] [Siguiente]
```

`_action_zone` es un `QWidget` con `QHBoxLayout` interno (spacing=8, márgenes=0), inicialmente oculto.

```python
self._action_zone = QWidget()
self._action_zone_layout = QHBoxLayout(self._action_zone)
self._action_zone_layout.setContentsMargins(0, 0, 0, 0)
self._action_zone_layout.setSpacing(8)
self._action_zone.setVisible(False)
row.addWidget(self._action_zone)
```

#### 2b. Hook `_get_step_actions(idx) → list[QWidget]`

Nuevo método en `PipelineWindow`, a sobreescribir en subclases:

```python
def _get_step_actions(self, idx: int) -> list[QWidget]:
    """Retorna botones contextuales para el paso idx. [] = sin acciones."""
    return []
```

#### 2c. `_refresh_action_zone(idx)`

Método privado que vacía y repuebla `_action_zone`. Solo gestiona la visibilidad de `_nav_next_btn` — NO llama a `_update_navbar` internamente (eso lo hace `_switch_section` antes de este método).

```python
def _refresh_action_zone(self, idx: int) -> None:
    # Desanclar widgets anteriores sin destruirlos (se reusan)
    while self._action_zone_layout.count():
        item = self._action_zone_layout.takeAt(0)
        if item.widget():
            item.widget().setParent(None)

    actions = self._get_step_actions(idx)
    for widget in actions:
        self._action_zone_layout.addWidget(widget)

    has_actions = bool(actions)
    self._action_zone.setVisible(has_actions)
    # Si hay acciones, ocultar Siguiente (lo reemplazan); si no, _update_navbar
    # ya habrá establecido su visibilidad correcta antes de esta llamada.
    if has_actions and hasattr(self, "_nav_next_btn"):
        self._nav_next_btn.setVisible(False)
```

#### 2d. `_switch_section` — orden de llamadas actualizado

El orden final en `_switch_section` debe ser:

```python
self._sync_child_accents()
self._on_section_activated(idx)      # subclase puede actualizar estado
if hasattr(self, "_nav_prev_btn"):
    self._update_navbar(idx)         # prev/next texto + visibilidad base
self._refresh_action_zone(idx)       # sobreescribe next si hay acciones
self._apply_primary_glows()          # glow sobre el estado final de botones
```

Esto garantiza que `_apply_primary_glows` siempre se ejecuta con los botones ya en su posición definitiva en el navbar.

#### 2e. `_update_navbar` — texto descriptivo para "Siguiente"

```python
# Antes:
self._nav_next_btn.setText(next_name)

# Después:
self._nav_next_btn.setText(f"Siguiente: {next_name}")
```

### 3. Refactor de `ProcessStep` (`ui/common/process_step.py`)

`ProcessStep` pasa a ser un widget puro de **estado + progreso**. No contiene botones.

#### 3a. Señales nuevas

```python
run_enabled_changed = pyqtSignal(bool)   # emitida por set_run_enabled
running_changed     = pyqtSignal(bool)   # emitida por start/stop_processing_ui
```

#### 3b. Eliminaciones en `_build()`

Eliminar completamente el bloque final de botones:
- El `QHBoxLayout nav`
- `self._cancel_btn`
- `self._run_btn`

#### 3c. Métodos actualizados

`set_run_enabled(enabled)`:
```python
# Antes: self._run_btn.setEnabled(enabled)
# Después:
self._run_enabled_requested = enabled
if not self._is_running:
    self.run_enabled_changed.emit(enabled)
```

`start_processing_ui()`:
```python
# Al inicio del bloque existente, después de shimmer:
self.running_changed.emit(True)
# Eliminar: self._run_btn.setEnabled(False) y self._cancel_btn.setEnabled(True)
```

`stop_processing_ui()`:
```python
# Al final del bloque existente:
self.running_changed.emit(False)
self.run_enabled_changed.emit(self._run_enabled_requested)
# Eliminar: self._run_btn.setEnabled(...) y self._cancel_btn.setEnabled(False)
```

Eliminar: `_refresh_run_glow()` y todas sus llamadas internas.

### 4. Patrón por herramienta

Aplica a **todas las herramientas** que usen `ProcessStep` con sección de Resultados.

#### 4a. Crear botones a nivel de window

En `_build_pages()` (o método dedicado `_build_action_buttons()`), crear y guardar los botones como atributos de instancia:

```python
# Paso Procesar
self._run_btn = QPushButton("<label específico>")   # ej: "Comprimir PDFs"
self._run_btn.setProperty("class", "Primary")
self._run_btn.setFixedHeight(36)
self._run_btn.setMinimumWidth(160)
set_button_icon(self._run_btn, "play")
self._run_btn.setEnabled(False)
self._run_btn.clicked.connect(self._on_run)

self._cancel_btn = QPushButton("Cancelar")
self._cancel_btn.setProperty("class", "Danger")
self._cancel_btn.setFixedHeight(36)
set_button_icon(self._cancel_btn, "square", color="#E5484D")
self._cancel_btn.setEnabled(False)
self._cancel_btn.clicked.connect(self._on_cancel)

# Paso Resultados
self._restart_btn = QPushButton("Nueva sesión")
self._restart_btn.setProperty("class", "Primary")
self._restart_btn.setFixedHeight(36)
self._restart_btn.setMinimumWidth(160)
set_button_icon(self._restart_btn, "refresh-cw")
self._restart_btn.clicked.connect(self._reset_session)
```

#### 4b. Wire con ProcessStep

```python
self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
self._proc_step.running_changed.connect(self._on_proc_running)

def _on_proc_running(self, running: bool) -> None:
    # run_btn se deshabilita al arrancar; se re-habilita vía run_enabled_changed
    # que ProcessStep emite en stop_processing_ui con el valor de _run_enabled_requested
    if running:
        self._run_btn.setEnabled(False)
    self._cancel_btn.setEnabled(running)
    self._apply_primary_glows()
```

`_proc_step.run_requested` y `_proc_step.cancel_requested` ya no existen — reemplazados por `self._run_btn.clicked` y `self._cancel_btn.clicked`.

#### 4c. Override de `_get_step_actions`

El índice varía por herramienta según cuántos pasos tiene:

```python
def _get_step_actions(self, idx: int) -> list[QWidget]:
    procesar_idx = next(
        (i for i, s in enumerate(self.SECTIONS) if s[1] == "Procesar"), None
    )
    resultados_idx = next(
        (i for i, s in enumerate(self.SECTIONS) if s[1] == "Resultados"), None
    )
    if idx == procesar_idx:
        return [self._cancel_btn, self._run_btn]
    if idx == resultados_idx:
        return [self._send_btn, self._restart_btn]
    return []
```

> **Nota:** Para herramientas sin `_send_btn` (si las hay), la lista de resultados omite ese widget.

#### 4d. Limpiar secciones

- En `_build_process_section()`: ya no se llama a `_proc_step.run_requested.connect(...)` ni `_proc_step.cancel_requested.connect(...)`.
- En `_build_results_section()`: eliminar el bloque `action_row` con SendToTool y restart_btn — esos widgets ahora se crean en 4a y se insertan vía `_get_step_actions`.

### 5. Herramientas alcanzadas

Cualquier herramienta que extienda `PipelineWindow` y use `ProcessStep` con sección de Resultados. Basado en el código actual, esto incluye al menos:

- `ui/compresor/window.py`
- `ui/unir/window.py`
- `ui/protector/window.py`
- `ui/marca_agua/window.py`
- `ui/membretado/window.py`
- `ui/firmador/window.py`
- `ui/imgs_a_pdf/window.py`
- `ui/pdf_to_imgs/window.py`
- `ui/pdf_to_word/window.py`
- `ui/word_a_pdf/window.py`
- `ui/separador/window.py`
- `ui/redactor/window.py`
- `ui/reparador/window.py`
- `ui/ocr/window.py`
- `ui/extraer_imagenes/window.py`
- `ui/quitar_fondo/window.py`
- `ui/foleador/window.py`
- `ui/formularios/window.py`

Herramientas sin `ProcessStep` (ej. `clasificador`, `comparador`, `organizador`) no requieren cambios — `_get_step_actions` retorna `[]` por defecto.

---

## Comportamiento de estado del botón Ejecutar

| Estado del sistema | `_run_btn` | `_cancel_btn` |
|---|---|---|
| Sin documentos cargados | Disabled | Disabled |
| Documentos listos, sin correr | **Enabled** (Primary + glow) | Disabled |
| Proceso activo | Disabled | **Enabled** (Danger) |
| Proceso completado | **Enabled** (Primary + glow) | Disabled |

---

## No cambia

- La barra de progreso dentro de `ProcessStep`
- El card de resumen dentro de `ProcessStep`
- El card de carpeta de salida dentro de `ProcessStep` (cuando aplica)
- `watch_documents()`, `set_summary_html()`, `set_progress()`, `set_accent()`, `animate_stats()`, `reset()`
- El flujo de auto-navegación a Resultados al terminar (`_switch_section` llamado en `_on_finished`)
- Los viewers de resultados (`GenericPdfViewer`, etc.) dentro de las secciones de resultados
- La animación slide entre pasos
- Los atajos Alt+1-9
- El glow de botones Primary (sigue funcionando vía `_apply_primary_glows`)

---

## Criterios de éxito

1. En el paso Procesar, el navbar muestra [Cancelar] + [Ejecutar] y NO aparece "Siguiente".
2. En el paso Resultados, el navbar muestra [Enviar a...] + [Nueva sesión] y NO aparece "Siguiente".
3. En otros pasos, el navbar muestra "Siguiente: {nombre}" sin botones extra.
4. El botón Ejecutar responde correctamente a `run_enabled_changed` (habilitado/deshabilitado según docs cargados).
5. Durante el proceso: Cancelar habilitado, Ejecutar deshabilitado. Al terminar: invertido.
6. El glow de accent aparece en el botón Primary activo del navbar.
7. Al terminar el proceso, la app navega automáticamente a Resultados (`_switch_section`).
8. Todas las herramientas listadas en la sección 5 se comportan igual.
