# PLAN MAESTRO PDFlex

Roadmap vivo para construir PDFlex durante multiples iteraciones.

Este documento es la fuente de verdad para saber que existe, que falta, que esta en curso y como debe quedar cada herramienta o mejora antes de marcarla como terminada.

---

## 1. Como Usar Este Documento

- Mantener los IDs estables. No reutilizar IDs eliminados.
- Actualizar el tablero Kanban al inicio y cierre de cada iteracion.
- Cada herramienta nueva debe tener ficha de producto, ficha tecnica, checklist y criterios de aceptacion.
- Cada mejora debe tener alcance claro, riesgo estimado y pruebas esperadas.
- Marcar como `Hecho` solo cuando la UI, el motor, el registro en launcher, el flujo de resultados y las pruebas esten cerrados.
- Registrar decisiones importantes en `Historial de avance`.

### Estados Permitidos

| Estado | Uso |
| --- | --- |
| Base completada | Ya existe y sirve como punto de partida del producto. |
| Pendiente | Aun no se ha iniciado. |
| En diseno | Se esta definiendo UX, alcance o arquitectura. |
| En implementacion | Se esta construyendo codigo o documentacion. |
| En pruebas | Implementado, pendiente de validacion fuerte. |
| Hecho | Completado, probado e integrado. |
| Pausado | Detenido por dependencia externa o decision pendiente. |
| Omitido | Excluido explicitamente del roadmap activo por decision de producto. |

### Prioridades

| Prioridad | Significado |
| --- | --- |
| P0 | Critico para estabilidad, seguridad o flujo base. |
| P1 | Alto impacto para usuarios y producto. |
| P2 | Valioso, pero puede esperar. |
| P3 | Conveniente o exploratorio. |

---

## 2. Estado Actual

Herramientas actuales consideradas base del producto.

| ID | Herramienta | Estado | Descripcion | Observaciones |
| --- | --- | --- | --- | --- |
| B-001 | Firmador masivo | Base completada | Firma PDFs por lote con posicionamiento, variacion natural y anti-colision. | Base fuerte para flujos visuales e insercion de imagenes en PDF. |
| B-002 | Foleador | Base completada | Agrega numeracion secuencial con formatos configurables. | Base para marcas de texto por pagina. |
| B-003 | Separador de PDF | Base completada | Divide PDFs por rangos de paginas. | Base para manipulacion estructural de paginas. |
| B-004 | Membretado | Base completada | Superpone documentos sobre hojas membretadas. | M-005 agrega biblioteca local de membretes y permite membrete Word convertido a PDF. |
| B-005 | Unir PDFs | Base completada | Combina varios PDFs en un unico documento. | Lista principal ordenable con miniaturas nativas; sin banda visual duplicada ni enlace al Organizador visual. |
| B-006 | PDF a Imagenes | Base completada | Exporta paginas PDF como PNG, JPG o WebP. | M-007 agrega presets rapidos y rangos de paginas con layout compacto y scrollable. |
| B-007 | Imagenes a PDF | Base completada | Convierte y combina imagenes en PDF. | Base para carga y ordenamiento visual de imagenes; M-008 agrega modo escaner documental con perfiles. |
| B-008 | OCR de PDF | Base completada | Extrae texto local y exporta Word/TXT. | Base para clasificacion por contenido. |
| B-009 | Word a PDF | Base completada | Convierte DOC/DOCX a PDF usando Microsoft Word. | Recien separada como herramienta dedicada. |
| B-010 | Quitar fondo | Base completada | Genera PNG transparente desde imagenes con fondo uniforme. | M-011 agrega comparacion antes/despues sobre fondo cuadriculado. |
| B-011 | Organizador visual | Base completada | Reordena, rota, duplica, quita y extrae paginas PDF desde miniaturas. | Implementa T-001 y habilita flujos visuales futuros. |
| B-012 | Comprimir PDF | Base completada | Optimiza PDFs por perfiles con reduccion de imagenes, limpieza interna y metricas antes/despues. | Implementa T-002 y evita aumentar peso cuando el PDF ya esta optimizado. |
| B-013 | Marca de agua | Base completada | Aplica sellos de texto o imagen por lote con presets, opacidad, posicion, rotacion, paginas y preview. | Implementa T-003 y reutiliza salida temporal, visor, bandeja y envio entre herramientas. |
| B-014 | Redaccion segura | Base completada | Elimina contenido sensible con redacciones reales dibujadas manualmente sobre el PDF. | Implementa T-004 con canvas, coordenadas por pagina, apply_redactions, visor y pruebas de extraccion. |
| B-015 | Clasificador OCR | Base completada | Clasifica y renombra PDFs por contenido usando texto nativo u OCR fallback, reglas y plantillas. | Implementa T-005 con copias temporales, nombres seguros, visor y pruebas de campos. |
| B-016 | Proteger PDF | Base completada | Cifra PDFs con AES-256, contrasena de apertura opcional, contrasena de propietario y permisos granulares. | Implementa T-006 con visor autenticado, salida temporal, bandeja y pruebas de cifrado. |
| B-017 | PDF a Word | Base completada | Convierte PDFs con texto nativo u OCR fallback a DOCX editable por lote. | Implementa T-007 con preview de texto, salida temporal, bandeja y envio a Word a PDF. |
| B-018 | Extraer imagenes | Base completada | Extrae imagenes y recursos embebidos del PDF sin renderizar paginas completas. | Implementa T-008 con deduplicacion por xref, filtros de tamano, visor agrupado y pruebas. |
| B-019 | Formularios PDF | Base completada | Rellena campos AcroForm y genera PDFs editables o aplanados. | Implementa T-009; UX endurecida con captura scrollable, validacion de requeridos, radios/checkboxes robustos y pruebas ampliadas. |
| B-020 | Comparar PDFs | Base completada | Compara dos versiones de un PDF y genera un reporte visual/textual de diferencias. | Implementa T-010 con render por pagina, texto nativo normalizado, paginas agregadas/eliminadas, visor y pruebas. |
| B-021 | Reparar PDF | Base completada | Reescribe y normaliza PDFs para mejorar compatibilidad y recuperar estructuras reparables. | Implementa T-011 con limpieza, garbage, deflate, perfiles, verificacion posterior y pruebas con PDF reparado por MuPDF. |

---

## 3. Tablero Kanban

### Herramientas Nuevas

| ID | Tipo | Iniciativa | Estado | Prioridad | Iteracion | Notas |
| --- | --- | --- | --- | --- | --- | --- |
| T-001 | Herramienta nueva | Organizador visual de paginas | Hecho | P1 | I-001 | Implementado con multiples PDFs mezclados, miniaturas, rotacion, duplicado, extraccion y visor. |
| T-002 | Herramienta nueva | Comprimir / Optimizar PDF | Hecho | P1 | I-002 | Implementado con perfiles Correo, Equilibrado y Alta calidad, metricas de reduccion, fallback anti-crecimiento, visor y pruebas. |
| T-003 | Herramienta nueva | Marca de agua / Sellos | Hecho | P1 | I-003 | Implementado con texto, imagen, presets, opacidad, rotacion, posicion, rangos, preview, visor y pruebas. |
| T-004 | Herramienta nueva | Redaccion segura | Hecho | P1 | I-004 | Implementado con redacciones reales, canvas manual, paginas rotadas, eliminacion de texto verificable, visor y pruebas. |
| T-005 | Herramienta nueva | Clasificador / Renombrador por OCR | Hecho | P1 | I-005 | Implementado con texto nativo, OCR fallback, reglas configurables, plantilla de nombres, copias temporales y pruebas. |
| T-006 | Herramienta nueva | Proteger PDF | Hecho | P2 | I-006 | Implementado con AES-256, password de apertura, propietario, permisos, visor autenticado y pruebas. |
| T-007 | Herramienta nueva | PDF a Word editable | Hecho | P2 | I-007 | Implementado con texto nativo, OCR fallback, DOCX editable, preview, envio a Word a PDF y pruebas. |
| T-008 | Herramienta nueva | Extraer imagenes / recursos de PDF | Hecho | P2 | I-008 | Implementado con extraccion por xref, formato original, deduplicacion, filtros, visor agrupado y pruebas. |
| T-009 | Herramienta nueva | Formularios PDF: rellenar y aplanar | Hecho | P2 | I-009 | Implementado con campos de texto, checkbox, radio, combos/listas, exportacion editable/aplanada y pruebas. |
| T-010 | Herramienta nueva | Comparar PDFs | Hecho | P2 | I-010 | Implementado con comparacion visual/textual, sensibilidad configurable, paginas agregadas/eliminadas y reporte PDF. |
| T-011 | Herramienta nueva | Reparar / Normalizar PDF | Hecho | P2 | I-011 | Implementado con perfiles de normalizacion, deteccion `is_repaired`, fallback de reconstruccion y pruebas. |
| T-012 | Herramienta nueva | PDF/A o archivo legal | Omitido | P3 | Excluido | Omitido del roadmap activo por decision de producto. |

### Mejoras Por Herramienta Actual

| ID | Tipo | Iniciativa | Estado | Prioridad | Iteracion | Notas |
| --- | --- | --- | --- | --- | --- | --- |
| M-001 | Mejora | Firmador: perfiles de firma | Omitido | P1 | Excluido | Omitido junto con mejoras de Firmador. |
| M-002 | Mejora | Firmador: firma por reglas | Omitido | P1 | Excluido | Omitido junto con mejoras de Firmador. |
| M-003 | Mejora | Foleador: QR/codigo de barras | Omitido | P2 | Excluido | Omitido junto con mejoras de Foleador. |
| M-004 | Mejora | Separador: separar por texto/bookmarks | Omitido | P1 | Excluido | Omitido junto con mejoras de Separador. |
| M-005 | Mejora | Membretado: biblioteca de membretes | Hecho | P2 | I-016 | Biblioteca local de membretes frecuentes, carga desde biblioteca y membrete PDF/Word. |
| M-006 | Mejora | Unir PDFs: miniaturas antes de unir | Hecho | P1 | I-012 | Revisado: se retiro la banda visual duplicada; queda lista principal ordenable con miniaturas nativas. |
| M-007 | Mejora | PDF a Imagenes: rangos y presets | Hecho | P2 | I-015 | Implementado con presets de formato/DPI/calidad, rangos y layout compacto scrollable para evitar cortes. |
| M-008 | Mejora | Imagenes a PDF: modo escaner documental | Hecho | P1 | I-013 | Implementado con perfiles Desactivado, Documento limpio, Foto de hoja y Alto contraste. |
| M-009 | Mejora | OCR: busqueda y exportacion CSV | Pendiente | P2 | Por definir | Revision y analisis de resultados. |
| M-010 | Mejora | Word a PDF: Office a PDF | Pendiente | P2 | Por definir | Extender a Excel y PowerPoint. |
| M-011 | Mejora | Quitar fondo: preview antes/despues | Hecho | P1 | I-014 | Implementado con visor comparativo original/PNG transparente y fondo cuadriculado. |

---

## 4. Proximo Bloque: Herramientas Nuevas Prioridad 1

Estas cinco iniciativas son el bloque inicial de crecimiento del producto.

---

### T-001 - Organizador Visual De Paginas

**Estado:** Hecho  
**Prioridad:** P1  
**Tipo:** Herramienta nueva  
**Valor principal:** Dar control visual total sobre paginas antes o despues de cualquier otro flujo.

#### Objetivo

Crear una herramienta para cargar uno o varios PDFs y manipular sus paginas visualmente: reordenar, rotar, eliminar, duplicar, extraer y exportar un PDF final.

#### Usuario / Valor

- Usuario administrativo que recibe PDFs largos y necesita reorganizarlos.
- Usuario que necesita quitar paginas sobrantes antes de firmar, unir, foliar u OCR.
- Usuario que arma expedientes desde multiples documentos.

#### Flujo UX Esperado

1. Cargar uno o varios PDFs.
2. Mostrar una grilla de miniaturas con numero de documento y pagina.
3. Permitir seleccionar una o varias paginas.
4. Acciones principales:
   - Reordenar arrastrando.
   - Rotar izquierda/derecha.
   - Eliminar.
   - Duplicar.
   - Extraer seleccion.
5. Mostrar resumen de salida.
6. Procesar y abrir visor de resultado.
7. Permitir `Guardar como`, `Guardar todo`, enviar a otra herramienta y agregar a bandeja.

#### MVP

- Carga multiple de PDFs.
- Miniaturas de paginas.
- Reordenamiento por drag and drop.
- Rotacion de paginas seleccionadas.
- Eliminacion de paginas seleccionadas.
- Exportacion de un PDF final.
- Resultado temporal con visor PDF comun.

#### Arquitectura Sugerida

- UI: nueva carpeta `ui/organizador/`.
- Motor core: `core/page_organizer_engine.py`.
- Modelo:
  - `PageRef`: path origen, indice pagina, rotacion acumulada, id estable.
  - `OrganizerJob`: lista ordenada de `PageRef`, output path.
  - `OrganizerResult`: output path, success, error, total pages.
- Base tecnica:
  - PyMuPDF para copiar paginas, rotar y guardar.
  - Reusar `GenericPdfViewer` para resultado.
  - Reusar patrones de `DocumentsCard`, `ProcessStep` y `SendToToolButton`.

#### Edge Cases

- PDF sin paginas.
- PDF protegido o corrupto.
- Rotaciones acumuladas mayores a 360.
- Muchas paginas con miniaturas pesadas.
- Duplicados del mismo archivo.
- El usuario elimina todas las paginas.

#### Pruebas

- Reordena paginas y verifica orden textual con PyMuPDF.
- Rota pagina y verifica metadata de rotacion.
- Elimina paginas y conserva el resto.
- Duplica pagina y aumenta conteo.
- Maneja error por PDF invalido sin bloquear UI.
- Smoke test de ventana en offscreen.

#### Criterios De Aceptacion

- El PDF final respeta exactamente el orden visual.
- Ninguna accion destruye archivos originales.
- El resultado se crea en temporal y se conserva con `Guardar como`.
- El boton de ejecutar solo se habilita con al menos una pagina valida.
- La herramienta aparece en launcher y acepta PDFs desde bandeja/envio.

#### Checklist

- [x] Definir modelo de pagina y estado UI.
- [x] Crear motor de organizacion.
- [x] Crear grilla visual de miniaturas.
- [x] Implementar acciones de pagina.
- [x] Integrar procesamiento y visor de resultado.
- [x] Registrar herramienta en `tool_registry`.
- [x] Agregar pruebas unitarias del motor.
- [x] Agregar pruebas de ventana.
- [x] Validar flujo manual con PDFs reales.

---

### T-002 - Comprimir / Optimizar PDF

**Estado:** Hecho  
**Prioridad:** P1  
**Tipo:** Herramienta nueva  
**Valor principal:** Reducir peso de PDFs para correo, archivo y carga en portales.

#### Objetivo

Crear una herramienta para optimizar PDFs por lote con perfiles simples y comprensibles.

#### Usuario / Valor

- Usuario que necesita enviar PDFs por correo.
- Usuario que sube documentos a sistemas con limite de MB.
- Usuario que quiere reducir peso sin aprender parametros tecnicos.

#### Flujo UX Esperado

1. Cargar PDFs.
2. Elegir perfil:
   - Correo: maxima reduccion razonable.
   - Equilibrado: buen balance entre peso y legibilidad.
   - Alta calidad: reduccion ligera.
3. Ver resumen con peso total de entrada y perfil elegido.
4. Procesar.
5. Ver lista de resultados con peso antes/despues y porcentaje reducido.

#### MVP

- Tres perfiles fijos.
- Procesamiento por lote.
- Salida temporal por documento.
- Visor de PDFs optimizados.
- Metadatos de peso antes/despues.

#### Arquitectura Sugerida

- UI: `ui/compresor/`.
- Motor core: `core/pdf_compress_engine.py`.
- Modelo:
  - `CompressProfile`: id, label, image quality, dpi target, deflate.
  - `CompressJob`: pdf path, output path, profile.
  - `CompressResult`: input bytes, output bytes, ratio, success, error.
- Base tecnica:
- PyMuPDF para reescritura, garbage, deflate.
- PyMuPDF `rewrite_images` para bajar DPI/calidad en imagenes grandes.
- Guardado con limpieza, deflate, object streams y fallback que conserva el original si la optimizacion aumenta el peso.

#### Edge Cases

- PDF ya optimizado que no reduce.
- PDF escaneado enorme.
- PDF con imagenes transparentes.
- PDF con formularios o anotaciones.
- Output mas grande que input.
- Archivos con permisos o bloqueos.

#### Pruebas

- PDF con imagen grande reduce peso en perfil correo.
- PDF simple no falla aunque reduzca poco.
- Resultado no queda en cero bytes.
- Nombre de salida respeta sufijo global.
- Errores parciales por archivo no cancelan todo el lote.

#### Criterios De Aceptacion

- El usuario puede comparar peso antes/despues.
- La herramienta nunca reemplaza el original.
- Si el output pesa mas, se muestra aviso claro.
- Los resultados se pueden guardar y enviar a otras herramientas PDF.

#### Checklist

- [x] Definir perfiles finales.
- [x] Implementar motor base con PyMuPDF.
- [x] Agregar medicion de peso y ratio.
- [x] Crear UI de perfil y resumen.
- [x] Integrar visor de resultado.
- [x] Registrar herramienta.
- [x] Agregar pruebas con PDFs sinteticos.
- [x] Validar con PDF sintetico pesado tipo escaneo.

---

### T-003 - Marca De Agua / Sellos

**Estado:** Hecho  
**Prioridad:** P1  
**Tipo:** Herramienta nueva  
**Valor principal:** Agregar sellos visuales y marcas repetibles a documentos por lote.

#### Objetivo

Crear una herramienta para aplicar texto o imagen como marca de agua/sello en una o varias paginas de cada PDF.

#### Usuario / Valor

- Usuario que marca documentos como confidenciales, pagados, recibidos o copia.
- Usuario que necesita sellar lotes de expedientes.
- Usuario que usa logos o imagenes institucionales.

#### Flujo UX Esperado

1. Cargar PDFs.
2. Elegir tipo:
   - Texto.
   - Imagen.
3. Elegir preset o configurar manualmente.
4. Ajustar posicion, opacidad, rotacion, tamano y paginas.
5. Previsualizar una pagina.
6. Procesar lote.
7. Revisar PDFs resultantes.

#### MVP

- Marcas de texto.
- Marcas de imagen/logo.
- Presets: Confidencial, Copia, Pagado, Recibido.
- Posiciones predefinidas: centro, superior izquierda/centro/derecha e inferior izquierda/centro/derecha.
- Opacidad, rotacion y tamano.
- Aplicar a todas las paginas, primera, ultima o rango personalizado.
- Preview basico de pagina antes de procesar.
- Resultado temporal con visor.

#### Arquitectura Sugerida

- UI: `ui/marca_agua/`.
- Motor core: `core/watermark_engine.py`.
- Modelo:
  - `WatermarkOptions`: tipo, texto/imagen, opacidad, angulo, posicion, tamano y paginas.
  - `WatermarkJob`: PDF origen, PDF salida y opciones.
  - `WatermarkResult`: salida, estado, error, paginas totales, paginas selladas y metadatos.
- Base tecnica:
  - PyMuPDF `insert_text` con opacidad real para texto.
  - PyMuPDF `insert_image` con preprocesamiento Pillow para imagen, opacidad y rotacion.
  - Preview generado desde una pagina temporal con el mismo motor.

#### Edge Cases

- Paginas con rotacion.
- Distintos tamanos de pagina en el mismo PDF.
- Texto muy largo.
- Imagen sin transparencia.
- Rango de paginas invalido.
- Marca que sale del area visible.

#### Pruebas

- Aplica texto en todas las paginas.
- Aplica solo rango seleccionado.
- Respeta opacidad y rotacion.
- Maneja paginas rotadas.
- Nombres de salida con sufijo configurable.

#### Criterios De Aceptacion

- La marca queda visible y dentro de pagina.
- Los presets funcionan sin configuracion extra.
- El preview representa fielmente el resultado.
- El flujo por lote maneja errores parciales.

#### Checklist

- [x] Definir presets.
- [x] Implementar motor de texto.
- [x] Implementar motor de imagen.
- [x] Implementar seleccion de paginas.
- [x] Crear preview basico.
- [x] Registrar herramienta.
- [x] Agregar pruebas unitarias y smoke UI.

---

### T-004 - Redaccion Segura

**Estado:** Hecho  
**Prioridad:** P1  
**Tipo:** Herramienta nueva  
**Valor principal:** Ocultar datos sensibles de forma irreversible y confiable.

#### Objetivo

Crear una herramienta para censurar informacion sensible en PDFs aplicando redacciones reales, no solo rectangulos visuales encima.

#### Usuario / Valor

- Usuario que comparte expedientes con datos personales.
- Usuario que debe ocultar RFC, CURP, domicilios, cuentas, firmas o montos.
- Usuario que necesita confianza de que el texto no se puede copiar despues.

#### Flujo UX Esperado

1. Cargar PDF.
2. Ver pagina en visor interactivo.
3. Dibujar rectangulos de redaccion.
4. Navegar paginas y agregar varias redacciones.
5. Previsualizar areas marcadas.
6. Aplicar redaccion segura.
7. Revisar PDF final.

#### MVP

- Un PDF por sesion.
- Redaccion manual con rectangulos.
- Aplicar redacciones reales con PyMuPDF.
- Exportar PDF final.
- Preview con overlays antes de procesar.

#### Arquitectura Sugerida

- UI: `ui/redactor/`.
- Motor core: `core/redaction_engine.py`.
- Modelo:
  - `RedactionRect`: pagina y rectangulo normalizado en coordenadas de vista.
  - `RedactionOptions`: color de relleno y soporte de imagenes/graficos.
  - `RedactionJob`: PDF origen, PDF salida, rectangulos y opciones.
  - `RedactionResult`: salida, estado, error, paginas y conteo de redacciones.
- Base tecnica:
  - PyMuPDF `add_redact_annot` y `apply_redactions`.
  - `PDF_REDACT_TEXT_REMOVE` para eliminar texto real.
  - `PDF_REDACT_IMAGE_PIXELS` para limpiar pixeles de imagen dentro del area.
  - Transformacion display -> PDF para paginas rotadas.

#### Edge Cases

- Usuario no agrega ninguna redaccion.
- Paginas rotadas.
- PDF escaneado sin texto.
- Redaccion sobre imagen y texto.
- Redaccion fuera de pagina.
- Archivo protegido.

#### Pruebas

- Texto redactado no aparece en extraccion posterior.
- Rectangulo visual existe en output.
- Varias paginas con redacciones.
- Pagina rotada mantiene coordenadas correctas.
- Sin redacciones muestra validacion.

#### Criterios De Aceptacion

- El texto redactado no se puede seleccionar ni extraer.
- No se modifica el original.
- La UI advierte que la operacion es irreversible sobre el archivo generado.
- El resultado queda listo para guardar o enviar.

#### Checklist

- [x] Investigar comportamiento exacto de PyMuPDF con texto e imagenes.
- [x] Crear modelo de cajas por pagina.
- [x] Implementar canvas de seleccion.
- [x] Implementar motor de redaccion segura.
- [x] Agregar pruebas de extraccion de texto post-redaccion.
- [x] Registrar herramienta.
- [x] Validar con PDFs sinteticos de texto y paginas rotadas.

---

### T-005 - Clasificador / Renombrador Por OCR

**Estado:** Hecho  
**Prioridad:** P1  
**Tipo:** Herramienta nueva  
**Valor principal:** Automatizar orden y nombres de documentos usando contenido real.

#### Objetivo

Crear una herramienta que lea texto nativo u OCR y permita clasificar/renombrar documentos por reglas.

#### Usuario / Valor

- Usuario con lotes grandes de facturas, contratos, identificaciones o expedientes.
- Usuario que necesita nombres consistentes sin abrir cada archivo.
- Usuario que ya usa OCR y quiere convertir texto en accion.

#### Flujo UX Esperado

1. Cargar PDFs.
2. Elegir plantilla de renombrado.
3. Definir reglas o campos:
   - RFC.
   - Fecha.
   - Folio.
   - Cliente.
   - Tipo de documento.
4. Ejecutar analisis.
5. Generar copias temporales con nombre sugerido.
6. Revisar resultados en visor y guardar/copiar por lote.

#### MVP

- Leer texto nativo si existe.
- Usar OCR existente cuando una pagina no tenga texto nativo.
- Reglas configurables por tipo: `Tipo=keyword, keyword`.
- Extraccion de RFC, fecha, folio, cliente, tipo y original.
- Plantilla de nombre con placeholders: `{tipo}`, `{rfc}`, `{fecha}`, `{folio}`, `{cliente}`, `{original}`.
- Copia temporal por PDF con nombre seguro y visor de resultados.

#### Arquitectura Sugerida

- UI: `ui/clasificador/`.
- Motor core: `core/document_classifier_engine.py`.
- Reusar:
  - `core.ocr_engine` para obtener texto.
  - `core.output_paths` y `core.output_naming` para nombres seguros.
- Modelo:
  - `ClassificationRule`: tipo y keywords.
  - `ClassifierConfig`: plantilla, reglas, max pages, OCR fallback y sufijo.
  - `ClassifierJob`: PDF origen, output dir y config.
  - `ClassifierResult`: campos detectados, metodo, output path, success/error.

#### Edge Cases

- Documento sin texto reconocible.
- Campos duplicados.
- RFC o fecha ambiguos.
- Nombres repetidos.
- Caracteres invalidos en nombre.
- Plantilla incompleta o placeholders faltantes.

#### Pruebas

- Extrae RFC desde texto nativo.
- Extrae fecha en formatos comunes.
- Genera nombre seguro.
- Resuelve duplicados.
- Usa fallback cuando faltan campos.
- Construye jobs desde UI.

#### Criterios De Aceptacion

- Ningun archivo original se renombra directamente.
- El usuario revisa resultados antes de usar Guardar como/Guardar todo.
- Los nombres finales son validos en Windows.
- Los resultados se pueden guardar por lote.

#### Checklist

- [x] Definir reglas MVP.
- [x] Crear motor de extraccion de campos.
- [x] Integrar OCR/texto nativo.
- [x] Implementar guardado/copia temporal con nombres finales.
- [x] Agregar pruebas de reglas y nombres.
- [x] Registrar herramienta.

#### Post-MVP

- Crear tabla editable de revision fina con confianza, avisos y correccion manual antes de guardar.

---

## 5. Backlog De Herramientas Nuevas

### T-006 - Proteger PDF

- **Estado:** Hecho
- **Prioridad:** P2
- **Objetivo:** Agregar contrasena y permisos de impresion/copia/edicion.
- **MVP:** cifrar PDF con AES-256, password de apertura opcional, password de propietario y permisos configurables.
- **Pruebas clave:** PDF requiere password al abrir; visor autentica resultados protegidos; permisos configurados; password vacia no permitida.
- **Entregado:** `core/pdf_protect_engine.py`, `ui/protector/`, registro en launcher, salida temporal, bandeja y envio entre herramientas.

### T-007 - PDF A Word Editable

- **Estado:** Hecho
- **Prioridad:** P2
- **Objetivo:** Exportar PDFs con texto nativo u OCR a DOCX editable.
- **MVP:** texto por paginas con estructura simple, conservacion de texto nativo, OCR fallback y exportacion DOCX.
- **Pruebas clave:** texto aparece en DOCX; nombres duplicados se resuelven; ventana construye jobs; registry expone la herramienta.
- **Entregado:** `core/pdf_to_word_engine.py`, `ui/pdf_to_word/`, preview de texto reutilizando resultados OCR, salida temporal, bandeja y envio a `Word a PDF`.

### T-008 - Extraer Imagenes / Recursos De PDF

- **Estado:** Hecho
- **Prioridad:** P2
- **Objetivo:** Extraer imagenes embebidas sin renderizar paginas completas.
- **MVP:** exportar imagenes originales por documento, agrupadas por PDF origen.
- **Pruebas clave:** extrae cantidad correcta; conserva formato cuando es posible; maneja PDFs sin imagenes; deduplica recursos repetidos.
- **Entregado:** `core/pdf_extract_images_engine.py`, `ui/extraer_imagenes/`, visor de imagenes con metadatos, salida temporal, bandeja y envio a herramientas compatibles.

### T-009 - Formularios PDF: Rellenar Y Aplanar

- **Estado:** Hecho
- **Prioridad:** P2
- **Objetivo:** Completar campos PDF y generar version aplanada.
- **MVP:** detectar campos AcroForm, editar valores por tipo, exportar PDF editable o aplanado y preservar originales.
- **Pruebas clave:** deteccion de texto/checkbox/listas; valores visibles; campos aplanados con `bake(widgets=True)`; salida editable opcional; PDF sin formularios muestra aviso claro.
- **Entregado:** `core/pdf_form_engine.py`, `ui/formularios/`, registro en launcher, salida temporal, visor de PDF, bandeja y envio entre herramientas.

### T-010 - Comparar PDFs

- **Estado:** Hecho
- **Prioridad:** P2
- **Objetivo:** Detectar diferencias entre dos versiones de un documento.
- **MVP:** comparar por render de pagina, comparar texto nativo normalizado y generar reporte PDF con paginas afectadas.
- **Pruebas clave:** detecta cambio visual; detecta cambio textual; maneja paginas agregadas; reporte sin diferencias; registry expone la herramienta.
- **Entregado:** `core/pdf_compare_engine.py`, `ui/comparador/`, registro en launcher, salida temporal, visor de PDF, bandeja y envio entre herramientas.

### T-011 - Reparar / Normalizar PDF

- **Estado:** Hecho
- **Prioridad:** P2
- **Objetivo:** Reescribir PDFs problematicos para mejorar compatibilidad.
- **MVP:** abrir, reescribir y verificar PDFs con limpieza, garbage, deflate y perfiles de compatibilidad.
- **Pruebas clave:** PDF corrupto recuperable se abre y se marca como reparado; PDF normal no pierde paginas ni modifica original; ruta de salida igual se rechaza; errores claros; registry expone la herramienta.
- **Entregado:** `core/pdf_repair_engine.py`, `ui/reparador/`, registro en launcher, salida temporal, visor de PDF, bandeja y envio entre herramientas.

### T-012 - PDF/A O Archivo Legal

- **Estado:** Omitido
- **Prioridad:** P3
- **Objetivo:** Preparar documentos para conservacion y archivo.
- **MVP:** validar requisitos basicos y generar reporte.
- **Pruebas clave:** reporte de cumplimiento; advertencias claras; no prometer certificacion si no se valida formalmente.
- **Decision:** Excluido del roadmap activo; no se implementara en este bloque.

---

## 6. Mejoras Por Herramienta Actual

### B-001 - Firmador Masivo

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-001 | Perfiles de firma | P1 | Omitido | Excluido del roadmap activo. |
| M-002 | Firma por reglas | P1 | Omitido | Excluido del roadmap activo. |
| M-012 | Vista antes/despues | P2 | Omitido | Excluido del roadmap activo. |
| M-013 | Firma digital criptografica | P3 | Omitido | Excluido del roadmap activo. |

### B-002 - Foleador

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-003 | QR/codigo de barras | P2 | Omitido | Excluido del roadmap activo. |
| M-014 | Importar consecutivos desde CSV/Excel | P2 | Omitido | Excluido del roadmap activo. |
| M-015 | Reinicio por seccion | P2 | Omitido | Excluido del roadmap activo. |

### B-003 - Separador De PDF

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-004 | Separar por texto/bookmarks | P1 | Omitido | Excluido del roadmap activo. |
| M-016 | Separar cada N paginas | P2 | Omitido | Excluido del roadmap activo. |
| M-017 | Plantillas de separacion | P2 | Omitido | Excluido del roadmap activo. |

### B-004 - Membretado

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-005 | Biblioteca de membretes | P2 | Hecho | Biblioteca local con copia segura del PDF, reutilizacion desde UI y soporte de membrete Word convertido a PDF. |
| M-018 | Reglas primera pagina/resto | P2 | Pendiente | Aplicar membretes distintos segun pagina. |
| M-019 | Preview lado a lado | P3 | Pendiente | Comparar original y membretado. |

### B-005 - Unir PDFs

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-006 | Miniaturas antes de unir | P1 | Hecho | Lista principal ordenable con miniaturas nativas y resumen claro; sin duplicar el Organizador visual dentro de Unir. |
| M-020 | Portada automatica | P2 | Pendiente | Crear portada de lote. |
| M-021 | Indice con marcadores | P2 | Pendiente | Navegacion automatica por documento. |
| M-022 | Normalizar tamanos | P2 | Pendiente | Homogeneizar paginas al unir. |

### B-006 - PDF A Imagenes

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-007 | Rangos y presets | P2 | Hecho | Presets rapidos y exportacion de paginas especificas, incluyendo `final`, pares e impares, en un layout compacto con scroll. |
| M-023 | Estimacion de peso final | P3 | Pendiente | Mostrar tamano aproximado antes de procesar. |
| M-024 | Nombres avanzados | P2 | Pendiente | Plantillas tipo `{doc}_p{page:03}`. |

### B-007 - Imagenes A PDF

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-008 | Modo escaner documental | P1 | Hecho | Recorte de bordes claros, enderezado leve, contraste documental y perfil de alto contraste. |
| M-025 | Correccion automatica de orientacion | P2 | Pendiente | Girar fotos de hojas de forma inteligente. |
| M-026 | Blanco y negro optimizado | P2 | Pendiente | Reducir peso y mejorar legibilidad. |

### B-008 - OCR De PDF

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-009 | Busqueda y exportacion CSV | P2 | Pendiente | Buscar en resultados y exportar resumen. |
| M-027 | Cola con reintentos | P2 | Pendiente | Robustecer lotes largos. |
| M-028 | Renombrado por contenido | P1 | Hecho | Cubierto por T-005; queda como mejora futura la tabla editable con confianza/avisos. |

### B-009 - Word A PDF

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-010 | Office a PDF | P2 | Pendiente | Extender a Excel y PowerPoint. |
| M-029 | Unir convertidos al final | P2 | Pendiente | Opcion para generar un solo PDF. |
| M-030 | Errores parciales por archivo | P1 | Pendiente | No abortar todo el lote si un documento falla. |
| M-031 | Mantener estructura relativa | P3 | Pendiente | Conservar carpetas al guardar lotes. |

### B-010 - Quitar Fondo

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-011 | Preview antes/despues | P1 | Hecho | Comparacion lado a lado original/resultado con PNG sobre fondo cuadriculado. |
| M-032 | Recorte automatico al contenido | P2 | Pendiente | Eliminar margenes transparentes. |
| M-033 | Presets firma/sello/logo | P2 | Pendiente | Configuraciones rapidas por tipo de imagen. |
| M-034 | Colorizar despues de quitar fondo | P2 | Pendiente | Llevar opcion del Firmador a herramienta independiente. |

---

## 7. Criterios Globales De Calidad

Estos criterios aplican a toda herramienta nueva o mejora importante.

### UX Y Flujo

- El launcher debe mantenerse compacto, buscable y escalable; las herramientas principales aparecen primero y el orden inteligente se basa en uso local.
- La primera pantalla debe ser la herramienta usable, no una landing page.
- Cada herramienta debe seguir el patron de pasos de PDFlex:
  - Entrada.
  - Opciones.
  - Procesar.
  - Resultados.
- Debe soportar drag and drop cuando aplique.
- Debe ofrecer validaciones claras antes de procesar.
- Los botones deben usar iconos consistentes de `ui.common.icons`.
- Los textos deben ser breves, accionables y no explicar obviedades.
- La UI debe mantener consistencia con `PipelineWindow`, `DocumentsCard`, `ProcessStep` y visores comunes.

### Salidas Y Nombres

- Nunca modificar archivos originales.
- Guardar resultados primero en temporal con `make_run_dir`.
- Conservar resultados mediante `Guardar como` o `Guardar todo`.
- Respetar el ajuste global de sufijo de herramienta cuando aplique.
- Usar `core.output_paths` y `core.output_naming` para nombres seguros.
- Resolver duplicados sin sobrescribir.

### Bandeja Y Envio Entre Herramientas

- Todo resultado PDF debe agregarse a bandeja cuando tenga sentido.
- Las herramientas con resultados compatibles deben usar `SendToToolButton`.
- `input_extensions` en `ToolDescriptor` debe estar correcto para que el envio sea confiable.
- Herramientas de imagen deben declarar extensiones de imagen.
- Herramientas PDF deben declarar `.pdf`.

### Procesamiento Y Errores

- Procesar trabajos largos en `QThread` o proceso aislado.
- Permitir cancelacion cuando sea tecnicamente segura.
- Manejar errores parciales por documento cuando el motor lo permita.
- Mostrar resumen de exitos y errores al finalizar.
- Liberar handles de PDFs antes de sobrescribir o guardar.

### Pruebas

- Motor core con pruebas unitarias.
- Prueba de nombres de salida cuando aplique.
- Smoke test de ventana en `QT_QPA_PLATFORM=offscreen`.
- Pruebas de edge cases principales.
- No marcar `Hecho` si solo se probo manualmente.

### Rendimiento

- Miniaturas y previews deben ser adaptativos para no consumir memoria excesiva.
- PDFs grandes deben procesarse sin congelar UI.
- Evitar renderizar paginas a DPI alto salvo que el usuario lo pida.
- En lotes grandes, emitir progreso por documento y por etapa.

### Seguridad Y Confianza

- Herramientas destructivas sobre contenido, como Redaccion segura, deben explicar el efecto antes de procesar.
- No prometer validez legal si no hay certificacion o firma digital real.
- OCR y procesamiento documental deben ser locales salvo decision explicita contraria.

---

## 8. Definicion De Hecho

Una iniciativa se marca como `Hecho` solo si cumple:

- [ ] Esta registrada en `shell/tool_registry.py` si es herramienta nueva.
- [ ] Aparece en el launcher en la categoria correcta y respeta el orden editorial/uso frecuente.
- [ ] Tiene flujo completo de entrada, opciones, proceso y resultados.
- [ ] No modifica originales.
- [ ] Usa temporal y visor/resultados reutilizables cuando aplique.
- [ ] Maneja validaciones y errores.
- [ ] Tiene pruebas unitarias del motor.
- [ ] Tiene smoke test de UI si incluye ventana.
- [ ] Pasa la suite relevante.
- [ ] El MD se actualizo con estado, notas e historial.

---

## 9. Historial De Avance

| Fecha | Iteracion | Cambio | Estado |
| --- | --- | --- | --- |
| 2026-06-05 | I-000 | Creacion del plan maestro y definicion del Top 5 de herramientas nuevas. | En implementacion |
| 2026-06-05 | Base | Word a PDF y Quitar fondo quedan reconocidas como herramientas base completadas. | Base completada |
| 2026-06-05 | I-001 | T-001 Organizador visual implementado con motor, UI, registro, resultados y pruebas. | Hecho |
| 2026-06-05 | I-002 | T-002 Comprimir PDF implementado con perfiles, metricas antes/despues, fallback anti-crecimiento, visor y pruebas. | Hecho |
| 2026-06-05 | I-003 | T-003 Marca de agua implementada con sellos de texto e imagen, presets, preview, rangos, visor y pruebas. | Hecho |
| 2026-06-05 | I-004 | T-004 Redaccion segura implementada con canvas manual, redaccion real PyMuPDF, soporte de paginas rotadas y pruebas de extraccion. | Hecho |
| 2026-06-05 | I-005 | T-005 Clasificador OCR implementado con reglas, plantilla, extraccion de campos, OCR fallback, copias renombradas y pruebas. | Hecho |
| 2026-06-06 | I-006 | T-006 Proteger PDF implementado con cifrado AES-256, permisos, visor autenticado y pruebas de password. | Hecho |
| 2026-06-06 | I-007 | T-007 PDF a Word implementado con motor dedicado, DOCX editable, preview de texto, OCR fallback y pruebas. | Hecho |
| 2026-06-06 | I-008 | T-008 Extraer imagenes implementado con recursos embebidos, deduplicacion xref, filtros, visor agrupado y pruebas. | Hecho |
| 2026-06-06 | I-009 | T-009 Formularios PDF implementado con deteccion de campos, captura por tipo, aplanado real y pruebas. | Hecho |
| 2026-06-06 | UX-002 | Formularios PDF robustecido: captura por filas scrollables, validacion de campos requeridos, soporte fuerte para estados de botones y metadata de campos. | Hecho |
| 2026-06-06 | I-010 | T-010 Comparar PDFs implementado con reporte visual/textual, sensibilidad configurable y pruebas de diferencias. | Hecho |
| 2026-06-06 | I-011 | T-011 Reparar PDF implementado con reescritura estructural, deteccion de reparacion, fallback y pruebas. | Hecho |
| 2026-06-06 | Alcance | T-012 y mejoras de Firmador, Foleador y Separador quedan omitidas del roadmap activo. | Omitido |
| 2026-06-06 | I-012 | M-006 Unir PDFs revisado con lista principal ordenable, miniaturas nativas y resumen claro; se evita duplicar el Organizador visual. | Hecho |
| 2026-06-06 | I-013 | M-008 Imagenes a PDF mejorado con modo escaner documental, perfiles de recorte/enderezado/contraste y pruebas. | Hecho |
| 2026-06-06 | I-014 | M-011 Quitar fondo mejorado con preview antes/despues, fondo cuadriculado y pruebas de visor comparativo. | Hecho |
| 2026-06-06 | I-015 | M-007 PDF a Imagenes mejorado con presets, rangos de paginas, layout compacto scrollable y pruebas de motor/UI. | Hecho |
| 2026-06-06 | UX-003 | Launcher redisenado como catalogo compacto con busqueda, categorias editoriales, orden por uso local y fallback para herramientas futuras. | Hecho |
| 2026-06-06 | I-016 | M-005 Membretado mejorado con biblioteca local de membretes, reutilizacion desde UI y carga de membrete Word convertido a PDF. | Hecho |
| 2026-06-06 | UX-001 | Correccion UI/UX: se retiro el orden visual redundante de Unir PDFs y se reacomodo Formato de PDF a Imagenes para evitar colapso o texto cortado. | Hecho |

---

## 10. Decisiones Abiertas

Estas decisiones se resolveran antes o durante la ficha correspondiente.

| ID | Tema | Decision pendiente | Afecta |
| --- | --- | --- | --- |
| D-001 | Organizador visual | Resuelta: v1 soporta multiples PDFs mezclados en una sola grilla. | T-001 |
| D-002 | Compresor | Resuelta: Correo 110 DPI/58%, Equilibrado 150 DPI/74%, Alta calidad 240 DPI/88%; si el output crece, se conserva el peso original y se avisa. | T-002 |
| D-003 | Marca de agua | Resuelta: imagen entra en MVP junto con texto; Pillow prepara opacidad/rotacion y PyMuPDF inserta el sello. | T-003 |
| D-004 | Redaccion segura | Resuelta: v1 redacta pixeles de imagen dentro del rectangulo dibujado; deteccion automatica por OCR queda para mejora posterior. | T-004 |
| D-005 | Clasificador OCR | Resuelta: reglas `Tipo=keyword, keyword`; plantillas con `{tipo}`, `{cliente}`, `{rfc}`, `{fecha}`, `{folio}`, `{original}`. | T-005 |
| D-006 | Proteger PDF | Resuelta: AES-256 por defecto; password de apertura opcional; si propietario queda vacio se usa apertura como propietario; permisos por checkboxes. | T-006 |
| D-007 | PDF a Word | Resuelta: v1 genera DOCX editable de texto por paginas usando OCR existente; reconstruccion visual avanzada queda para mejora futura. | T-007 |
| D-008 | Extraer imagenes | Resuelta: v1 conserva bytes/formato expuesto por PyMuPDF y deduplica por xref por defecto; conversion forzada queda para mejora futura. | T-008 |
| D-009 | Formularios PDF | Resuelta: v1 trabaja un PDF por sesion, soporta texto/checkbox/radio/combo/lista, valida requeridos, preserva valores al navegar y usa `bake(widgets=True)` para aplanar. | T-009 |
| D-010 | Comparar PDFs | Resuelta: v1 compara exactamente dos PDFs; el primero es base, el segundo revisado; el resultado es un reporte PDF con resaltado rojo sobre la version revisada. | T-010 |
| D-011 | Reparar PDF | Resuelta: v1 no promete recuperar PDFs irrecuperables; si MuPDF puede abrirlos, se reescriben y se verifica que el resultado abra con el mismo numero de paginas. | T-011 |
| D-012 | Alcance de roadmap | Resuelta: se omite T-012 y se excluyen mejoras de Firmador, Foleador y Separador; el siguiente bloque activo inicia con mejoras de otras herramientas. | T-012, M-001..M-004, M-012..M-017 |
| D-013 | Unir PDFs | Resuelta: Unir PDFs no duplica el Organizador visual; el orden se controla en la lista principal del lote con miniaturas nativas y resumen compacto. | M-006 |
| D-014 | Imagenes a PDF | Resuelta: M-008 se implementa como perfiles documentales; blanco y negro optimizado avanzado y orientacion inteligente quedan como M-026/M-025 pendientes. | M-008 |
| D-015 | Quitar fondo | Resuelta: el visor de imagenes queda con modo opcional de comparacion; Quitar fondo lo usa para original vs PNG sobre cuadricula sin afectar otros visores. | M-011 |
| D-016 | PDF a Imagenes | Resuelta: los rangos se interpretan en el motor con sintaxis `1-3,5,final`, `pares` e `impares`; la UI usa cards compactas dentro de un panel scrollable para evitar cortes. | M-007 |
