param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir,
    [switch]$CheckOnly,
    [switch]$SkipLaunch,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$RuntimeSchema = "3"
$transcriptStarted = $false
$exitCode = 0

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $current = $env:Path
    $parts = @($machine, $user, $current) | Where-Object { $_ }
    $env:Path = $parts -join ";"
}

function Test-SupportedPython([string]$File, [string[]]$Prefix = @()) {
    if (-not $File) { return $null }
    try {
        $commandArgs = @($Prefix) + @(
            "-c",
            "import sys; ok=(3,10) <= sys.version_info[:2] <= (3,12) and sys.maxsize > 2**32; print(('OK|' if ok else 'NO|') + sys.executable + '|' + '.'.join(map(str, sys.version_info[:3]))); raise SystemExit(0 if ok else 2)"
        )
        $output = & $File @commandArgs 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $line = [string](@($output) | Select-Object -Last 1)
        if (-not $line.StartsWith("OK|")) { return $null }
        $fields = $line.Split("|")
        return [pscustomobject]@{
            File = $File
            Prefix = @($Prefix)
            Executable = $fields[1]
            Version = $fields[2]
        }
    } catch {
        return $null
    }
}

function Find-SupportedPython {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) {
        foreach ($version in ("3.12", "3.11", "3.10")) {
            $found = Test-SupportedPython $launcher.Source @("-$version")
            if ($found) { return $found }
        }
    }

    $candidates = New-Object System.Collections.Generic.List[string]
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pythonCommand -and $pythonCommand.Source -notlike "*\WindowsApps\python.exe") {
        $candidates.Add($pythonCommand.Source)
    }
    foreach ($pattern in @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python*\python.exe"),
        (Join-Path $env:ProgramFiles "Python*\python.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Python*\python.exe")
    )) {
        if (-not $pattern) { continue }
        Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue |
            ForEach-Object { $candidates.Add($_.FullName) }
    }

    $seen = @{}
    foreach ($candidate in $candidates) {
        $key = [string]$candidate
        if (-not $key -or $seen.ContainsKey($key.ToLowerInvariant())) { continue }
        $seen[$key.ToLowerInvariant()] = $true
        $found = Test-SupportedPython $candidate
        if ($found) { return $found }
    }
    return $null
}

function Install-Python312 {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $winget) {
        throw "64-bit Python 3.10-3.12 was not found and WinGet is unavailable. Install 64-bit Python 3.12 from python.org, then launch StreamSnip AI again."
    }
    Write-Host "A supported Python was not found. Installing Python 3.12..." -ForegroundColor Yellow
    $installArgs = @(
        "install", "--id", "Python.Python.3.12", "--exact", "--source", "winget",
        "--scope", "user", "--accept-package-agreements", "--accept-source-agreements",
        "--disable-interactivity"
    )
    & $winget.Source @installArgs | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "The per-user Python install did not complete; retrying with WinGet defaults..." -ForegroundColor Yellow
        $installArgs = @(
            "install", "--id", "Python.Python.3.12", "--exact", "--source", "winget",
            "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"
        )
        & $winget.Source @installArgs | ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -ne 0) { throw "Python 3.12 installation failed." }
    }
    Refresh-ProcessPath
    $python = Find-SupportedPython
    if (-not $python) {
        $known = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
        if (Test-Path $known) { $python = Test-SupportedPython $known }
    }
    if (-not $python) {
        throw "Python 3.12 was installed, but this setup could not locate it. Restart Windows and launch StreamSnip AI again."
    }
    return $python
}

function Invoke-Python($Python, [string[]]$Arguments) {
    $commandArgs = @($Python.Prefix) + @($Arguments)
    & $Python.File @commandArgs | ForEach-Object { Write-Host $_ }
    $result = $LASTEXITCODE
    return [int]$result
}

function Find-FFmpeg {
    Refresh-ProcessPath
    $command = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command -and (Test-Path $command.Source)) { return $command.Source }

    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:LOCALAPPDATA) {
        $candidates.Add((Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\ffmpeg.exe"))
        $packages = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
        if (Test-Path $packages) {
            Get-ChildItem -Path $packages -Directory -Filter "Gyan.FFmpeg_*" -ErrorAction SilentlyContinue |
                ForEach-Object {
                    Get-ChildItem -Path $_.FullName -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue |
                        ForEach-Object { $candidates.Add($_.FullName) }
                }
        }
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    return $null
}

function Ensure-FFmpeg {
    $ffmpeg = Find-FFmpeg
    if (-not $ffmpeg) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $winget) {
            throw "FFmpeg was not found and WinGet is unavailable. Install FFmpeg, then launch StreamSnip AI again."
        }
        Write-Host "Installing FFmpeg..." -ForegroundColor Yellow
        & $winget.Source install --id Gyan.FFmpeg --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity |
            ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -ne 0) { throw "FFmpeg installation failed." }
        $ffmpeg = Find-FFmpeg
    }
    if (-not $ffmpeg) {
        throw "FFmpeg was installed, but this setup could not locate it. Restart Windows and launch StreamSnip AI again."
    }
    $ffmpegDir = Split-Path -Parent $ffmpeg
    $env:Path = $ffmpegDir + ";" + $env:Path
    return $ffmpeg
}

function Ensure-SpeechModels($RuntimePython, [string]$ModelRoot) {
    $models = @("distil-large-v3", "large-v3-turbo", "medium", "large-v3", "small", "base")
    $bootstrap = @'
from pathlib import Path
import shutil
import sys
from faster_whisper import download_model

root = Path(sys.argv[1])
for name in sys.argv[2:]:
    destination = root / name
    model_file = destination / "model.bin"
    if model_file.is_file():
        print(f"Speech model already ready: {name}")
        continue
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    print(f"Downloading speech model: {name}", flush=True)
    downloaded = Path(download_model(name, output_dir=str(destination), local_files_only=False))
    if not model_file.is_file() and not (downloaded / "model.bin").is_file():
        raise RuntimeError(f"{name} downloaded without model.bin")
    print(f"Speech model ready: {name}", flush=True)
'@
    & $RuntimePython -c $bootstrap $ModelRoot @models
    if ($LASTEXITCODE -ne 0) { throw "Could not download and verify all StreamSnip AI speech models." }
}

try {
    $AppDir = [IO.Path]::GetFullPath($AppDir)
    $source = Join-Path $AppDir "source"
    $main = Join-Path $source "autoclip.py"
    $requirements = Join-Path $source "requirements.txt"
    $runtime = Join-Path $AppDir "runtime"
    $runtimePython = Join-Path $runtime "Scripts\python.exe"
    $runtimeMarker = Join-Path $runtime ".streamsnip-requirements"
    $logBase = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { $AppDir }
    $logRoot = Join-Path $logBase "StreamSnip AI"
    $logPath = Join-Path $logRoot "setup.log"

    New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
    try {
        Start-Transcript -Path $logPath -Append | Out-Null
        $transcriptStarted = $true
    } catch {}

    Write-Host "StreamSnip AI setup" -ForegroundColor Cyan
    Write-Host "Setup log: $logPath"
    if (-not (Test-Path $main) -or -not (Test-Path $requirements)) {
        throw "The StreamSnip AI source files are incomplete. Reinstall the application and try again."
    }

    $python = Find-SupportedPython
    if (-not $python -and -not $CheckOnly) { $python = Install-Python312 }
    if (-not $python) { throw "64-bit Python 3.10, 3.11, or 3.12 is required." }
    Write-Host "Python $($python.Version): $($python.Executable)" -ForegroundColor Green

    $ffmpeg = Ensure-FFmpeg
    Write-Host "FFmpeg: $ffmpeg" -ForegroundColor Green
    if ($CheckOnly) {
        Write-Host "Installer prerequisites are available." -ForegroundColor Green
    } else {
        $runtimeInfo = $null
        if (Test-Path $runtimePython) { $runtimeInfo = Test-SupportedPython $runtimePython }
        if (-not $runtimeInfo) {
            if (Test-Path $runtime) { Remove-Item -LiteralPath $runtime -Recurse -Force }
            Write-Host "Creating StreamSnip AI's isolated Python runtime..." -ForegroundColor Cyan
            $venvResult = Invoke-Python $python @("-m", "venv", $runtime)
            if ($venvResult -ne 0 -or -not (Test-Path $runtimePython)) {
                throw "Could not create the StreamSnip AI Python runtime."
            }
            $runtimeInfo = Test-SupportedPython $runtimePython
            if (-not $runtimeInfo) { throw "The StreamSnip AI Python runtime is invalid." }
        }

        $requirementsHash = (Get-FileHash $requirements -Algorithm SHA256).Hash.ToLowerInvariant()
        $expectedMarker = "$RuntimeSchema|$requirementsHash"
        $savedMarker = if (Test-Path $runtimeMarker) { (Get-Content $runtimeMarker -Raw).Trim() } else { "" }
        $dependencyProbe = & $runtimePython -c "import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(x) for x in ('numpy','faster_whisper','streamlink')) else 1)" 2>$null
        $dependenciesReady = ($LASTEXITCODE -eq 0)
        if ($savedMarker -ne $expectedMarker -or -not $dependenciesReady) {
            Write-Host "Installing StreamSnip AI dependencies. The first setup can take several minutes..." -ForegroundColor Cyan
            & $runtimePython -m pip install --upgrade pip
            if ($LASTEXITCODE -ne 0) { throw "Could not upgrade pip in the StreamSnip AI runtime." }
            & $runtimePython -m pip install --prefer-binary -r $requirements
            if ($LASTEXITCODE -ne 0) { throw "Could not install StreamSnip AI dependencies." }
            & $runtimePython -m pip check
            if ($LASTEXITCODE -ne 0) { throw "The installed Python dependencies are inconsistent." }
            & $runtimePython -c "import numpy, faster_whisper, streamlink"
            if ($LASTEXITCODE -ne 0) { throw "A required StreamSnip AI package could not be loaded after installation." }
            Set-Content -Path $runtimeMarker -Value $expectedMarker -Encoding ASCII
        } else {
            Write-Host "StreamSnip AI dependencies are already installed." -ForegroundColor Green
        }

        $speechModelRoot = Join-Path $source "models"
        Write-Host "Downloading and verifying StreamSnip AI speech models. This can take a while and needs an internet connection..." -ForegroundColor Cyan
        Ensure-SpeechModels $runtimePython $speechModelRoot

        if (-not $SkipLaunch) {
            Write-Host "Launching StreamSnip AI..." -ForegroundColor Cyan
            $quotedMain = '"' + $main.Replace('"', '\"') + '"'
            $process = Start-Process -FilePath $runtimePython -ArgumentList $quotedMain -WorkingDirectory $source -PassThru
            if (-not $process) { throw "StreamSnip AI could not be launched." }
            Write-Host "StreamSnip AI started successfully." -ForegroundColor Green
        }
    }
} catch {
    $exitCode = 1
    Write-Host ""
    Write-Host ("Setup failed: " + $_.Exception.Message) -ForegroundColor Red
    if ($logPath) { Write-Host "Details were saved to: $logPath" -ForegroundColor Yellow }
    if (-not $NoPause) {
        try { Read-Host "Press Enter to close" | Out-Null } catch {}
    }
} finally {
    if ($transcriptStarted) {
        try { Stop-Transcript | Out-Null } catch {}
    }
}

exit $exitCode
