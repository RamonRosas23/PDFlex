# Bitácora - Rediseño de Bandeja y Documentos de Trabajo

> **Plan maestro:** `docs/superpowers/plans/2026-06-23-document-workspace-bandeja.md`  
> **Estado general:** Seguimiento posterior en progreso: estabilidad de copia de imágenes en Windows.  
> **Última actualización:** 2026-06-23.

## Resumen Ejecutivo

Se documentó el rediseño del sistema de documentos para separar:

- Bandeja global de sesión.
- Lote de trabajo de cada herramienta.
- Transferencias entre herramientas.
- Políticas de limpieza/conservación de bandeja.

El objetivo es que el usuario siempre entienda qué archivos están disponibles, cuáles serán procesados y qué ocurre al enviar resultados a otra herramienta.

## Estado por Fase

| Fase | Nombre | Estado |
| --- | --- | --- |
| 0 | Auditoría y seguridad | Completada |
| 1 | Modelo de bandeja enriquecido | Completada |
| 2 | Contrato de transferencia | Completada |
| 3 | Rediseño de `SendToToolButton` | Completada |
| 4 | `DocumentWorkspace` común | Completada |
| 5 | Migración por grupos | En progreso |
| 6 | Bandeja global mejorada | Pendiente |
| 7 | Pulido UX y QA | Pendiente |

## Decisiones Iniciales

- La bandeja no debe ser la lista de trabajo de la herramienta.
- El lote de trabajo debe vivir visualmente separado de la bandeja.
- El envío entre herramientas debe preguntar, o al menos exponer, qué hacer con:
  - documentos actuales del destino;
  - bandeja global.
- Default seguro:
  - reemplazar documentos actuales del destino;
  - conservar bandeja.
- La implementación debe mantener compatibilidad con las herramientas existentes mientras se migra.

## Archivos Clave Detectados

- `shell/tray.py`: modelo y popup actual de bandeja.
- `shell/context.py`: contrato de `ShellContext.open_tool`.
- `shell/shell_window.py`: navegación y apertura de herramientas.
- `ui/common/documents_step.py`: componente actual de documentos.
- `ui/common/send_to_tool.py`: envío actual entre herramientas.
- `ui/common/process_step.py`: habilitación del botón ejecutar según documentos.
- `docs/superpowers/plans/2026-06-23-document-workspace-bandeja-auditoria.md`: inventario de entradas, herramientas y nombres finales.

## Entrada 2026-06-23 - Creación del Plan

**Objetivo de la sesión:** crear el plan maestro y la bitácora viva para iniciar el rediseño de bandeja/documentos.

**Trabajo realizado:**

- Se revisó el flujo actual:
  - `PdfTray` es lista plana.
  - `DocumentsCard` mezcla bandeja, archivos manuales y enviados.
  - `SendToToolButton` no permite elegir política de bandeja.
  - `ShellWindow._open_tool` solo pasa `list[str]` a `set_inputs`.
- Se definió arquitectura objetivo:
  - `TrayItem` enriquecido.
  - `ToolTransfer`.
  - `DocumentWorkspace`.
  - panel de envío con políticas.
- Se definieron fases, gates y criterios de aceptación.

**Archivos creados:**

- `docs/superpowers/plans/2026-06-23-document-workspace-bandeja.md`
- `docs/superpowers/plans/2026-06-23-document-workspace-bandeja-bitacora.md`

**Estado:** listo para comenzar Fase 0.

## Entrada 2026-06-23 - Fase 0 Completada

**Objetivo de la sesión:** iniciar trabajo con bitácora alineada y cerrar la auditoría de seguridad antes de tocar el modelo central.

**Trabajo realizado:**

- Se inventariaron 22 herramientas registradas en `shell/tool_registry.py`.
- Se confirmaron 17 herramientas usando `DocumentsCard`.
- Se separaron 5 herramientas con entrada especial:
  - `organizador`
  - `separador`
  - `imgs_a_pdf`
  - `quitar_fondo`
  - `word_a_pdf`
- Se documentó el contrato actual de:
  - `PdfTray`
  - `DocumentsCard`
  - `SendToToolButton`
  - `ShellWindow._open_tool`
- Se definieron nombres finales para estados, acciones de trabajo, acciones de bandeja y modos de transferencia.
- Se añadieron pruebas base del comportamiento actual antes del rediseño.

**Archivos creados:**

- `docs/superpowers/plans/2026-06-23-document-workspace-bandeja-auditoria.md`
- `tests/test_document_workspace_baseline.py`

**Pruebas añadidas:**

- `test_pdf_tray_keeps_existing_files_once_and_emits_on_changes`
- `test_documents_card_loads_tray_into_work_list_without_clearing_tray`
- `test_send_to_tool_button_and_panel_use_current_open_tool_contract`

**Resultado:** Fase 0 completada. El sistema actual queda cubierto con pruebas base y una auditoría usable para implementar Fase 1 sin perder compatibilidad.

## Entrada 2026-06-23 - Inicio de Fase 1

**Objetivo de la sesión:** enriquecer `PdfTray` sin romper el contrato actual usado por todas las herramientas.

**Alcance inmediato:**

- Extender `TrayItem` con metadatos de origen, grupo, estado y timestamps.
- Mantener intacto el comportamiento de `PdfTray.paths()` y `PdfTray.add_items(paths, source_tool)`.
- Añadir operaciones nuevas con pruebas:
  - `replace_with`
  - `mark_in_work`
  - `mark_sent`
  - `refresh_missing`
  - `items_by_group`

**Criterio de seguridad:** las pruebas base de Fase 0 deben seguir pasando después del cambio.

## Entrada 2026-06-23 - Fase 1 Completada

**Objetivo de la sesión:** enriquecer `PdfTray` manteniendo compatibilidad con todas las herramientas actuales.

**Trabajo realizado:**

- `TrayItem` ahora conserva metadatos de trazabilidad:
  - `id`
  - `kind`
  - `source_tool_id`
  - `source_tool_title`
  - `batch_id`
  - `parent_ids`
  - `status`
  - `last_used_at`
- `PdfTray.add_items(paths, source_tool)` sigue funcionando igual para llamadas existentes.
- `PdfTray.paths()` sigue devolviendo `list[str]` plano en orden.
- Se añadieron operaciones nuevas:
  - `replace_with`
  - `mark_in_work`
  - `mark_sent`
  - `refresh_missing`
  - `items_by_group`

**Archivos modificados:**

- `shell/tray.py`

**Archivos creados:**

- `tests/test_pdf_tray_enriched_model.py`

**Pruebas añadidas:**

- `test_pdf_tray_add_items_stores_enriched_metadata`
- `test_pdf_tray_replace_with_keeps_legacy_paths_contract`
- `test_pdf_tray_marks_work_sent_and_missing_statuses`
- `test_pdf_tray_items_by_group_preserves_insertion_order`

**Resultado:** Fase 1 completada. La bandeja ya soporta trazabilidad y estados, y la compatibilidad anterior quedó protegida por pruebas.

## Entrada 2026-06-23 - Inicio de Fase 2

**Objetivo de la sesión:** crear un contrato de transferencia entre herramientas que permita controlar destino y bandeja sin romper `open_tool(tool_id, list[str])`.

**Alcance inmediato:**

- Crear `ToolTransfer`.
- Ajustar tipos de `ShellContext.open_tool`.
- Enseñar a `ShellWindow` a recibir `ToolTransfer`.
- Implementar fallback a `set_inputs(paths)`.
- Probar modos:
  - `replace`
  - `append`
  - `keep`
  - `replace_with_sent`
  - `clear`

**Criterio de seguridad:** los botones actuales que siguen enviando listas deben comportarse igual.

## Entrada 2026-06-23 - Fase 2 Completada

**Objetivo de la sesión:** crear el contrato formal para enviar documentos entre herramientas con control de destino y bandeja.

**Trabajo realizado:**

- Se creó `ToolTransfer` en `shell/transfer.py`.
- `ShellContext.open_tool` ahora acepta:
  - `list[str]`
  - `ToolTransfer`
  - `None`
- `ShellWindow` ahora puede:
  - aplicar politica `keep`;
  - aplicar politica `replace_with_sent`;
  - aplicar politica `clear`;
  - entregar transferencias completas a widgets con `set_transfer`;
  - usar fallback `set_inputs(paths)` en widgets legacy;
  - limpiar inputs conocidos antes de `replace` cuando existe API de limpieza.

**Archivos modificados:**

- `shell/context.py`
- `shell/shell_window.py`

**Archivos creados:**

- `shell/transfer.py`
- `tests/test_tool_transfer.py`

**Pruebas añadidas:**

- Validacion de modos y politicas.
- Envio legacy con `list[str]`.
- Transferencia `replace` con limpieza de inputs.
- Transferencia `append` sin limpieza.
- Entrega a widget con `set_transfer`.
- Politica `replace_with_sent`.
- Politica `clear`.

**Resultado:** Fase 2 completada. El contrato existe y es compatible con los flujos actuales.

## Entrada 2026-06-23 - Inicio de Fase 3

**Objetivo de la sesión:** actualizar `SendToToolButton` para que el usuario controle destino y bandeja al enviar resultados.

**Alcance inmediato:**

- Mantener chips de herramientas compatibles y sugeridas.
- Agregar selector de destino:
  - reemplazar documentos actuales;
  - agregar a documentos actuales.
- Agregar selector de bandeja:
  - mantener bandeja;
  - dejar solo enviados;
  - limpiar bandeja.
- Enviar usando `ToolTransfer`.
- Actualizar pruebas del panel.

**Default seguro:** `replace` + `keep`.

## Entrada 2026-06-23 - Fase 3 Completada

**Objetivo de la sesión:** actualizar el panel de envio para que pueda elegir politica de destino y bandeja.

**Trabajo realizado:**

- `SendToToolPanel` ahora muestra contador de archivos.
- Se agrego selector de destino:
  - `Reemplazar`
  - `Agregar`
- Se agrego selector de bandeja:
  - `Mantener`
  - `Solo enviados`
  - `Limpiar`
- `_send_to()` ahora construye `ToolTransfer` con:
  - `source_tool_id`
  - `source_tool_title`
  - `mode`
  - `tray_policy`
  - `kind="output"`
- Se conservaron herramientas sugeridas y herramientas compatibles.

**Archivos modificados:**

- `ui/common/send_to_tool.py`
- `tests/test_document_workspace_baseline.py`

**Ajuste de estabilidad detectado durante suite:**

- `RedactionCanvas.close_doc()` ahora espera el hilo de render pendiente para evitar handles abiertos de PDF en Windows.

**Archivos adicionales modificados:**

- `ui/redactor/window.py`

**Resultado:** Fase 3 completada. El envio entre herramientas ya expone politicas de destino/bandeja y usa el contrato formal.

## Entrada 2026-06-23 - Inicio de Fase 4

**Objetivo de la sesión:** crear `DocumentWorkspace` como componente comun con bandeja visible y lote de trabajo separado.

**Alcance inmediato:**

- Crear panel izquierdo de bandeja.
- Mantener `DocumentsCard` como motor del lote de trabajo para conservar conversion Word, drag/drop y thumbnails.
- Exponer API compatible:
  - `paths`
  - `add_paths`
  - `set_paths`
  - `clear`
  - `count`
  - `is_empty`
  - `remove_selected`
  - `remove_path`
  - `reorder_paths`
  - `files_changed`
- Soportar `ToolTransfer` con `set_transfer`.

**Criterio de seguridad:** `DocumentWorkspace` debe poder sustituir a `DocumentsCard` en una herramienta sin cambiar su motor.

## Entrada 2026-06-23 - Fase 4 Completada

**Objetivo de la sesión:** crear el componente comun que separa bandeja y lote de trabajo.

**Trabajo realizado:**

- Se creo `DocumentWorkspace`.
- Panel izquierdo:
  - muestra bandeja global;
  - permite agregar seleccionados al trabajo;
  - permite reemplazar trabajo;
  - permite quitar seleccionados de bandeja;
  - permite vaciar bandeja.
- Panel derecho:
  - delega en `DocumentsCard`;
  - conserva conversion Word a PDF;
  - conserva thumbnails;
  - conserva drag/drop;
  - conserva reordenamiento.
- API compatible expuesta:
  - `paths`
  - `add_paths`
  - `set_paths`
  - `set_transfer`
  - `clear`
  - `count`
  - `is_empty`
  - `remove_selected`
  - `remove_at`
  - `remove_path`
  - `reorder_paths`
  - `set_accent`
  - `files_changed`

**Archivos creados:**

- `ui/common/document_workspace.py`
- `tests/test_document_workspace.py`

**Pruebas añadidas:**

- Cargar seleccionados desde bandeja al trabajo.
- Reemplazar trabajo con seleccionados.
- Recibir `ToolTransfer` en modo `replace` y `append`.
- Quitar seleccionados de bandeja.

**Resultado:** Fase 4 completada. El componente ya puede sustituir `DocumentsCard` por grupos.

## Entrada 2026-06-23 - Inicio de Fase 5 / Grupo A

**Objetivo de la sesión:** migrar herramientas PDF estandar de `DocumentsCard` a `DocumentWorkspace` sin cambiar motores.

**Grupo A:**

- `compresor`
- `protector`
- `reparador`
- `clasificador`
- `formularios`
- `marca_agua`
- `quitar_logos`
- `redactor`

**Criterio de seguridad:** cada ventana debe seguir usando la misma API de documentos y pasar sus pruebas actuales.

## Entrada 2026-06-23 - Fase 5 / Grupo A Completado

**Trabajo realizado:**

- `compresor` usa `DocumentWorkspace`.
- `protector` usa `DocumentWorkspace`.
- `reparador` usa `DocumentWorkspace`.
- `clasificador` usa `DocumentWorkspace`.
- `formularios` usa `DocumentWorkspace`.
- `marca_agua` usa `DocumentWorkspace`.
- `quitar_logos` usa `DocumentWorkspace`.
- `redactor` usa `DocumentWorkspace`.

**Archivos modificados:**

- `ui/compresor/window.py`
- `ui/protector/window.py`
- `ui/reparador/window.py`
- `ui/clasificador/window.py`
- `ui/formularios/window.py`
- `ui/marca_agua/window.py`
- `ui/quitar_logos/window.py`
- `ui/redactor/window.py`

**Resultado:** Grupo A migrado sin cambios de motor.

## Entrada 2026-06-23 - Fase 5 / Migraciones Directas B y C

**Objetivo de la sesión:** extender la separación visual entre bandeja y trabajo a las herramientas restantes sin alterar sus motores de procesamiento.

**Trabajo realizado:**

- Grupo B, migración directa a `DocumentWorkspace`:
  - `firmador`
  - `membretado`
  - `foleador`
  - `unir`
- Se incluyó `comparador`, detectado durante el recorrido como consumidor directo de `DocumentsCard` aunque no estaba en la primera lista del grupo.
- Grupo C, migración directa a `DocumentWorkspace`:
  - `pdf_to_imgs`
  - `pdf_to_word`
  - `ocr`
  - `extraer_imagenes`
- Se creó `FileWorkspace` para conservar los componentes especializados de imágenes y Word, aportándoles el mismo panel de bandeja y el contrato de transferencias:
  - `imgs_a_pdf`
  - `quitar_fondo`
  - `word_a_pdf`

**Archivos creados:**

- `ui/common/file_workspace.py`

**Resultado de pruebas:**

- Grupo A: `24 passed`.
- Grupo B directo y smoke: `33 passed`.
- Grupo C directo y smoke: `32 passed`.
- Especiales de imágenes y Word: `34 passed`.
- Suite completa tras la migración: `366 passed, 3 subtests passed in 24.45s`.

**Pendiente acotado:** Separador y Organizador usan flujos de trabajo propios (`un PDF con rangos` y `carriles de páginas`). Se integrarán con una entrada de bandeja adaptada a esos flujos, en vez de sustituir sus controles especializados por una lista genérica.

## Entrada 2026-06-23 - Fase 5 / Flujos Especiales Integrados

**Objetivo de la sesión:** dar a Separador y Organizador una entrada explícita desde bandeja sin perder las herramientas que hacen especiales a esos flujos.

**Trabajo realizado:**

- Separador ahora usa `DocumentWorkspace` en modo de documento único:
  - bandeja visible a la izquierda;
  - documento de trabajo a la derecha;
  - conserva su ficha de páginas, miniatura y editor de rangos;
  - delega la conversión Word a PDF al componente común.
- Se creó `TrayInputPanel` para flujos cuyo espacio de trabajo no es una lista de archivos.
- Organizador incorpora `TrayInputPanel` junto a sus carriles:
  - `Agregar` crea carriles para los PDFs seleccionados;
  - `Reemplazar` vacía carriles y carga la selección;
  - `set_transfer` respeta el modo `replace` o `append`.
- Se eliminó del Separador la ruta duplicada de conversión Word, ya cubierta por `DocumentWorkspace`.

**Archivos creados:**

- `ui/common/tray_input_panel.py`
- `tests/test_file_workspace.py`

**Pruebas añadidas:**

- Cargar el documento único de Separador desde bandeja.
- Agregar un PDF desde bandeja a los carriles de Organizador.
- Filtrar la bandeja de Word y agregar un archivo seleccionado al trabajo.

**Resultado de pruebas enfocadas:**

- `51 passed in 2.01s`.

**Validación final de Fase 5:**

- `python -m pytest -q`
  - Resultado: `369 passed, 3 subtests passed in 26.18s`.

**Estado:** Fase 5 completada. Las 22 herramientas tienen una entrada alineada con bandeja y trabajo: `DocumentWorkspace`, `FileWorkspace` o el adaptador especializado de carriles para Organizador.

## Próximo Paso

Continuar **Fase 6 - Bandeja Global Mejorada**:

- Rediseñar `TrayPopup` por grupos, origen y estado.
- Agregar acciones masivas y uso en la herramienta activa cuando sea compatible.

## Entrada 2026-06-23 - Inicio de Fase 6

**Objetivo de la sesión:** convertir el popup global de bandeja en una vista operativa que exponga grupos, procedencia, estado y acciones seguras sobre la selección.

**Alcance inmediato:**

- Agrupar visualmente por lote y origen, conservando el orden de llegada.
- Mostrar tipo y estado de cada archivo.
- Añadir acciones masivas para resultados, originales/manuales y archivos faltantes.
- Ofrecer `Usar en herramienta actual` solo para extensiones compatibles con la herramienta abierta.
- Conservar el contrato plano de `PdfTray.paths()` y cubrir el popup con pruebas Qt enfocadas.

## Entrada 2026-06-23 - Fase 6 / Implementación del Popup

**Trabajo realizado:**

- `PdfTray` ahora expone:
  - `source_counts`;
  - `clear_results`;
  - `clear_originals`;
  - `remove_missing`.
- `TrayPopup` pasó de una lista plana a grupos por lote, origen y tipo.
- Cada archivo muestra su estado (`Disponible`, `En trabajo`, `Enviado` o `Faltante`) y permite quitarlo de forma individual.
- El popup incorpora limpiezas masivas para resultados/conversiones, originales/manuales y faltantes.
- Al haber una herramienta activa, el popup permite seleccionar solo archivos compatibles y enviarlos a su lote actual.
- La topbar conserva el contador compacto y agrega un tooltip con el desglose por origen.

**Archivos modificados:**

- `shell/tray.py`
- `shell/shell_window.py`
- `tests/test_pdf_tray_enriched_model.py`

**Archivos creados:**

- `tests/test_tray_popup.py`

**Resultado de pruebas enfocadas:**

- `42 passed in 1.41s`.

**Pendiente de fase:** ejecutar la suite completa y registrar el gate.

## Entrada 2026-06-23 - Fase 6 Completada

**Validación final:**

- `python -m pytest -q`
  - Resultado: `373 passed, 3 subtests passed in 13.80s`.

**Estado:** Fase 6 completada. El contador de la topbar conserva una lectura rápida y su tooltip resume procedencias; el popup muestra los grupos y los estados sin perder acciones de limpieza o envío contextual.

## Entrada 2026-06-23 - Inicio de Fase 7

**Objetivo de la sesión:** validar el pulido final de textos, tooltips, límites de layout y comportamiento con bandejas grandes antes de declarar terminado el rediseño completo.

**Validaciones realizadas:**

- Se revisó el popup con la hoja de estilos real en render offscreen: grupos, acciones masivas y acción contextual conservan una composición sin solapamientos.
- Los encabezados de grupo pasaron a `ElidedLabel`, por lo que un origen largo se recorta visualmente sin perder el nombre completo en tooltip.
- Se añadió una prueba con 100 archivos repartidos en cuatro grupos.
- Se confirmó la cobertura existente de miniaturas asíncronas en `tests/test_thumb_async.py`.

**Resultado de pruebas enfocadas:**

- `17 passed in 0.41s`.

**Pendiente de fase:** ejecutar la suite completa final.

## Entrada 2026-06-23 - Fase 7 y Plan Completados

**Validación final:**

- `python -m pytest -q`
  - Resultado: `375 passed, 3 subtests passed in 25.21s`.

**Resultado:** el plan de rediseño queda completado. La bandeja conserva compatibilidad con los flujos anteriores, aporta trazabilidad y acciones de sesión, y cada herramienta separa la selección global de su lote de trabajo mediante el componente común o el adaptador adecuado a su flujo.

**Cierre:** no quedan tareas abiertas en este plan. Cualquier mejora futura de preferencias persistentes de envío se tratará como una iniciativa independiente.

## Entrada 2026-06-23 - Corrección Posterior / Copiar Imagen

**Objetivo de la sesión:** corregir la interacción de copiar imagen desde la previsualización cuando el clic derecho muestra una confirmación que desaparece de inmediato.

**Diagnóstico:** la acción se ejecutaba en `MouseButtonPress` y abría un `QToolTip` antes de que Qt procesara la liberación del botón derecho. No existía un menú contextual real, por lo que el feedback podía ocultarse en seguida.

**Corrección prevista:** atender el evento `ContextMenu`, que ocurre después de soltar el botón, y mostrar un menú estable con la acción explícita `Copiar imagen`.

**Implementación realizada:**

- `ImageResultsViewer` deja pasar la presión del botón derecho y atiende `QEvent.ContextMenu`.
- El menú usa `QMenu.exec()` para permanecer visible hasta elegir o cancelar.
- `Copiar imagen` se deshabilita cuando el panel no tiene una imagen válida.
- El tooltip de confirmación aparece solo tras elegir la acción y se mantiene 1.8 segundos.

**Pruebas añadidas:**

- El evento de contexto se atiende después de soltar el botón derecho.
- La presión inicial no dispara la copia ni cierra el menú potencial.

**Resultado de pruebas enfocadas:**

- `23 passed in 1.27s`.

**Hallazgo de validación completa:** la suite reveló una carrera independiente en Organizador: un hilo de miniaturas podía abrir un PDF temporal después de que la prueba llamara a `deleteLater()`, dejando un handle activo en Windows. Se corregirá el apagado explícito del hilo antes de revalidar el cambio de copiar imagen.

**Corrección adicional realizada:**

- `LaneContainer.deleteLater()` ahora detiene el worker de miniaturas de inmediato antes de diferir la destrucción del widget.
- El apagado es idempotente y conserva el gancho de destrucción existente.
- Se añadió una prueba que verifica la liberación del PDF temporal justo después de `deleteLater()`.

**Resultado combinado de pruebas enfocadas:**

- `45 passed in 1.53s`.

**Validación final de la corrección:**

- `python -m pytest -q`
  - Resultado: `377 passed, 3 subtests passed in 43.87s`.

**Estado:** corregido y validado. El menú contextual de copiar imagen se abre tras la liberación del clic derecho y permanece disponible hasta que el usuario toma una decisión.

## Registro de Pruebas

- `python -m pytest tests/test_document_workspace_baseline.py -q`
  - Resultado: `3 passed in 0.15s`
- `python -m pytest -q`
  - Resultado: `350 passed, 3 subtests passed in 16.26s`
- `python -m pytest tests/test_document_workspace_baseline.py tests/test_pdf_tray_enriched_model.py -q`
  - Resultado: `7 passed in 0.24s`
- `python -m pytest -q`
  - Resultado: `354 passed, 3 subtests passed in 23.97s`
- `python -m pytest tests/test_tool_transfer.py tests/test_pdf_tray_enriched_model.py tests/test_document_workspace_baseline.py -q`
  - Resultado: `14 passed in 0.26s`
- `python -m pytest -q`
  - Resultado: `361 passed, 3 subtests passed in 24.08s`
- `python -m pytest tests/test_document_workspace_baseline.py tests/test_tool_transfer.py -q`
  - Resultado: `11 passed in 0.22s`
- `python -m pytest tests/test_redactor_window.py::RedactorWindowTests::test_redaction_controls_follow_canvas_state -q`
  - Resultado: `1 passed in 0.31s`
- `python -m pytest -q`
  - Resultado: `362 passed, 3 subtests passed in 23.80s`
- `python -m pytest tests/test_document_workspace.py tests/test_document_workspace_baseline.py -q`
  - Resultado: `8 passed in 0.29s`
- `python -m pytest -q`
  - Resultado: `366 passed, 3 subtests passed in 17.42s`
- `python -m pytest -q`
  - Resultado: `366 passed, 3 subtests passed in 24.45s`
- `python -m pytest tests/test_separador_window.py tests/test_organizador_window.py tests/test_file_workspace.py tests/test_document_workspace.py tests/test_smoke_tools.py -q`
  - Resultado: `51 passed in 2.01s`
- `python -m pytest -q`
  - Resultado: `369 passed, 3 subtests passed in 26.18s`
- `python -m pytest tests/test_tray_popup.py tests/test_pdf_tray_enriched_model.py tests/test_thumb_async.py -q`
  - Resultado: `17 passed in 0.41s`
- `python -m pytest -q`
  - Resultado: `375 passed, 3 subtests passed in 25.21s`

## Ideas Futuras

- Recordar opcionalmente la preferencia de envío entre sesiones. No forma parte de este plan completado.

## Entrada 2026-06-23 - Seguimiento de Copia de Imágenes

**Incidente reportado:** el menú contextual de copia puede cerrarse de inmediato y Windows registra `OleSetClipboard` con `0x800401d0` al abrir el portapapeles.

**Hipótesis confirmada por código:**

- El menú se ejecuta de forma modal y temporal dentro del filtro de eventos.
- La copia publica de una vez imagen Qt, PNG y URL del archivo, lo que fuerza varios formatos OLE cuando el portapapeles puede estar ocupado por otro proceso.

**Corrección planificada:**

- Conservar un menú no modal mientras está visible.
- Publicar únicamente una imagen de píxeles al portapapeles.
- Verificar la escritura y reintentar unas pocas veces con espera corta antes de mostrar error.
- Añadir cobertura para el ciclo de vida del menú y reintentos.
