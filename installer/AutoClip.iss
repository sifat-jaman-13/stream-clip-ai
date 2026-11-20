#define MyAppName "StreamSnip AI"
#define MyAppVersion "1.1.9"
#define MyAppPublisher "ScarZero"
#define MyAppExeName "StreamSnipAI.exe"

[Setup]
AppId={{B4D1D9B4-53A8-4F78-9B4D-7D23C2F50F4C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\StreamSnip AI
DefaultGroupName=StreamSnip AI
OutputDir=..\dist\installer
OutputBaseFilename=StreamSnipAI-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\StreamSnipAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\StreamSnip AI"; Filename: "{app}\StreamSnipAI.exe"
Name: "{autodesktop}\StreamSnip AI"; Filename: "{app}\StreamSnipAI.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional options:"; Flags: unchecked

[Run]
Filename: "{app}\StreamSnipAI.exe"; Description: "Launch StreamSnip AI"; Flags: nowait postinstall skipifsilent
