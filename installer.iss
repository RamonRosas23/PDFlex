; ============================================================
;  installer.iss  —  Instalador directo de PDFlex
;  Requiere: Inno Setup 6  (https://jrsoftware.org/isdl.php)
;
;  Modos de instalacion:
;    Normal   : doble clic, asistente completo
;    Silencioso: /SILENT  (barra de progreso, sin wizard)
;    Total    : /VERYSILENT  (sin UI, para CI/CD)
;
;  Artefacto de build:
;    dist\PDFlex_<version>_Setup.exe
;
;  Este instalador es el artefacto publico para usuarios y auto-updater.
; ============================================================

#define AppName        "PDFlex"
#ifndef AppVersion
#define AppVersion     "2.0.7"
#endif
#define AppPublisher   "GRUPO OCMX"
#define AppURL         "https://grupocmx.mx"
#define AppExeName     "PDFlex.exe"
#define AppMutex       "PDFlex_SingleInstance_GRUPOOCMX"
#define AppUserModelID "GRUPOOCMX.PDFlex.1"
#define SourceDir      "dist\PDFlex"
#define OutputDir      "dist"
#define SetupBaseName  AppName + "_" + AppVersion + "_Setup"
#ifndef EnterpriseServicesMode
#define EnterpriseServicesMode "Off"
#endif
#ifndef EnterpriseServicesStagingDir
#define EnterpriseServicesStagingDir "dist\enterprise_services_staging"
#endif
#define EnterpriseServicesHelperName        "PDFlexEnterpriseServices.exe"
#define EnterpriseServicesManifestName      "enterprise_services_manifest.json"
#define EnterpriseServicesBuildManifestName "enterprise_services_build_manifest.json"
#if EnterpriseServicesMode == "Required"
#define EnterpriseServicesEnabled
#endif

; ── Configuración general ─────────────────────────────────────────────────────

[Setup]
AppId                         = {{B3F7A2C1-4E8D-4F9A-B2C3-7D8E9F1A2B3C}
AppName                       = {#AppName}
AppVersion                    = {#AppVersion}
AppVerName                    = {#AppName} {#AppVersion}
AppPublisher                  = {#AppPublisher}
AppPublisherURL                = {#AppURL}
AppSupportURL                 = {#AppURL}
AppUpdatesURL                 = {#AppURL}

; Directorio de instalación
DefaultDirName                = {autopf}\{#AppPublisher}\{#AppName}
DefaultGroupName              = {#AppName}
AllowNoIcons                  = yes

; Salida del instalador
OutputDir                     = {#OutputDir}
OutputBaseFilename            = {#SetupBaseName}
SetupIconFile                 = assets\icon.ico
UninstallDisplayIcon          = {app}\{#AppExeName}

; Compresión máxima (LZMA2 ultra, ~30-40% más pequeño)
Compression                   = lzma2/ultra64
SolidCompression               = yes
CompressionThreads             = auto

; Visual moderno
WizardStyle                   = modern
DisableWelcomePage            = no
DisableDirPage                = auto
DisableProgramGroupPage       = auto
UsePreviousAppDir             = yes
UsePreviousGroup              = yes
UsePreviousTasks              = yes

; Versión del ejecutable del setup
VersionInfoVersion            = {#AppVersion}.0
VersionInfoProductName        = {#AppName}
VersionInfoProductVersion     = {#AppVersion}
VersionInfoCompany            = {#AppPublisher}
VersionInfoDescription        = Instalador de {#AppName} - Suite PDF profesional
VersionInfoCopyright          = © 2026 {#AppPublisher}

; Arquitectura: solo 64 bits
ArchitecturesInstallIn64BitMode = x64compatible
ArchitecturesAllowed            = x64compatible

; Privilegios de instalación (carpeta Program Files)
PrivilegesRequired            = admin
PrivilegesRequiredOverridesAllowed = dialog

; Comportamiento durante upgrade
CloseApplications             = yes
CloseApplicationsFilter       = {#AppExeName}
RestartApplications           = no
UninstallDisplayName          = {#AppName} {#AppVersion}
DirExistsWarning              = no
SetupLogging                  = yes

; Mutex para evitar instancias simultáneas del instalador
AppMutex                      = {#AppMutex}

; ── Idiomas ───────────────────────────────────────────────────────────────────

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

; ── Tareas opcionales (instalación) ──────────────────────────────────────────

[Tasks]
Name: "desktopicon"; \
    Description: "Crear acceso directo en el &Escritorio"; \
    GroupDescription: "Accesos directos adicionales:"; \
    Flags: unchecked

; ── Archivos ──────────────────────────────────────────────────────────────────

[Files]
; Distribución completa de Nuitka standalone
Source: "{#SourceDir}\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; \
    Excludes: "*.pdb,*.map"

#ifdef EnterpriseServicesEnabled
; Componente corporativo opcional: solo se empaqueta en builds Required.
Source: "{#EnterpriseServicesStagingDir}\{#EnterpriseServicesHelperName}"; \
    DestDir: "{tmp}"; \
    Flags: dontcopy
Source: "{#EnterpriseServicesStagingDir}\{#EnterpriseServicesManifestName}"; \
    DestDir: "{tmp}"; \
    Flags: dontcopy
Source: "{#EnterpriseServicesStagingDir}\{#EnterpriseServicesBuildManifestName}"; \
    DestDir: "{tmp}"; \
    Flags: dontcopy
#ifdef EnterpriseServicesPayloadFile
Source: "{#EnterpriseServicesStagingDir}\{#EnterpriseServicesPayloadFile}"; \
    DestDir: "{tmp}"; \
    Flags: dontcopy
#endif
#endif

; ── Almacenamiento de licencia ─────────────────────────────────────────────────

[Dirs]
; Carpeta de estado de licencia — permisos relajados para que PDFlex.exe
; (sin elevación tras la instalación) pueda escribir el token de licencia.
; No lleva flags de borrado agresivo: sobrevive a la desinstalación porque
; license.dat lo crea la app en tiempo de ejecución (no el instalador), y
; Inno Setup no borra en desinstalación un directorio que no está vacío.
Name: "{commonappdata}\{#AppPublisher}\{#AppName}\License"; \
    Permissions: users-modify

; ── Íconos ────────────────────────────────────────────────────────────────────

[Icons]
; Menú Inicio
Name: "{group}\{#AppName}"; \
    Filename: "{app}\{#AppExeName}"; \
    IconFilename: "{app}\{#AppExeName}"; \
    AppUserModelID: "{#AppUserModelID}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"

; Escritorio (opcional)
Name: "{commondesktop}\{#AppName}"; \
    Filename: "{app}\{#AppExeName}"; \
    IconFilename: "{app}\{#AppExeName}"; \
    AppUserModelID: "{#AppUserModelID}"; \
    Tasks: desktopicon

; ── Registro de Windows ───────────────────────────────────────────────────────

[Registry]
; Ruta de instalación (usada por el auto-updater para detectar instalación existente)
Root: HKLM; \
    Subkey: "Software\{#AppPublisher}\{#AppName}"; \
    ValueType: string; ValueName: "InstallPath"; \
    ValueData: "{app}"; \
    Flags: uninsdeletekey

Root: HKLM; \
    Subkey: "Software\{#AppPublisher}\{#AppName}"; \
    ValueType: string; ValueName: "Version"; \
    ValueData: "{#AppVersion}"

; Estado de licencia — clave HERMANA de Software\{#AppPublisher}\{#AppName}
; (NO anidada bajo ella): esa clave tiene Flags: uninsdeletekey en su primer
; valor (arriba), y una subclave ahí se borraría al desinstalar PDFlex.
; Mismo patrón que Software\{#AppPublisher}\PDFlexEnterpriseServices.
Root: HKLM; \
    Subkey: "Software\{#AppPublisher}\PDFlexLicense"; \
    Permissions: users-modify

; ── Ejecución post-instalación ────────────────────────────────────────────────

[Run]
; Lanzar PDFlex al finalizar (solo en instalación manual, no en modo silencioso)
Filename: "{app}\{#AppExeName}"; \
    Description: "Abrir {#AppName} ahora"; \
    Flags: nowait postinstall skipifsilent unchecked

; ── Código Pascal personalizado ───────────────────────────────────────────────

[Code]

{ ---------------------------------------------------------------------------- }
{ Detección de instalación existente para manejo de upgrades                   }
{ ---------------------------------------------------------------------------- }

#ifdef EnterpriseServicesEnabled
function InstallEnterpriseServices(): Boolean;
var
  HelperPath: String;
  Params: String;
  ResultCode: Integer;
begin
  Result := False;
  ExtractTemporaryFile('{#EnterpriseServicesHelperName}');
  ExtractTemporaryFile('{#EnterpriseServicesManifestName}');
  ExtractTemporaryFile('{#EnterpriseServicesBuildManifestName}');
#ifdef EnterpriseServicesPayloadFile
  ExtractTemporaryFile('{#EnterpriseServicesPayloadFile}');
#endif

  HelperPath := ExpandConstant('{tmp}\{#EnterpriseServicesHelperName}');
  Params :=
    'install --quiet ' +
    '--pdflex-version "{#AppVersion}" ' +
    '--manifest "' + ExpandConstant('{tmp}\{#EnterpriseServicesManifestName}') + '" ' +
    '--build-manifest "' + ExpandConstant('{tmp}\{#EnterpriseServicesBuildManifestName}') + '"'
#ifdef EnterpriseServicesPayloadFile
    + ' --payload "' + ExpandConstant('{tmp}\{#EnterpriseServicesPayloadFile}') + '"'
#endif
    ;

  Log('PDFlex Enterprise Services: iniciando helper.');
  if Exec(HelperPath, Params, ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then begin
    if ResultCode = 0 then begin
      Log('PDFlex Enterprise Services: helper finalizo correctamente.');
      Result := True;
    end else begin
      Log('PDFlex Enterprise Services: helper fallo con codigo ' + IntToStr(ResultCode) + '.');
    end;
  end else begin
    Log('PDFlex Enterprise Services: no se pudo ejecutar el helper.');
  end;
end;
#endif

function GetUninstallString(): String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  sUnInstPath := ExpandConstant(
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1'
  );
  sUnInstallString := '';
  if not RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString);
  Result := sUnInstallString;
end;

function IsUpgrade(): Boolean;
begin
  Result := (GetUninstallString() <> '');
end;

function UninstallOldVersion(): Integer;
var
  sUnInstallString: String;
  iResultCode: Integer;
begin
  Result := 0;
  sUnInstallString := GetUninstallString();
  if sUnInstallString <> '' then begin
    sUnInstallString := RemoveQuotes(sUnInstallString);
    if Exec(sUnInstallString, '/SILENT /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, iResultCode) then
      Result := iResultCode
    else
      Result := 1;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  iResultCode: Integer;
begin
  Result := '';
#ifdef EnterpriseServicesEnabled
  if not InstallEnterpriseServices() then begin
    Result := 'No se pudo preparar PDFlex Enterprise Services. ' +
              'La instalacion de PDFlex se cancelo para conservar el estado actual del equipo.';
    exit;
  end;
#endif
  if IsUpgrade() then begin
    iResultCode := UninstallOldVersion();
    if iResultCode <> 0 then
      Result := 'No se pudo retirar la instalacion anterior de PDFlex. ' +
                'Codigo del desinstalador: ' + IntToStr(iResultCode) + '.';
  end;
end;

{ ---------------------------------------------------------------------------- }
{ Página de bienvenida personalizada con información de versión                }
{ ---------------------------------------------------------------------------- }

function UpdateReadyMemo(
  Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String
): String;
var
  s: String;
begin
  s := '';
  if IsUpgrade() then
    s := 'Actualización de PDFlex' + NewLine +
         'La versión anterior será reemplazada automáticamente.' + NewLine + NewLine
  else
    s := 'Nueva instalación de PDFlex' + NewLine + NewLine;

  s := s + MemoDirInfo + NewLine;
  if MemoGroupInfo <> '' then
    s := s + MemoGroupInfo + NewLine;
  if MemoTasksInfo <> '' then
    s := s + MemoTasksInfo + NewLine;
  Result := s;
end;
