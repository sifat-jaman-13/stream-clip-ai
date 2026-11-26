param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir,
    [string]$DependencyStatePath = "",
    [switch]$KeepConfig,
    [switch]$RemoveAllData,
    [switch]$SkipGlobalDependencyRemoval
)

$ErrorActionPreference = "Stop"
$AppDir = [IO.Path]::GetFullPath($AppDir)
$localRoot = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "StreamSnip AI" } else { Split-Path -Parent $AppDir }
$appDataRoot = Join-Path $localRoot "Library"
$uninstallLog = Join-Path $env:TEMP "StreamSnipAI-uninstall-$PID.log"
if (-not $DependencyStatePath) {
    $DependencyStatePath = Join-Path $localRoot "installer-dependencies.json"
}
$ownership = $null
if (Test-Path -LiteralPath $DependencyStatePath) {
    try { $ownership = Get-Content -LiteralPath $DependencyStatePath -Raw | ConvertFrom-Json }
    catch { Write-Host "Could not read dependency ownership; shared global dependencies will be kept." }
}

function Write-CleanupLog([string]$Message) {
    try { Add-Content -LiteralPath $uninstallLog -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message) } catch {}
}

function Remove-PathSafely([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        Write-CleanupLog "Removed $Label."
    } catch {
        Write-CleanupLog "ERROR removing ${Label}: $($_.Exception.Message)"
        throw
    }
}

# Stop only StreamSnip-owned processes before deleting runtime files.
$appPrefix = $AppDir.TrimEnd('\') + '\'
$ownedProcesses = @(Get-CimInstance Win32_Process | Where-Object {
    ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($appPrefix, [StringComparison]::OrdinalIgnoreCase)) -or
    ($_.CommandLine -and $_.CommandLine.IndexOf($appPrefix, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        ($_.Name -match '^(python|pythonw|StreamSnip\.Desktop)\.exe$'))
})
foreach ($processInfo in $ownedProcesses) {
    try {
        Stop-Process -Id $processInfo.ProcessId -Force -ErrorAction Stop
        Write-CleanupLog "Stopped StreamSnip-owned process $($processInfo.ProcessId) ($($processInfo.Name))."
    } catch {
        Write-CleanupLog "Could not stop process $($processInfo.ProcessId): $($_.Exception.Message)"
    }
}
Start-Sleep -Milliseconds 700

# Keep only explicit configuration files. Clips, recordings (including streamsnip.db),
# native-engine.json, cached models, runtime logs and diagnostic traces are never kept.
if ($KeepConfig) {
    $configFiles = @(
        @{ Relative = "desktop-preferences.json"; Target = "desktop-preferences.json" },
        @{ Relative = "Library\settings.json"; Target = "Library\settings.json" },
        @{ Relative = "Library\ai_settings.json"; Target = "Library\ai_settings.json" },
        @{ Relative = "Library\zernio.json"; Target = "Library\zernio.json" },
        @{ Relative = "Library\publishing.json"; Target = "Library\publishing.json" },
        @{ Relative = "Library\custom_words.txt"; Target = "Library\custom_words.txt" }
    )
    $backupRoot = Join-Path $env:TEMP "StreamSnipAI-config-$PID"
    New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
    foreach ($entry in $configFiles) {
        $sourcePath = Join-Path $localRoot $entry.Relative
        if (Test-Path -LiteralPath $sourcePath -PathType Leaf) {
            $backupPath = Join-Path $backupRoot $entry.Target
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupPath) | Out-Null
            Copy-Item -LiteralPath $sourcePath -Destination $backupPath -Force
            Write-CleanupLog "Preserved configuration: $($entry.Relative)"
        }
    }
} else {
    $backupRoot = ""
}

Remove-PathSafely $localRoot "StreamSnip AI app data"

if ($KeepConfig -and $backupRoot -and (Test-Path -LiteralPath $backupRoot)) {
    New-Item -ItemType Directory -Force -Path $localRoot | Out-Null
    Get-ChildItem -LiteralPath $backupRoot -Force | ForEach-Object {
        $destination = Join-Path $localRoot $_.Name
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Recurse -Force
    }
    Remove-PathSafely $backupRoot "temporary configuration backup"
    Write-CleanupLog "Restored only the explicitly whitelisted configuration files."
}

if (-not $SkipGlobalDependencyRemoval -and $ownership) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($winget) {
        if ($ownership.python_installed_by_streamsnip) {
            & $winget.Source uninstall --id Python.Python.3.12 --exact --source winget --disable-interactivity 2>&1 | ForEach-Object { Write-CleanupLog ([string]$_) }
            if ($LASTEXITCODE -ne 0) {
                Write-CleanupLog "ERROR: app-owned Python package uninstall returned $LASTEXITCODE."
                throw "Could not uninstall the Python package installed by StreamSnip AI. Install/repair WinGet and retry uninstall."
            }
        }
        if ($ownership.ffmpeg_installed_by_streamsnip) {
            & $winget.Source uninstall --id Gyan.FFmpeg --exact --source winget --disable-interactivity 2>&1 | ForEach-Object { Write-CleanupLog ([string]$_) }
            if ($LASTEXITCODE -ne 0) {
                Write-CleanupLog "ERROR: app-owned FFmpeg package uninstall returned $LASTEXITCODE."
                throw "Could not uninstall the FFmpeg package installed by StreamSnip AI. Install/repair WinGet and retry uninstall."
            }
        }
    } elseif ($ownership.python_installed_by_streamsnip -or $ownership.ffmpeg_installed_by_streamsnip) {
        Write-CleanupLog "ERROR: WinGet unavailable; app-owned global dependency uninstall could not be run."
        throw "WinGet is unavailable, so StreamSnip AI cannot remove its app-owned global dependencies. Repair WinGet and retry uninstall."
    }
}

Remove-PathSafely (Join-Path $AppDir "runtime") "isolated Python runtime"
Remove-PathSafely (Join-Path $AppDir "runtime.previous") "previous Python runtime backup"
Remove-PathSafely (Join-Path $AppDir "python-base") "app-local Python base"
Remove-PathSafely (Join-Path $AppDir "source\models") "downloaded speech models"
Remove-PathSafely (Join-Path $AppDir "source\dashboard") "dashboard runtime payload"

Write-CleanupLog "Uninstall cleanup completed. KeepConfig=$KeepConfig; RemoveAllData=$RemoveAllData."
Remove-Item -LiteralPath $uninstallLog -Force -ErrorAction SilentlyContinue
Write-Host "StreamSnip AI cleanup completed. All selected app data and generated runtime files were removed."
exit 0
