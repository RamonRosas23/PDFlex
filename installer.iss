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
#define AppVersion     "2.0.3"
#endif
#define AppPublisher   "GRUPO OCMX"
#define AppURL         "https://grupocmx.mx"
#define AppExeName     "PDFlex.exe"
#define AppMutex       "PDFlex_SingleInstance_GRUPOOCMX"
#define AppUserModelID "GRUPOOCMX.PDFlex.1"
#define SourceDir      "dist\PDFlex"
#define OutputDir      "dist"
#define SetupBaseName  AppName + "_" + AppVersion + "_Setup"

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
