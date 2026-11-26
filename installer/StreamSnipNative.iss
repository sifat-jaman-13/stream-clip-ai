#ifndef MyAppVersion
  #define MyAppVersion "4.0.6"
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
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\third-party\*"; DestDir: "{app}\licenses\third-party"; Flags: ignoreversion recursesubdirs createallsubdirs
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

[UninstallDelete]
Type: files; Name: "{localappdata}\StreamSnip AI\native-engine.json"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\runtime.previous"
Type: filesandordirs; Name: "{app}\python-base"
Type: filesandordirs; Name: "{app}\source"
Type: filesandordirs; Name: "{app}\desktop"
Type: filesandordirs; Name: "{app}\licenses"

[Code]
var
  KeepConfigOnUninstall: Boolean;

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

function InitializeUninstall(): Boolean;
var
  Choice: Integer;
begin
  Result := True;
  KeepConfigOnUninstall := Pos('/KEEPCONFIG', Uppercase(GetCmdTail)) > 0;
  if not UninstallSilent then
  begin
    Choice := MsgBox(
      'Keep only settings and configuration?' + #13#10 + #13#10 +
      'YES: Keep app settings, AI provider settings/API keys, publishing settings, custom words and desktop preferences.' + #13#10 +
      'NO: Remove all app data, clips, recordings, models, runtime and configuration.' + #13#10 +
      'Your personal files outside StreamSnip AI folders are not touched.',
      mbConfirmation, MB_YESNOCANCEL or MB_DEFBUTTON2);
    if Choice = IDYES then
      KeepConfigOnUninstall := True
    else if Choice = IDNO then
      KeepConfigOnUninstall := False
    else
      Result := False;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  PowerShellPath: string;
  Parameters: string;
begin
  if CurUninstallStep = usUninstall then
  begin
    PowerShellPath := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
    Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{app}\uninstall_windows.ps1') +
      '" -AppDir "' + ExpandConstant('{app}') + '" -RemoveAllData';
    if KeepConfigOnUninstall then
      Parameters := Parameters + ' -KeepConfig';
    if not Exec(PowerShellPath, Parameters, ExpandConstant('{app}'),
      SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('Could not start StreamSnip AI cleanup. Check the uninstall cleanup log in your TEMP folder.');
    if ResultCode <> 0 then
      RaiseException('StreamSnip AI cleanup failed (exit code ' + IntToStr(ResultCode) +
        '). Check StreamSnipAI-uninstall-*.log in your TEMP folder.');
  end;
end;
