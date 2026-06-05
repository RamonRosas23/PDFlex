# ============================================================
#  build_nuitka.ps1  —  Compila PDFlex con Nuitka (standalone)
#                       + genera instalador directo Inno Setup
#
#  Resultado: dist\PDFlex\PDFlex.exe  (carpeta standalone)
#             dist\PDFlex_<version>_Setup.exe  (Inno Setup directo)
#
#  Uso:
#      .\build_nuitka.ps1              # build normal
#      .\build_nuitka.ps1 -SkipVenv   # reutiliza el venv existente
#      .\build_nuitka.ps1 -SkipBuild  # solo recompila el instalador
# ============================================================
param(
    [switch]$SkipVenv,
    [switch]$SkipBuild,
    [switch]$SkipSetupBootstrapper,
    [switch]$SkipSign
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Configuración ────────────────────────────────────────────────────────────
$ProjectDir  = $PSScriptRoot
$VenvDir     = Join-Path $ProjectDir ".venv_nuitka"
$NuitkaOut   = Join-Path $ProjectDir ".nuitka_build"
$DistDir     = Join-Path $ProjectDir "dist"
$AppDir      = Join-Path $DistDir    "PDFlex"
$Python      = "C:\Users\OCMX_Sistemas1\AppData\Local\Programs\Python\Python311\python.exe"

# Versión (sincronizada con update_config.py)
$UpdateConfigPath = Join-Path $ProjectDir "core\update_config.py"
$UpdateConfig = Get-Content -LiteralPath $UpdateConfigPath -Raw
if ($UpdateConfig -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') {
    throw "No se pudo leer APP_VERSION desde core\update_config.py"
}
$AppVersion  = $Matches[1]

# Rutas Inno Setup (instalación estándar + Chocolatey + PATH)
$ISSCPaths = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\ProgramData\chocolatey\bin\ISCC.exe",
    (Get-Command ISCC -ErrorAction SilentlyContinue)?.Source
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

# ── Helpers ───────────────────────────────────────────────────────────────────
function Step([string]$n, [string]$msg) {
    Write-Host "`n[$n] $msg" -ForegroundColor Cyan
}
function Ok([string]$msg)   { Write-Host "    ✓ $msg" -ForegroundColor Green  }
function Warn([string]$msg) { Write-Host "    ⚠ $msg" -ForegroundColor Yellow }
function Err([string]$msg)  { Write-Host "    ✗ $msg" -ForegroundColor Red; throw $msg }

# ── 0. Validaciones previas ───────────────────────────────────────────────────
Step "0/8" "Validando entorno"

if (-not (Test-Path $Python)) {
    Err "Python no encontrado en: $Python`nEdita la variable `$Python en este script."
}
$pyVer = & $Python --version 2>&1
Ok "Python: $pyVer"

if (-not (Test-Path (Join-Path $ProjectDir "main.py"))) {
    Err "Ejecuta desde la raíz del proyecto PDFlex."
}
Ok "Directorio del proyecto: $ProjectDir"

if ($ISSCPaths) { Ok "Inno Setup: $ISSCPaths" }
else            { Err "Inno Setup no encontrado. Se requiere para generar el instalador." }

# ── 1. Limpiar builds anteriores ─────────────────────────────────────────────
Step "1/8" "Limpiando builds anteriores"
$dirsToClean = @($NuitkaOut, (Join-Path $DistDir "__pycache__"))
if (-not $SkipBuild) { $dirsToClean += $AppDir }

foreach ($dir in $dirsToClean) {
    if (Test-Path $dir) {
        Remove-Item $dir -Recurse -Force
        Ok "Eliminado: $dir"
    }
}
foreach ($iss_exe in Get-ChildItem -Path $DistDir -Filter "PDFlex_*_Setup.exe" -ErrorAction SilentlyContinue) {
    Remove-Item $iss_exe.FullName -Force
    Ok "Eliminado: $($iss_exe.Name)"
}
foreach ($engine_exe in Get-ChildItem -Path $DistDir -Filter "PDFlex_*_Engine.exe" -ErrorAction SilentlyContinue) {
    Remove-Item $engine_exe.FullName -Force
    Ok "Eliminado: $($engine_exe.Name)"
}

# ── 2. Entorno virtual ────────────────────────────────────────────────────────
if ($SkipBuild) {
    Step "2/8" "Omitiendo entorno virtual (--SkipBuild)"
} elseif (-not $SkipVenv) {
    Step "2/8" "Creando entorno virtual limpio en .venv_nuitka"
    if (Test-Path $VenvDir) { Remove-Item $VenvDir -Recurse -Force }
    & $Python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Err "No se pudo crear el venv." }
    Ok "Venv creado"
} else {
    Step "2/8" "Reutilizando venv existente (--SkipVenv)"
    if (-not (Test-Path $VenvDir)) { Err "Venv no existe. Ejecuta sin -SkipVenv." }
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"

$SSLFlags = @(
    "--trusted-host", "pypi.org",
    "--trusted-host", "files.pythonhosted.org",
    "--trusted-host", "pypi.python.org"
)

# ── 3. Instalar dependencias ──────────────────────────────────────────────────
if ($SkipBuild) {
    Step "3/8" "Omitiendo dependencias (--SkipBuild)"
} elseif (-not $SkipVenv) {
    Step "3/8" "Instalando dependencias del proyecto"

    & $VenvPython -m pip install --upgrade pip @SSLFlags --quiet
    if ($LASTEXITCODE -ne 0) { Err "No se pudo actualizar pip." }

    & $VenvPython -m pip install @SSLFlags `
        -r (Join-Path $ProjectDir "requirements.txt") `
        --quiet
    if ($LASTEXITCODE -ne 0) { Err "Error instalando requirements.txt." }
    Ok "Dependencias del proyecto instaladas"

    # pywin32 necesita post-install para registrar sus DLLs en el venv
    $PyWin32PostInstall = Join-Path $VenvDir "Scripts\pywin32_postinstall.py"
    if (Test-Path $PyWin32PostInstall) {
        & $VenvPython $PyWin32PostInstall -install 2>&1 | Out-Null
        Ok "pywin32 post-install ejecutado"
    }

    # Nuitka y dependencias de compilación
    & $VenvPython -m pip install @SSLFlags `
        "nuitka" `
        "ordered-set" `
        "zstandard" `
        --quiet
    if ($LASTEXITCODE -ne 0) { Err "No se pudo instalar Nuitka." }

    $nuitkaVer = & $VenvPython -m nuitka --version 2>&1 | Select-Object -First 1
    Ok "Nuitka: $nuitkaVer"
}

# ── 4. Verificar assets críticos ─────────────────────────────────────────────
Step "4/8" "Verificando assets"

$tessdata = Join-Path $ProjectDir "assets\tessdata"
if (-not (Test-Path $tessdata)) { Err "assets\tessdata no encontrado." }
$tdFiles = Get-ChildItem $tessdata -Filter "*.traineddata"
if ($tdFiles.Count -eq 0) { Err "No hay modelos .traineddata en assets\tessdata." }
$tdSize = ($tdFiles | Measure-Object -Property Length -Sum).Sum / 1MB
Ok "tessdata: $($tdFiles.Count) modelos ($([math]::Round($tdSize,1)) MB)"

$icoPath = Join-Path $ProjectDir "assets\icon.ico"
if (-not (Test-Path $icoPath)) { Err "Ícono no encontrado: $icoPath" }
Ok "Ícono: OK"

# ── 5. Compilar con Nuitka ────────────────────────────────────────────────────
if (-not $SkipBuild) {
    Step "5/8" "Compilando con Nuitka (esto tarda 15-40 minutos)"
    Write-Host "    El compilador C descargará dependencias si no están instaladas." -ForegroundColor DarkGray

    New-Item -ItemType Directory -Force -Path $NuitkaOut | Out-Null

    # Obtener ruta del certifi CA bundle para SSL de requests
    $certifiPath = & $VenvPython -c "import certifi; print(certifi.where())" 2>$null
    $certifiFlag = if ($certifiPath -and (Test-Path $certifiPath)) {
        "--include-data-files=$certifiPath=certifi/cacert.pem"
    } else { "" }

    $nuitkaArgs = @(
        "-m", "nuitka",

        # ── Modo de distribución ──────────────────────────────────────────
        "--standalone",                          # carpeta portable (gratis)

        # ── PyQt6 ────────────────────────────────────────────────────────
        "--enable-plugin=pyqt6",
        "--include-qt-plugins=platforms,styles,imageformats",

        # ── Assets y datos ────────────────────────────────────────────────
        "--include-data-dir=assets=assets",      # tessdata, iconos, etc.
        "--include-package-data=certifi",        # CA bundle para requests

        # ── Módulos con imports dinámicos ─────────────────────────────────
        "--include-module=win32com.client",
        "--include-module=win32com.server.util",
        "--include-module=pythoncom",
        "--include-module=pywintypes",
        "--include-module=winreg",
        "--include-module=ctypes",
        "--include-module=charset_normalizer",
        "--include-module=idna",
        "--include-module=urllib3",
        "--nofollow-import-to=win32com.gen_py",  # evitar miles de stubs COM

        # ── Excluir módulos innecesarios ──────────────────────────────────
        "--nofollow-import-to=tkinter",
        "--nofollow-import-to=test",
        "--nofollow-import-to=unittest",
        "--nofollow-import-to=IPython",
        "--nofollow-import-to=matplotlib",
        "--nofollow-import-to=scipy",
        "--nofollow-import-to=pandas",

        # ── Metadatos del ejecutable Windows ─────────────────────────────
        "--windows-console-mode=disable",
        "--windows-icon-from-ico=assets\icon.ico",
        "--windows-company-name=GRUPO OCMX",
        "--windows-product-name=PDFlex",
        "--windows-product-version=$AppVersion.0",
        "--windows-file-version=$AppVersion.0",
        "--windows-file-description=PDFlex - Suite de herramientas PDF",

        # ── Salida ────────────────────────────────────────────────────────
        "--output-dir=$NuitkaOut",
        "--output-filename=PDFlex.exe",

        # ── Optimización ─────────────────────────────────────────────────
        "--python-flag=-O",                      # desactiva assert y __debug__
        "--jobs=4",                              # compilación paralela

        # ── Descargas automáticas (compilador C si no está) ───────────────
        "--assume-yes-for-downloads",

        "main.py"
    )

    if ($certifiFlag) { $nuitkaArgs = $nuitkaArgs + $certifiFlag }

    Write-Host "    Comando Nuitka lanzado. Salida en tiempo real:" -ForegroundColor DarkGray
    & $VenvPython @nuitkaArgs
    if ($LASTEXITCODE -ne 0) { Err "Nuitka terminó con error. Revisa la salida arriba." }
    Ok "Compilación Nuitka completada"
}

# ── 6. Post-procesado del output ──────────────────────────────────────────────
Step "6/8" "Post-procesando distribución"

if ($SkipBuild) {
    if (-not (Test-Path $AppDir)) {
        Err "No existe dist\PDFlex\. Ejecuta sin -SkipBuild para compilar la app antes de generar el instalador."
    }
    Ok "Usando distribución existente: dist\PDFlex\"
} else {
    # Nuitka genera: .nuitka_build/main.dist/
    $nuitkaMainDist = Join-Path $NuitkaOut "main.dist"
    if (-not (Test-Path $nuitkaMainDist)) {
        Err "No se encontró el directorio de salida: $nuitkaMainDist"
    }

    # Mover y renombrar a dist\PDFlex\
    New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
    if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
    Move-Item $nuitkaMainDist $AppDir
    Ok "Directorio renombrado: dist\PDFlex\"
}

# Copiar DLLs de pywin32 que Nuitka puede no detectar automáticamente
$pywin32SysDir = Join-Path $VenvDir "Lib\site-packages\pywin32_system32"
if ((-not $SkipBuild) -and (Test-Path $pywin32SysDir)) {
    $win32Dlls = Get-ChildItem $pywin32SysDir -Filter "*.dll"
    foreach ($dll in $win32Dlls) {
        $dest = Join-Path $AppDir $dll.Name
        if (-not (Test-Path $dest)) {
            Copy-Item $dll.FullName -Destination $AppDir
            Ok "Copiado: $($dll.Name)"
        }
    }
}

# Verificar que el .exe existe y tiene tamaño razonable
$exePath = Join-Path $AppDir "PDFlex.exe"
if (-not (Test-Path $exePath)) { Err "PDFlex.exe no se encontró en dist\PDFlex\" }
$exeSizeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
if ($exeSizeMB -lt 5) { Warn "PDFlex.exe parece demasiado pequeño ($exeSizeMB MB) — posible error." }
else                  { Ok "PDFlex.exe: $exeSizeMB MB" }

# Verificar tessdata fue copiado
$tdDest = Join-Path $AppDir "assets\tessdata"
if (Test-Path $tdDest) {
    $tdCount = (Get-ChildItem $tdDest -Filter "*.traineddata").Count
    Ok "tessdata en distribución: $tdCount modelos"
} else {
    Warn "tessdata NO copiado a dist\PDFlex\assets\tessdata — verifica el build."
}

# Tamaño total de la distribución
$totalMB = [math]::Round(
    (Get-ChildItem $AppDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB, 1
)
Ok "Tamaño total: $totalMB MB"

# ── 7. Compilar instalador directo ────────────────────────────────────────────
Step "7/8" "Compilando instalador Inno directo"

$setupBuilder = Join-Path $ProjectDir "build_setup.ps1"
if (-not (Test-Path $setupBuilder)) {
    Err "build_setup.ps1 no encontrado."
}

$setupArgs = @{}
if ($SkipSetupBootstrapper) { Warn "-SkipSetupBootstrapper esta obsoleto; se generara el instalador directo." }
if ($SkipSign)              { $setupArgs["SkipSign"] = $true }

& $setupBuilder @setupArgs
if ($LASTEXITCODE -ne 0) { Err "build_setup.ps1 terminó con error $LASTEXITCODE." }

$setupExe = Join-Path $DistDir "PDFlex_${AppVersion}_Setup.exe"
if (-not (Test-Path $setupExe)) {
    Err "No se encontró el instalador esperado: $setupExe"
}

# ── 8. Resumen final ──────────────────────────────────────────────────────────
Step "8/8" "Build completado"

$exeInfo = Get-Item $exePath
Write-Host ""
Write-Host "  ┌─────────────────────────────────────────────────┐" -ForegroundColor Green
Write-Host "  │  PDFlex v$AppVersion — Build exitoso                  │" -ForegroundColor Green
Write-Host "  │                                                   │" -ForegroundColor Green
Write-Host "  │  Distribución: dist\PDFlex\                       │" -ForegroundColor Green
Write-Host "  │  Ejecutable:   PDFlex.exe ($exeSizeMB MB)              │" -ForegroundColor Green
Write-Host "  │  Total:        $totalMB MB                             │" -ForegroundColor Green

$setupExe2 = Get-Item $setupExe -ErrorAction SilentlyContinue
if ($setupExe2) {
    $s2MB = [math]::Round($setupExe2.Length / 1MB, 1)
    Write-Host "  │  Instalador:   $($setupExe2.Name) ($s2MB MB)  │" -ForegroundColor Green
}
Write-Host "  └─────────────────────────────────────────────────┘" -ForegroundColor Green
Write-Host ""

Start-Process explorer.exe $DistDir
