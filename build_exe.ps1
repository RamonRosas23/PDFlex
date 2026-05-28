# ============================================================
#  build_exe.ps1  —  Compila FirmadorMasivo.exe con entorno limpio
#  Ejecutar desde la carpeta del proyecto:
#      .\build_exe.ps1
# ============================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$VenvDir    = Join-Path $ProjectDir ".venv_build"
$Python     = "python"   # Cambia a la ruta absoluta si tienes varios Python instalados

# ── 1. Limpiar build anterior ────────────────────────────────
Write-Host "`n[1/5] Limpiando builds anteriores..." -ForegroundColor Cyan
foreach ($folder in @("build", "dist", "__pycache__")) {
    $path = Join-Path $ProjectDir $folder
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force
        Write-Host "      Eliminado: $folder"
    }
}
$specFile = Join-Path $ProjectDir "FirmadorMasivo.spec"
if (Test-Path $specFile) { Remove-Item $specFile -Force }

# ── 2. Crear entorno virtual limpio ─────────────────────────
Write-Host "`n[2/5] Creando entorno virtual limpio en .venv_build..." -ForegroundColor Cyan
if (Test-Path $VenvDir) {
    Remove-Item $VenvDir -Recurse -Force
}
& $Python -m venv $VenvDir
if ($LASTEXITCODE -ne 0) { throw "Error al crear el entorno virtual." }

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"

# ── 3. Instalar dependencias mínimas ────────────────────────
Write-Host "`n[3/5] Instalando dependencias..." -ForegroundColor Cyan

# Flags SSL: necesarios en redes corporativas con certificados autofirmados
$SSLFlags = @(
    "--trusted-host", "pypi.org",
    "--trusted-host", "files.pythonhosted.org",
    "--trusted-host", "pypi.python.org"
)

& $VenvPython -m pip install --upgrade pip @SSLFlags --quiet
& $VenvPython -m pip install @SSLFlags `
    "PyMuPDF>=1.24.0" `
    "Pillow>=10.0.0" `
    "PyQt6>=6.6.0" `
    "numpy>=1.24.0" `
    "pyinstaller" `
    --quiet

if ($LASTEXITCODE -ne 0) { throw "Error al instalar dependencias." }
Write-Host "      Dependencias instaladas correctamente."

# ── 4. Compilar con PyInstaller ──────────────────────────────
Write-Host "`n[4/5] Compilando ejecutable..." -ForegroundColor Cyan
Set-Location $ProjectDir

& $VenvPython -m PyInstaller `
    --onefile `
    --windowed `
    --name "FirmadorMasivo" `
    --icon "assets\FirmaFolio_cuadrado_sin_fondo.ico" `
    --add-data "assets;assets" `
    --collect-all pymupdf `
    --collect-all PIL `
    --collect-all PyQt6 `
    --clean `
    main.py

if ($LASTEXITCODE -ne 0) { throw "PyInstaller terminó con error." }

# ── 5. Resultado ─────────────────────────────────────────────
$ExePath = Join-Path $ProjectDir "dist\FirmadorMasivo.exe"
if (Test-Path $ExePath) {
    $SizeMB = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)
    Write-Host "`n[5/5] ¡Listo! Ejecutable generado:" -ForegroundColor Green
    Write-Host "      $ExePath  ($SizeMB MB)" -ForegroundColor Green
    # Abrir carpeta dist en el explorador
    Start-Process explorer.exe (Join-Path $ProjectDir "dist")
} else {
    throw "No se encontró el ejecutable. Revisa los errores de PyInstaller arriba."
}
