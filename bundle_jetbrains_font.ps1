$ErrorActionPreference = 'Stop'
$sourceRoot = Join-Path $env:TEMP 'JetBrainsMono-2.304'
$targetRoot = Join-Path $PSScriptRoot 'desktop\StreamSnip.Desktop\Assets\Fonts'
if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot 'fonts\variable\JetBrainsMono[wght].ttf'))) { throw 'The official JetBrains Mono variable font archive is not available.' }
New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceRoot 'fonts\variable\JetBrainsMono[wght].ttf') -Destination (Join-Path $targetRoot 'JetBrainsMono-Variable.ttf') -Force
Copy-Item -LiteralPath (Join-Path $sourceRoot 'OFL.txt') -Destination (Join-Path $targetRoot 'OFL.txt') -Force
Get-FileHash -LiteralPath (Join-Path $targetRoot 'JetBrainsMono-Variable.ttf') -Algorithm SHA256 | Format-List
