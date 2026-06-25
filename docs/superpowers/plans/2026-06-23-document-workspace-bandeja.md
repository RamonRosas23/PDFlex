# PDFlex - Rediseño de Bandeja y Documentos de Trabajo

> **Estado:** Completado.  
> **Bitácora viva:** `docs/superpowers/plans/2026-06-23-document-workspace-bandeja-bitacora.md`  
> **Auditoría:** `docs/superpowers/plans/2026-06-23-document-workspace-bandeja-auditoria.md`  
> **Objetivo:** separar claramente la bandeja global de sesión y el lote de trabajo de cada herramienta, con transferencias controladas entre herramientas.

## Objetivo

Convertir el sistema actual de documentos importados, bandeja y "Enviar a herramienta" en una experiencia robusta y predecible:

- La **bandeja** será un repositorio temporal global de archivos disponibles en la sesión.
- Cada herramienta tendrá un **lote de trabajo** propio, que indica qué archivos se van a procesar.
- Los archivos enviados desde otra herramienta llegarán con origen claro y sin mezclarse silenciosamente con archivos anteriores.
- Al enviar resultados a otra herramienta, el usuario podrá elegir si limpia, conserva o reemplaza la bandeja.
- El diseño deberá ser común para todas las herramientas, no una solución aislada por ventana.

## Problema Actual

La arquitectura actual funciona, pero mezcla responsabilidades:

- `shell/tray.py` guarda una lista plana de archivos.
- `ui/common/documents_step.py` mezcla archivos agregados manualmente, cargados desde bandeja y enviados desde otras herramientas en una sola lista.
- `ui/common/send_to_tool.py` abre la herramienta destino directamente con `open_tool(tool_id, paths)` sin preguntar política de bandeja ni modo de inserción.
- La herramienta destino no sabe si los archivos son importados originales, resultados nuevos, convertidos o elementos ya existentes en bandeja.

Resultado: el usuario puede no saber qué va a procesar, qué quedó en bandeja, qué venía de otra herramienta y qué se está mezclando con trabajos anteriores.

## Principios de Diseño

- **Separación mental clara:** bandeja a la izquierda, trabajo actual a la derecha.
- **Nada se mezcla en silencio:** toda entrada enviada desde otra herramienta debe ser visible como un grupo/origen.
- **Acciones explícitas:** agregar, reemplazar, limpiar y conservar deben estar nombradas con claridad.
- **Compatibilidad progresiva:** mantener APIs actuales (`paths()`, `add_paths()`, `clear()`, `files_changed`) para migrar por fases.
- **Sin pérdida accidental:** la opción por defecto debe conservar bandeja y reemplazar el trabajo destino, salvo que el usuario indique otra cosa.
- **UI densa pero amable:** es una herramienta operativa, no una landing page; debe ser clara, escaneable y rápida.

## Arquitectura Propuesta

### Modelo de Bandeja Enriquecido

Extender `TrayItem` para representar archivos con origen, relación y estado.

```python
class TrayItem:
    id: str
    path: str
    label: str
    kind: Literal["original", "output", "converted", "manual"]
    source_tool_id: str
    source_tool_title: str
    batch_id: str
    parent_ids: list[str]
    status: Literal["available", "in_work", "sent", "missing"]
    created_at: datetime
    last_used_at: datetime
```

Compatibilidad obligatoria:

- `PdfTray.paths()` sigue devolviendo `list[str]`.
- `PdfTray.add_items(paths, source_tool)` sigue funcionando.
- Las herramientas existentes no deben romperse mientras se migra.

### Transferencia Entre Herramientas

Crear un contrato explícito para transferencias.

```python
class ToolTransfer:
    paths: list[str]
    source_tool_id: str
    source_tool_title: str
    mode: Literal["replace", "append"]
    tray_policy: Literal["keep", "replace_with_sent", "clear"]
```

Políticas:

- `replace`: reemplaza el lote de trabajo de la herramienta destino.
- `append`: agrega al lote existente.
- `keep`: conserva bandeja actual.
- `replace_with_sent`: deja en bandeja solo los archivos enviados.
- `clear`: limpia bandeja después de abrir destino.

Default recomendado:

- `mode = "replace"`
- `tray_policy = "keep"`

### Nuevo Componente Común

Crear `DocumentWorkspace` como sucesor de `DocumentsCard`.

Responsabilidades:

- Panel izquierdo: bandeja global.
- Panel derecho: lote de trabajo de la herramienta.
- Drag/drop de archivos externos.
- Carga desde explorador.
- Carga desde bandeja.
- Reordenamiento si la herramienta lo permite.
- Eliminación sin borrar archivos del disco.
- Conversión Word a PDF donde aplique.
- Señal `files_changed(list[str])`.

API compatible:

```python
workspace.paths() -> list[str]
workspace.add_paths(paths: list[str], source: str = "manual") -> None
workspace.set_paths(paths: list[str], source: str = "transfer") -> None
workspace.clear() -> None
workspace.count() -> int
workspace.is_empty() -> bool
workspace.remove_selected() -> None
workspace.files_changed
```

## UI Propuesta

### Vista Principal de Documentos

```text
┌─────────────────────────────┬──────────────────────────────────────────┐
│ Bandeja                     │ Trabajo de esta herramienta              │
│                             │                                          │
│ [Grupo: Importados]         │ [Grupo: Enviados desde Firmador]         │
│  archivo-a.pdf              │  contrato_firmado.pdf                    │
│  archivo-b.pdf              │                                          │
│                             │ [Grupo: Agregados manualmente]           │
│ [Grupo: Membretado]         │  anexos.pdf                              │
│  contrato_membretado.pdf    │                                          │
│                             │                                          │
│ Acciones:                   │ Acciones:                                │
│ Agregar seleccionados       │ Agregar archivos                          │
│ Reemplazar trabajo          │ Quitar seleccionados                      │
│ Quitar de bandeja           │ Vaciar trabajo                            │
└─────────────────────────────┴──────────────────────────────────────────┘
```

Estados visuales:

- `Original`: importado o arrastrado por el usuario.
- `Resultado`: generado por una herramienta.
- `Convertido`: Word convertido a PDF temporal.
- `En trabajo`: actualmente usado por la herramienta abierta.
- `Faltante`: el archivo ya no existe.

### Panel de Enviar a Herramienta

Antes de abrir destino, mostrar opciones compactas:

- Destino:
  - Reemplazar documentos actuales.
  - Agregar a documentos actuales.

- Bandeja:
  - Mantener bandeja.
  - Dejar solo archivos enviados.
  - Limpiar bandeja.

El usuario debe poder enviar rápido con defaults, pero tener control cuando lo necesite.

## Fases de Implementación

### Fase 0 - Auditoría y Seguridad

- [x] Inventariar todas las herramientas que usan `DocumentsCard`.
- [x] Inventariar herramientas con componentes especiales de entrada (`ImageListCard`, Word, Separador, Organizador).
- [x] Confirmar qué herramientas aceptan PDF, Word, imágenes o combinaciones.
- [x] Añadir pruebas base de `PdfTray`, `SendToToolButton` y `DocumentsCard` actuales antes de modificar.
- [x] Definir nombres finales de estados y acciones en español.

Gate:

- [x] Tests actuales pasan.
- [x] Hay lista final de herramientas por categoría de entrada.

### Fase 1 - Modelo de Bandeja Enriquecido

- [x] Extender `TrayItem` con `id`, `kind`, `batch_id`, `parent_ids`, `status`, `last_used_at`.
- [x] Mantener compatibilidad de `add_items`, `paths`, `items`, `remove`, `clear`.
- [x] Añadir operaciones nuevas: `replace_with`, `mark_in_work`, `mark_sent`, `items_by_group`.
- [x] Detectar y marcar archivos faltantes sin romper la UI.
- [x] Tests unitarios de deduplicación, limpieza y agrupación.

Gate:

- [x] Ninguna herramienta existente rompe por el cambio de modelo.
- [x] `PdfTray.paths()` conserva comportamiento anterior.

### Fase 2 - Contrato de Transferencia

- [x] Crear modelo `ToolTransfer`.
- [x] Extender `ShellContext.open_tool` para aceptar transferencia sin romper `list[str]`.
- [x] Actualizar `ShellWindow._open_tool` y `_show_tool_widget`.
- [x] Definir fallback: si una herramienta no implementa transferencia, usar `set_inputs(paths)`.
- [x] Tests de `replace`, `append`, `keep`, `replace_with_sent`, `clear`.

Gate:

- [x] Enviar outputs a herramienta destino funciona como antes con defaults.
- [x] Las políticas de bandeja son verificables por tests.

### Fase 3 - Rediseño de `SendToToolButton`

- [x] Rehacer panel de envío con opciones de destino y bandeja.
- [x] Mantener sección de herramientas sugeridas.
- [x] Mostrar contador de archivos enviados.
- [x] Mostrar origen de los archivos cuando sea posible.
- [x] Implementar defaults seguros.
- [x] Tests de panel: herramientas compatibles, defaults y políticas.

Gate:

- [x] El usuario puede enviar con un clic adicional mínimo.
- [x] Puede elegir limpiar bandeja o conservarla.

### Fase 4 - `DocumentWorkspace` Común

- [x] Crear `ui/common/document_workspace.py`.
- [x] Implementar panel izquierdo de bandeja.
- [x] Implementar panel derecho de trabajo.
- [x] Soportar `single_file`, `allow_reorder`, `show_thumbnails`, `file_filter`.
- [x] Soportar conversión Word a PDF.
- [x] Soportar drag/drop.
- [x] Mantener API compatible con `DocumentsCard`.
- [x] Tests de agregar, reemplazar, cargar desde bandeja, limpiar y reordenar.

Gate:

- [x] `DocumentWorkspace` puede sustituir a `DocumentsCard` en una herramienta sin cambios de motor.
- [x] UX diferencia bandeja y trabajo con claridad.

### Fase 5 - Migración por Grupos

Grupo A - PDF estándar:

- [x] Compresor
- [x] Protector
- [x] Reparador
- [x] Clasificador
- [x] Formularios
- [x] Marca de agua
- [x] Quitar logos
- [x] Redactor
- [x] Comparador

Grupo B - Flujo avanzado:

- [x] Firmador
- [x] Membretado
- [x] Foleador
- [x] Unir
- [x] Separador
- [x] Organizador

Grupo C - Conversión e imagen:

- [x] PDF a imágenes
- [x] PDF a Word
- [x] Word a PDF
- [x] Imágenes a PDF
- [x] Extraer imágenes
- [x] Quitar fondo
- [x] OCR

Gate:

- [x] Cada grupo pasa sus tests específicos.
- [x] La suite completa pasa tras cada grupo.

### Fase 6 - Bandeja Global Mejorada

- [x] Rediseñar `TrayPopup` para mostrar grupos.
- [x] Añadir acciones masivas: limpiar resultados, limpiar originales, quitar faltantes.
- [x] Mostrar origen y estado.
- [x] Añadir "Usar en herramienta actual" si hay herramienta activa compatible.
- [x] Tests de popup y modelo.

Gate:

- [x] La topbar deja claro cuántos archivos hay y de dónde vienen.
- [x] La bandeja global ya no es solo una lista plana.

### Fase 7 - Pulido UX y QA

- [x] Revisar textos y tooltips.
- [x] Verificar layout desktop y ventana mínima.
- [x] Verificar que no haya texto cortado.
- [x] Verificar rendimiento con 100+ documentos en bandeja.
- [x] Verificar thumbnails async.
- [x] Ejecutar suite completa.

Gate final:

- [x] `python -m pytest -q` pasa.
- [x] No hay regresiones en envío entre herramientas.
- [x] La experiencia de bandeja/trabajo es clara en al menos 5 herramientas principales.

## Criterios de Aceptación Final

- La sección de documentos separa visualmente **Bandeja** y **Trabajo**.
- Los archivos enviados desde otra herramienta aparecen diferenciados.
- El usuario puede elegir si conserva o limpia la bandeja al enviar.
- Una herramienta destino puede reemplazar o anexar documentos recibidos.
- Los archivos originales y resultados pueden convivir sin confundirse.
- La bandeja soporta grupos por origen.
- Las herramientas migradas conservan sus flujos actuales.
- La suite completa de tests pasa.

## Seguimiento Posterior

- [ ] Estabilizar el menú contextual y la copia de imágenes en Windows. En progreso.
- [ ] Evitar formatos MIME redundantes en la escritura al portapapeles.
- [ ] Reintentar de forma acotada cuando `OpenClipboard` esté ocupado.
- [ ] Añadir pruebas de menú persistente y de la ruta de reintento.

## Riesgos y Mitigaciones

- **Riesgo:** tocar muchas herramientas a la vez.  
  **Mitigación:** migración por grupos y API compatible.

- **Riesgo:** romper `set_inputs`.  
  **Mitigación:** mantener fallback con `list[str]` y tests específicos.

- **Riesgo:** UI demasiado cargada.  
  **Mitigación:** dos paneles simples, acciones primarias claras y detalles en tooltips.

- **Riesgo:** rendimiento con muchos documentos.  
  **Mitigación:** thumbnails async y render diferido.

- **Riesgo:** limpiar bandeja accidentalmente.  
  **Mitigación:** default conserva bandeja; limpieza explícita.

## Regla de Trabajo

Antes de tocar código de una fase:

1. Actualizar la bitácora con el objetivo de la sesión.
2. Marcar en este plan el task en progreso.
3. Implementar con tests enfocados.
4. Registrar resultados y pruebas ejecutadas en la bitácora.
5. Solo avanzar a la siguiente fase cuando el gate esté cumplido.
