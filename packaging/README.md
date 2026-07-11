# PDFlex Setup

El instalador publico actual es Inno Setup directo:

```text
dist\PDFlex_<version>_Setup.exe
```

Este archivo copia `dist\PDFlex`, registra la version instalada, crea accesos
directos, gestiona upgrades y desinstalacion, y es compatible con el
auto-updater.

## Build

```powershell
.\build_nuitka.ps1
```

El build copia los avisos legales base desde `docs\legal` y recolecta las
licencias exactas de los paquetes instalados hacia:

```text
dist\PDFlex\legal\third_party_licenses\
```

Antes de publicar, completa y revisa:

- `docs\legal\EULA.md`
- `docs\legal\PRIVACY_NOTICE.md`
- `docs\legal\CODE_SIGNING.md`
- `docs\legal\RELEASE_CHECKLIST.md`

Si vas a vender OCR como incluido/offline, usa el modo estricto:

```powershell
.\build_nuitka.ps1 -RequireBundledTesseract
```

Ese modo exige `assets\tesseract\tesseract.exe`; sin ese binario, OCR debe
documentarse como dependiente de `PDFLEX_TESSERACT` o de una instalación externa
de Tesseract.

Para regenerar solo el instalador usando la distribucion existente:

```powershell
.\build_nuitka.ps1 -SkipVenv -SkipBuild
```

O directamente:

```powershell
.\build_setup.ps1
```

## Auto-updater

El updater debe descargar `PDFlex_<version>_Setup.exe`. Se lanza con:

```powershell
/SILENT /NORESTART /CLOSEAPPLICATIONS
```

Inno Setup acepta esos argumentos directamente, asi que no se necesita
bootstrapper intermedio.

## Firma digital

La firma es opcional y se activa por variables de entorno:

```powershell
$env:CODESIGN_CERT_PATH = "C:\certs\pdflex.pfx"
$env:CODESIGN_CERT_PASSWORD = "..."
$env:CODESIGN_TIMESTAMP_URL = "http://timestamp.digicert.com"
.\build_nuitka.ps1 -RequireSign
```

Tambien se soporta firma desde el almacen de certificados:

```powershell
$env:CODESIGN_THUMBPRINT = "THUMBPRINT_DEL_CERTIFICADO"
.\build_nuitka.ps1 -RequireSign
```

`-RequireSign` falla el build si falta SignTool, certificado o timestamp/firma
correcta. Para pruebas locales sin firma puedes usar `-SkipSign`.
