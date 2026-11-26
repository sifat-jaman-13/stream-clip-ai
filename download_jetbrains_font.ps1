$ErrorActionPreference = 'Stop'
$download = Join-Path $env:TEMP 'JetBrainsMono-2.304.zip'
$extract = Join-Path $env:TEMP 'JetBrainsMono-2.304'
if (Test-Path $extract) { Remove-Item -LiteralPath $extract -Recurse -Force }
Invoke-WebRequest -Uri 'https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip' -OutFile $download
Get-FileHash -LiteralPath $download -Algorithm SHA256 | Format-List
Expand-Archive -LiteralPath $download -DestinationPath $extract -Force
Get-ChildItem -LiteralPath $extract -Recurse -Include '*.ttf','OFL.txt' | Select-Object FullName,Length | Format-Table -AutoSize
