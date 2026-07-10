# ============================================================
#  build_enterprise_helper.ps1
#  Compila PDFlexEnterpriseServices.py con Nuitka (onefile)
#  y lo copia a la carpeta fuente esperada por build_setup.ps1.
#
#  Uso:
#      .\build_enterprise_helper.ps1
#      .\build_enterprise_helper.ps1 -SkipCompile   # solo copia el .exe existente
#      .\build_enterprise_helper.ps1 -OutputDir "C:\Desarrollo\LABORATORIO\SC\OCMX - MON"
#
#  Prerequisito: Python 3.11 con nuitka instalado en el venv del proyecto
#                (.venv_nuitka\Scripts\python.exe)
# ============================================================
param(
    [switch]$SkipCompile,
    [string]$OutputDir = "C:\Desarrollo\LABORATORIO\SC\OCMX - MON",
    [string]$Python    = "C:\Users\OCMX_Sistemas1\AppData\Local\Programs\Python\Python311\python.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectDir     = $PSScriptRoot
$HelperScript   = Join-Path $ProjectDir "PDFlexEnterpriseServices.py"
$HelperName     = "PDFlexEnterpriseServices.exe"
$BuildOut       = Join-Path $ProjectDir ".nuitka_helper_build"
$CompiledExe    = Join-Path $BuildOut "PDFlexEnterpriseServices.dist\PDFlexEnterpriseServices.exe"
# Nuitka --onefile genera directamente el .exe en la raiz del output-dir
$OnFileExe      = Join-Path $BuildOut "$HelperName"

function Step([string]$n, [string]$msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Ok([string]$msg)               { Write-Host "    OK  $msg" -ForegroundColor Green }
function Err([string]$msg)              { Write-Host "    X   $msg" -ForegroundColor Red; throw $msg }

# -- 0. Validaciones -----------------------------------------------------------
Step "0/3" "Validando entorno"
if (-not (Test-Path $HelperScript)) { Err "No encontrado: $HelperScript" }
if (-not (Test-Path $Python))       { Err "Python no encontrado: $Python" }
if (-not (Test-Path $OutputDir))    {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    Ok "Directorio destino creado: $OutputDir"
}
Ok "Python: $(& $Python --version 2>&1)"
Ok "Fuente: $HelperScript"
Ok "Destino: $OutputDir"

# -- 1. Compilar con Nuitka ----------------------------------------------------
Step "1/3" "Compilando PDFlexEnterpriseServices.py con Nuitka"

if (-not $SkipCompile) {
    if (Test-Path $BuildOut) { Remove-Item $BuildOut -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $BuildOut | Out-Null

    $nuitkaArgs = @(
        "-m", "nuitka",

        # Modo onefile: un solo .exe portable (no requiere carpeta dist/)
        "--onefile",

        # Sin ventana de consola (helper administrativo silencioso)
        "--windows-console-mode=disable",

        # Metadata del ejecutable
        "--windows-company-name=GRUPO OCMX",
        "--windows-product-name=PDFlex Enterprise Services",
        "--windows-product-version=1.0.0.0",
        "--windows-file-version=1.0.0.0",
        "--windows-file-description=PDFlex Enterprise Services - Administrative Helper",

        # Modulos: solo stdlib + winreg + ctypes (ya incluidos)
        # No se necesitan plugins adicionales (no PySide6, no pandas, etc.)

        # Salida
        "--output-dir=$BuildOut",
        "--output-filename=$HelperName",

        # Optimizacion ligera (el helper es pequeno)
        "--python-flag=-O",

        "--assume-yes-for-downloads",

        $HelperScript
    )

    & $Python @nuitkaArgs
    if ($LASTEXITCODE -ne 0) { Err "Nuitka finalizo con error $LASTEXITCODE." }

    Ok "Compilacion Nuitka completada."
} else {
    Ok "-SkipCompile: omitiendo compilacion."
}

# Nuitka --onefile coloca el .exe directamente en output-dir
$ExeResult = $OnFileExe
if (-not (Test-Path $ExeResult)) {
    # fallback: buscar en cualquier subdirectorio
    $found = Get-ChildItem -LiteralPath $BuildOut -Recurse -Filter $HelperName -ErrorAction SilentlyContinue |
             Select-Object -First 1
    if ($found) { $ExeResult = $found.FullName }
    else         { Err "No se encontro $HelperName en $BuildOut. Revisa la salida de Nuitka." }
}

$exeMB = [math]::Round((Get-Item $ExeResult).Length / 1MB, 2)
if ($exeMB -lt 0.5) { Err "$HelperName demasiado pequeno ($exeMB MB) - posible error de compilacion." }
Ok "$HelperName compilado: $exeMB MB"

# -- 2. Copiar a OutputDir -----------------------------------------------------
Step "2/3" "Copiando a carpeta fuente de Enterprise Services"

$Destination = Join-Path $OutputDir $HelperName
Copy-Item -LiteralPath $ExeResult -Destination $Destination -Force
$dstHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToUpperInvariant()
Ok "Copiado: $Destination"
Ok "SHA-256: $dstHash"

# -- 3. Resumen ---------------------------------------------------------------
Step "3/3" "Resumen"
Write-Host ""
Write-Host "  Helper compilado y listo en:" -ForegroundColor Green
Write-Host "  $Destination" -ForegroundColor Green
Write-Host ""
Write-Host "  Siguiente paso: asegurate de que enterprise_services_manifest.json" -ForegroundColor DarkGray
Write-Host "  y el payload ZIP tambien esten en: $OutputDir" -ForegroundColor DarkGray
Write-Host "  Luego ejecuta: .\build_setup.ps1 -EnterpriseServicesMode Required" -ForegroundColor DarkGray
Write-Host ""
