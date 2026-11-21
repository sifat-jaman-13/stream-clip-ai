param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir,
    [string]$DependencyStatePath = "",
    [switch]$SkipGlobalDependencyRemoval
)

$ErrorActionPreference = "Continue"
$AppDir = [IO.Path]::GetFullPath($AppDir)
$logRoot = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "StreamSnip AI" } else { $AppDir }
$uninstallLog = Join-Path $logRoot "uninstall-cleanup.log"

try { New-Item -ItemType Directory -Force -Path $logRoot | Out-Null } catch {}

function Write-CleanupLog([string]$Message) {
    try { Add-Content -LiteralPath $uninstallLog -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message) } catch {}
}

function Remove-AppDependency([string]$Path, [string]$Label) {
    try {
        $resolvedPath = [IO.Path]::GetFullPath($Path)
        $prefix = $AppDir.TrimEnd('\') + '\'
        if (-not $resolvedPath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
            Write-CleanupLog "Skipped $Label because its path was outside the application folder."
            return
        }
        if (Test-Path -LiteralPath $resolvedPath) {
            Remove-Item -LiteralPath $resolvedPath -Recurse -Force -ErrorAction Stop
            Write-CleanupLog "Removed $Label."
        } else {
            Write-CleanupLog "$Label was already absent."
        }
    } catch {
        Write-CleanupLog "Could not remove ${Label}: $($_.Exception.Message)"
    }
}

# These are app-owned generated dependencies. User clips, recordings, and settings are kept.
Remove-AppDependency (Join-Path $AppDir "runtime") "isolated Python runtime and pip packages"
Remove-AppDependency (Join-Path $AppDir "source\models") "downloaded Whisper speech models"

if (-not $DependencyStatePath) {
    $DependencyStatePath = Join-Path $logRoot "installer-dependencies.json"
}

if (-not $SkipGlobalDependencyRemoval -and (Test-Path -LiteralPath $DependencyStatePath)) {
    try {
        $ownership = Get-Content -LiteralPath $DependencyStatePath -Raw | ConvertFrom-Json
    } catch {
        $ownership = $null
        Write-CleanupLog "Dependency ownership record was unreadable; global Python and FFmpeg will be kept."
    }

    if ($ownership) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $winget -and ($ownership.python_installed_by_streamsnip -or $ownership.ffmpeg_installed_by_streamsnip)) {
            Write-CleanupLog "WinGet was not found; app-installed global dependencies could not be removed."
        } else {
            if ($ownership.python_installed_by_streamsnip) {
                try {
                    & $winget.Source uninstall --id Python.Python.3.12 --exact --source winget --disable-interactivity 2>&1 |
                        ForEach-Object { Write-CleanupLog ([string]$_) }
                    if ($LASTEXITCODE -eq 0) { Write-CleanupLog "Removed Python 3.12 installed by StreamSnip AI." }
                    else { Write-CleanupLog "WinGet could not remove Python 3.12 (exit $LASTEXITCODE)." }
                } catch { Write-CleanupLog "Python uninstall failed: $($_.Exception.Message)" }
            }
            if ($ownership.ffmpeg_installed_by_streamsnip) {
                try {
                    & $winget.Source uninstall --id Gyan.FFmpeg --exact --source winget --disable-interactivity 2>&1 |
                        ForEach-Object { Write-CleanupLog ([string]$_) }
                    if ($LASTEXITCODE -eq 0) { Write-CleanupLog "Removed FFmpeg installed by StreamSnip AI." }
                    else { Write-CleanupLog "WinGet could not remove FFmpeg (exit $LASTEXITCODE)." }
                } catch { Write-CleanupLog "FFmpeg uninstall failed: $($_.Exception.Message)" }
            }
        }
    }
} else {
    Write-CleanupLog "No owned global dependencies were recorded; Python and FFmpeg were left untouched."
}

if (Test-Path -LiteralPath $DependencyStatePath) {
    try {
        Remove-Item -LiteralPath $DependencyStatePath -Force -ErrorAction Stop
        Write-CleanupLog "Removed dependency ownership record."
    } catch {
        Write-CleanupLog "Could not remove dependency ownership record: $($_.Exception.Message)"
    }
}

Write-CleanupLog "Uninstaller dependency cleanup finished. Clips, recordings, and local settings were not targeted."
exit 0
