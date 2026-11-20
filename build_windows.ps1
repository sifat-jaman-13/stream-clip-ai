$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Preparing AutoClip Windows build..." -ForegroundColor Cyan
if (-not (Test-Path "venv\Scripts\python.exe")) {
    py -3.14 -m venv venv
}
$py = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt pyinstaller pillow

if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist) { Remove-Item dist -Recurse -Force }

& $py -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --console `
    --name AutoClip `
    --icon assets\app-icon.png `
    --add-data "assets;assets" `
    --collect-all faster_whisper `
    --collect-all ctranslate2 `
    --collect-all nvidia.cublas `
    --collect-submodules streamlink `
    --collect-submodules streamlink_cli `
    --collect-submodules zernio_poster `
    autoclip.py

& $py -m PyInstaller --noconfirm --clean --onefile --console --name StreamSnipAI --icon assets\app-icon.png launcher.py

# Include FFmpeg in the portable/installable application when it is available.
$ffmpeg = (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue).Source
if ($ffmpeg) {
    New-Item -ItemType Directory -Force -Path "dist\AutoClip\vendor\ffmpeg" | Out-Null
    Copy-Item $ffmpeg "dist\AutoClip\vendor\ffmpeg\ffmpeg.exe" -Force
    Write-Host "Bundled FFmpeg from $ffmpeg" -ForegroundColor Green
} else {
    Write-Warning "FFmpeg was not found. Install Gyan.FFmpeg before using the build."
}

Copy-Item README.md "dist\AutoClip\README.md" -Force
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { $iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source }
if ($iscc) {
    & $iscc "installer\AutoClip.iss"
    Write-Host "Installer created in dist\installer" -ForegroundColor Green
} else {
    Write-Warning "Inno Setup is not installed; no installer EXE was created."
}
Write-Host "Installer build complete." -ForegroundColor Green
