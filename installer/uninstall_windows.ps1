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
$localRoot = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "StreamSnip AI" } else { $null }
$uninstallLog = Join-Path $env:TEMP "StreamSnipAI-uninstall-$PID.log"
if (-not $DependencyStatePath -and $localRoot) {
    $DependencyStatePath = Join-Path $localRoot "installer-dependencies.json"
}
$ownership = $null
if ($DependencyStatePath -and (Test-Path -LiteralPath $DependencyStatePath -PathType Leaf)) {
    try { $ownership = Get-Content -LiteralPath $DependencyStatePath -Raw -ErrorAction Stop | ConvertFrom-Json }
    catch { Write-Host "Could not read dependency ownership; shared global dependencies will be kept." }
}

function Write-CleanupLog([string]$Message) {
    try { Add-Content -LiteralPath $uninstallLog -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message) } catch {}
}

function Remove-PathSafely([string]$Path, [string]$Label) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    if (-not (Test-Path -LiteralPath $Path)) { return }
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        Write-CleanupLog "Removed $Label."
    } catch {
        Write-CleanupLog "ERROR removing ${Label}: $($_.Exception.Message)"
        throw
    }
}

function Save-DependencyOwnership {
    if ([string]::IsNullOrWhiteSpace($DependencyStatePath) -or $null -eq $ownership) { return }
    $parent = Split-Path -Parent $DependencyStatePath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $temporaryPath = "$DependencyStatePath.$PID.tmp"
    try {
        $ownership | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
        Move-Item -LiteralPath $temporaryPath -Destination $DependencyStatePath -Force
        Write-CleanupLog "Updated dependency ownership state."
    } finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-OwnedDependencyCleanup {
    if ($SkipGlobalDependencyRemoval -or $null -eq $ownership) { return }
    $needsPython = [bool]$ownership.python_installed_by_streamsnip
    $needsFfmpeg = [bool]$ownership.ffmpeg_installed_by_streamsnip
    if (-not ($needsPython -or $needsFfmpeg)) { return }

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $winget) {
        Write-CleanupLog "ERROR: WinGet unavailable; app-owned global dependency uninstall could not be run."
        throw "WinGet is unavailable, so StreamSnip AI cannot remove its app-owned global dependencies. Repair WinGet and retry uninstall."
    }

    if ($needsPython) {
        & $winget.Source uninstall --id Python.Python.3.12 --exact --source winget --disable-interactivity 2>&1 | ForEach-Object { Write-CleanupLog ([string]$_) }
        if ($LASTEXITCODE -ne 0) {
            Write-CleanupLog "ERROR: app-owned Python package uninstall returned $LASTEXITCODE."
            throw "Could not uninstall the Python package installed by StreamSnip AI. Install/repair WinGet and retry uninstall."
        }
        $ownership.python_installed_by_streamsnip = $false
        Save-DependencyOwnership
    }

    if ($needsFfmpeg) {
        & $winget.Source uninstall --id Gyan.FFmpeg --exact --source winget --disable-interactivity 2>&1 | ForEach-Object { Write-CleanupLog ([string]$_) }
        if ($LASTEXITCODE -ne 0) {
            Write-CleanupLog "ERROR: app-owned FFmpeg package uninstall returned $LASTEXITCODE."
            throw "Could not uninstall the FFmpeg package installed by StreamSnip AI. Install/repair WinGet and retry uninstall."
        }
        $ownership.ffmpeg_installed_by_streamsnip = $false
        Save-DependencyOwnership
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

# Remove globally installed dependencies before deleting the ownership state.
# Each successful removal is persisted so a later attempt can finish only what remains.
Invoke-OwnedDependencyCleanup

$configFiles = @(
    @{ Relative = "desktop-preferences.json"; Target = "desktop-preferences.json" },
    @{ Relative = "Library\settings.json"; Target = "Library\settings.json" },
    @{ Relative = "Library\ai_settings.json"; Target = "Library\ai_settings.json" },
    @{ Relative = "Library\zernio.json"; Target = "Library\zernio.json" },
    @{ Relative = "Library\publishing.json"; Target = "Library\publishing.json" },
    @{ Relative = "Library\custom_words.txt"; Target = "Library\custom_words.txt" }
)

$backupRoot = ""
if ($KeepConfig -and $localRoot) {
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $backupKey = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($AppDir.ToUpperInvariant()))).Replace("-", "").Substring(0, 16).ToLowerInvariant()
    } finally { $hasher.Dispose() }
    $backupRoot = Join-Path $env:TEMP "StreamSnipAI-config-$backupKey"
    New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

    # native-engine.json, streamsnip.db recordings, clips and dependency ownership are deliberately not preserved.
# A pre-existing backup is authoritative after an interrupted uninstall. Never overwrite it.
    foreach ($entry in $configFiles) {
        $sourcePath = Join-Path $localRoot $entry.Relative
        if (Test-Path -LiteralPath $sourcePath -PathType Leaf) {
            $backupPath = Join-Path $backupRoot $entry.Target
            if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupPath) | Out-Null
                Copy-Item -LiteralPath $sourcePath -Destination $backupPath -ErrorAction Stop
                if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
                    throw "Configuration backup failed for $($entry.Relative). The original files have not been removed."
                }
                $sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
                $backupHash = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash
                if ($sourceHash -ne $backupHash) {
                    throw "Configuration backup verification failed for $($entry.Relative). The original files have not been removed."
                }
            }
            Write-CleanupLog "Backed up configuration: $($entry.Relative)"
        }
    }
}

# Do not guess a parent directory when LOCALAPPDATA is absent: that could remove
# the user's entire Programs directory. App installation cleanup remains scoped to AppDir.
if ($localRoot) {
    Remove-PathSafely $localRoot "StreamSnip AI app data"
} else {
    Write-CleanupLog "LOCALAPPDATA is unavailable; skipped app-data cleanup rather than deleting an installation parent."
}

if ($KeepConfig -and $backupRoot -and (Test-Path -LiteralPath $backupRoot -PathType Container)) {
    try {
        New-Item -ItemType Directory -Force -Path $localRoot | Out-Null
        foreach ($entry in $configFiles) {
            $backupPath = Join-Path $backupRoot $entry.Target
            if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) { continue }
            $destination = Join-Path $localRoot $entry.Relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
            Copy-Item -LiteralPath $backupPath -Destination $destination -Force -ErrorAction Stop
            if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
                throw "Configuration restore did not create $($entry.Relative)."
            }
            $backupHash = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash
            $restoredHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
            if ($backupHash -ne $restoredHash) {
                throw "Configuration restore verification failed for $($entry.Relative)."
            }
        }
        Remove-PathSafely $backupRoot "temporary configuration backup"
        Write-CleanupLog "Restored only the explicitly whitelisted configuration files."
    } catch {
        Write-CleanupLog "Configuration backup retained for retry at $backupRoot. Restore error: $($_.Exception.Message)"
        throw "Configuration restore failed. Your backup has been retained for retry at: $backupRoot. $($_.Exception.Message)"
    }
} elseif ($KeepConfig -and -not $localRoot) {
    Write-CleanupLog "Configuration preservation was requested but LOCALAPPDATA is unavailable; no local settings folder was removed."
}

Remove-PathSafely (Join-Path $AppDir "runtime") "isolated Python runtime"
Remove-PathSafely (Join-Path $AppDir "runtime.previous") "previous Python runtime backup"
Remove-PathSafely (Join-Path $AppDir "python-base") "app-local Python base"
Remove-PathSafely (Join-Path $AppDir "source\models") "downloaded speech models"
Remove-PathSafely (Join-Path $AppDir "source\dashboard") "dashboard runtime payload"

if ($DependencyStatePath -and (Test-Path -LiteralPath $DependencyStatePath -PathType Leaf)) {
    Remove-Item -LiteralPath $DependencyStatePath -Force -ErrorAction Stop
}

Write-CleanupLog "Uninstall cleanup completed. KeepConfig=$KeepConfig; RemoveAllData=$RemoveAllData."
Remove-Item -LiteralPath $uninstallLog -Force -ErrorAction SilentlyContinue
Write-Host "StreamSnip AI cleanup completed. All selected app data and generated runtime files were removed."
exit 0
