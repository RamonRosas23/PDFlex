# ============================================================
#  build_exe.ps1  —  Compila PDFlex.exe con entorno limpio
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

# ── 5. Resultado ─────────────────────────────────────────────
$ExePath = Join-Path $ProjectDir "dist\PDFlex.exe"
if (Test-Path $ExePath) {
    $SizeMB = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)
    Write-Host "`n[5/5] ¡Listo! Ejecutable generado:" -ForegroundColor Green
    Write-Host "      $ExePath  ($SizeMB MB)" -ForegroundColor Green
    Start-Process explorer.exe (Join-Path $ProjectDir "dist")
} else {
    throw "No se encontró el ejecutable. Revisa los errores de PyInstaller arriba."
}
