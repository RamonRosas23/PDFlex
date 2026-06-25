# Bitacora - Compresion PDF por Reglas de Pagina

> **Plan maestro:** `docs/superpowers/plans/2026-06-25-pdf-compression-page-rules.md`
> **Estado general:** Implementacion base terminada; QA final en curso.
> **Ultima actualizacion:** 2026-06-25.

## Resumen Ejecutivo

Se documenta la feature para permitir reglas de compresion por paginas o intervalos dentro de **Comprimir PDF**.

La prioridad es que el usuario pueda:

- excluir paginas sensibles;
- usar perfiles distintos por intervalos;
- mantener legibilidad en tablas, firmas y letras pequenas;
- obtener un resultado validado y explicable.

La implementacion debe ser conservadora: si una regla puede degradar una pagina protegida, la app debe conservar calidad y reportarlo.

## Estado por Fase

| Fase | Nombre | Estado |
| --- | --- | --- |
| 0 | Preparacion y contratos | Completada |
| 1 | Parser y plan efectivo | Completada |
| 2 | UI de reglas | Completada |
| 3 | Motor page-aware | Completada |
| 4 | Validacion y reporte | Completada |
| 5 | Pulido y QA | En progreso |
| 6 | Sugerencias automaticas | Pendiente |

## Decisiones Iniciales

- La primera version no debe depender de Ghostscript para reglas mixtas por pagina.
- PyMuPDF interno sera el motor principal para page-aware.
- Las reglas solapadas no se resolveran silenciosamente en Fase 1.
- Cada pagina debe tener una sola regla efectiva.
- `No comprimir` protege calidad visual, no promete bytes identicos.
- El mapa visual inicial sera compacto, sin miniaturas pesadas.
- Las sugerencias automaticas quedan para una fase posterior.

## Archivos Clave a Tocar

- `core/pdf_compress_engine.py`
- `ui/compresor/window.py`
- posible nuevo modulo: `core/pdf_page_rules.py`
- posible nuevo modulo UI: `ui/compresor/page_rules.py`
- `tests/test_pdf_compress_engine.py`
- `tests/test_compresor_window.py`
- posible nuevo test: `tests/test_pdf_page_rules.py`

## Entrada 2026-06-25 - Creacion del Plan

**Objetivo de la sesion:** dejar documentado el analisis y plan de implementacion antes de modificar el motor o la UI.

**Trabajo realizado:**

- Se definio el objetivo de reglas por pagina para Comprimir PDF.
- Se separo el alcance en fases:
  - excluir paginas;
  - perfiles por intervalo;
  - personalizacion por regla;
  - sugerencias automaticas.
- Se definio el riesgo tecnico principal:
  - recursos de imagen compartidos entre paginas.
- Se decidio que la primera implementacion debe usar PyMuPDF page-aware.
- Se definio la UX:
  - panel de reglas dentro de Perfil;
  - editor compacto;
  - mapa visual de paginas;
  - presets claros;
  - scroll y validacion de errores.
- Se definieron criterios de aceptacion y matriz de pruebas.

**Archivos creados:**

- `docs/superpowers/plans/2026-06-25-pdf-compression-page-rules.md`
- `docs/superpowers/plans/2026-06-25-pdf-compression-page-rules-bitacora.md`

**Estado:** Fase 0 iniciada. Siguiente paso: auditar `core/pdf_compress_engine.py` y definir los contratos finales de `PageCompressionRule`, parser y plan efectivo.

## Entrada 2026-06-25 - Implementacion Base

**Objetivo de la sesion:** entregar la primera version funcional de reglas por pagina con UX clara, motor page-aware y validacion confiable.

**Trabajo realizado:**

- Se creo `core/pdf_page_rules.py` con:
  - presets de regla;
  - `PageCompressionRule`;
  - `EffectivePageCompression`;
  - `PageCompressionPlan`;
  - parser de rangos `1`, `1-5`, `1,3,7-10`, `10-fin`, `pares`, `impares`, `todo`;
  - deteccion de solapamientos y errores de rango.
- Se integro `page_rules` en `CompressJob`.
- Se extendio `CompressResult` con:
  - paginas comprimibles por reglas;
  - paginas excluidas;
  - paginas personalizadas;
  - resumen de reglas;
  - advertencias de seguridad.
- Se agrego candidato page-aware en `core/pdf_compress_engine.py`:
  - usa PyMuPDF interno;
  - divide el PDF por segmentos de regla efectiva;
  - evita Ghostscript y QPDF como motor principal cuando hay reglas por pagina;
  - conserva paginas excluidas sin recomprimir imagenes;
  - valida visualmente segun la regla efectiva;
  - reporta imagenes compartidas entre reglas distintas.
- Se creo `ui/compresor/page_rules.py` con:
  - editor de reglas;
  - lista editable;
  - presets `No comprimir`, `Alta legibilidad`, `Equilibrado`, `Maxima reduccion`, `Personalizado`;
  - controles custom de DPI, umbral, JPEG, grises y validacion;
  - mapa compacto de paginas con scroll;
  - validacion inmediata de rangos, solapamientos y DPI custom.
- Se integro el panel en `ui/compresor/window.py`:
  - vive dentro del paso Perfil;
  - ocupa ancho completo en layout de dos columnas;
  - mantiene scroll en ventanas pequenas;
  - valida reglas contra todos los PDFs cargados;
  - bloquea motores incompatibles con un mensaje claro;
  - envia reglas a cada job.
- Se hizo auditoria visual offscreen en ventanas:
  - `785x652`;
  - `1180x760`;
  - `1420x860`;
  - vista scrolleada del panel de reglas.
- Se agregaron pruebas focalizadas:
  - parser y plan efectivo;
  - solapamientos;
  - reglas custom;
  - engine incompatible;
  - todas las paginas excluidas;
  - compresion por paginas permitidas;
  - imagen compartida entre reglas;
  - construccion de jobs desde UI;
  - rechazo de rangos fuera del documento;
  - rechazo de DPI custom invalido;
  - procesamiento asincrono ya existente.

**Resultado de pruebas focalizadas:**

- `python -m py_compile core\pdf_page_rules.py core\pdf_compress_engine.py ui\compresor\page_rules.py ui\compresor\window.py tests\test_pdf_page_rules.py tests\test_pdf_compress_engine.py tests\test_compresor_window.py`
- `python -m pytest tests\test_pdf_page_rules.py tests\test_pdf_compress_engine.py tests\test_compresor_window.py -q`
- Estado: `34 passed, 5 subtests passed`.

**Resultado de suite amplia:**

- `python -m pytest -q`
- Estado: `405 passed, 8 subtests passed`.

**Decisiones finales de esta entrega:**

- Las reglas por pagina requieren `Automatico` o `PyMuPDF`.
- Si todas las paginas quedan excluidas, se copia el original y se reporta.
- Si hay una imagen compartida entre paginas con reglas distintas, se aisla al reconstruir segmentos y se reporta la advertencia.
- `No comprimir` protege fidelidad visual; no promete bytes identicos.
- Las sugerencias automaticas quedan fuera de esta entrega.

**Estado:** Fases 0 a 5 completadas. Siguiente paso: limpiar temporales, revisar `git status` y cerrar con commit.

## Pendientes Inmediatos

- Eliminar artefactos temporales de auditoria visual.
- Revisar diff final y `git status`.
- Crear commit de implementacion.

## Registro de Riesgos

| Riesgo | Estado | Nota |
| --- | --- | --- |
| Imagen compartida entre paginas con reglas distintas | Mitigado | Segmentos aislados y advertencia en resultado |
| UI demasiado compleja | Mitigado | Presets, mapa compacto y scroll |
| Ghostscript incompatible con reglas mixtas | Mitigado | Bloqueado para reglas por pagina |
| Rendimiento con PDFs grandes | Mitigado inicial | Mapa sin miniaturas pesadas, maximo visual compacto |
| PDFs firmados | Mitigado en plan | Mantener politica actual de no modificar |

## Criterios para Cerrar Fase 0

- Contratos de datos definidos.
- Parser especificado.
- Ubicacion de modulos decidida.
- Primer set de tests creado.
- Bitacora actualizada con decisiones finales.
