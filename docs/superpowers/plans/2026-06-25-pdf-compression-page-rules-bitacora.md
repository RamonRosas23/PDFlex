# Bitacora - Compresion PDF por Reglas de Pagina

> **Plan maestro:** `docs/superpowers/plans/2026-06-25-pdf-compression-page-rules.md`  
> **Estado general:** Plan creado, pendiente de implementacion.  
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
| 0 | Preparacion y contratos | En progreso |
| 1 | Parser y plan efectivo | Pendiente |
| 2 | UI de reglas | Pendiente |
| 3 | Motor page-aware | Pendiente |
| 4 | Validacion y reporte | Pendiente |
| 5 | Pulido y QA | Pendiente |
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

## Pendientes Inmediatos

- Revisar estructura actual de `CompressJob`, `CompressOptions` y `CompressResult`.
- Decidir si las reglas viven en `core/pdf_compress_engine.py` o en `core/pdf_page_rules.py`.
- Implementar pruebas del parser antes de tocar UI.
- Definir mensajes de error UX para rangos invalidos y solapamientos.
- Definir estrategia exacta para recursos compartidos.

## Registro de Riesgos

| Riesgo | Estado | Nota |
| --- | --- | --- |
| Imagen compartida entre paginas con reglas distintas | Abierto | Debe resolverse con regla mas conservadora |
| UI demasiado compleja | Abierto | Mantener presets y mapa compacto |
| Ghostscript incompatible con reglas mixtas | Mitigado en plan | No usarlo como motor principal page-aware |
| Rendimiento con PDFs grandes | Abierto | Evitar miniaturas pesadas en Fase 1 |
| PDFs firmados | Mitigado en plan | Mantener politica actual de no modificar |

## Criterios para Cerrar Fase 0

- Contratos de datos definidos.
- Parser especificado.
- Ubicacion de modulos decidida.
- Primer set de tests creado.
- Bitacora actualizada con decisiones finales.
