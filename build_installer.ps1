$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$dashboard = Join-Path $PSScriptRoot "dashboard"
$dist = Join-Path $PSScriptRoot "dist"
$shellDist = Join-Path $dist "StreamSnipAI"
$installerDir = Join-Path $dist "installer"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) {
        $python = (& $launcher.Source -3.12 -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
    }
}
if (-not $python -or -not (Test-Path -LiteralPath $python)) {
    throw "A compatible Python 3.10+ interpreter is required to build StreamSnip AI."
}

Write-Host "Building the single React/TypeScript application interface..." -ForegroundColor Cyan
Push-Location $dashboard
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw "Could not install dashboard build dependencies." }
    & npm.cmd run lint
    if ($LASTEXITCODE -ne 0) { throw "Dashboard lint failed." }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "Dashboard production build failed." }
} finally {
    Pop-Location
}

Write-Host "Checking Python desktop-shell build dependencies..." -ForegroundColor Cyan
& $python -c "import webview, PyInstaller; print('pywebview and PyInstaller are ready')"
if ($LASTEXITCODE -ne 0) {
    & $python -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw "Could not prepare pip in the project Python environment." }
    & $python -m pip install -r (Join-Path $PSScriptRoot "requirements-build.txt")
    if ($LASTEXITCODE -ne 0) { throw "Could not install PyInstaller and pywebview." }
}

if (Test-Path -LiteralPath $shellDist) { Remove-Item -LiteralPath $shellDist -Recurse -Force }
New-Item -ItemType Directory -Force -Path $installerDir | Out-Null

Write-Host "Packaging the pywebview desktop shell..." -ForegroundColor Cyan
# PyInstaller logs normally to stderr; PowerShell 5.1 treats native stderr as errors.
# Keep the real process exit code as the packaging success signal.
$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    & $python -m PyInstaller --noconfirm --clean --distpath $dist --workpath (Join-Path $PSScriptRoot "build\pyinstaller") (Join-Path $PSScriptRoot "StreamSnipShell.spec")
    $pyInstallerExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($pyInstallerExitCode -ne 0) { throw "PyInstaller could not build the pywebview shell (exit code $pyInstallerExitCode)." }

$shellExe = Join-Path $shellDist "StreamSnipAI.exe"
if (-not (Test-Path -LiteralPath $shellExe)) { throw "The pywebview application executable was not produced." }
foreach ($required in @(
    (Join-Path $dashboard "dist\index.html"),
    (Join-Path $PSScriptRoot "autoclip.py"),
    (Join-Path $PSScriptRoot "api_server.py"),
    (Join-Path $PSScriptRoot "desktop_shell.py"),
    (Join-Path $PSScriptRoot "assets\app-icon.ico"),
    (Join-Path $PSScriptRoot "models\face_detection_yunet_2023mar.onnx"),
    (Join-Path $PSScriptRoot "installer\setup_windows.ps1"),
    (Join-Path $PSScriptRoot "installer\uninstall_windows.ps1"),
    (Join-Path $PSScriptRoot "requirements.txt")
)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "A required installer input is missing: $required"
    }
}

# Fail rather than silently shipping a stale or guessed application version.
$versionMatch = Select-String -Path (Join-Path $PSScriptRoot "autoclip.py") -Pattern '^APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $versionMatch -or -not $versionMatch.Matches[0].Groups[1].Value) {
    throw "Could not read APP_VERSION from autoclip.py; refusing to build an incorrectly versioned installer."
}
$version = $versionMatch.Matches[0].Groups[1].Value

$programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
$programFiles = [Environment]::GetEnvironmentVariable("ProgramFiles")
$localPrograms = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6"
$isccCandidates = @(
    (Join-Path $programFilesX86 "Inno Setup 6\ISCC.exe"),
    (Join-Path $programFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $localPrograms "ISCC.exe")
)
$iscc = $isccCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $iscc) {
    $command = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($command) { $iscc = $command.Source }
}
if (-not $iscc) { throw "Inno Setup 6 is required to create the Windows installer." }

$iss = Join-Path $PSScriptRoot "installer\StreamSnipAI.iss"
Write-Host "Compiling StreamSnipAI-Setup.exe (version $version)..." -ForegroundColor Cyan
& $iscc "/DMyAppVersion=$version" $iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed to compile the Windows installer." }

$setup = Join-Path $installerDir "StreamSnipAI-Setup.exe"
if (-not (Test-Path -LiteralPath $setup)) { throw "The installer output was not created." }
$hash = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  StreamSnipAI-Setup.exe" | Set-Content -LiteralPath ($setup + ".sha256") -Encoding ASCII

$sizeMiB = [Math]::Round((Get-Item -LiteralPath $setup).Length / 1MB, 2)
Write-Host ""
Write-Host "STREAMSNIP AI WINDOWS INSTALLER BUILD SUCCEEDED" -ForegroundColor Green
Write-Host "Installer: $setup" -ForegroundColor Green
Write-Host "Size: $sizeMiB MiB"
Write-Host "SHA-256: $hash"
