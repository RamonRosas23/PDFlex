# ============================================================
#  build_exe.ps1  —  Compila PDFlex onedir con entorno limpio
#  Ejecutar desde la carpeta del proyecto:
#      .\build_exe.ps1
# ============================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$VenvDir    = Join-Path $ProjectDir ".venv_build"
$Python     = "C:\Users\OCMX_Sistemas1\AppData\Local\Programs\Python\Python311\python.exe"

# ── 1. Limpiar build anterior ────────────────────────────────
Write-Host "`n[1/5] Limpiando builds anteriores..." -ForegroundColor Cyan
foreach ($folder in @("build", "dist", "__pycache__")) {
    $path = Join-Path $ProjectDir $folder
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force
        Write-Host "      Eliminado: $folder"
    }
}

# ── 2. Crear entorno virtual limpio ─────────────────────────
Write-Host "`n[2/5] Creando entorno virtual limpio en .venv_build..." -ForegroundColor Cyan
if (Test-Path $VenvDir) {
    Remove-Item $VenvDir -Recurse -Force
}
& $Python -m venv $VenvDir
if ($LASTEXITCODE -ne 0) { throw "Error al crear el entorno virtual." }

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"

# ── 3. Instalar dependencias ─────────────────────────────────
Write-Host "`n[3/5] Instalando dependencias..." -ForegroundColor Cyan

$SSLFlags = @(
    "--trusted-host", "pypi.org",
    "--trusted-host", "files.pythonhosted.org",
    "--trusted-host", "pypi.python.org"
)

& $VenvPython -m pip install --upgrade pip @SSLFlags --quiet
& $VenvPython -m pip install @SSLFlags -r (Join-Path $ProjectDir "requirements.txt") --quiet
& $VenvPython -m pip install @SSLFlags "pyinstaller" --quiet

if ($LASTEXITCODE -ne 0) { throw "Error al instalar dependencias." }
Write-Host "      Dependencias instaladas correctamente."

& $VenvPython -c "from PySide6 import QtCore, QtGui, QtSvg, QtWidgets; print(QtCore.qVersion())" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { throw "PySide6 no se puede importar en el entorno de build." }
Write-Host "      PySide6 validado correctamente."

$LegalSource = Join-Path $ProjectDir "docs\legal"
$ThirdPartyNoticeSource = Join-Path $LegalSource "THIRD_PARTY_NOTICES.md"
if (-not (Test-Path -LiteralPath $ThirdPartyNoticeSource)) {
    throw "No se encontro docs\legal\THIRD_PARTY_NOTICES.md. No se generara una build sin avisos legales."
}
Write-Host "      Documentos legales base validados."

$TesseractExe = Join-Path $ProjectDir "assets\tesseract\tesseract.exe"
if (-not (Test-Path -LiteralPath $TesseractExe)) {
    Write-Host "      Aviso: Tesseract no esta embebido; OCR requerira PDFLEX_TESSERACT o instalacion externa." -ForegroundColor Yellow
} else {
    $TesseractDir = Split-Path -Parent $TesseractExe
    $TesseractNoticeFiles = Get-ChildItem -LiteralPath $TesseractDir -Recurse -File |
        Where-Object { $_.Name -match '^(LICENSE|LICENCE|NOTICE|COPYING|COPYRIGHT)' }
    if ($TesseractNoticeFiles.Count -eq 0) {
        throw "Tesseract esta embebido, pero faltan LICENSE/NOTICE/COPYING en assets\tesseract."
    }
    Write-Host "      Tesseract embebido con avisos legales."
}

# ── 3b. post-install script de pywin32 ───────────────────────
#  pywin32 requiere correr su post-install para registrar las DLLs en el venv
$PyWin32PostInstall = Join-Path $VenvDir "Scripts\pywin32_postinstall.py"
if (Test-Path $PyWin32PostInstall) {
    Write-Host "      Ejecutando pywin32 post-install..." -ForegroundColor DarkCyan
    & $VenvPython $PyWin32PostInstall -install
}

# ── 4. Compilar con PyInstaller usando PDFlex.spec ───────────
Write-Host "`n[4/5] Compilando ejecutable..." -ForegroundColor Cyan
Set-Location $ProjectDir

$SpecFile = Join-Path $ProjectDir "PDFlex.spec"
& $VenvPython -m PyInstaller $SpecFile --clean --noconfirm

if ($LASTEXITCODE -ne 0) { throw "PyInstaller terminó con error." }

$LegalDir = Join-Path $ProjectDir "dist\PDFlex\legal"
if (-not (Test-Path -LiteralPath $LegalDir)) {
    New-Item -ItemType Directory -Force -Path $LegalDir | Out-Null
    Copy-Item -LiteralPath (Join-Path $LegalSource "*") -Destination $LegalDir -Recurse -Force
}

$ThirdPartyNotice = Join-Path $LegalDir "THIRD_PARTY_NOTICES.md"
if (-not (Test-Path -LiteralPath $ThirdPartyNotice)) {
    throw "PyInstaller no incluyo dist\PDFlex\legal\THIRD_PARTY_NOTICES.md."
}

$LicenseCollector = Join-Path $ProjectDir "packaging\collect_licenses.py"
if (-not (Test-Path -LiteralPath $LicenseCollector)) {
    throw "No se encontro packaging\collect_licenses.py."
}

$LicenseOut = Join-Path $LegalDir "third_party_licenses"
& $VenvPython $LicenseCollector --output $LicenseOut
if ($LASTEXITCODE -ne 0) { throw "No se pudieron recolectar licencias de terceros." }

$LicenseManifest = Join-Path $LicenseOut "manifest.json"
if (-not (Test-Path -LiteralPath $LicenseManifest)) {
    throw "No se genero dist\PDFlex\legal\third_party_licenses\manifest.json."
}
Write-Host "      Avisos y licencias de terceros incluidos."

# ── 5. Resultado ─────────────────────────────────────────────
$ExePath = Join-Path $ProjectDir "dist\PDFlex\PDFlex.exe"
if (Test-Path $ExePath) {
    $SizeMB = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)
    Write-Host "`n[5/5] ¡Listo! Ejecutable generado:" -ForegroundColor Green
    Write-Host "      $ExePath  ($SizeMB MB)" -ForegroundColor Green
    Start-Process explorer.exe (Join-Path $ProjectDir "dist")
} else {
    throw "No se encontró el ejecutable. Revisa los errores de PyInstaller arriba."
}
