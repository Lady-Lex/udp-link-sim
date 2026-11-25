# Build Windows x64 onefile UdpLinkSim.exe and generate SHA256SUMS.txt
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    throw "Virtual environment not found at $Py"
}

Write-Host "==> Building UdpLinkSim.exe (PyInstaller onefile)..."
& $Py -m PyInstaller --clean --noconfirm (Join-Path $Root "scripts\UdpLinkSim.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

$ExePath = Join-Path $Root "dist\UdpLinkSim.exe"
if (-not (Test-Path $ExePath)) {
    throw "Expected artifact not found: $ExePath"
}

$Info = Get-Item $ExePath
$Hash = (Get-FileHash -Algorithm SHA256 $ExePath).Hash.ToLower()
$SumLine = "$Hash  UdpLinkSim.exe"
$SumPath = Join-Path $Root "dist\SHA256SUMS.txt"
Set-Content -Path $SumPath -Value $SumLine -Encoding Ascii

Write-Host ("==> Built: {0} ({1:N2} MB)" -f $ExePath, ($Info.Length / 1MB))
Write-Host ("==> SHA256: {0}" -f $Hash)
