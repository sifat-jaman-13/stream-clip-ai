param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir
)

$ErrorActionPreference = "Stop"
$AppDir = [IO.Path]::GetFullPath($AppDir)
$setup = Join-Path $AppDir "setup_windows.ps1"
$source = Join-Path $AppDir "source"
$desktop = Join-Path $AppDir "desktop"
$python = Join-Path $AppDir "runtime\Scripts\python.exe"
$nativeExe = Join-Path $desktop "StreamSnip.Desktop.exe"

foreach ($required in @($setup, (Join-Path $AppDir "python315_support.ps1"), $nativeExe)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "The native StreamSnip installer is incomplete: $required"
    }
}

Write-Host "Preparing the StreamSnip AI Python engine and dependencies..." -ForegroundColor Cyan
$arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $setup + '" -AppDir "' + $AppDir + '" -SkipLaunch -NoPause'
$process = Start-Process -FilePath (Join-Path $PSHOME "powershell.exe") -ArgumentList $arguments -WorkingDirectory $AppDir -PassThru -Wait
if ($process.ExitCode -ne 0) {
    throw "StreamSnip AI engine setup failed with exit code $($process.ExitCode). See the setup log under %LOCALAPPDATA%\StreamSnip AI."
}
if (-not (Test-Path -LiteralPath (Join-Path $source "autoclip.py"))) {
    throw "The StreamSnip AI Python source is missing after setup."
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "The private StreamSnip AI Python runtime was not created."
}

$localData = Join-Path $env:LOCALAPPDATA "StreamSnip AI"
$dataRoot = Join-Path $localData "Library"
$configPath = Join-Path $localData "native-engine.json"
New-Item -ItemType Directory -Force -Path $localData, $dataRoot | Out-Null

$config = [ordered]@{
    source_root = $source
    python_executable = $python
    data_root = $dataRoot
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 4), $utf8NoBom)

Write-Host "Native engine configuration created: $configPath" -ForegroundColor Green
Write-Host "Clip library and application data: $dataRoot" -ForegroundColor Green
