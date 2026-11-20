#define MyAppName "StreamSnip AI"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "ScarZero"
#define MyAppExeName "AutoClip.exe"

[Setup]
AppId={{B4D1D9B4-53A8-4F78-9B4D-7D23C2F50F4C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\StreamSnip AI
DefaultGroupName=StreamSnip AI
OutputDir=..\dist\installer
OutputBaseFilename=StreamSnipAI-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\AutoClip\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\StreamSnip AI"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\StreamSnip AI"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch StreamSnip AI"; Flags: nowait postinstall skipifsilent
