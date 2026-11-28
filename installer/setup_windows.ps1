param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir,
    [switch]$CheckOnly,
    [switch]$SkipLaunch,
    [switch]$NoPause,
    [switch]$DesktopShell,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"

# Prevent two installer/repair attempts from mutating the same runtime, models,
# settings, or append-only setup transcript at the same time.
$setupMutex = New-Object System.Threading.Mutex($false, "Local\StreamSnipAI.Setup")
$setupMutexOwned = $false
try {
    $setupMutexOwned = $setupMutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    # The previous setup process exited unexpectedly; this process now owns the mutex.
    $setupMutexOwned = $true
}
if (-not $setupMutexOwned) {
    $setupMutex.Dispose()
    Write-Host "Another StreamSnip AI setup is already running. Let it finish before starting another installation or repair." -ForegroundColor Yellow
    exit 1
}

. (Join-Path $PSScriptRoot "python315_support.ps1")
$RuntimeSchema = "5"
$transcriptStarted = $false
$exitCode = 0

$script:DependencyStatePath = $null
$script:RuntimeBackupPath = $null
$script:DependencyOwnership = @{
    python_installed_by_streamsnip = $false
    ffmpeg_installed_by_streamsnip = $false
}

function Save-DependencyOwnership {
    if (-not $script:DependencyStatePath) { return }
    $directory = Split-Path -Parent $script:DependencyStatePath
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $temporaryPath = "$($script:DependencyStatePath).$PID.tmp"
    $json = $script:DependencyOwnership | ConvertTo-Json -Depth 5
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($temporaryPath, $json, $utf8NoBom)
    Move-Item -LiteralPath $temporaryPath -Destination $script:DependencyStatePath -Force
}

function Mark-DependencyInstalled([string]$Name) {
    if ($Name -notin @("python", "ffmpeg")) { throw "Unknown dependency ownership key: $Name" }
    $key = $Name + "_installed_by_streamsnip"
    $script:DependencyOwnership[$key] = $true
    Save-DependencyOwnership
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $current = $env:Path
    $parts = @($machine, $user, $current) | Where-Object { $_ }
    $env:Path = $parts -join ";"
}

function Test-SupportedPython([string]$File, [string[]]$Prefix = @()) {
    if (-not $File) { return $null }
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $commandArgs = @($Prefix) + @(
            "-c",
            "import sys; ok=sys.version_info[:2] >= (3,10) and sys.version_info.releaselevel == 'final' and sys.maxsize > 2**32; print(('OK|' if ok else 'NO|') + sys.executable + '|' + '.'.join(map(str, sys.version_info[:3]))); raise SystemExit(0 if ok else 2)"
        )
        $output = & $File @commandArgs 2>$null
        $commandExitCode = $LASTEXITCODE
        if ($commandExitCode -ne 0) { return $null }
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
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Test-PythonDependencyCompatibility($Python, [string]$RequirementsPath) {
    # Resolve requirements in a disposable venv so the check never installs
    # or upgrades packages in a user's global Python environment.
    $profilePath = New-StreamSnipRequirementsProfile $Python.Version $RequirementsPath
    $probeRoot = Join-Path $env:TEMP ("streamsnip-python-probe-" + [guid]::NewGuid().ToString("N"))
    $probePython = Join-Path $probeRoot "Scripts\python.exe"
    $ErrorActionPreference = "Continue"
    try {
        $venvArgs = @($Python.Prefix) + @("-m", "venv", $probeRoot)
        & $Python.File @venvArgs *> $null
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $probePython)) {
            Write-Host "Skipping Python $($Python.Version): could not create a clean test environment." -ForegroundColor DarkYellow
            return $false
        }

        & $probePython -m pip install --upgrade pip --disable-pip-version-check --quiet *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Skipping Python $($Python.Version): pip could not be prepared in the temporary test environment." -ForegroundColor DarkYellow
            return $false
        }

        $resolution = & $probePython -m pip install --dry-run --prefer-binary --disable-pip-version-check -r $profilePath 2>&1
        $resolutionExitCode = $LASTEXITCODE
        if ($resolutionExitCode -ne 0) {
            $detail = @($resolution | ForEach-Object { [string]$_ } | Where-Object { $_.Trim() } | Select-Object -Last 1)
            Write-Host "Skipping Python $($Python.Version): $($detail -join '')" -ForegroundColor DarkYellow
            return $false
        }
        return $true
    } catch {
        Write-Host "Skipping Python $($Python.Version): $($_.Exception.Message)" -ForegroundColor DarkYellow
        return $false
    } finally {
        if ($profilePath -and $profilePath -ne $RequirementsPath) { Remove-Item -LiteralPath $profilePath -Force -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $probeRoot) {
            Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Find-SupportedPython([string]$RequirementsPath) {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($AppDir) {
        $candidates.Add((Join-Path $AppDir "python-base\python.exe"))
    }

    # The Python launcher knows about registered installations even when they
    # are not on PATH. -0p lists every interpreter with its full executable path.
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) {
        $launcherOutput = & $launcher.Source -0p 2>$null
        if ($LASTEXITCODE -eq 0) {
            foreach ($line in $launcherOutput) {
                if ([string]$line -match '(?i)([A-Z]:\\.*?pythonw?\.exe)\s*$') {
                    $candidates.Add($Matches[1].Trim())
                }
            }
        }
    }

    # Also inspect PATH, common python.org install locations, and registry
    # registrations so embedded or per-user installs are not missed.
    foreach ($commandName in @("python.exe", "python3.exe")) {
        Get-Command $commandName -All -ErrorAction SilentlyContinue |
            ForEach-Object {
                if ($_.Source -and $_.Source -notlike "*\WindowsApps\*") {
                    $candidates.Add($_.Source)
                }
            }
    }

    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    foreach ($pattern in @(
        (Join-Path $env:LOCALAPPDATA "Python\pythoncore-*\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python*\python.exe"),
        (Join-Path $env:ProgramFiles "Python*\python.exe"),
        (Join-Path $programFilesX86 "Python*\python.exe"),
        "C:\Python*\python.exe"
    )) {
        if (-not $pattern) { continue }
        Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue |
            ForEach-Object { $candidates.Add($_.FullName) }
    }

    foreach ($registryRoot in @(
        "HKCU:\SOFTWARE\Python\PythonCore",
        "HKLM:\SOFTWARE\Python\PythonCore"
    )) {
        if (-not (Test-Path $registryRoot)) { continue }
        foreach ($entry in (Get-ChildItem -Path $registryRoot -ErrorAction SilentlyContinue)) {
            $installKey = Join-Path $entry.PSPath "InstallPath"
            if (-not (Test-Path $installKey)) { continue }
            $key = Get-Item -LiteralPath $installKey -ErrorAction SilentlyContinue
            if (-not $key) { continue }
            $executable = [string]$key.GetValue("ExecutablePath")
            if (-not $executable) {
                $directory = [string]$key.GetValue("")
                if ($directory) { $executable = Join-Path $directory "python.exe" }
            }
            if ($executable) { $candidates.Add($executable) }
        }
    }

    $seen = @{}
    $supported = New-Object System.Collections.Generic.List[object]
    foreach ($candidate in $candidates) {
        $key = [string]$candidate
        if (-not $key -or $seen.ContainsKey($key.ToLowerInvariant())) { continue }
        $seen[$key.ToLowerInvariant()] = $true
        if (-not (Test-Path -LiteralPath $key)) { continue }
        $found = Test-SupportedPython $key
        if ($found) { $supported.Add($found) }
    }

    if ($supported.Count -eq 0) { return $null }
    $ordered = @($supported | Sort-Object -Property @{ Expression = { [version]$_.Version }; Descending = $true })
    foreach ($candidate in $ordered) {
        if (Test-PythonDependencyCompatibility $candidate $RequirementsPath) {
            Write-Host "Using compatible Python $($candidate.Version): $($candidate.Executable)" -ForegroundColor Green
            return $candidate
        }
    }
    return $null
}
function Install-PythonStable([string]$RequirementsPath) {
    # Keep the fallback interpreter app-local. This avoids modifying PATH or
    # replacing/side-by-siding with a Python installation owned by the user.
    $pythonBase = Join-Path $AppDir "python-base"
    $pythonExecutable = Join-Path $pythonBase "python.exe"
    $installerPath = Join-Path $env:TEMP "streamsnip-python-3.14.10-amd64.exe"
    $downloadUrl = "https://www.python.org/ftp/python/3.14.10/python-3.14.10-amd64.exe"
    $expectedSha256 = "92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965"

    Write-Host "No compatible 64-bit Python 3.10+ installation was found." -ForegroundColor Yellow
    Write-Host "Installing the stable Python 3.14.10 runtime privately for StreamSnip AI..." -ForegroundColor Cyan
    try {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath -UseBasicParsing
        $actualSha256 = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSha256 -ne $expectedSha256) {
            throw "The downloaded Python installer failed its SHA-256 verification."
        }

        New-Item -ItemType Directory -Force -Path $pythonBase | Out-Null
        $targetArgument = 'TargetDir="' + $pythonBase + '"'
        $installArguments = @(
            "/quiet",
            "InstallAllUsers=0",
            $targetArgument,
            "Include_pip=1",
            "Include_launcher=0",
            "Include_doc=0",
            "Include_test=0",
            "PrependPath=0",
            "Shortcuts=0"
        )
        $process = Start-Process -FilePath $installerPath -ArgumentList $installArguments -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Python 3.14.10 installation failed with exit code $($process.ExitCode)."
        }
    } finally {
        Remove-Item -LiteralPath $installerPath -Force -ErrorAction SilentlyContinue
    }

    $python = Test-SupportedPython $pythonExecutable
    if (-not $python) {
        throw "Python 3.14.10 was installed, but the private interpreter failed validation."
    }
    if (-not (Test-PythonDependencyCompatibility $python $RequirementsPath)) {
        throw "The private Python fallback does not have compatible distributions for every StreamSnip AI requirement."
    }
    Write-Host "Installed app-local Python $($python.Version): $($python.Executable)" -ForegroundColor Green
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
        Mark-DependencyInstalled "ffmpeg"
        $ffmpeg = Find-FFmpeg
    }
    if (-not $ffmpeg) {
        throw "FFmpeg was installed, but this setup could not locate it. Restart Windows and launch StreamSnip AI again."
    }
    $ffmpegDir = Split-Path -Parent $ffmpeg
    $env:Path = $ffmpegDir + ";" + $env:Path
    return $ffmpeg
}

function Test-CudaWheelFiles([string]$RuntimePython) {
    $probe = @'
import importlib.util
from pathlib import Path

required = {
    "nvidia.cublas": ("cublas64_12.dll", "cublasLt64_12.dll"),
    "nvidia.cuda_runtime": ("cudart64_12.dll",),
    "nvidia.cudnn": ("cudnn64_9.dll", "cudnn_ops64_9.dll"),
}
missing = []
for package, names in required.items():
    spec = importlib.util.find_spec(package)
    if not spec or not spec.submodule_search_locations:
        missing.append(package)
        continue
    package_root = Path(next(iter(spec.submodule_search_locations)))
    for name in names:
        if not (package_root / "bin" / name).is_file():
            missing.append(f"{package}/bin/{name}")
print("CUDA wheel DLL check: " + ("OK" if not missing else "missing " + ", ".join(missing)))
raise SystemExit(1 if missing else 0)
'@
    $probePath = Join-Path $env:TEMP "streamsnip-cuda-wheel-probe-$PID.py"
    $probeExit = 1
    try {
        Set-Content -LiteralPath $probePath -Value $probe -Encoding UTF8
        $probeOutput = & $RuntimePython $probePath 2>&1
        $probeExit = $LASTEXITCODE
        $probeOutput | ForEach-Object { Write-Host $_ }
    } finally {
        Remove-Item -LiteralPath $probePath -Force -ErrorAction SilentlyContinue
    }
    return ($probeExit -eq 0)
}

function Repair-CudaWheelDependencies([string]$RuntimePython) {
    Write-Host "Repairing missing CUDA 12/cuDNN 9 wheel DLLs from PyPI..." -ForegroundColor Yellow
    & $RuntimePython -m pip install --disable-pip-version-check --prefer-binary --force-reinstall nvidia-cublas-cu12 nvidia-cuda-runtime-cu12 "nvidia-cudnn-cu12>=9,<10"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not reinstall the CUDA/cuDNN runtime wheels. Check internet access and the pip output."
    }
    if (-not (Test-CudaWheelFiles $RuntimePython)) {
        throw "CUDA/cuDNN packages were reinstalled, but required DLLs are still missing."
    }
}

function Ensure-SpeechModels($RuntimePython, [string]$ModelRoot) {
    $models = @("distil-large-v3", "large-v3-turbo", "medium", "large-v3", "small", "base")
    $bootstrap = @'
from pathlib import Path
import shutil
import sys
from faster_whisper import download_model

root = Path(sys.argv[1])

def is_valid_model(folder: Path) -> bool:
    model_file = folder / "model.bin"
    return (
        model_file.is_file()
        and model_file.stat().st_size > 1_000_000
        and (folder / "config.json").is_file()
        and (folder / "tokenizer.json").is_file()
    )

for name in sys.argv[2:]:
    destination = root / name
    if is_valid_model(destination):
        print(f"Speech model already ready: {name}")
        continue
    if destination.exists():
        print(f"Repairing incomplete speech model: {name}", flush=True)
        shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    print(f"Downloading speech model: {name}", flush=True)
    downloaded = Path(download_model(name, output_dir=str(destination), local_files_only=False))
    if not is_valid_model(destination) and not is_valid_model(downloaded):
        raise RuntimeError(f"{name} download is incomplete (model.bin/config/tokenizer missing or invalid)")
    print(f"Speech model ready: {name}", flush=True)
'@
    $bootstrapPath = Join-Path $env:TEMP "streamsnip-model-bootstrap-$PID.py"
    try {
        Set-Content -LiteralPath $bootstrapPath -Value $bootstrap -Encoding UTF8
        & $RuntimePython $bootstrapPath $ModelRoot @models
        if ($LASTEXITCODE -ne 0) { throw "Could not download and verify all StreamSnip AI speech models." }
    } finally {
        Remove-Item -LiteralPath $bootstrapPath -Force -ErrorAction SilentlyContinue
    }
}

function Save-HuggingFaceSetupSettings($Settings, [string]$SettingsPath) {
    $directory = Split-Path -Parent $SettingsPath
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $temporaryPath = "$SettingsPath.$PID.tmp"
    $json = $Settings | ConvertTo-Json -Depth 10
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($temporaryPath, $json, $utf8NoBom)
    Move-Item -LiteralPath $temporaryPath -Destination $SettingsPath -Force
}

function Request-HuggingFaceToken {
    $settingsPath = if ($DesktopShell) {
        Join-Path $logRoot "Library\ai_settings.json"
    } else {
        Join-Path $source "ai_settings.json"
    }
    $settings = $null
    if (Test-Path $settingsPath) {
        try { $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json } catch {}
    }
    if ($null -eq $settings) { $settings = [pscustomobject]@{} }

    $savedToken = [string]$settings.huggingface_token
    $environmentToken = if ($env:HF_TOKEN) { $env:HF_TOKEN } else { $env:HUGGING_FACE_HUB_TOKEN }

    if ($savedToken) {
        $env:HF_TOKEN = $savedToken.Trim()
        $env:HUGGING_FACE_HUB_TOKEN = $env:HF_TOKEN
    } elseif ($environmentToken) {
        $env:HF_TOKEN = $environmentToken.Trim()
        $env:HUGGING_FACE_HUB_TOKEN = $env:HF_TOKEN
    }

    $choiceValue = [string]$settings.huggingface_setup_completed
    $setupCompleted = $choiceValue.Trim().ToLowerInvariant() -in @("true", "1", "yes", "completed")

    if ($savedToken -or $environmentToken) {
        if (-not $setupCompleted) {
            if ($settings.PSObject.Properties["huggingface_setup_completed"]) {
                $settings.huggingface_setup_completed = $true
            } else {
                $settings | Add-Member -NotePropertyName "huggingface_setup_completed" -NotePropertyValue $true
            }
            Save-HuggingFaceSetupSettings $settings $settingsPath
        }
        return
    }

    if ($setupCompleted) { return }
    if ($NonInteractive) {
        Write-Host "Skipping the optional Hugging Face token prompt for this non-interactive setup." -ForegroundColor Yellow
        return
    }

    Write-Host ""
    Write-Host "Hugging Face authentication (optional, one-time setup)" -ForegroundColor Cyan
    Write-Host "You can paste an hf_... token for authenticated model downloads." -ForegroundColor Yellow
    Write-Host "You can ignore this step and press Enter to continue without a token." -ForegroundColor Yellow
    Write-Host "Without a token, public model downloads may be slower." -ForegroundColor Yellow
    Write-Host "Your choice is saved, so this question will not appear again." -ForegroundColor Green
    $secureToken = Read-Host -AsSecureString -Prompt "HF token (optional; input is hidden)"

    if ($secureToken -and $secureToken.Length -gt 0) {
        $tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
        try {
            $savedToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer)
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
        }
        $savedToken = $savedToken.Trim()
        $settings | Add-Member -NotePropertyName "huggingface_token" -NotePropertyValue $savedToken -Force
        $env:HF_TOKEN = $savedToken
        $env:HUGGING_FACE_HUB_TOKEN = $savedToken
        Write-Host "Hugging Face token saved. Authenticated model downloads enabled." -ForegroundColor Green
    } else {
        Write-Host "No token saved. Continuing with public downloads; they may be slower." -ForegroundColor Yellow
    }

    $settings | Add-Member -NotePropertyName "huggingface_setup_completed" -NotePropertyValue $true -Force
    Save-HuggingFaceSetupSettings $settings $settingsPath
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
    $script:DependencyStatePath = Join-Path $logRoot "installer-dependencies.json"

    New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
    if (Test-Path $script:DependencyStatePath) {
        try {
            $savedOwnership = Get-Content -LiteralPath $script:DependencyStatePath -Raw | ConvertFrom-Json
            $script:DependencyOwnership.python_installed_by_streamsnip = [bool]$savedOwnership.python_installed_by_streamsnip
            $script:DependencyOwnership.ffmpeg_installed_by_streamsnip = [bool]$savedOwnership.ffmpeg_installed_by_streamsnip
        } catch {
            Write-Host "Previous dependency ownership could not be read; existing global tools will be kept during uninstall." -ForegroundColor Yellow
        }
    }
    try {
        Start-Transcript -Path $logPath -Append | Out-Null
        $transcriptStarted = $true
    } catch {}

    Write-Host "StreamSnip AI setup" -ForegroundColor Cyan
    Write-Host "Setup log: $logPath"
    Request-HuggingFaceToken
    $requiredSourceFiles = @(
        "autoclip.py",
        "api_server.py",
        "ai_highlights.py",
        "post_metadata.py",
        "zernio_poster.py",
        "zernio_connections.py",
        "facecam_detect.py",
        "requirements.txt",
        "models\face_detection_yunet_2023mar.onnx",
        "dashboard\dist\index.html"
    )
    $missingSourceFiles = @($requiredSourceFiles | Where-Object { -not (Test-Path (Join-Path $source $_)) })
    if ($missingSourceFiles.Count -gt 0) {
        throw ("The StreamSnip AI package is incomplete. Missing: " + ($missingSourceFiles -join ", ") + ". Reinstall the application.")
    }

    $python = Find-SupportedPython $requirements
    if (-not $python -and -not $CheckOnly) { $python = Install-PythonStable $requirements }
    if (-not $python) { throw "A stable 64-bit Python 3.10 or newer is required." }
    Write-Host "Python $($python.Version): $($python.Executable)" -ForegroundColor Green

    $ffmpeg = Ensure-FFmpeg
    Write-Host "FFmpeg: $ffmpeg" -ForegroundColor Green
    $ffmpegProbe = & $ffmpeg -hide_banner -v error -f lavfi -i "color=c=black:s=128x128:d=0.1" -frames:v 1 -f null NUL 2>&1
    $ffmpegProbeExit = $LASTEXITCODE
    if ($ffmpegProbeExit -ne 0) {
        throw ("FFmpeg was found but failed its decode/encode smoke test: " + (@($ffmpegProbe) -join " "))
    }
    Write-Host "FFmpeg decode/encode smoke test passed." -ForegroundColor Green
    if ($CheckOnly) {
        Write-Host "Installer prerequisites are available." -ForegroundColor Green
    } else {
        $runtimeInfo = $null
        if (Test-Path $runtimePython) { $runtimeInfo = Test-SupportedPython $runtimePython }

        $selectedPythonVersion = [version]$python.Version
        $runtimeMatchesSelectedPython = $false
        if ($runtimeInfo) {
            $installedRuntimeVersion = [version]$runtimeInfo.Version
            $runtimeMatchesSelectedPython = (
                $installedRuntimeVersion.Major -eq $selectedPythonVersion.Major -and
                $installedRuntimeVersion.Minor -eq $selectedPythonVersion.Minor
            )
        }

        $runtimeBackup = Join-Path $AppDir "runtime.previous"
        if (Test-Path -LiteralPath $runtimeBackup) {
            if (-not (Test-Path -LiteralPath $runtime)) {
                Move-Item -LiteralPath $runtimeBackup -Destination $runtime
                Write-Host "Recovered the previous working Python runtime after an interrupted update." -ForegroundColor Yellow
                $runtimeInfo = Test-SupportedPython $runtimePython
            } else {
                throw "A previous runtime backup exists at $runtimeBackup. Both runtime folders were preserved; remove the stale backup only after verifying the current runtime."
            }
        }

        if (-not $runtimeMatchesSelectedPython) {
            if (Test-Path -LiteralPath $runtime) {
                Move-Item -LiteralPath $runtime -Destination $runtimeBackup
                $script:RuntimeBackupPath = $runtimeBackup
            }
            try {
                Write-Host "Creating StreamSnip AI's isolated runtime with Python $($python.Version)..." -ForegroundColor Cyan
                $venvResult = Invoke-Python $python @("-m", "venv", $runtime)
                if ($venvResult -ne 0 -or -not (Test-Path $runtimePython)) {
                    throw "Could not create the StreamSnip AI Python runtime."
                }
                $runtimeInfo = Test-SupportedPython $runtimePython
                if (-not $runtimeInfo) { throw "The StreamSnip AI Python runtime is invalid." }
                $runtimeVersion = [version]$runtimeInfo.Version
                if ($runtimeVersion.Major -ne $selectedPythonVersion.Major -or $runtimeVersion.Minor -ne $selectedPythonVersion.Minor) {
                    throw "The new Python runtime does not match the selected Python $($python.Version)."
                }
            } catch {
                if (Test-Path -LiteralPath $runtime) {
                    Remove-Item -LiteralPath $runtime -Recurse -Force -ErrorAction SilentlyContinue
                }
                if ($script:RuntimeBackupPath -and (Test-Path -LiteralPath $script:RuntimeBackupPath)) {
                    Move-Item -LiteralPath $script:RuntimeBackupPath -Destination $runtime -Force
                    $script:RuntimeBackupPath = $null
                    Write-Host "Restored the previous Python runtime after the new runtime could not be created." -ForegroundColor Yellow
                }
                throw
            }
        }

        $requirementsHash = (Get-FileHash $requirements -Algorithm SHA256).Hash.ToLowerInvariant()
        $expectedMarker = "$RuntimeSchema|$requirementsHash"
        $savedMarker = if (Test-Path $runtimeMarker) { (Get-Content $runtimeMarker -Raw).Trim() } else { "" }
        $dependencyProbe = & $runtimePython -c "import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(x) for x in ('numpy','faster_whisper','streamlink','cv2','fastapi','uvicorn','annotated_doc','anyio','attrs','annotated_types')) else 1)" 2>$null
        $dependenciesReady = ($LASTEXITCODE -eq 0)
        if ($savedMarker -ne $expectedMarker -or -not $dependenciesReady) {
            Write-Host "Installing StreamSnip AI dependencies. The first setup can take several minutes..." -ForegroundColor Cyan
            & $runtimePython -m pip install --upgrade pip
            if ($LASTEXITCODE -ne 0) { throw "Could not upgrade pip in the StreamSnip AI runtime." }
            Install-StreamSnipDependencies $runtimePython $requirements $python.Version
            if ($LASTEXITCODE -ne 0) { throw "Could not install StreamSnip AI dependencies." }
            Test-StreamSnipDependencyConsistency $runtimePython $python.Version
            & $runtimePython -c "import numpy, faster_whisper, streamlink, cv2, fastapi, uvicorn, annotated_doc, anyio, attrs, annotated_types"
            if ($LASTEXITCODE -ne 0) { throw "A required StreamSnip AI package could not be loaded after installation." }
            Set-Content -Path $runtimeMarker -Value $expectedMarker -Encoding ASCII
        } else {
            Write-Host "StreamSnip AI dependencies are already installed." -ForegroundColor Green
        }

        $nvidiaPresent = @(
            Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
                Where-Object { $_.PNPDeviceID -like "*VEN_10DE*" -or $_.Name -match "NVIDIA" }
        ).Count -gt 0
        if ($nvidiaPresent -and -not (Test-CudaWheelFiles $runtimePython)) {
            Repair-CudaWheelDependencies $runtimePython
            Test-StreamSnipDependencyConsistency $runtimePython $python.Version
        }

        # Explicitly probe CTranslate2's CUDA runtime on every setup/repair.
        # The actual model load and inference smoke below is the final GPU gate.
        $cudaProbe = & $runtimePython -c "import ctranslate2; n=ctranslate2.get_cuda_device_count(); print('CUDA devices detected: ' + str(n)); raise SystemExit(0 if n > 0 else 3)" 2>&1
        $cudaProbeExit = $LASTEXITCODE
        $cudaProbe | ForEach-Object { Write-Host $_ }
        if ($cudaProbeExit -eq 0) {
            Write-Host "CUDA runtime is ready for Whisper inference." -ForegroundColor Green
        } else {
            if ($nvidiaPresent) {
                throw "An NVIDIA GPU is installed, but CTranslate2 cannot initialize CUDA. Repair the NVIDIA driver/CUDA runtime before using StreamSnip AI."
            }
            Write-Host "No NVIDIA CUDA GPU was detected; StreamSnip AI will use CPU inference." -ForegroundColor Yellow
        }

        # Desktop shell uses STREAMSNIP_DATA_DIR=<Library>, so its active
        # Whisper models must live in Library\models, not the packaged source tree.
        $speechModelRoot = if ($DesktopShell) {
            Join-Path $logRoot "Library\models"
        } else {
            Join-Path $source "models"
        }
        if ($DesktopShell) {
            $legacyModelRoot = Join-Path $source "models"
            New-Item -ItemType Directory -Force -Path $speechModelRoot | Out-Null
            foreach ($modelName in @("distil-large-v3", "large-v3-turbo", "medium", "large-v3", "small", "base")) {
                $legacyModelPath = Join-Path $legacyModelRoot $modelName
                $modelDestination = Join-Path $speechModelRoot $modelName
                $legacyBin = Join-Path $legacyModelPath "model.bin"
                if (-not (Test-Path -LiteralPath $modelDestination) -and
                    (Test-Path -LiteralPath $legacyBin) -and
                    (Get-Item -LiteralPath $legacyBin).Length -gt 1MB -and
                    (Test-Path (Join-Path $legacyModelPath "config.json")) -and
                    (Test-Path (Join-Path $legacyModelPath "tokenizer.json"))) {
                    Move-Item -LiteralPath $legacyModelPath -Destination $modelDestination
                    Write-Host "Moved verified installed model into the engine's active model store: $modelName" -ForegroundColor Green
                }
            }
        }
        Write-Host "Downloading and verifying StreamSnip AI speech models. This can take a while and needs an internet connection..." -ForegroundColor Cyan
        Ensure-SpeechModels $runtimePython $speechModelRoot

        # Exercise the exact default Whisper model through CUDA inference before
        # marking setup complete. This catches CUDA DLL, model, and backend issues
        # that package imports alone cannot detect.
        $whisperSmoke = @'
import os
import sys
import tempfile
import wave
import subprocess
import threading
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

root = Path(sys.argv[1])
source = Path(sys.argv[2])
os.environ["STREAMSNIP_DATA_DIR"] = str(root.parent)
os.environ["STREAMSNIP_FFMPEG_PATH"] = sys.argv[3]
sys.path.insert(0, str(source))
import autoclip  # initializes the same CUDA DLL search paths as the running engine
import numpy as np
import ctranslate2
from faster_whisper import WhisperModel

name = "distil-large-v3"
model_path = root / name
device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
compute_types = ("float16", "int8_float16") if device == "cuda" else ("int8",)
last_error = None
model = None
for compute_type in compute_types:
    try:
        print(f"Loading installed default Whisper model on {device} ({compute_type})...", flush=True)
        model = WhisperModel(str(model_path), device=device, compute_type=compute_type)
        break
    except Exception as exc:
        last_error = exc
if model is None:
    raise RuntimeError(f"Default Whisper model could not load on {device}: {last_error}")
segments, _ = model.transcribe(np.zeros(32000, dtype=np.float32), language="en", vad_filter=False, beam_size=1)
list(segments)
print(f"WHISPER_RUNTIME_SMOKE_PASS model={name} device={device}", flush=True)

# Verify the installed Engine.transcribe path too, including FFmpeg decoding
# and optional VAD behavior on Python versions without ONNX Runtime.
autoclip._model = model
autoclip._model_key = (name, device)
smoke_wav = Path(tempfile.gettempdir()) / f"streamsnip-engine-transcribe-smoke-{os.getpid()}.wav"
with wave.open(str(smoke_wav), "wb") as audio_file:
    audio_file.setnchannels(1)
    audio_file.setsampwidth(2)
    audio_file.setframerate(16000)
    audio_file.writeframes(bytes(32000 * 2))
engine = autoclip.Engine(autoclip.clean_cfg({"model": name}), lambda *_: None)
engine.transcribe(str(smoke_wav))
smoke_wav.unlink(missing_ok=True)
print("ENGINE_TRANSCRIPTION_SMOKE_PASS", flush=True)

# Exercise actual clip rendering and Streamlink-to-FFmpeg capture using a local
# generated HLS source. No account, credentials, or public stream are required.
with tempfile.TemporaryDirectory(prefix="streamsnip-install-smoke-") as temp_dir:
    smoke_root = Path(temp_dir)
    smoke_out = smoke_root / "out"
    smoke_rec = smoke_root / "rec"
    smoke_hls = smoke_root / "hls"
    for folder in (smoke_out, smoke_rec, smoke_hls):
        folder.mkdir(parents=True, exist_ok=True)
    autoclip.OUT = smoke_out
    autoclip.REC = smoke_rec
    ffmpeg = os.environ["STREAMSNIP_FFMPEG_PATH"]
    source_video = smoke_root / "smoke-source.mp4"
    source_result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
         "-map", "0:v:0", "-map", "1:a:0", "-shortest",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", str(source_video)],
        capture_output=True, text=True,
    )
    if source_result.returncode != 0 or not source_video.is_file():
        raise RuntimeError(f"Could not create synthetic render/capture source: {source_result.stderr[-800:]}")

    render_engine = autoclip.Engine(
        autoclip.clean_cfg({"mode": "file", "output_format": "9:16",
                            "layout": "Blur background", "subtitle_style": "Minimal"}),
        lambda *_: None,
    )
    render_engine.out_dir = smoke_out
    render_engine.ai_cfg_for_render = {"provider": "hooks"}
    smoke_words = [(0.25, 0.65, "stream"), (0.65, 1.05, "snip"),
                   (1.05, 1.55, "runtime"), (1.55, 2.0, "test")]
    render_engine.render(source_video, 0.0, 5.0, smoke_words, "setup_render_smoke")
    rendered = smoke_out / "setup_render_smoke.mp4"
    if not rendered.is_file() or rendered.stat().st_size < 10000:
        raise RuntimeError("The installed clip renderer did not produce a valid MP4.")
    decode_result = subprocess.run(
        [ffmpeg, "-hide_banner", "-v", "error", "-i", str(rendered), "-f", "null", "NUL"],
        capture_output=True, text=True,
    )
    if decode_result.returncode != 0:
        raise RuntimeError(f"The rendered MP4 failed FFmpeg decode verification: {decode_result.stderr[-800:]}")
    print("RENDER_RUNTIME_SMOKE_PASS", flush=True)

    hls_result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source_video),
         "-c", "copy", "-hls_time", "2", "-hls_list_size", "0",
         "-hls_flags", "independent_segments",
         "-hls_segment_filename", str(smoke_hls / "capture_%03d.ts"),
         str(smoke_hls / "live.m3u8")],
        capture_output=True, text=True,
    )
    if hls_result.returncode != 0 or not (smoke_hls / "live.m3u8").is_file():
        raise RuntimeError(f"Could not create the local HLS capture test stream: {hls_result.stderr[-800:]}")

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    handler = partial(QuietHandler, directory=str(smoke_hls))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    capture_url = f"http://127.0.0.1:{server.server_port}/live.m3u8"

    class CaptureSmokeEngine(autoclip.Engine):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.captured_segments = []

        def process(self, path):
            segment_path = Path(path)
            self.captured_segments.append((segment_path, segment_path.stat().st_size))

    capture_engine = CaptureSmokeEngine(
        autoclip.clean_cfg({"mode": "live", "target": capture_url,
                            "chunk_min": 3, "clips_per_chunk": 0}),
        lambda *_: None,
    )
    capture_engine.rec_dir = smoke_rec
    capture_engine.out_dir = smoke_out
    capture_engine.seg_seconds = 3
    try:
        capture_engine.record_session(capture_url)
    finally:
        server.shutdown()
        server.server_close()
    if not capture_engine.captured_segments or max(size for _, size in capture_engine.captured_segments) < 200000:
        raise RuntimeError("Streamlink/FFmpeg capture produced no usable recording segment.")
    captured_path = capture_engine.captured_segments[0][0]
    captured_decode = subprocess.run(
        [ffmpeg, "-hide_banner", "-v", "error", "-i", str(captured_path), "-f", "null", "NUL"],
        capture_output=True, text=True,
    )
    if captured_decode.returncode != 0:
        raise RuntimeError(f"The captured segment failed FFmpeg decode verification: {captured_decode.stderr[-800:]}")
    print("CAPTURE_RUNTIME_SMOKE_PASS", flush=True)
'@
        $whisperSmokePath = Join-Path $env:TEMP "streamsnip-whisper-smoke-$PID.py"
        try {
            Set-Content -LiteralPath $whisperSmokePath -Value $whisperSmoke -Encoding UTF8
            & $runtimePython $whisperSmokePath $speechModelRoot $source $ffmpeg
            if ($LASTEXITCODE -ne 0) {
                throw "Installed default Whisper model failed its real inference smoke test. Capture/render setup cannot be marked complete."
            }
        } finally {
            Remove-Item -LiteralPath $whisperSmokePath -Force -ErrorAction SilentlyContinue
        }

        # Commit the runtime migration only after dependencies and speech models are verified.
        if ($script:RuntimeBackupPath -and (Test-Path -LiteralPath $script:RuntimeBackupPath)) {
            Remove-Item -LiteralPath $script:RuntimeBackupPath -Recurse -Force
            $script:RuntimeBackupPath = $null
            Write-Host "New Python runtime verified; previous runtime backup removed." -ForegroundColor Green
        }

        if ($DesktopShell) {
            # The pywebview shell reads this config to find the installed engine and
            # user library. Write it only after Python, packages and all speech
            # models have passed setup verification.
            $dataRoot = Join-Path $logRoot "Library"
            $nativeConfigPath = Join-Path $logRoot "desktop-shell.json"
            $nativeConfigTemp = "$nativeConfigPath.$PID.tmp"
            New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
            $nativeConfig = [ordered]@{
                source_root = $source
                python_executable = $runtimePython
                data_root = $dataRoot
                ffmpeg_executable = $ffmpeg
            }
            $nativeConfigJson = $nativeConfig | ConvertTo-Json -Depth 4
            $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::WriteAllText($nativeConfigTemp, $nativeConfigJson, $utf8NoBom)
            Move-Item -LiteralPath $nativeConfigTemp -Destination $nativeConfigPath -Force
            Write-Host "Desktop shell engine configuration saved: $nativeConfigPath" -ForegroundColor Green
            Write-Host "Clip library and application data: $dataRoot" -ForegroundColor Green
        }

        if (-not $SkipLaunch) {
            Write-Host "Launching StreamSnip AI..." -ForegroundColor Cyan
            $quotedMain = '"' + $main.Replace('"', '\"') + '"'
            $process = Start-Process -FilePath $runtimePython -ArgumentList $quotedMain -WorkingDirectory $source -PassThru
            if (-not $process) { throw "StreamSnip AI could not be launched." }
        }
    }
} catch {
    $exitCode = 1
    if ($script:RuntimeBackupPath -and (Test-Path -LiteralPath $script:RuntimeBackupPath)) {
        try {
            if (Test-Path -LiteralPath $runtime) {
                Remove-Item -LiteralPath $runtime -Recurse -Force -ErrorAction Stop
            }
            Move-Item -LiteralPath $script:RuntimeBackupPath -Destination $runtime -Force -ErrorAction Stop
            $script:RuntimeBackupPath = $null
            Write-Host "Runtime migration failed. The previous working Python runtime was restored." -ForegroundColor Yellow
        } catch {
            Write-Host "Automatic runtime rollback failed. The previous runtime backup is preserved at $script:RuntimeBackupPath" -ForegroundColor Red
        }
    }
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
    if ($setupMutexOwned) {
        try { $setupMutex.ReleaseMutex() } catch {}
    }
    if ($setupMutex) { $setupMutex.Dispose() }
}

exit $exitCode
