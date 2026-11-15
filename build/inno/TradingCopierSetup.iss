; Inno Setup script for Trading Copier (Windows x64)
; Builds TradingCopierSetup_x64.exe
; Compile: ISCC build/inno/TradingCopierSetup.iss  (after PyInstaller build)

#define MyAppName "Trading Copier"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "Trading Copier"
#define MyAppExeName "TradingCopier.exe"

[Setup]
AppId={{7E4A2C91-8B3D-4F5A-9C2E-A1D3B4C5F6E8}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install: no admin rights required (spec: no admin needed)
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\TradingCopier
DefaultGroupName={#MyAppName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\..\Output
OutputBaseFilename=TradingCopierSetup_x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
CloseApplications=no
ChangesAssociations=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"
Name: "startupicon"; Description: "Run at Windows startup"; \
    GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\..\dist\TradingCopier\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; IMPORTANT: user data in %LOCALAPPDATA%\TradingCopier (DB, logs) is NOT
; removed by the uninstaller on purpose - it preserves your history/settings.
Type: filesandordirs; Name: "{app}"
