#ifndef MyAppVersion
  #define MyAppVersion "4.0.5"
#endif
#define MyAppName "StreamSnip AI"
#define MyAppPublisher "ScarZero"
#define MyNativeExe "StreamSnip.Desktop.exe"

[Setup]
AppId={{A6F21D5A-9C77-48A7-8B65-F33DE03D2C80}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\StreamSnip AI Native
DefaultGroupName=StreamSnip AI
OutputDir=..\dist\installer
OutputBaseFilename=StreamSnipAI-Native-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\app-icon.ico
UninstallDisplayIcon={app}\desktop\{#MyNativeExe}
DisableProgramGroupPage=yes

[Files]
Source: "..\dist\StreamSnipDesktopNative\*"; DestDir: "{app}\desktop"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE-NeonClipping.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE-YuNet.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\autoclip.py"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\api_server.py"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\ai_highlights.py"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\post_metadata.py"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\zernio_poster.py"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\zernio_connections.py"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\facecam_detect.py"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}\source"; Flags: ignoreversion
Source: "..\assets\*"; DestDir: "{app}\source\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\models\face_detection_yunet_2023mar.onnx"; DestDir: "{app}\source\models"; Flags: ignoreversion
Source: "..\dashboard\dist\*"; DestDir: "{app}\source\dashboard\dist"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "setup_windows.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "python315_support.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall_windows.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\StreamSnip AI"; Filename: "{app}\desktop\{#MyNativeExe}"; WorkingDir: "{app}\desktop"
Name: "{autodesktop}\StreamSnip AI"; Filename: "{app}\desktop\{#MyNativeExe}"; WorkingDir: "{app}\desktop"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional options:"; Flags: unchecked

[Run]
Filename: "{app}\desktop\{#MyNativeExe}"; WorkingDir: "{app}\desktop"; Description: "Launch StreamSnip AI"; Flags: postinstall nowait skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  PowerShellPath: string;
  Parameters: string;
  SetupLog: string;
  ShowCommand: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    PowerShellPath := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
    Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{app}\setup_windows.ps1') +
      '" -AppDir "' + ExpandConstant('{app}') +
      '" -SkipLaunch -NoPause -NativeDesktop';
    SetupLog := ExpandConstant('{localappdata}\StreamSnip AI\setup.log');
    ShowCommand := SW_SHOW;
    if WizardSilent then
    begin
      Parameters := Parameters + ' -NonInteractive';
      ShowCommand := SW_HIDE;
    end;

    if not Exec(PowerShellPath, Parameters, ExpandConstant('{app}'),
      ShowCommand, ewWaitUntilTerminated, ResultCode) then
      RaiseException('Could not start StreamSnip AI setup. Check that Windows PowerShell is available.');

    if ResultCode <> 0 then
      RaiseException('StreamSnip AI setup failed (exit code ' +
        IntToStr(ResultCode) + '). The app was not launched. Setup log: ' + SetupLog);
  end;
end;

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall_windows.ps1"" -AppDir ""{app}"" -NoPause"; WorkingDir: "{app}"; RunOnceId: "StreamSnipAIDependencyCleanup"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: files; Name: "{localappdata}\StreamSnip AI\native-engine.json"
