$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string] $FilePath,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]] $Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

$python = "python"
$venvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $python = $venvPython
}

$srcPath = (Resolve-Path (Join-Path $PSScriptRoot "..\src")).Path
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$srcPath$([System.IO.Path]::PathSeparator)$env:PYTHONPATH"
}
else {
    $env:PYTHONPATH = $srcPath
}

Invoke-Checked $python -m compileall -q src tests
Invoke-Checked $python -m pytest
Invoke-Checked $python -m ruff check .
Invoke-Checked $python -m mypy src
Invoke-Checked $python scripts/run_benchmarks.py

$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("agent-runtime-" + [System.Guid]::NewGuid())
$env:AGENT_MODEL_PROVIDER = "fake"
try {
    New-Item -ItemType Directory -Path $tmpRoot | Out-Null
    Invoke-Checked $python -m agent_runtime /init --root (Join-Path $tmpRoot "workspace")
    Invoke-Checked $python -m agent_runtime /model-check --root (Join-Path $tmpRoot "workspace")
    Invoke-Checked $python -m agent_runtime /new "create offline artifact" --root (Join-Path $tmpRoot "workspace")
    Invoke-Checked $python -m agent_runtime /sessions --root (Join-Path $tmpRoot "workspace")
    Invoke-Checked $python -m agent_runtime /run --root (Join-Path $tmpRoot "workspace")
    Invoke-Checked $python -m agent_runtime /compact --root (Join-Path $tmpRoot "workspace")
    Invoke-Checked $python -m agent_runtime /handoff --root (Join-Path $tmpRoot "workspace") --to FutureRun
    $sessionsContext = & $python -m agent_runtime /sessions --root (Join-Path $tmpRoot "workspace") --context
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $python -m agent_runtime /sessions --context"
    }
    $sessionsContextText = $sessionsContext -join "`n"
    if ($sessionsContextText -notmatch "snapshot:" -or $sessionsContextText -notmatch "handoff:" -or $sessionsContextText -notmatch "next:") {
        throw "Expected sessions --context output to include snapshot, handoff, and next command. Output: $sessionsContextText"
    }
    $snapshots = Get-ChildItem -Path (Join-Path $tmpRoot "workspace\.agent\context\snapshots") -Filter *.json
    if ($snapshots.Count -lt 1) {
        throw "Expected at least one context snapshot to be created."
    }
    $handoffs = Get-ChildItem -Path (Join-Path $tmpRoot "workspace\.agent\context\handoffs") -Filter *.json
    if ($handoffs.Count -lt 1) {
        throw "Expected at least one handoff package to be created."
    }
    $artifact = Join-Path $tmpRoot "workspace\offline_artifact.txt"
    if (-not (Test-Path $artifact)) {
        throw "Expected offline artifact was not created: $artifact"
    }
    Invoke-Checked $python scripts/write_verification_summary.py --root . --platform windows --cli-workspace (Join-Path $tmpRoot "workspace")
    Invoke-Checked $python -m agent_runtime /verification --root .
}
finally {
    if (Test-Path $tmpRoot) {
        Remove-Item -LiteralPath $tmpRoot -Recurse -Force
    }
}
