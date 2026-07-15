<#
  Asteria Studio launcher.

  Default (production single-entry): builds the UI once and serves the whole app — UI + API — from
  ONE server on ONE port, then opens your browser to it. A teammate runs this one command and lands on
  a working app; there is no dev server, no second port, no localhost number to remember.

    powershell -ExecutionPolicy Bypass -File ./start-studio.ps1
    # → builds studio/dist (first run), starts http://127.0.0.1:8787, opens the browser

  Switches:
    -Dev         Developer mode: run the Vite dev server (HMR) on -UiPort alongside the API. Use this
                 while editing the frontend so changes hot-reload; NOT for handing the app to others.
    -Rebuild     Force a fresh `npm run build` even if studio/dist already exists.
    -NoOpen      Do not auto-open the browser (still prints the URL).
    -BackendOnly Start only the API/server (no browser, no UI build in dev mode).

  Requirements on the machine: Node.js (for the server + build) and Python (the runtime the server
  shells out to). Both are needed regardless of mode — this is a local-first harness, not a hosted app.
#>
param(
  [string]$Workspace = (Split-Path -Parent $PSScriptRoot),
  [string]$RuntimeRoot = (Split-Path -Parent $PSScriptRoot),
  [int]$ApiPort = 8787,
  [int]$UiPort = 5174,
  [string]$Python = "python",
  [switch]$Dev,
  [switch]$Rebuild,
  [switch]$NoOpen,
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

# Run `npm run <script>` in the Studio root, failing loudly on a non-zero exit. We check
# $LASTEXITCODE by hand: a native command's failure does not raise even under -ErrorAction Stop, and
# a launcher that silently proceeds past a failed build would then serve a stale or missing UI.
function Invoke-Npm {
  param(
    [string[]]$Arguments,
    [string]$What
  )
  Write-Host "$What..."
  Push-Location $StudioRoot
  try {
    & npm.cmd @Arguments
    if ($LASTEXITCODE -ne 0) {
      throw "$What failed (npm exit $LASTEXITCODE)."
    }
  }
  finally {
    Pop-Location
  }
}

try {
  if (-not (Test-Path (Join-Path $StudioRoot "node_modules"))) {
    Invoke-Npm -Arguments @("install") -What "Installing Studio dependencies"
  }

  # Production single-entry: ensure the UI is built so the server can serve it from studio/dist. The
  # server serves dist/ + the API on the same port, so no Vite dev server and no second port are needed.
  if (-not $Dev) {
    $indexHtml = Join-Path $StudioRoot "dist/index.html"
    if ($Rebuild -or -not (Test-Path $indexHtml)) {
      Invoke-Npm -Arguments @("run", "build") -What "Building Studio UI (studio/dist)"
    }
    else {
      Write-Host "Reusing existing studio/dist (pass -Rebuild to force a fresh build)."
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

  # Dev mode only: the Vite dev server (HMR) on its own port, proxying /api to the API server. In
  # production mode the API server already serves the built UI, so this second process is not started.
  if ($Dev -and -not $BackendOnly) {
    Start-StudioProcess `
      -FilePath "npm.cmd" `
      -Arguments @(
        "run", "dev", "--",
        "--host", "127.0.0.1",
        "--port", "$UiPort"
      ) `
      -Name "Asteria Studio UI (dev)"
  }

  # The one URL a user opens. In production it is the API server itself (it serves the UI); in dev it
  # is the Vite dev server.
  $appUrl = if ($Dev -and -not $BackendOnly) { "http://127.0.0.1:$UiPort" } else { "http://127.0.0.1:$ApiPort" }

  Write-Host ""
  Write-Host "Asteria Studio is running."
  Write-Host "Open:  $appUrl"
  if ($Dev -and -not $BackendOnly) {
    Write-Host "API:   http://127.0.0.1:$ApiPort (dev server proxies /api here)"
  }
  Write-Host "Press Ctrl+C to stop."

  if (-not $NoOpen -and -not $BackendOnly) {
    # Give the server a moment to bind before opening the browser, so the first load is not a refused
    # connection the user has to reload past.
    Start-Sleep -Seconds 2
    Start-Process $appUrl | Out-Null
  }

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
