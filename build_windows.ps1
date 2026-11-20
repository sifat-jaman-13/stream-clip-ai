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

& $py -m PyInstaller --noconfirm --clean --distpath (Join-Path $PSScriptRoot "dist") --workpath (Join-Path $PSScriptRoot "build\work") (Join-Path $PSScriptRoot "AutoClip.spec")
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

# Publish a complete portable bundle with the actual app EXE, not the bootstrap launcher.
$portable = Join-Path $PSScriptRoot "dist\StreamSnipAI-Portable"
New-Item -ItemType Directory -Force -Path $portable | Out-Null
Copy-Item "dist\AutoClip\*" $portable -Recurse -Force
Rename-Item (Join-Path $portable "AutoClip.exe") "StreamSnipAI.exe" -Force
$portableZip = Join-Path $PSScriptRoot "dist\StreamSnipAI-Portable.zip"
if (Test-Path $portableZip) { Remove-Item $portableZip -Force }
Compress-Archive -Path (Join-Path $portable "*") -DestinationPath $portableZip -CompressionLevel Fastest
if (-not (Test-Path $portableZip)) { throw "Could not create the StreamSnip AI portable app bundle." }
Write-Host "Portable app bundle created at $portableZip" -ForegroundColor Green

$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { $iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source }
if ($iscc) {
    & $iscc "installer\AutoClip.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup could not create the StreamSnip AI installer." }
    if (-not (Test-Path "dist\installer\StreamSnipAI-Setup.exe")) { throw "The installer build finished without producing StreamSnipAI-Setup.exe." }
    Write-Host "Installer created in dist\installer" -ForegroundColor Green
} else {
    Write-Warning "Inno Setup is not installed; no installer EXE was created."
}
Write-Host "Installer build complete." -ForegroundColor Green
