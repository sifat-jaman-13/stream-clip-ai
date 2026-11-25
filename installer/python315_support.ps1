function New-StreamSnipRequirementsProfile([string]$Version,[string]$RequirementsPath) {
    if ([version]$Version -lt [version]"3.15") { return $RequirementsPath }
    $profilePath = Join-Path $env:TEMP ("streamsnip-py315-" + [guid]::NewGuid().ToString("N") + ".txt")
    $lines = @(Get-Content -LiteralPath $RequirementsPath | Where-Object { ([string]$_) -notmatch '(?i)^[ ]*(faster-whisper|onnxruntime)([<>=!~]|[ ]|$)' })
    $lines += @("av>=11","ctranslate2>=4.0,<5","huggingface-hub>=0.21","tokenizers>=0.13,<1","tqdm>=4")
    [IO.File]::WriteAllLines($profilePath,[string[]]$lines,(New-Object System.Text.UTF8Encoding($false)))
    return $profilePath
}
function Install-StreamSnipDependencies([string]$RuntimePython,[string]$RequirementsPath,[string]$Version) {
    $profilePath = New-StreamSnipRequirementsProfile $Version $RequirementsPath
    try {
        & $RuntimePython -m pip install --prefer-binary -r $profilePath
        if ($LASTEXITCODE -ne 0) { throw "Could not install StreamSnip AI dependencies." }
        if ([version]$Version -ge [version]"3.15") {
            & $RuntimePython -m pip install --prefer-binary --no-deps "faster-whisper==1.2.1"
            if ($LASTEXITCODE -ne 0) { throw "Could not install faster-whisper for Python 3.15." }
        }
    } finally { if ($profilePath -ne $RequirementsPath) { Remove-Item -LiteralPath $profilePath -Force -ErrorAction SilentlyContinue } }
}
function Test-StreamSnipDependencyConsistency([string]$RuntimePython,[string]$Version) {
    $output = @(& $RuntimePython -m pip check 2>&1)
    if ($LASTEXITCODE -eq 0) { return $true }
    if ([version]$Version -ge [version]"3.15" -and $output.Count -eq 1 -and ([string]$output[0]).Trim().StartsWith("faster-whisper ") -and ([string]$output[0]).Trim().EndsWith("requires onnxruntime, which is not installed.")) {
        Write-Host "Optional VAD's ONNX Runtime is omitted on Python 3.15." -ForegroundColor Yellow
        return $true
    }
    throw ("The installed Python dependencies are inconsistent: " + ($output -join " "))
}
