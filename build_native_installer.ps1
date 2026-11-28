$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$project = Join-Path $PSScriptRoot "desktop\StreamSnip.Desktop\StreamSnip.Desktop.csproj"
$publishDir = Join-Path $PSScriptRoot "dist\StreamSnipDesktopNative"
$facecamProject = Join-Path $PSScriptRoot "tools\FacecamInference\FacecamInference.csproj"
$facecamPublishDir = Join-Path $PSScriptRoot "dist\FacecamInference"
$installerDir = Join-Path $PSScriptRoot "dist\installer"
$iss = Join-Path $PSScriptRoot "installer\StreamSnipNative.iss"

Write-Host "Building the Creator Studio dashboard included for engine compatibility..." -ForegroundColor Cyan
Push-Location (Join-Path $PSScriptRoot "dashboard")
try {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "Dashboard production build failed." }
} finally {
    Pop-Location
}

if (Test-Path -LiteralPath $publishDir) {
    Remove-Item -LiteralPath $publishDir -Recurse -Force
}
if (Test-Path -LiteralPath $facecamPublishDir) {
    Remove-Item -LiteralPath $facecamPublishDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $publishDir, $facecamPublishDir, $installerDir | Out-Null

Write-Host "Publishing the self-contained DirectML facecam inference helper..." -ForegroundColor Cyan
& dotnet publish $facecamProject -c Release -r win-x64 --self-contained true -p:PublishSingleFile=false -p:PublishTrimmed=false -o $facecamPublishDir
if ($LASTEXITCODE -ne 0) { throw "DirectML facecam inference helper publish failed." }
foreach ($required in @(
    (Join-Path $facecamPublishDir "FacecamInference.exe"),
    (Join-Path $facecamPublishDir "DirectML.dll"),
    (Join-Path $facecamPublishDir "onnxruntime.dll")
)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "The DirectML facecam helper is missing a required runtime file: $required"
    }
}

$fontAsset = Join-Path $PSScriptRoot "desktop\StreamSnip.Desktop\Assets\Fonts\JetBrainsMono-Variable.ttf"
if (-not (Test-Path -LiteralPath $fontAsset)) {
    Write-Host "Preparing the licensed JetBrains Mono font from the official upstream release..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "download_jetbrains_font.ps1")
    & (Join-Path $PSScriptRoot "bundle_jetbrains_font.ps1")
}
if (-not (Test-Path -LiteralPath $fontAsset)) { throw "JetBrains Mono font asset could not be prepared." }

Write-Host "Publishing the self-contained native WinUI 3 desktop app..." -ForegroundColor Cyan
& dotnet publish $project -c Release -r win-x64 -p:Platform=x64 -p:WindowsPackageType=None -p:WindowsAppSDKSelfContained=true -p:SelfContained=true -p:PublishTrimmed=false -p:PublishSingleFile=false -p:PublishReadyToRun=true -o $publishDir
if ($LASTEXITCODE -ne 0) { throw "Native WinUI 3 Release publish failed." }

$appResourceIndex = Join-Path $publishDir "StreamSnip.Desktop.pri"
if (-not (Test-Path -LiteralPath $appResourceIndex)) {
    throw "Native publish is missing StreamSnip.Desktop.pri; compiled XAML resources would fail at startup."
}

$nativeExe = Join-Path $publishDir "StreamSnip.Desktop.exe"
if (-not (Test-Path -LiteralPath $nativeExe)) {
    throw "The native publish did not produce StreamSnip.Desktop.exe."
}
foreach ($required in @(
    (Join-Path $publishDir "Assets\Fonts\JetBrainsMono-Variable.ttf"),
    (Join-Path $publishDir "Assets\Fonts\Inter-Variable.ttf"),
    (Join-Path $publishDir "Assets\Fonts\OpenSans-Variable.ttf"),
    (Join-Path $publishDir "Assets\Fonts\IBMPlexSans-Variable.ttf"),
    (Join-Path $publishDir "Assets\Fonts\Roboto-Variable.ttf"),
    (Join-Path $publishDir "Assets\Fonts\SourceSans3-Variable.ttf"),
    (Join-Path $publishDir "Assets\Fonts\DMSans-Variable.ttf"),
    (Join-Path $publishDir "Assets\Fonts\Poppins-Regular.ttf"),
    (Join-Path $publishDir "Assets\Fonts\Lato-Regular.ttf"),
    (Join-Path $publishDir "Assets\Fonts\Manrope-Variable.ttf"),
    (Join-Path $publishDir "Assets\Fonts\NunitoSans-Variable.ttf"),
    (Join-Path $publishDir "Assets\Fonts\FiraCode-Variable.ttf"),
    (Join-Path $PSScriptRoot "zernio_connections.py"),
    (Join-Path $PSScriptRoot "secret_store.py"),
    (Join-Path $PSScriptRoot "dashboard\dist\index.html"),
    (Join-Path $PSScriptRoot "installer\setup_windows.ps1")
)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "A required installer input is missing: $required"
    }
}

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
if (-not $iscc) { throw "Inno Setup 6 is required to create the native StreamSnip AI installer." }

$versionMatch = Select-String -Path (Join-Path $PSScriptRoot "autoclip.py") -Pattern '^APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
$version = if ($versionMatch) { $versionMatch.Matches[0].Groups[1].Value } else { "4.0.14" }

Write-Host "Compiling StreamSnipAI-Native-Setup.exe (version $version)..." -ForegroundColor Cyan
& $iscc "/DMyAppVersion=$version" $iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed to compile the native installer." }

$setup = Join-Path $installerDir "StreamSnipAI-Native-Setup.exe"
if (-not (Test-Path -LiteralPath $setup)) { throw "Native installer output was not created." }
$hash = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  StreamSnipAI-Native-Setup.exe" | Set-Content -LiteralPath ($setup + ".sha256") -Encoding ASCII

$sizeMiB = [Math]::Round((Get-Item -LiteralPath $setup).Length / 1MB, 2)
Write-Host ""
Write-Host "NATIVE INSTALLER BUILD SUCCEEDED" -ForegroundColor Green
Write-Host "Installer: $setup" -ForegroundColor Green
Write-Host "Size: $sizeMiB MiB"
Write-Host "SHA-256: $hash"
