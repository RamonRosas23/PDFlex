# Auditoria - Bandeja y Documentos de Trabajo

> **Fecha:** 2026-06-23  
> **Plan:** `docs/superpowers/plans/2026-06-23-document-workspace-bandeja.md`  
> **Objetivo:** dejar inventario verificable antes de redisenar bandeja, transferencias y seccion de documentos.

## Contratos Actuales

- `shell/tray.py`
  - `PdfTray` guarda `TrayItem(path, source_tool, label, created_at)`.
  - `add_items(paths, source_tool)` solo agrega archivos existentes, deduplica por path y emite `changed` si hubo alta real.
  - `paths()` devuelve la lista plana en orden de insercion.
  - `TrayPopup` muestra una lista plana con nombre, origen textual y accion de quitar.

- `ui/common/documents_step.py`
  - `DocumentsCard` mantiene una sola lista de trabajo.
  - `add_paths()` agrega PDFs y convierte Word a PDF si hay Office disponible.
  - `_on_load_from_tray()` copia todos los paths de `ctx.tray.paths()` a la misma lista de trabajo.
  - No limpia bandeja, no marca estado y no distingue origen visual.
  - API usada por herramientas: `paths()`, `add_paths()`, `clear()`, `count()`, `is_empty()`, `remove_path()`, `reorder_paths()`, `files_changed`.

- `ui/common/send_to_tool.py`
  - `SendToToolPanel` calcula herramientas compatibles por extension de salida.
  - `_send_to(tool)` llama `ctx.open_tool(tool.id, list(output_paths))`.
  - No existe politica de bandeja ni modo append/replace.

- `shell/shell_window.py`
  - `ShellContext.open_tool` apunta a `ShellWindow._open_tool(tool_id, inputs)`.
  - `_show_tool_widget()` llama `widget.set_inputs(inputs)` si `inputs` trae datos.
  - No hay contrato de transferencia enriquecido.

## Herramientas Por Tipo de Entrada

### Usan `DocumentsCard`

Estas herramientas son candidatas directas para migrar a `DocumentWorkspace` compatible:

| Herramienta | ID | Entrada registrada | Reordena | Observacion |
| --- | --- | --- | --- | --- |
| Firmador masivo | `firmador` | `.pdf` | Si | UI menciona PDF o Word; `DocumentsCard` convierte Word. |
| Comprimir PDF | `compresor` | `.pdf` | No | Flujo PDF estandar. |
| Marca de agua | `marca_agua` | `.pdf` | No | Flujo PDF estandar. |
| Redaccion segura | `redactor` | `.pdf` | No | UI habla de un solo PDF, pero no usa `single_file`; validar al migrar. |
| Quitar logos | `quitar_logos` | `.pdf` | No | Flujo PDF estandar. |
| Proteger PDF | `protector` | `.pdf` | No | Flujo PDF estandar. |
| Formularios PDF | `formularios` | `.pdf` | No | UI habla de un documento por sesion; validar `single_file` al migrar. |
| Comparar PDFs | `comparador` | `.pdf` | Si | Requiere exactamente dos PDFs. |
| Reparar PDF | `reparador` | `.pdf` | No | Flujo PDF estandar. |
| Foleador | `foleador` | `.pdf` | Si | Orden relevante para folio continuo. |
| Membretado | `membretado` | `.pdf` | Si | Ya tiene configuracion avanzada por documento. |
| PDF a Imagenes | `pdf_to_imgs` | `.pdf` | Si | Entrada PDF, salida imagenes. |
| Extraer imagenes | `extraer_imagenes` | `.pdf` | No | Entrada PDF, salida imagenes. |
| Unir PDFs | `unir` | `.pdf` | Si | Orden de lista es critico. |
| PDF a Word | `pdf_to_word` | `.pdf` | No | Entrada PDF, salida `.docx`. |
| OCR de PDF | `ocr` | `.pdf` | Si | Puede procesar multiples PDFs. |
| Clasificador OCR | `clasificador` | `.pdf` | No | Flujo PDF estandar. |

### Componentes Especiales

| Herramienta | ID | Componente actual | Entrada registrada | Observacion |
| --- | --- | --- | --- | --- |
| Organizador visual | `organizador` | UI propia de paginas/lienzos | `.pdf` | No usa `DocumentsCard`; `set_inputs()` abre PDFs en su flujo visual. |
| Separador de PDF | `separador` | Selector propio de un archivo | `.pdf` | Acepta PDF/Word en UI y carga primer elemento valido de bandeja. |
| Imagenes a PDF | `imgs_a_pdf` | `ImageListCard` | imagenes | Requiere reordenar imagenes; salida PDF. |
| Quitar fondo | `quitar_fondo` | `ImageListCard` | imagenes | Reusa el componente de imagenes. |
| Word a PDF | `word_a_pdf` | `WordListCard` | `.doc`, `.docx` | No convierte al cargar; procesa con Word en ejecucion. |

## Registro de Extensiones

| ID | Titulo | Extensiones |
| --- | --- | --- |
| `organizador` | Organizador visual | `.pdf` |
| `firmador` | Firmador masivo | `.pdf` |
| `compresor` | Comprimir PDF | `.pdf` |
| `marca_agua` | Marca de agua | `.pdf` |
| `redactor` | Redaccion segura | `.pdf` |
| `quitar_logos` | Quitar logos | `.pdf` |
| `protector` | Proteger PDF | `.pdf` |
| `formularios` | Formularios PDF | `.pdf` |
| `comparador` | Comparar PDFs | `.pdf` |
| `reparador` | Reparar PDF | `.pdf` |
| `foleador` | Foleador | `.pdf` |
| `separador` | Separador de PDF | `.pdf` |
| `membretado` | Membretado | `.pdf` |
| `pdf_to_imgs` | PDF a Imagenes | `.pdf` |
| `extraer_imagenes` | Extraer imagenes | `.pdf` |
| `unir` | Unir PDFs | `.pdf` |
| `imgs_a_pdf` | Imagenes a PDF | `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tiff`, `.tif`, `.gif` |
| `word_a_pdf` | Word a PDF | `.doc`, `.docx` |
| `pdf_to_word` | PDF a Word | `.pdf` |
| `ocr` | OCR de PDF | `.pdf` |
| `clasificador` | Clasificador OCR | `.pdf` |
| `quitar_fondo` | Quitar fondo | `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tiff`, `.tif`, `.gif` |

## Nombres Finales Propuestos

### Estados de Archivo

- `Disponible`: esta en bandeja y puede usarse.
- `En trabajo`: esta cargado en la herramienta actual.
- `Enviado`: fue enviado a otra herramienta.
- `Resultado`: fue generado por una herramienta.
- `Original`: fue importado por el usuario.
- `Convertido`: viene de conversion Word a PDF u otra conversion temporal.
- `Faltante`: el path ya no existe en disco.

### Acciones de Trabajo

- `Agregar al trabajo`
- `Reemplazar trabajo`
- `Quitar del trabajo`
- `Vaciar trabajo`
- `Agregar archivos`
- `Cargar seleccionados`

### Acciones de Bandeja

- `Mantener bandeja`
- `Dejar solo enviados`
- `Limpiar bandeja`
- `Quitar de bandeja`
- `Limpiar resultados`
- `Limpiar faltantes`

### Modos de Transferencia

- `Reemplazar documentos actuales`
- `Agregar a documentos actuales`

## Reglas Para Migracion

- `DocumentWorkspace.paths()` debe seguir retornando solo el lote de trabajo.
- `DocumentWorkspace.add_paths()` debe comportarse como `DocumentsCard.add_paths()` por defecto.
- Cargar desde bandeja debe ser una accion visible desde el panel izquierdo, no una mezcla silenciosa.
- Enviar a otra herramienta debe conservar el comportamiento actual con defaults:
  - destino: `Reemplazar documentos actuales`;
  - bandeja: `Mantener bandeja`.
- Herramientas con orden critico deben conservar reordenamiento:
  - `firmador`, `comparador`, `foleador`, `membretado`, `pdf_to_imgs`, `unir`, `ocr`, `imgs_a_pdf`.
- Herramientas con cantidad exacta o limite funcional deben mostrar restriccion clara:
  - `comparador`: exactamente 2 PDFs.
  - `formularios`: 1 PDF.
  - `redactor`: 1 PDF.
  - `separador`: 1 PDF/Word de origen.
