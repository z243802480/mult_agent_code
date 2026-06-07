# Install Asteria Beta from GitHub Release bundle (Windows).
param(
    [string]$VenvPath = "$env:USERPROFILE\.asteria\venv",
    [string]$StudioRoot = "$env:USERPROFILE\.asteria\studio"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$wheel = Get-ChildItem (Join-Path $here "dist-packages\*.whl") | Select-Object -First 1
if (-not $wheel) { throw "dist-packages/*.whl not found. Run from asteria-beta-* bundle root." }

$studioSrc = Join-Path $here "studio"
if (-not (Test-Path (Join-Path $studioSrc "server.mjs"))) { throw "studio/server.mjs not found in bundle." }

python --version | Out-Null
if (-not (Test-Path $VenvPath)) {
    python -m venv $VenvPath
}
$python = Join-Path $VenvPath "Scripts\python.exe"
$pip = Join-Path $VenvPath "Scripts\pip.exe"
& $python -m pip install --upgrade pip --quiet
& $pip install $wheel.FullName --quiet

$version = "0.1.0"
if ($wheel.Name -match 'asteria_runtime-([\d.]+)-') {
  $version = $matches[1]
}
$studioDest = Join-Path $StudioRoot $version
New-Item -ItemType Directory -Force -Path $studioDest | Out-Null
Copy-Item -Path (Join-Path $studioSrc "*") -Destination $studioDest -Recurse -Force
Set-Content -Path (Join-Path $StudioRoot "current") -Value $studioDest -Encoding utf8

Write-Host ""
Write-Host "Asteria Beta installed."
Write-Host "  venv:    $VenvPath"
Write-Host "  studio:  $studioDest"
Write-Host ""
Write-Host "Add to PATH (current user): $VenvPath\Scripts"
Write-Host "Then:"
Write-Host "  asteria init --root $env:USERPROFILE\asteria-workspace"
Write-Host "  asteria studio --root $env:USERPROFILE\asteria-workspace"
Write-Host ""
Write-Host "Read docs\Beta用户入门.md and docs\Beta试跑清单.md in this folder."
