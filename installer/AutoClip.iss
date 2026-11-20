#define MyAppName "StreamSnip AI"
#define MyAppVersion "1.2.7"
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
SetupIconFile=..\assets\app-icon.ico
UninstallDisplayIcon={app}\StreamSnipAI.exe

[Files]
Source: "..\dist\StreamSnipAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\autoclip.py"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\ai_highlights.py"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\zernio_poster.py"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\installer\setup_windows.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\StreamSnip AI"; Filename: "{app}\StreamSnipAI.exe"
Name: "{autodesktop}\StreamSnip AI"; Filename: "{app}\StreamSnipAI.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional options:"; Flags: unchecked

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup_windows.ps1"" -AppDir ""{app}"""; WorkingDir: "{app}"; Description: "Install dependencies and launch StreamSnip AI"; StatusMsg: "Preparing StreamSnip AI..."; Flags: waituntilterminated skipifsilent
