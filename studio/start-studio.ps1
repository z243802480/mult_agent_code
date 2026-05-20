param(
  [string]$Workspace = "F:\mult_agent_code",
  [string]$RuntimeRoot = "F:\mult_agent_code",
  [int]$ApiPort = 8787,
  [int]$UiPort = 5174,
  [string]$Python = "python",
  [switch]$BackendOnly
)

$ErrorActionPreference = "Stop"

$StudioRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$processes = New-Object System.Collections.Generic.List[System.Diagnostics.Process]

function Start-StudioProcess {
  param(
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$Name
  )

  $process = Start-Process `
    -FilePath $FilePath `
    -ArgumentList $Arguments `
    -WorkingDirectory $StudioRoot `
    -WindowStyle Hidden `
    -PassThru

  $processes.Add($process)
  Write-Host "$Name started. pid=$($process.Id)"
}

function Stop-StudioProcesses {
  foreach ($process in $processes) {
    if ($null -ne $process -and -not $process.HasExited) {
      Write-Host "Stopping pid=$($process.Id)"
      Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
  }
}

try {
  if (-not (Test-Path (Join-Path $StudioRoot "node_modules"))) {
    Write-Host "Installing Studio dependencies..."
    Push-Location $StudioRoot
    try {
      npm install
    }
    finally {
      Pop-Location
    }
  }

  Start-StudioProcess `
    -FilePath "node" `
    -Arguments @(
      "server.mjs",
      "--workspace", $Workspace,
      "--runtime-root", $RuntimeRoot,
      "--port", "$ApiPort",
      "--python", $Python
    ) `
    -Name "Asteria Studio API"

  if (-not $BackendOnly) {
    Start-StudioProcess `
      -FilePath "npm.cmd" `
      -Arguments @(
        "run", "dev", "--",
        "--host", "127.0.0.1",
        "--port", "$UiPort"
      ) `
      -Name "Asteria Studio UI"
  }

  Write-Host ""
  Write-Host "Asteria Studio is running."
  Write-Host "API: http://127.0.0.1:$ApiPort"
  if (-not $BackendOnly) {
    Write-Host "UI:  http://127.0.0.1:$UiPort"
  }
  Write-Host "Press Ctrl+C to stop."

  while ($true) {
    foreach ($process in $processes) {
      if ($process.HasExited) {
        throw "A Studio child process exited unexpectedly. pid=$($process.Id)"
      }
    }
    Start-Sleep -Seconds 2
  }
}
finally {
  Stop-StudioProcesses
}
