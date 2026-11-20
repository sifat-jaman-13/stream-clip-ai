$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Preparing the StreamSnip AI application build..." -ForegroundColor Cyan
$dist = Join-Path $PSScriptRoot "dist"
$thinDir = Join-Path $dist "StreamSnipAI"
New-Item -ItemType Directory -Force -Path $thinDir | Out-Null

$csc = Get-ChildItem "C:\Windows\Microsoft.NET\Framework64" -Filter csc.exe -Recurse -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
if (-not $csc) { throw "The Windows C# compiler is required to create the thin StreamSnipAI.exe launcher." }

$launcher = Join-Path $PSScriptRoot "installer\StreamSnipAILauncher.cs"
$launcherExe = Join-Path $thinDir "StreamSnipAI.exe"
& $csc /nologo /target:exe /out:$launcherExe $launcher
if ($LASTEXITCODE -ne 0) { throw "Could not compile the thin StreamSnip AI launcher." }

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
