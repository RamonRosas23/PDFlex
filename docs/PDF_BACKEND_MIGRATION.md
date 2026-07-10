# Sustitución completa de PyMuPDF en PDFlex

Fecha de decisión: 2026-07-10

## Objetivo

Eliminar completamente `PyMuPDF`/`fitz` antes de distribuir PDFlex como
software comercial cerrado, sin comprar una licencia comercial y sin degradar
silenciosamente las funciones existentes.

La migración se considera terminada sólo cuando:

- no existe ningún import o dependencia de `fitz`/`PyMuPDF` en producción,
  pruebas ni scripts de empaquetado;
- cada operación conserva páginas, tamaños, rotaciones, formularios,
  anotaciones y metadatos según corresponda;
- las salidas se vuelven a abrir y renderizar con un motor distinto del que las
  escribió;
- el paquete incluye todos los avisos y textos de licencia requeridos;
- la suite completa y el corpus visual de regresión pasan.

## Alcance encontrado

PyMuPDF aparece actualmente en 59 archivos de producción. No actúa como una
sola biblioteca: PDFlex lo usa como renderizador, lector de texto, editor de
contenido, manipulador estructural, motor de formularios y puente hacia OCR.
Por eso una sustitución por búsqueda y reemplazo sería incorrecta.

| Capacidad actual | Ejemplos en PDFlex | Sustituto elegido |
| --- | --- | --- |
| Render y miniaturas | visores, organizador, comparador, previsualizaciones | `pypdfium2` / PDFium |
| Texto y geometría visual | clasificador, analizador, márgenes, OCR nativo | PDFium; extracción geométrica encapsulada |
| Estructura, reparación y optimización | unir, separar, organizar, reparar, metadatos | `pikepdf` / QPDF |
| Formularios y cifrado | lectura/relleno AcroForm, AES-256 | `pypdf` con `cryptography` |
| Texto, imágenes y gráficos vectoriales nuevos | firma, membrete, folio, marca de agua, editor | ReportLab + overlay/underlay estructural |
| OCR | texto de escaneos y rotaciones | Tesseract 5, invocado por un adaptador propio |
| Redacción y eliminación visual | redactor y quitar logos | PDFium + reconstrucción irreversible de páginas afectadas |

No se usará Poppler, Ghostscript ni otra dependencia GPL/AGPL como componente
obligatorio del producto.

## Dependencias aprobadas

- `pypdfium2 5.11.x`: Apache-2.0 o BSD-3-Clause. La rueda de Windows incluye
  PDFium y un directorio `BUILD_LICENSES` que debe copiarse íntegro al producto.
- `pikepdf 10.10.x`: MPL-2.0; incluye QPDF bajo Apache-2.0. PDFlex puede seguir
  siendo cerrado. Se conservará la licencia MPL y se indicará dónde obtener el
  código fuente exacto de pikepdf distribuido. No se modificarán sus fuentes.
- `pypdf 6.14.x`: BSD-3-Clause.
- `reportlab 4.5.x`: BSD. Se excluirán del paquete sus fuentes demostrativas y
  la fuente opcional DarkGarden, que usa GPL con excepción para documentos.
- `cryptography`: Apache-2.0 o BSD-3-Clause; se usa para AES.
- Tesseract 5: Apache-2.0, con Leptonica BSD-2-Clause. El binario, datos de
  idioma y licencias se versionarán y verificarán por hash antes de distribuir.

Fuentes primarias:

- <https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright>
- <https://pypdfium2.readthedocs.io/en/stable/readme.html#licensing>
- <https://github.com/pikepdf/pikepdf#license>
- <https://qpdf.readthedocs.io/en/stable/license.html>
- <https://github.com/py-pdf/pypdf/blob/main/LICENSE>
- <https://docs.reportlab.com/developerfaqs/#13-licensing>
- <https://github.com/tesseract-ocr/tesseract#license>

Este inventario técnico no reemplaza una revisión jurídica de los términos de
venta, EULA, marcas, privacidad o normativa local.

## Arquitectura objetivo

Todo acceso a las bibliotecas externas vivirá bajo `core/pdf_backend/`:

- `geometry.py`: `Point`, `Rect`, matrices y conversiones de coordenadas;
- `rendering.py`: apertura de sólo lectura, render, texto, imágenes y páginas;
- `structure.py`: copiar, unir, separar, rotar, reparar, metadatos y optimizar;
- `composition.py`: overlays vectoriales de texto, imagen y formas;
- `forms.py`: inspección, relleno y aplanado de AcroForm;
- `security.py`: contraseñas, permisos, sanitización y redacción;
- `ocr.py`: ejecución local de Tesseract y reconstrucción de párrafos.

Los módulos de interfaz no importarán directamente PDFium, pikepdf, pypdf ni
ReportLab. Así se evita volver a acoplar toda la aplicación a una API externa.

### Seguridad de hilos

PDFium no es thread-safe, incluso con documentos distintos. Todas sus llamadas
quedarán detrás de un `RLock` global. Las tareas costosas que deban ser paralelas
usarán procesos, nunca llamadas PDFium concurrentes desde `QThread`.

### Coordenadas y rotación

La capa interna usará puntos PDF (1/72 de pulgada), origen superior izquierdo
para la interfaz y rectángulos normalizados. Cada backend realizará la
conversión explícita. Habrá pruebas para rotaciones 0/90/180/270, crop boxes y
páginas no estándar antes de migrar herramientas de escritura.

## Redacción segura

Cubrir contenido con un rectángulo no es redacción. Para las páginas afectadas:

1. PDFium renderiza la apariencia completa a una resolución de seguridad;
2. se eliminan o rellenan las regiones seleccionadas sobre la imagen;
3. se construye una página nueva con el mismo tamaño y rotación visual;
4. se eliminan miniaturas, índices, metadatos privados y acciones auxiliares;
5. se verifica que la salida no contenga texto, imágenes ni objetos del original
   en esa página y que pueda abrirse con PDFium y pypdf.

Las páginas no afectadas se copian sin rasterizar. La página redaccionada pierde
selección de texto, pero gana una garantía de eliminación superior a intentar
interpretar parcialmente streams PDF arbitrarios.

La herramienta de quitar logos podrá conservar un camino vectorial cuando se
identifique un objeto de imagen completo; los casos visuales o ambiguos usarán
la reconstrucción segura.

## Evidencia inicial

La prueba de concepto en Windows comprobó:

- creación vectorial y formulario con ReportLab;
- render y extracción de texto con PDFium;
- reescritura, metadatos y linearización con QPDF;
- relleno de formulario y ciclo AES-256 con pypdf;
- reapertura y render de todas las salidas con PDFium.

En el documento sintético a 144 dpi, ambos renderizadores produjeron
1224 x 1584 px y la diferencia media PDFium/PyMuPDF fue 0.790 sobre 255. En
cuatro documentos reales locales la apariencia fue visualmente equivalente;
la diferencia media estuvo entre 0.030 y 4.265 sobre 255. PDFium tardó entre
17 y 77 ms en la primera página de esos ejemplos, dentro del presupuesto de las
previsualizaciones actuales.

## Orden de migración

1. Crear geometría, render de sólo lectura y pruebas de contrato.
2. Migrar visores, miniaturas y análisis que no escriben PDFs.
3. Migrar unión, separación, organización, reparación y protección.
4. Migrar composición vectorial, firmas, membretes, marcas y editor.
5. Migrar formularios y OCR.
6. Migrar compresión, redacción y eliminación de logos con pruebas específicas.
7. Eliminar PyMuPDF, añadir un detector antirregresión y validar el paquete.

Cada bloque tendrá su propio commit y deberá dejar verde la suite antes de
continuar al siguiente.

## Criterios de aceptación

- Suite completa sin fallos ni cierres anómalos.
- Comparación de render en páginas de texto, escaneos, transparencias,
  formularios y rotaciones.
- Conteo idéntico de páginas y dimensiones con tolerancia menor a 0.01 pt en
  operaciones que deben preservar estructura.
- AES-256 verificable y contraseñas incorrectas rechazadas.
- Formularios rellenados visibles en Adobe Reader, Edge y PDFium.
- Redacciones sin texto extraíble ni objetos originales en páginas afectadas.
- Ningún archivo distribuido con licencia AGPL/GPL obligatoria para PDFlex.
- `THIRD_PARTY_NOTICES` generado desde las ruedas exactas usadas en el build.
