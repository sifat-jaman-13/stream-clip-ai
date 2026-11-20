$ErrorActionPreference = "Stop"
$runtime = Join-Path $env:LOCALAPPDATA "StreamSnip AI\runtime"
$python = $null
$pythonArgs = @()

function Find-Python312 {
  $launcher = Get-Command py -ErrorAction SilentlyContinue
  if ($launcher) {
    $candidate = (& $launcher.Source -3.12 -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
    if ($candidate -and (Test-Path $candidate)) { $script:pythonArgs = @(); return $candidate }
  }
  $candidate = Get-Command python -ErrorAction SilentlyContinue
  if ($candidate) {
    $version = (& $candidate.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null | Select-Object -Last 1)
    if ($version -eq "3.12") { return $candidate.Source }
  }
  return $null
}

$python = Find-Python312
if (-not $python) {
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) { throw "Python 3.12 is required. Install Python 3.12 and run setup again." }
  & $winget.Source install --id Python.Python.3.12 --exact --scope user --silent --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0) { throw "Python 3.12 installation failed." }
  $python = Find-Python312
}
if (-not $python) { throw "Python 3.12 was installed but could not be found. Restart Windows, then run setup again." }

if (Test-Path (Join-Path $runtime "Scripts\python.exe")) {
  $runtimeVersion = & (Join-Path $runtime "Scripts\python.exe") -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
  if ($runtimeVersion.Trim() -ne "3.12") { Remove-Item -LiteralPath $runtime -Recurse -Force }
}
if (-not (Test-Path (Join-Path $runtime "Scripts\python.exe"))) {
  & $python -m venv $runtime
  if ($LASTEXITCODE -ne 0) { throw "Could not create the Python 3.12 runtime." }
}
$venvPython = Join-Path $runtime "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Pip could not be upgraded." }
& $venvPython -m pip install --upgrade -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Required Python packages could not be installed. Check your internet connection and try setup again." }
# Pre-fetch the default speech model during installation so first use does not
# unexpectedly download it while the user is clipping.
& $venvPython -c "from faster_whisper import WhisperModel; WhisperModel('distil-large-v3', device='cpu', compute_type='int8')"
if ($LASTEXITCODE -ne 0) { throw "The speech model could not be installed." }
Write-Host "StreamSnip AI runtime installed successfully."
