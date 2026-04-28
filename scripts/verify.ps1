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
    $artifact = Join-Path $tmpRoot "workspace\offline_artifact.txt"
    if (-not (Test-Path $artifact)) {
        throw "Expected offline artifact was not created: $artifact"
    }
}
finally {
    if (Test-Path $tmpRoot) {
        Remove-Item -LiteralPath $tmpRoot -Recurse -Force
    }
}
