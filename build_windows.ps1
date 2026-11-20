$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Preparing AutoClip Windows build..." -ForegroundColor Cyan
if (-not (Test-Path "venv\Scripts\python.exe")) {
    py -3.14 -m venv venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Windows build environment." }
}
$py = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not update pip in the build environment." }
& $py -m pip install -r requirements.txt pyinstaller pillow
if ($LASTEXITCODE -ne 0) { throw "Could not install the Windows build dependencies." }

if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist) { Remove-Item dist -Recurse -Force }
New-Item -ItemType Directory -Force -Path build | Out-Null

& $py -m PyInstaller `
    --noconfirm `
    --clean `
    --specpath (Join-Path $PSScriptRoot "build") `
    --onedir `
    --console `
    --name AutoClip `
    --icon (Join-Path $PSScriptRoot "assets\app-icon.png") `
    --add-data "$($PSScriptRoot)\assets;assets" `
    --collect-all faster_whisper `
    --collect-all ctranslate2 `
    --collect-all nvidia.cublas `
    --collect-submodules streamlink `
    --collect-submodules streamlink_cli `
    --collect-submodules zernio_poster `
    (Join-Path $PSScriptRoot "autoclip.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller could not build the AutoClip application." }

& $py -m PyInstaller --noconfirm --clean --specpath (Join-Path $PSScriptRoot "build") --onefile --console --name StreamSnipAI --icon (Join-Path $PSScriptRoot "assets\app-icon.png") (Join-Path $PSScriptRoot "launcher.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller could not build the StreamSnip AI launcher." }

# Include FFmpeg in the portable/installable application when it is available.
$ffmpeg = (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue).Source
$ffprobe = (Get-Command ffprobe.exe -ErrorAction SilentlyContinue).Source
if ($ffmpeg) {
    New-Item -ItemType Directory -Force -Path "dist\AutoClip\vendor\ffmpeg" | Out-Null
    Copy-Item $ffmpeg "dist\AutoClip\vendor\ffmpeg\ffmpeg.exe" -Force
    if ($ffprobe) {
        Copy-Item $ffprobe "dist\AutoClip\vendor\ffmpeg\ffprobe.exe" -Force
    } else {
        Write-Warning "FFprobe was not found. The app will preserve original audio and skip CTA voice mixing if no system FFprobe is available."
    }
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
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup could not create the StreamSnip AI installer." }
    Write-Host "Installer created in dist\installer" -ForegroundColor Green
} else {
    Write-Warning "Inno Setup is not installed; no installer EXE was created."
}
Write-Host "Installer build complete." -ForegroundColor Green
