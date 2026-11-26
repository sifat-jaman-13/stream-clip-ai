function New-StreamSnipRequirementsProfile([string]$Version,[string]$RequirementsPath) {
    if ([version]$Version -lt [version]"3.15") { return $RequirementsPath }
    $profilePath = Join-Path $env:TEMP ("streamsnip-py315-" + [guid]::NewGuid().ToString("N") + ".txt")
    $lines = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($raw in (Get-Content -LiteralPath $RequirementsPath)) {
        $line = [string]$raw
        if ($line -match '(?i)^[ ]*(faster-whisper|onnxruntime)([<>=!~]|[ ]|$)') { continue }
        $trimmed = $line.Trim()
        if ($trimmed -and -not $seen.Add($trimmed)) { continue }
        $lines.Add($line)
    }
    foreach ($dep in @("av>=11","ctranslate2>=4.0,<5","huggingface-hub>=0.21","tokenizers>=0.13,<1","tqdm>=4","annotated-doc>=0.0.2","anyio>=4.1","attrs>=23.2","annotated-types>=0.6")) {
        $pkg = ($dep -split '[<>=!~ ]')[0]
        $alreadyPresent = $lines | Where-Object { $_ -match "(?i)^[ ]*$([regex]::Escape($pkg))([<>=!~]|[ ]|$)" }
        if (-not $alreadyPresent) { $lines.Add($dep) }
    }
    [IO.File]::WriteAllLines($profilePath,[string[]]$lines.ToArray(),(New-Object System.Text.UTF8Encoding($false)))
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
