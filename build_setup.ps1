# ============================================================
#  build_setup.ps1  -  Genera el instalador directo de PDFlex
#
#  Resultado:
#      dist\PDFlex_<version>_Setup.exe  (Inno Setup directo)
#
#  Uso:
#      .\build_setup.ps1
#      .\build_setup.ps1 -SkipInstaller # reutiliza setup existente
#      .\build_setup.ps1 -SkipSign      # omite firma aunque haya variables
#
#  Firma opcional por variables de entorno:
#      SIGNTOOL_PATH
#      CODESIGN_CERT_PATH
#      CODESIGN_CERT_PASSWORD
#      CODESIGN_THUMBPRINT
#      CODESIGN_TIMESTAMP_URL
# ============================================================
param(
    [switch]$SkipInstaller,
    [switch]$SkipEngine,
    [switch]$SkipBootstrapper,
    [switch]$SkipSign,
    [string]$Python = "C:\Users\OCMX_Sistemas1\AppData\Local\Programs\Python\Python311\python.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectDir   = $PSScriptRoot
$DistDir      = Join-Path $ProjectDir "dist"
$AppDir       = Join-Path $DistDir "PDFlex"
$IssFile      = Join-Path $ProjectDir "installer.iss"

$UpdateConfig = Get-Content -LiteralPath (Join-Path $ProjectDir "core\update_config.py") -Raw
if ($UpdateConfig -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') {
    throw "No se pudo leer APP_VERSION desde core\update_config.py"
}
$AppVersion    = $Matches[1]
$SetupFileName = "PDFlex_${AppVersion}_Setup.exe"
$SetupExe      = Join-Path $DistDir $SetupFileName

function Step([string]$n, [string]$msg) {
    Write-Host "`n[$n] $msg" -ForegroundColor Cyan
}
function Ok([string]$msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "    !   $msg" -ForegroundColor Yellow }
function Err([string]$msg)  { Write-Host "    X   $msg" -ForegroundColor Red; throw $msg }

function Find-ISCC {
    @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "C:\ProgramData\chocolatey\bin\ISCC.exe",
        (Get-Command ISCC -ErrorAction SilentlyContinue)?.Source
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

function Find-SignTool {
    $fromPath = (Get-Command signtool -ErrorAction SilentlyContinue)?.Source
    $kitRoots = @(
        "C:\Program Files (x86)\Windows Kits\10\bin",
        "C:\Program Files\Windows Kits\10\bin"
    )
    $kitCandidates = foreach ($root in $kitRoots) {
        if (Test-Path $root) {
            Get-ChildItem -LiteralPath $root -Recurse -Filter "signtool.exe" -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match "\\x64\\signtool\.exe$" } |
                Sort-Object FullName -Descending |
                Select-Object -ExpandProperty FullName
        }
    }

    @(
        $env:SIGNTOOL_PATH,
        $fromPath,
        $kitCandidates
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

function Sign-Artifact([string]$Path) {
    if ($SkipSign) {
        Warn "Firma omitida por -SkipSign: $(Split-Path $Path -Leaf)"
        return
    }

    $signtool = Find-SignTool
    if (-not $signtool) {
        Warn "SignTool no encontrado. El instalador queda sin firma digital."
        return
    }

    $timestamp = if ($env:CODESIGN_TIMESTAMP_URL) {
        $env:CODESIGN_TIMESTAMP_URL
    } else {
        "http://timestamp.digicert.com"
    }

    if ($env:CODESIGN_CERT_PATH) {
        if (-not (Test-Path $env:CODESIGN_CERT_PATH)) {
            Err "CODESIGN_CERT_PATH no existe: $env:CODESIGN_CERT_PATH"
        }
        $args = @(
            "sign", "/fd", "SHA256", "/td", "SHA256", "/tr", $timestamp,
            "/f", $env:CODESIGN_CERT_PATH
        )
        if ($env:CODESIGN_CERT_PASSWORD) {
            $args += @("/p", $env:CODESIGN_CERT_PASSWORD)
        }
        $args += $Path
    } elseif ($env:CODESIGN_THUMBPRINT) {
        $args = @(
            "sign", "/fd", "SHA256", "/td", "SHA256", "/tr", $timestamp,
            "/sha1", $env:CODESIGN_THUMBPRINT, $Path
        )
    } else {
        Warn "Firma digital no configurada. Define CODESIGN_CERT_PATH o CODESIGN_THUMBPRINT."
        return
    }

    & $signtool @args | Out-Host
    if ($LASTEXITCODE -ne 0) { Err "La firma digital fallo para: $Path" }
    Ok "Firmado: $(Split-Path $Path -Leaf)"
}

$reuseExisting = [bool]$SkipInstaller -or [bool]$SkipEngine

Step "1/4" "Validando artefactos base"
if ($SkipBootstrapper) {
    Warn "-SkipBootstrapper ya no es necesario; se usa Inno directo."
}
if ($SkipEngine) {
    Warn "-SkipEngine se interpreta como -SkipInstaller porque ya no hay motor interno."
}
if (-not (Test-Path $IssFile)) { Err "installer.iss no encontrado." }
if (-not (Test-Path (Join-Path $AppDir "PDFlex.exe"))) {
    Err "No existe dist\PDFlex\PDFlex.exe. Ejecuta .\build_nuitka.ps1 primero."
}
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
Ok "Version: $AppVersion"
Ok "Distribucion: dist\PDFlex\"

Step "2/4" "Generando instalador Inno Setup directo"
if ($reuseExisting) {
    if (-not (Test-Path $SetupExe)) {
        Err "No existe $SetupFileName y se pidio reutilizar el instalador."
    }
    Ok "Instalador existente: $SetupFileName"
} else {
    $iscc = Find-ISCC
    if (-not $iscc) { Err "ISCC.exe no encontrado. Instala Inno Setup 6." }

    foreach ($old in Get-ChildItem -Path $DistDir -Filter "PDFlex_*_Setup.exe" -ErrorAction SilentlyContinue) {
        Remove-Item -LiteralPath $old.FullName -Force
        Ok "Eliminado: $($old.Name)"
    }
    foreach ($old in Get-ChildItem -Path $DistDir -Filter "PDFlex_*_Engine.exe" -ErrorAction SilentlyContinue) {
        Remove-Item -LiteralPath $old.FullName -Force
        Ok "Eliminado motor obsoleto: $($old.Name)"
    }

    Push-Location $ProjectDir
    try {
        & $iscc $IssFile /Q "/DAppVersion=$AppVersion"
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) { Err "Inno Setup termino con error $LASTEXITCODE." }
    if (-not (Test-Path $SetupExe)) {
        Err "Inno finalizo sin error, pero no se encontro $SetupFileName."
    }
    $setupMB = [math]::Round((Get-Item $SetupExe).Length / 1MB, 1)
    Ok "Instalador Inno: $SetupFileName ($setupMB MB)"
}

Step "3/4" "Firma opcional"
Sign-Artifact $SetupExe

Step "4/4" "Resumen"
$setupInfo = Get-Item $SetupExe
$setupMB = [math]::Round($setupInfo.Length / 1MB, 1)
$setupHash = (Get-FileHash -LiteralPath $SetupExe -Algorithm SHA256).Hash.ToUpperInvariant()

Write-Host ""
Write-Host "  Artefacto final para publicar:" -ForegroundColor Green
Write-Host "  dist\$SetupFileName ($setupMB MB)" -ForegroundColor Green
Write-Host ""
Write-Host "  SHA-256:" -ForegroundColor Green
Write-Host "  $setupHash" -ForegroundColor Green
Write-Host ""
