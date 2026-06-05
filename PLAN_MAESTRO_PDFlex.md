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
| B-004 | Membretado | Base completada | Superpone documentos sobre hojas membretadas. | Base para composicion por capas. |
| B-005 | Unir PDFs | Base completada | Combina varios PDFs en un unico documento. | Base para resultados multi-documento. |
| B-006 | PDF a Imagenes | Base completada | Exporta paginas PDF como PNG, JPG o WebP. | Base para renderizado y salidas de imagen. |
| B-007 | Imagenes a PDF | Base completada | Convierte y combina imagenes en PDF. | Base para carga y ordenamiento visual de imagenes. |
| B-008 | OCR de PDF | Base completada | Extrae texto local y exporta Word/TXT. | Base para clasificacion por contenido. |
| B-009 | Word a PDF | Base completada | Convierte DOC/DOCX a PDF usando Microsoft Word. | Recien separada como herramienta dedicada. |
| B-010 | Quitar fondo | Base completada | Genera PNG transparente desde imagenes con fondo uniforme. | Recien separada como herramienta dedicada. |

---

## 3. Tablero Kanban

### Herramientas Nuevas

| ID | Tipo | Iniciativa | Estado | Prioridad | Iteracion | Notas |
| --- | --- | --- | --- | --- | --- | --- |
| T-001 | Herramienta nueva | Organizador visual de paginas | Pendiente | P1 | I-001 | Primer bloque de impacto. |
| T-002 | Herramienta nueva | Comprimir / Optimizar PDF | Pendiente | P1 | I-002 | Depende de decisiones de perfiles y calidad. |
| T-003 | Herramienta nueva | Marca de agua / Sellos | Pendiente | P1 | I-003 | Reutiliza patrones de insercion por pagina. |
| T-004 | Herramienta nueva | Redaccion segura | Pendiente | P1 | I-004 | Requiere cuidado especial de seguridad. |
| T-005 | Herramienta nueva | Clasificador / Renombrador por OCR | Pendiente | P1 | I-005 | Reutiliza OCR y reglas de nombres. |
| T-006 | Herramienta nueva | Proteger PDF | Pendiente | P2 | Por definir | Passwords, permisos y cifrado. |
| T-007 | Herramienta nueva | PDF a Word editable | Pendiente | P2 | Por definir | Complemento natural de OCR. |
| T-008 | Herramienta nueva | Extraer imagenes / recursos de PDF | Pendiente | P2 | Por definir | Exporta recursos embebidos sin renderizar pagina. |
| T-009 | Herramienta nueva | Formularios PDF: rellenar y aplanar | Pendiente | P2 | Por definir | Util para tramites y documentos administrativos. |
| T-010 | Herramienta nueva | Comparar PDFs | Pendiente | P2 | Por definir | Comparacion visual/textual. |
| T-011 | Herramienta nueva | Reparar / Normalizar PDF | Pendiente | P2 | Por definir | Mejora estabilidad para documentos problematicos. |
| T-012 | Herramienta nueva | PDF/A o archivo legal | Pendiente | P3 | Por definir | Validacion/conversion para conservacion. |

### Mejoras Por Herramienta Actual

| ID | Tipo | Iniciativa | Estado | Prioridad | Iteracion | Notas |
| --- | --- | --- | --- | --- | --- | --- |
| M-001 | Mejora | Firmador: perfiles de firma | Pendiente | P1 | Por definir | Guardar posicion, tamano, color, variacion y fondo. |
| M-002 | Mejora | Firmador: firma por reglas | Pendiente | P1 | Por definir | Ultima pagina, texto detectado o linea de firma. |
| M-003 | Mejora | Foleador: QR/codigo de barras | Pendiente | P2 | Por definir | Folio visual y legible por maquina. |
| M-004 | Mejora | Separador: separar por texto/bookmarks | Pendiente | P1 | Por definir | Usa OCR/texto nativo y marcadores. |
| M-005 | Mejora | Membretado: biblioteca de membretes | Pendiente | P2 | Por definir | Presets reutilizables. |
| M-006 | Mejora | Unir PDFs: miniaturas antes de unir | Pendiente | P1 | Por definir | Relacionado con T-001. |
| M-007 | Mejora | PDF a Imagenes: rangos y presets | Pendiente | P2 | Por definir | DPI/formato/rangos guardables. |
| M-008 | Mejora | Imagenes a PDF: modo escaner documental | Pendiente | P1 | Por definir | Recorte, enderezado y contraste. |
| M-009 | Mejora | OCR: busqueda y exportacion CSV | Pendiente | P2 | Por definir | Revision y analisis de resultados. |
| M-010 | Mejora | Word a PDF: Office a PDF | Pendiente | P2 | Por definir | Extender a Excel y PowerPoint. |
| M-011 | Mejora | Quitar fondo: preview antes/despues | Pendiente | P1 | Por definir | Eleva confianza del usuario. |

---

## 4. Proximo Bloque: Herramientas Nuevas Prioridad 1

Estas cinco iniciativas son el bloque inicial de crecimiento del producto.

---

### T-001 - Organizador Visual De Paginas

**Estado:** Pendiente  
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

- [ ] Definir modelo de pagina y estado UI.
- [ ] Crear motor de organizacion.
- [ ] Crear grilla visual de miniaturas.
- [ ] Implementar acciones de pagina.
- [ ] Integrar procesamiento y visor de resultado.
- [ ] Registrar herramienta en `tool_registry`.
- [ ] Agregar pruebas unitarias del motor.
- [ ] Agregar pruebas de ventana.
- [ ] Validar flujo manual con PDFs reales.

---

### T-002 - Comprimir / Optimizar PDF

**Estado:** Pendiente  
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
  - Para reduccion agresiva, renderizar imagenes grandes o recomprimir recursos si es viable.

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

- [ ] Definir perfiles finales.
- [ ] Implementar motor base con PyMuPDF.
- [ ] Agregar medicion de peso y ratio.
- [ ] Crear UI de perfil y resumen.
- [ ] Integrar visor de resultado.
- [ ] Registrar herramienta.
- [ ] Agregar pruebas con PDFs sinteticos.
- [ ] Validar con PDFs escaneados reales.

---

### T-003 - Marca De Agua / Sellos

**Estado:** Pendiente  
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
- Presets: Confidencial, Copia, Pagado, Recibido.
- Posiciones predefinidas: centro, esquina superior, esquina inferior.
- Opacidad y rotacion.
- Aplicar a todas las paginas o rango simple.
- Resultado temporal con visor.

#### Arquitectura Sugerida

- UI: `ui/marca_agua/`.
- Motor core: `core/watermark_engine.py`.
- Modelo:
  - `WatermarkConfig`: text/image, opacity, angle, position, pages.
  - `WatermarkJob`: pdf path, output path, config.
  - `WatermarkResult`: output path, success, error.
- Base tecnica:
  - PyMuPDF `insert_textbox` o insercion de imagen.
  - Reusar conceptos visuales de Firmador y Membretado.

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

- [ ] Definir presets.
- [ ] Implementar motor de texto.
- [ ] Implementar seleccion de paginas.
- [ ] Crear preview basico.
- [ ] Agregar imagen como fase posterior del MVP si el texto queda cerrado.
- [ ] Registrar herramienta.
- [ ] Agregar pruebas unitarias y smoke UI.

---

### T-004 - Redaccion Segura

**Estado:** Pendiente  
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

- UI: `ui/redaccion/`.
- Motor core: `core/redaction_engine.py`.
- Modelo:
  - `RedactionBox`: page index, rect normalizado o puntos PDF, label opcional.
  - `RedactionJob`: pdf path, output path, boxes.
  - `RedactionResult`: output path, redactions count, success, error.
- Base tecnica:
  - PyMuPDF `add_redact_annot` y `apply_redactions`.
  - Reusar visor interactivo de preview como base conceptual.

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

- [ ] Investigar comportamiento exacto de PyMuPDF con texto e imagenes.
- [ ] Crear modelo de cajas por pagina.
- [ ] Implementar canvas de seleccion.
- [ ] Implementar motor de redaccion segura.
- [ ] Agregar pruebas de extraccion de texto post-redaccion.
- [ ] Registrar herramienta.
- [ ] Validar manualmente con PDFs reales.

---

### T-005 - Clasificador / Renombrador Por OCR

**Estado:** Pendiente  
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
5. Mostrar tabla editable con nombre sugerido, confianza y avisos.
6. Confirmar y guardar/copiar resultados.

#### MVP

- Leer texto nativo si existe.
- Usar OCR existente cuando el documento no tenga texto suficiente.
- Reglas por expresiones simples para RFC, fecha y folio.
- Plantilla de nombre: `{tipo}_{rfc}_{fecha}_{folio}.pdf`.
- Tabla de revision antes de guardar.

#### Arquitectura Sugerida

- UI: `ui/clasificador/`.
- Motor core: `core/document_classifier_engine.py`.
- Reusar:
  - `core.ocr_engine` para obtener texto.
  - `core.output_paths` y `core.output_naming` para nombres seguros.
- Modelo:
  - `ClassifyRule`: field, pattern, label, required.
  - `RenameTemplate`: template string.
  - `ClassifyJob`: pdf path, output dir, rules, template.
  - `ClassifyResult`: fields, confidence, suggested name, output path, warnings.

#### Edge Cases

- Documento sin texto reconocible.
- Campos duplicados.
- RFC o fecha ambiguos.
- Nombres repetidos.
- Caracteres invalidos en nombre.
- Usuario edita nombre sugerido a algo invalido.

#### Pruebas

- Extrae RFC desde texto nativo.
- Extrae fecha en formatos comunes.
- Genera nombre seguro.
- Resuelve duplicados.
- Usa fallback cuando faltan campos.
- Tabla muestra warnings para baja confianza.

#### Criterios De Aceptacion

- Ningun archivo original se renombra directamente sin confirmacion.
- El usuario puede revisar y corregir antes de guardar.
- Los nombres finales son validos en Windows.
- Los resultados se pueden guardar por lote.

#### Checklist

- [ ] Definir reglas MVP.
- [ ] Crear motor de extraccion de campos.
- [ ] Crear tabla editable de resultados.
- [ ] Integrar OCR/texto nativo.
- [ ] Implementar guardado/copia con nombres finales.
- [ ] Agregar pruebas de reglas y nombres.
- [ ] Registrar herramienta.

---

## 5. Backlog De Herramientas Nuevas

### T-006 - Proteger PDF

- **Estado:** Pendiente
- **Prioridad:** P2
- **Objetivo:** Agregar contrasena y permisos de impresion/copia/edicion.
- **MVP:** cifrar PDF con password de apertura y password de propietario.
- **Pruebas clave:** PDF requiere password al abrir; permisos configurados; password vacia no permitida.

### T-007 - PDF A Word Editable

- **Estado:** Pendiente
- **Prioridad:** P2
- **Objetivo:** Exportar PDFs con texto nativo u OCR a DOCX editable.
- **MVP:** texto por paginas con estructura simple y exportacion DOCX.
- **Pruebas clave:** texto aparece en DOCX; OCR se usa en escaneos; errores parciales no bloquean lote.

### T-008 - Extraer Imagenes / Recursos De PDF

- **Estado:** Pendiente
- **Prioridad:** P2
- **Objetivo:** Extraer imagenes embebidas sin renderizar paginas completas.
- **MVP:** exportar imagenes originales por documento.
- **Pruebas clave:** extrae cantidad correcta; conserva formato cuando sea posible; maneja PDFs sin imagenes.

### T-009 - Formularios PDF: Rellenar Y Aplanar

- **Estado:** Pendiente
- **Prioridad:** P2
- **Objetivo:** Completar campos PDF y generar version aplanada.
- **MVP:** detectar campos, editar valores y exportar PDF no editable.
- **Pruebas clave:** valores visibles; campos aplanados; PDF sin formularios muestra aviso.

### T-010 - Comparar PDFs

- **Estado:** Pendiente
- **Prioridad:** P2
- **Objetivo:** Detectar diferencias entre dos versiones de un documento.
- **MVP:** comparar por render de pagina y listar paginas con cambios.
- **Pruebas clave:** detecta cambio visual; detecta cambio textual; maneja distinto numero de paginas.

### T-011 - Reparar / Normalizar PDF

- **Estado:** Pendiente
- **Prioridad:** P2
- **Objetivo:** Reescribir PDFs problematicos para mejorar compatibilidad.
- **MVP:** abrir y guardar con limpieza, garbage y deflate.
- **Pruebas clave:** PDF corrupto recuperable se abre; PDF normal no pierde paginas; errores claros.

### T-012 - PDF/A O Archivo Legal

- **Estado:** Pendiente
- **Prioridad:** P3
- **Objetivo:** Preparar documentos para conservacion y archivo.
- **MVP:** validar requisitos basicos y generar reporte.
- **Pruebas clave:** reporte de cumplimiento; advertencias claras; no prometer certificacion si no se valida formalmente.

---

## 6. Mejoras Por Herramienta Actual

### B-001 - Firmador Masivo

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-001 | Perfiles de firma | P1 | Pendiente | Guardar posicion, tamano, variacion, color y fondo por perfil. |
| M-002 | Firma por reglas | P1 | Pendiente | Firmar ultima pagina, paginas con texto especifico o lineas detectadas. |
| M-012 | Vista antes/despues | P2 | Pendiente | Comparacion rapida entre original y firmado. |
| M-013 | Firma digital criptografica | P3 | Pendiente | Evaluar como herramienta separada por complejidad legal/tecnica. |

### B-002 - Foleador

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-003 | QR/codigo de barras | P2 | Pendiente | Folio visible y escaneable. |
| M-014 | Importar consecutivos desde CSV/Excel | P2 | Pendiente | Folios externos por documento o pagina. |
| M-015 | Reinicio por seccion | P2 | Pendiente | Numeracion configurable por documento, rango o marcador. |

### B-003 - Separador De PDF

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-004 | Separar por texto/bookmarks | P1 | Pendiente | Dividir automaticamente por marcadores o texto detectado. |
| M-016 | Separar cada N paginas | P2 | Pendiente | Caso rapido para lotes homogeneos. |
| M-017 | Plantillas de separacion | P2 | Pendiente | Guardar reglas repetibles. |

### B-004 - Membretado

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-005 | Biblioteca de membretes | P2 | Pendiente | Presets reutilizables con preview. |
| M-018 | Reglas primera pagina/resto | P2 | Pendiente | Aplicar membretes distintos segun pagina. |
| M-019 | Preview lado a lado | P3 | Pendiente | Comparar original y membretado. |

### B-005 - Unir PDFs

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-006 | Miniaturas antes de unir | P1 | Pendiente | Reordenar visualmente documentos y paginas. |
| M-020 | Portada automatica | P2 | Pendiente | Crear portada de lote. |
| M-021 | Indice con marcadores | P2 | Pendiente | Navegacion automatica por documento. |
| M-022 | Normalizar tamanos | P2 | Pendiente | Homogeneizar paginas al unir. |

### B-006 - PDF A Imagenes

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-007 | Rangos y presets | P2 | Pendiente | Exportar paginas especificas y guardar DPI/formato. |
| M-023 | Estimacion de peso final | P3 | Pendiente | Mostrar tamano aproximado antes de procesar. |
| M-024 | Nombres avanzados | P2 | Pendiente | Plantillas tipo `{doc}_p{page:03}`. |

### B-007 - Imagenes A PDF

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-008 | Modo escaner documental | P1 | Pendiente | Recorte de bordes, enderezado y contraste. |
| M-025 | Correccion automatica de orientacion | P2 | Pendiente | Girar fotos de hojas de forma inteligente. |
| M-026 | Blanco y negro optimizado | P2 | Pendiente | Reducir peso y mejorar legibilidad. |

### B-008 - OCR De PDF

| ID | Mejora | Prioridad | Estado | Resultado esperado |
| --- | --- | --- | --- | --- |
| M-009 | Busqueda y exportacion CSV | P2 | Pendiente | Buscar en resultados y exportar resumen. |
| M-027 | Cola con reintentos | P2 | Pendiente | Robustecer lotes largos. |
| M-028 | Renombrado por contenido | P1 | Pendiente | Se relaciona con T-005. |

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
| M-011 | Preview antes/despues | P1 | Pendiente | Comparacion visual con fondo cuadriculado. |
| M-032 | Recorte automatico al contenido | P2 | Pendiente | Eliminar margenes transparentes. |
| M-033 | Presets firma/sello/logo | P2 | Pendiente | Configuraciones rapidas por tipo de imagen. |
| M-034 | Colorizar despues de quitar fondo | P2 | Pendiente | Llevar opcion del Firmador a herramienta independiente. |

---

## 7. Criterios Globales De Calidad

Estos criterios aplican a toda herramienta nueva o mejora importante.

### UX Y Flujo

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
- [ ] Aparece en el launcher en la categoria correcta.
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

---

## 10. Decisiones Abiertas

Estas decisiones se resolveran antes o durante la ficha correspondiente.

| ID | Tema | Decision pendiente | Afecta |
| --- | --- | --- | --- |
| D-001 | Organizador visual | Si v1 soportara multiples PDFs mezclados o solo un PDF por sesion. | T-001 |
| D-002 | Compresor | Nivel exacto de reduccion por perfil. | T-002 |
| D-003 | Marca de agua | Si imagen entra en MVP o fase 2. | T-003 |
| D-004 | Redaccion segura | Nivel de soporte para redaccion sobre imagenes escaneadas. | T-004 |
| D-005 | Clasificador OCR | Sintaxis final de reglas y plantillas. | T-005 |

