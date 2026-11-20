$ErrorActionPreference = "Stop"
$runtime = Join-Path $env:LOCALAPPDATA "StreamSnip AI\runtime"
$python = $null

function Find-Python {
  foreach ($candidate in @("py", "python")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
  }
  return $null
}

$python = Find-Python
if (-not $python) {
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) { throw "Python is required. Install Python 3.10+ and run setup again." }
  & $winget.Source install --id Python.Python.3.12 --exact --scope user --silent --accept-source-agreements --accept-package-agreements
  $python = Find-Python
}
if (-not $python) { throw "Python was installed but could not be found. Restart Windows, then run setup again." }

if (-not (Test-Path (Join-Path $runtime "Scripts\python.exe"))) {
  & $python -m venv $runtime
}
$venvPython = Join-Path $runtime "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install --upgrade -r (Join-Path $PSScriptRoot "requirements.txt")
Write-Host "StreamSnip AI runtime installed successfully."
