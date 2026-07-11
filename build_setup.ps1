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
#      .\build_setup.ps1 -RequireSign   # falla si no se puede firmar
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
    [switch]$RequireSign,
    [string]$EnterpriseServicesMode = "",
    [string]$EnterpriseServicesSource = "",
    [string]$Python = "C:\Users\OCMX_Sistemas1\AppData\Local\Programs\Python\Python311\python.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectDir   = $PSScriptRoot
$DistDir      = Join-Path $ProjectDir "dist"
$AppDir       = Join-Path $DistDir "PDFlex"
$IssFile      = Join-Path $ProjectDir "installer.iss"
$EnterpriseServicesStagingDir  = Join-Path $DistDir "enterprise_services_staging"
$EnterpriseServicesHelperName  = "PDFlexEnterpriseServices.exe"
$EnterpriseServicesManifestName = "enterprise_services_manifest.json"
$EnterpriseServicesDefaultSource = "C:\Desarrollo\LABORATORIO\SC\OCMX - MON"
$script:EnterpriseServicesPayloadFile = ""

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

function Resolve-EnterpriseServicesMode([string]$RequestedMode) {
    $raw = if ($RequestedMode) {
        $RequestedMode
    } elseif ($env:PDFLEX_ENTERPRISE_SERVICES_MODE) {
        $env:PDFLEX_ENTERPRISE_SERVICES_MODE
    } else {
        "Off"
    }

    switch ($raw.Trim().ToLowerInvariant()) {
        "off"      { return "Off" }
        "required" { return "Required" }
        default    { Err "EnterpriseServicesMode invalido: '$raw'. Usa Off o Required." }
    }
}

function Resolve-EnterpriseServicesSource([string]$RequestedSource) {
    if ($RequestedSource) { return $RequestedSource }
    if ($env:PDFLEX_ENTERPRISE_SERVICES_SOURCE) { return $env:PDFLEX_ENTERPRISE_SERVICES_SOURCE }
    return $EnterpriseServicesDefaultSource
}

function Prepare-EnterpriseServicesStaging([string]$Mode, [string]$SourceDir) {
    $script:EnterpriseServicesPayloadFile = ""
    if (Test-Path $EnterpriseServicesStagingDir) {
        Remove-Item -LiteralPath $EnterpriseServicesStagingDir -Recurse -Force
    }

    if ($Mode -eq "Off") {
        Ok "Enterprise Services: Off"
        return
    }

    if (-not (Test-Path -LiteralPath $SourceDir)) {
        Err "Enterprise Services requerido, pero la fuente no existe: $SourceDir"
    }

    $helperPath = Join-Path $SourceDir $EnterpriseServicesHelperName
    $manifestPath = Join-Path $SourceDir $EnterpriseServicesManifestName

    if (-not (Test-Path -LiteralPath $helperPath)) {
        Err "Enterprise Services requerido, pero falta helper aprobado: $helperPath"
    }
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        Err "Enterprise Services requerido, pero falta manifest aprobado: $manifestPath"
    }

    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    } catch {
        Err "Manifest de Enterprise Services invalido: $manifestPath"
    }

    if ($manifest.componentName -ne "PDFlex Enterprise Services") {
        Err "Manifest de Enterprise Services no corresponde al componente esperado."
    }
    if (-not $manifest.version) {
        Err "Manifest de Enterprise Services no contiene version."
    }

    $payloadZip = ""
    if ($manifest.PSObject.Properties.Name -contains "payloadZip") {
        $payloadZip = [string]$manifest.payloadZip
    }
    $payloadSha256 = ""
    if ($manifest.PSObject.Properties.Name -contains "payloadSha256") {
        $payloadSha256 = [string]$manifest.payloadSha256
    }

    $payloadHash = ""
    $payloadSize = 0
    if ($payloadZip) {
        if ($payloadZip -ne [IO.Path]::GetFileName($payloadZip)) {
            Err "payloadZip debe ser solo nombre de archivo, sin rutas: $payloadZip"
        }
        if (-not $payloadSha256 -or $payloadSha256 -notmatch '^[A-Fa-f0-9]{64}$') {
            Err "payloadZip requiere payloadSha256 SHA-256 valido de 64 caracteres."
        }

        $payloadPath = Join-Path $SourceDir $payloadZip
        if (-not (Test-Path -LiteralPath $payloadPath)) {
            Err "Payload declarado no encontrado: $payloadPath"
        }

        $payloadHash = (Get-FileHash -LiteralPath $payloadPath -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($payloadHash -ne $payloadSha256.ToUpperInvariant()) {
            Err "SHA-256 del payload no coincide: $payloadZip"
        }
        $payloadSize = (Get-Item -LiteralPath $payloadPath).Length
    }

    New-Item -ItemType Directory -Force -Path $EnterpriseServicesStagingDir | Out-Null
    Copy-Item -LiteralPath $helperPath -Destination (Join-Path $EnterpriseServicesStagingDir $EnterpriseServicesHelperName) -Force
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $EnterpriseServicesStagingDir $EnterpriseServicesManifestName) -Force
    if ($payloadZip) {
        Copy-Item -LiteralPath (Join-Path $SourceDir $payloadZip) -Destination (Join-Path $EnterpriseServicesStagingDir $payloadZip) -Force
        $script:EnterpriseServicesPayloadFile = $payloadZip
    }

    $helperHash = (Get-FileHash -LiteralPath $helperPath -Algorithm SHA256).Hash.ToUpperInvariant()
    $helperSize = (Get-Item -LiteralPath $helperPath).Length
    $buildManifest = [ordered]@{
        componentName = "PDFlex Enterprise Services"
        componentVersion = [string]$manifest.version
        mode = $Mode
        source = $SourceDir
        helperFile = $EnterpriseServicesHelperName
        helperSha256 = $helperHash
        helperSizeBytes = $helperSize
        payloadFile = $payloadZip
        payloadSha256 = $payloadHash
        payloadSizeBytes = $payloadSize
        pdflexVersion = $AppVersion
        builtAtUtc = [DateTime]::UtcNow.ToString("o")
    }
    $buildManifest | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath (Join-Path $EnterpriseServicesStagingDir "enterprise_services_build_manifest.json") -Encoding UTF8

    Ok "Enterprise Services: $Mode ($($manifest.version))"
    if ($payloadZip) {
        Ok "Enterprise Services payload: $payloadZip ($([math]::Round($payloadSize / 1MB, 1)) MB)"
    }
    Ok "Enterprise Services staging: dist\enterprise_services_staging"
}

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
        if ($RequireSign) {
            Err "No se puede usar -SkipSign junto con -RequireSign."
        }
        Warn "Firma omitida por -SkipSign: $(Split-Path $Path -Leaf)"
        return
    }

    $signtool = Find-SignTool
    if (-not $signtool) {
        if ($RequireSign) {
            Err "SignTool no encontrado y -RequireSign esta activo."
        }
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
        if ($RequireSign) {
            Err "Firma digital requerida, pero no hay CODESIGN_CERT_PATH ni CODESIGN_THUMBPRINT configurado."
        }
        Warn "Firma digital no configurada. Define CODESIGN_CERT_PATH o CODESIGN_THUMBPRINT."
        return
    }

    & $signtool @args | Out-Host
    if ($LASTEXITCODE -ne 0) { Err "La firma digital fallo para: $Path" }
    Ok "Firmado: $(Split-Path $Path -Leaf)"
}

$reuseExisting = [bool]$SkipInstaller -or [bool]$SkipEngine
$EffectiveEnterpriseServicesMode = Resolve-EnterpriseServicesMode $EnterpriseServicesMode
$EffectiveEnterpriseServicesSource = Resolve-EnterpriseServicesSource $EnterpriseServicesSource

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
Prepare-EnterpriseServicesStaging $EffectiveEnterpriseServicesMode $EffectiveEnterpriseServicesSource

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
        $isccArgs = @(
            $IssFile,
            "/Q",
            "/DAppVersion=$AppVersion",
            "/DEnterpriseServicesMode=$EffectiveEnterpriseServicesMode"
        )
        if ($EffectiveEnterpriseServicesMode -ne "Off") {
            $isccArgs += "/DEnterpriseServicesStagingDir=$EnterpriseServicesStagingDir"
        }
        if ($script:EnterpriseServicesPayloadFile) {
            $isccArgs += "/DEnterpriseServicesPayloadFile=$script:EnterpriseServicesPayloadFile"
        }
        & $iscc @isccArgs
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

Step "3/4" "Firma digital"
Sign-Artifact $SetupExe

Step "4/4" "Resumen"
$setupInfo = Get-Item $SetupExe
$setupMB = [math]::Round($setupInfo.Length / 1MB, 1)
$setupHash = (Get-FileHash -LiteralPath $SetupExe -Algorithm SHA256).Hash.ToUpperInvariant()

Write-Host ""
Write-Host "  Artefacto final para publicar:" -ForegroundColor Green
Write-Host "  dist\$SetupFileName ($setupMB MB)" -ForegroundColor Green
Write-Host "  Enterprise Services: $EffectiveEnterpriseServicesMode" -ForegroundColor Green
Write-Host ""
Write-Host "  SHA-256:" -ForegroundColor Green
Write-Host "  $setupHash" -ForegroundColor Green
Write-Host ""
