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

Invoke-Checked python -m compileall -q src tests
Invoke-Checked python -m pytest
Invoke-Checked python -m ruff check .
Invoke-Checked python -m mypy src

$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("agent-runtime-" + [System.Guid]::NewGuid())
$env:AGENT_MODEL_PROVIDER = "fake"
try {
    New-Item -ItemType Directory -Path $tmpRoot | Out-Null
    Invoke-Checked agent /init --root (Join-Path $tmpRoot "workspace")
    Invoke-Checked agent /model-check --root (Join-Path $tmpRoot "workspace")
    Invoke-Checked agent /new "create offline artifact" --root (Join-Path $tmpRoot "workspace")
    Invoke-Checked agent /sessions --root (Join-Path $tmpRoot "workspace")
    Invoke-Checked agent /run --root (Join-Path $tmpRoot "workspace")
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
