# PDFlex

Caja de herramientas de escritorio diseñada para manipular documentos PDF con flujos automatizados de múltiples herramientas: **Firma Masiva (inteligente)**, **Foleado (paginado)**, **OCR Local (offline)**, **Membretado**, **Separación**, **Unión**, y conversión hacia o desde imágenes y Word. Orientado a grandes volúmenes de documentos respetando colisiones de texto e integridad del archivo original.

## Herramientas / Funciones

- **Firmador Masivo:**
  - Carga múltiple de PDFs.
  - Firma imagen PNG arrastrable, redimensionable y rotable.
  - *Algoritmo de zona segura* y detección de texto/líneas de firma.
  - Variación natural por página y documento (ángulo, escala, posición, opacidad, "pressure jitter").

- **Foleador (Paginación):**
  - Numera masivamente los documentos PDF.
  - Soporta múltiples formatos de texto ("Página X de Y", alfanuméricos, prefijos, ceros a la izquierda).
  - Posicionamiento inteligente para no tapar texto ni códigos de barras presentes en el membrete.

- **Membretado Masivo:**
  - Aplica imágenes de encabezado y pie de página en todo un bloque de documentos.
  - Ajuste de opacidad y alineación.

- **OCR (Local Neural Engine):**
  - Convierte PDFs escaneados a Word/TXT editable sin depender de la nube.
  - Usa los modelos oficiales `tessdata` (spa, eng) de Tesseract.
  - Ejecuta pesados análisis OCR en procesos aislados, recuperando automáticamente páginas giradas y pre-procesando imágenes tenues.

- **Herramientas de formato:**
  - Unir múltiples PDFs.
  - Separar PDFs por rangos (ej. 1-2, 3, 5-9) o a páginas individuales.
  - Imágenes a PDF / PDF a Imágenes, y Word a PDF masivo (vía automatización local de COM de Word).
  - Quitar "Fondo blanco" de imágenes (para preparar tu firma PNG perfecta).

## Instalación

### Requisitos

- Python **3.9 o superior** → [python.org/downloads](https://www.python.org/downloads/)
- Windows 10/11 (64-bit)

### Opción A — Ejecutar directamente (desarrollo)

```powershell
# 1. Crear y activar entorno virtual
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Lanzar la aplicación principal
python main.py
```

> **Red corporativa con certificado autofirmado (SSL):**  
> Si ves errores `SSLCertVerificationError`, agrega los flags de confianza:
> ```powershell
> pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
> ```

Dependencias principales:
- `PyMuPDF` (lectura/escritura veloz de PDFs, Detección de bloques de texto)
- `Pillow` y `OpenCV` (manipulación de firmas, remoción de fondos, pre-procesamiento)
- `pytesseract` (enlace al motor de OCR Tesseract)
- `PyQt6` (Interfaz moderna, QThreads, UX limpia)

### Opción B — Opciones de Compilación (distribución)

El repositorio incluye automatizaciones para obtener ejecutables independientes de Python.

- `build_nuitka.ps1`: Compilación preferida y más optimizada (convierte código Python a C y crea un binario rápido). Requiere gcc/msvc instalado.
- `build_exe.ps1`: Construye el `.exe` portable standard mediante PyInstaller.
- `build_setup.ps1`: Genera un instalador formal y un ZIP portable distribuyendo los artefactos con InnoSetup (`installer.iss`).

> NOTA: Para el OCR, la carpeta `assets/tessdata/` debe ser distribuida junto con el ejecutable generado o empaquetada e instruido a Tesseract sobre su ubicación en ejecución temporal.

## Flujo de Trabajo y Arquitectura

PDFlex se conforma por tres capas principales:

```
PDFlex/
├── main.py                    # Bootstrap y punto de entrada visual
├── core/                      # Lógica de procesamiento y motores
│   ├── ocr_engine.py          # Multiprocessing OCR
│   ├── signature_engine.py    # Motor inteligente de inserción
│   └── background_removal_engine.py
├── shell/                     # Núcleo modular del sistema
│   ├── launcher.py            # Orquestador del Grid de Herramientas
│   └── tool_registry.py       # Registro dinámico de herramientas
└── ui/                        # Implementación gráfica (PyQt6)
    ├── main_window.py         # Home (Grid Menu)
    └── common/                # Flujo estándar paso a paso (Files -> Config -> Result)
```

**Arquitectura "Tool Scaffold":** 
Todas las herramientas internas comparten una UI Wizard consistente bajo `ui/common/tool_scaffold.py`: (1) Carga de Documentos, (2) Configuración Específica, (3) Confirmación, y (4) Resultados. El resultado nunca altera el original en primera fase, los arroja en el grid de Resultados desde Temp y el usuario ejecuta la acción `Guardar como` sobre local.

## Notas Técnicas (Firmador Inteligente/Foleador)

1. El previsualizador renderiza el PDF a 144 DPI para nitidez. Las coordenadas se convierten a puntos PDF (72 DPI).
2. Algoritmos como `safe_zone.py` implementan bounding-box collisions: si un foleo o firma caerá sobre un bloque de texto que el PDF declara o en una zona prohibida (márgenes estrictos), busca en espiral la zona válida más cercana intentando no alterar la legibilidad.
3. El OCR es de alto consumo. Se aísla por `multiprocessing` con colas y señales cruzadas para evitar crashes en el loop principal de PyQt6. Se implementa auto-healing por crash.
