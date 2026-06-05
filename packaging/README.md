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
```

Tambien se soporta firma desde el almacen de certificados:

```powershell
$env:CODESIGN_THUMBPRINT = "THUMBPRINT_DEL_CERTIFICADO"
```
