#define MyAppName "StreamSnip AI"
#define MyAppVersion "1.0.6"
#define MyAppPublisher "ScarZero"
#define MyAppExeName "AutoClip.exe"

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
Source: "..\autoclip.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\zernio_poster.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\run_streamsnip.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "bootstrap.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\StreamSnip AI"; Filename: "{app}\run_streamsnip.cmd"
Name: "{autodesktop}\StreamSnip AI"; Filename: "{app}\run_streamsnip.cmd"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\bootstrap.ps1"""; Flags: waituntilterminated
Filename: "{app}\run_streamsnip.cmd"; Description: "Launch StreamSnip AI"; Flags: nowait postinstall skipifsilent
