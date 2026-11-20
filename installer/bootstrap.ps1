$ErrorActionPreference = "Stop"
$runtime = Join-Path $env:LOCALAPPDATA "StreamSnip AI\runtime"
$python = $null
function Find-PythonCompatible {
  $launcher = Get-Command py -ErrorAction SilentlyContinue
  if ($launcher) {
    foreach ($version in @("3.10", "3.11", "3.12", "3.13", "3.14")) {
      $candidate = (& $launcher.Source "-$version" -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
      if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
  }
  $candidate = Get-Command python -ErrorAction SilentlyContinue
  if ($candidate) {
    $version = (& $candidate.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null | Select-Object -Last 1)
    if ($version -in @("3.10", "3.11", "3.12", "3.13", "3.14")) { return $candidate.Source }
  }
  return $null
}

$python = Find-PythonCompatible
if (-not $python) {
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) { throw "Python 3.10+ is required. Install a supported Python version and run setup again." }
  & $winget.Source install --id Python.Python.3.12 --exact --scope user --silent --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0) { throw "A compatible Python runtime could not be installed." }
  $python = Find-PythonCompatible
}
if (-not $python) { throw "A compatible Python runtime was installed but could not be found. Restart Windows, then run setup again." }

if (Test-Path (Join-Path $runtime "Scripts\python.exe")) {
  $runtimeVersion = & (Join-Path $runtime "Scripts\python.exe") -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
  if ($runtimeVersion.Trim() -notin @("3.10", "3.11", "3.12", "3.13", "3.14")) { Remove-Item -LiteralPath $runtime -Recurse -Force }
}
if (-not (Test-Path (Join-Path $runtime "Scripts\python.exe"))) {
  & $python -m venv $runtime
  if ($LASTEXITCODE -ne 0) { throw "Could not create the Python runtime." }
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
