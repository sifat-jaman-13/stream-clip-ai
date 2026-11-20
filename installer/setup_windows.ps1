param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir
)

$ErrorActionPreference = "Stop"
Write-Host "StreamSnip AI setup" -ForegroundColor Cyan

function Fail-Setup([string]$Message) {
    Write-Host $Message -ForegroundColor Red
    exit 1
}

$python = Get-Command py -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python was not found. Installing Python 3.12..." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            Fail-Setup "Python installation failed."
        }
    } else {
        Fail-Setup "winget is unavailable. Install Python 3.12 and rerun this setup."
    }
}

$pythonCmd = Get-Command py -ErrorAction SilentlyContinue
if ($pythonCmd) {
    & py -3.12 -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { Fail-Setup "Could not upgrade pip." }
    & py -3.12 -m pip install -r (Join-Path $AppDir "source\requirements.txt") streamlink
    if ($LASTEXITCODE -ne 0) { Fail-Setup "Could not install StreamSnip AI dependencies." }
} else {
    $pythonExe = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonExe) {
        Fail-Setup "Python installation could not be found."
    }
    & python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { Fail-Setup "Could not upgrade pip." }
    & python -m pip install -r (Join-Path $AppDir "source\requirements.txt") streamlink
    if ($LASTEXITCODE -ne 0) { Fail-Setup "Could not install StreamSnip AI dependencies." }
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "Installing FFmpeg..." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { Fail-Setup "FFmpeg installation failed." }
    }
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Fail-Setup "FFmpeg is still unavailable after setup."
}

$exe = Join-Path $AppDir "StreamSnipAI.exe"
if (-not (Test-Path $exe)) {
    Write-Host "StreamSnipAI.exe was not found." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

Start-Process -FilePath $exe -WorkingDirectory $AppDir
