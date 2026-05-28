# Firmador Masivo de Documentos

Aplicación de escritorio para firmar PDFs masivamente con variación natural por página, evitando colisión con texto y respetando los márgenes de cada página.

## Características

- **Carga múltiple** de PDFs (drag & drop o diálogo).
- **Previsualizador interactivo** del PDF con la firma arrastrable, redimensionable (handles en las esquinas) y rotable (handle dedicado).
- **Análisis por página** que detecta bloques de texto y líneas de firma típicas (`______`).
- **Algoritmo de zona segura** con búsqueda en espiral cuadrada: si la posición elegida tapa texto, mueve la firma a la zona libre más cercana.
- **Snap a línea de firma**: si hay una línea típica de firma cerca, la firma se ajusta sobre ella.
- **Variación natural por página** (determinista vía semilla):
  - Ángulo (±°)
  - Escala (±%)
  - Desplazamiento X / Y (±pt)
  - Opacidad mínima
  - "Pressure jitter": ligera variación de contraste/brillo/blur que simula presión de bolígrafo
- **Visor de resultados** con thumbnails por página, mostrando si la firma fue ajustada automáticamente.
- **UI/UX moderna** con tema oscuro y navegación por secciones.

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

# 3. Lanzar la aplicación
python main.py
```

> **Red corporativa con certificado autofirmado (SSL):**  
> Si ves errores `SSLCertVerificationError`, agrega los flags de confianza:
> ```powershell
> pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
> ```

Dependencias principales:
- `PyMuPDF` — lectura/escritura de PDFs y extracción de texto con bounding boxes
- `Pillow` — transformación de imágenes (rotación, opacidad, jitter)
- `PyQt6` — UI
- `numpy` — operaciones numéricas para variación

### Opción B — Compilar `.exe` (distribución)

El script `build_exe.ps1` crea un entorno virtual **limpio** (sin librerías del sistema),
instala solo las dependencias necesarias y genera `dist/FirmadorMasivo.exe`.

```powershell
# Desde la carpeta del proyecto:
Set-ExecutionPolicy -Scope Process Bypass
.\build_exe.ps1
```

El ejecutable resultante en `dist\FirmadorMasivo.exe` es **portable** —
no requiere Python instalado en el equipo destino (~130 MB).

> **Sobre los `WARNING: Library not found` durante la compilación:**  
> Son normales. PyInstaller analiza todos los plugins de Qt6 (3D, WebEngine, QML, etc.)
> que no están instalados en el entorno limpio porque la app no los usa.
> El ejecutable funciona correctamente sin ellos.

## Uso

```bash
python main.py
```

Flujo:

1. **Documentos**: carga uno o más PDFs.
2. **Firma & Posición**: carga una imagen PNG con fondo transparente. Arrástrala sobre la página, ajusta tamaño con las esquinas y rota con el handle superior.
3. **Variación**: ajusta los rangos de variación con los sliders.
4. **Procesar**: define la carpeta de salida y ejecuta. Se procesa en un thread separado con barra de progreso.
5. **Resultados**: revisa página por página el resultado final, con indicadores de páginas donde la firma fue reposicionada para evitar texto.

## Arquitectura

```
firmador_masivo/
├── main.py                    # Punto de entrada
├── requirements.txt
├── README.md
├── core/                      # Lógica de negocio
│   ├── pdf_analyzer.py        # Análisis de texto + márgenes + líneas
│   ├── safe_zone.py           # Búsqueda de zona segura (espiral)
│   ├── variation.py           # Generador determinista de variaciones
│   └── signature_engine.py    # Motor principal (combina todo)
└── ui/                        # Interfaz
    ├── main_window.py         # Ventana principal + sidebar + secciones
    ├── pdf_preview.py         # Vista previa con firma arrastrable
    ├── results_viewer.py      # Visor de páginas firmadas
    └── styles.py              # Tema oscuro (QSS)
```

## Algoritmo de zona segura

1. La firma deseada se calcula a partir de:
   - Posición base normalizada en el preview (fracción 0..1 de la página)
   - Tamaño base en puntos PDF
   - Ángulo base
   - **+ variación pseudoaleatoria** determinista por (documento, página, seed)

2. Si el bounding box rotado de la firma:
   - **No se sale** de los márgenes Y
   - **No intersecta** ningún bloque de texto (con padding)
   
   → se acepta esa posición.

3. Si **sí choca**, se ejecuta una **búsqueda en espiral cuadrada** alrededor del punto deseado, probando candidatos a paso configurable hasta encontrar uno válido (máx. 80 intentos).

4. Si la espiral no encuentra nada, se hace un **barrido en grilla** del cuarto inferior derecho.

5. Si hay una **línea de firma** (línea horizontal larga y delgada, o secuencia de `_`) a menos de 40 pt de la posición candidata, se hace **snap** centrando la firma sobre ella.

## Notas técnicas

- El previsualizador renderiza el PDF a 144 DPI para nitidez. Las coordenadas se convierten automáticamente a puntos PDF (72 DPI).
- La rotación se aplica pre-rotando la imagen con PIL (`expand=True`) y luego insertándola en el bbox correspondiente, lo que permite ángulos arbitrarios (no solo múltiplos de 90).
- El procesamiento corre en un `QThread` separado para no bloquear la UI.
- Misma semilla = mismo resultado exacto: útil si necesitas reproducir un firmado.
