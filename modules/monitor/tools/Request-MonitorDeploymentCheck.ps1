param([int]$TimeoutSeconds = 15)

# This tool does NOT reload the Chrome extension.
# It writes a deployment-observation token and waits for the running Monitor
# to observe and acknowledge that token during its startup/focus deployment check.

$runtimeRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$ext = Join-Path $runtimeRoot 'extension'
$tokenPath = Join-Path $ext '.reload-token'
$ackPath = Join-Path $ext '.reload-ack'

if (!(Test-Path -LiteralPath $ext -PathType Container)) {
  throw "DesktopWindow Monitor extension directory not found: $ext"
}

$checkerPath = Join-Path $runtimeRoot 'tools\check_monitor_structure.py'
if (!(Test-Path -LiteralPath $checkerPath -PathType Leaf)) {
  throw "Monitor pre-reload gate checker not found: $checkerPath"
}
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) {
  throw "Monitor pre-reload gate cannot run: python not found"
}
$gateOutput = @(& $pythonCommand.Source $checkerPath --root $runtimeRoot 2>&1)
$gateExitCode = $LASTEXITCODE
if ($gateExitCode -ne 0) {
  $gateText = $gateOutput -join [Environment]::NewLine
  throw ("Monitor pre-reload gate failed before deployment token update:" + [Environment]::NewLine + $gateText)
}

$token = [guid]::NewGuid().ToString('N')
Set-Content -LiteralPath $tokenPath -Value $token -Encoding UTF8

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
  Start-Sleep -Milliseconds 250
  if (Test-Path -LiteralPath $ackPath -PathType Leaf) {
    $ack = (Get-Content -LiteralPath $ackPath -Raw).Trim()
    if ($ack -eq $token) {
      Write-Output "MONITOR_DEPLOYMENT_OBSERVED $token"
      exit 0
    }
  }
} while ((Get-Date) -lt $deadline)

throw "Monitor deployment observation ACK timeout: $token"
