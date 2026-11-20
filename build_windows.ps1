$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Preparing the StreamSnip AI application build..." -ForegroundColor Cyan
if (-not (Test-Path "venv\Scripts\python.exe")) {
    py -3.14 -m venv venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Windows build environment." }
}
$py = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not update pip in the build environment." }
& $py -m pip install -r requirements.txt pyinstaller pillow
if ($LASTEXITCODE -ne 0) { throw "Could not install the Windows build dependencies." }

New-Item -ItemType Directory -Force -Path "build\work" | Out-Null
& $py -m PyInstaller --noconfirm --clean --distpath (Join-Path $PSScriptRoot "dist") --workpath (Join-Path $PSScriptRoot "build\work") (Join-Path $PSScriptRoot "AutoClip.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller could not build the StreamSnip AI application." }

$appFolder = Join-Path $PSScriptRoot "dist\StreamSnipAI"
if (-not (Test-Path (Join-Path $appFolder "StreamSnipAI.exe"))) { throw "The StreamSnip AI application EXE was not created." }

# Include FFmpeg in the install when present. Otherwise the app can use FFmpeg from PATH.
$ffmpeg = (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue).Source
$ffprobe = (Get-Command ffprobe.exe -ErrorAction SilentlyContinue).Source
if ($ffmpeg) {
    $vendor = Join-Path $appFolder "vendor\ffmpeg"
    New-Item -ItemType Directory -Force -Path $vendor | Out-Null
    Copy-Item -LiteralPath $ffmpeg -Destination (Join-Path $vendor "ffmpeg.exe") -Force
    if ($ffprobe) {
        Copy-Item -LiteralPath $ffprobe -Destination (Join-Path $vendor "ffprobe.exe") -Force
    } else {
        Write-Warning "FFprobe was not found; the app will preserve original audio and skip CTA voice mixing if no system FFprobe is available."
    }
    Write-Host "Bundled FFmpeg from $ffmpeg" -ForegroundColor Green
} else {
    Write-Warning "FFmpeg was not found. Install Gyan.FFmpeg before using the build."
}

$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { $iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source }
if (-not $iscc) { throw "Inno Setup 6 is required to create StreamSnipAI-Setup.exe." }

& $iscc "installer\AutoClip.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup could not create the StreamSnip AI installer." }
$setup = Join-Path $PSScriptRoot "dist\installer\StreamSnipAI-Setup.exe"
if (-not (Test-Path $setup)) { throw "The installer build finished without producing StreamSnipAI-Setup.exe." }
Write-Host "Created the single installable app: $setup" -ForegroundColor Green
