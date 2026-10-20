[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [ValidateRange(1, 120)]
    [int]$TimeoutSeconds = 15,
    [switch]$WaitForObservation
)

# Publish a source update as one distinct internal Monitor build.  Plain UI
# reloads intentionally do not call this script and therefore do not change
# the visible extension version.
$ErrorActionPreference = 'Stop'
$runtimeRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$ext = Join-Path $runtimeRoot 'extension'
$manifestPath = Join-Path $ext 'manifest.json'
$tokenPath = Join-Path $ext '.reload-token'
$ackPath = Join-Path $ext '.reload-ack'
$runtimeTelemetryPath = Join-Path $env:LOCALAPPDATA 'DesktopWindowMonitor\shared-runtime.json'
$checkerPath = Join-Path $runtimeRoot 'tools\check_monitor_structure.py'

if (!(Test-Path -LiteralPath $ext -PathType Container)) {
    throw "DesktopWindow Monitor extension directory not found: $ext"
}
if (!(Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Monitor manifest not found: $manifestPath"
}
if (!(Test-Path -LiteralPath $checkerPath -PathType Leaf)) {
    throw "Monitor pre-publish gate checker not found: $checkerPath"
}
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) {
    throw 'Monitor pre-publish gate cannot run: python not found'
}

function Invoke-MonitorStructureGate {
    $gateOutput = @(& $pythonCommand.Source $checkerPath --root $runtimeRoot 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw ("Monitor pre-publish gate failed:" + [Environment]::NewLine + ($gateOutput -join [Environment]::NewLine))
    }
}

Invoke-MonitorStructureGate
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$currentVersion = [string]$manifest.version
$match = [regex]::Match($currentVersion, '^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$')
if (!$match.Success) {
    throw "Monitor manifest version must have three or four numeric components: $currentVersion"
}
$parts = @($match.Groups[1..3] | ForEach-Object { [int]$_.Value })
if ($match.Groups[4].Success) { $parts += [int]$match.Groups[4].Value }
if ($parts | Where-Object { $_ -gt 65535 }) {
    throw "Monitor manifest version component exceeds Chrome limit: $currentVersion"
}
if ($parts[-1] -ge 65535) {
    throw "Monitor final version component is exhausted; choose a reviewed base version before publishing: $currentVersion"
}
if ($parts.Count -eq 3) {
    $nextVersion = "$($parts[0]).$($parts[1]).$($parts[2] + 1)"
} else {
    $nextVersion = "$($parts[0]).$($parts[1]).$($parts[2]).$($parts[3] + 1)"
}

if (!$PSCmdlet.ShouldProcess($manifestPath, "publish Monitor extension version $currentVersion -> $nextVersion")) {
    Write-Output "MONITOR_DEPLOYMENT_PREVIEW version=$nextVersion"
    return
}

$manifest.version = $nextVersion
$stagedManifest = Join-Path $ext ('.manifest-stage-' + [guid]::NewGuid().ToString('N'))
$replacementBackup = Join-Path $ext ('.manifest-backup-' + [guid]::NewGuid().ToString('N'))
try {
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($stagedManifest, (($manifest | ConvertTo-Json -Depth 20) + [Environment]::NewLine), $utf8NoBom)
    $stagedVersion = [string]((Get-Content -LiteralPath $stagedManifest -Raw | ConvertFrom-Json).version)
    if ($stagedVersion -ne $nextVersion) {
        throw "Staged manifest version verification failed: expected $nextVersion, got $stagedVersion"
    }
    # File.Replace is atomic on this volume, but this Windows/.NET runtime
    # requires a concrete backup path.  The backup exists only during the
    # replacement and is removed in finally after the new manifest is read.
    [System.IO.File]::Replace($stagedManifest, $manifestPath, $replacementBackup)
} finally {
    if (Test-Path -LiteralPath $stagedManifest) { Remove-Item -LiteralPath $stagedManifest -Force }
    if (Test-Path -LiteralPath $replacementBackup) { Remove-Item -LiteralPath $replacementBackup -Force }
}

# Re-run the fail-closed gate after the atomic manifest replacement.  A token
# is never published when the active payload fails the post-write check.
Invoke-MonitorStructureGate
$token = [guid]::NewGuid().ToString('N')
$publishedAtMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
[System.IO.File]::WriteAllText($tokenPath, $token + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
Write-Output "MONITOR_DEPLOYMENT_PUBLISHED version=$nextVersion token=$token"

if (!$WaitForObservation) {
    Write-Output 'MONITOR_DEPLOYMENT_PENDING reload the Monitor extension, then verify the running version and token acknowledgement.'
    return
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$lastObservedVersion = ''
$lastObservedToken = ''
do {
    Start-Sleep -Milliseconds 250
    $ackMatches = $false
    if (Test-Path -LiteralPath $ackPath -PathType Leaf) {
        $ack = (Get-Content -LiteralPath $ackPath -Raw).Trim()
        $ackMatches = $ack -eq $token
    }
    if ($ackMatches -and (Test-Path -LiteralPath $runtimeTelemetryPath -PathType Leaf)) {
        try {
            $runtime = Get-Content -LiteralPath $runtimeTelemetryPath -Raw | ConvertFrom-Json
            $row = $runtime.'__MONITOR_INSTANCE__:GOOGLE'
            $loaded = if ($row -and $row.label) { $row.label | ConvertFrom-Json } else { $null }
            $lastObservedVersion = [string]$loaded.manifest_version
            $lastObservedToken = [string]$loaded.reload_token
            $seenAtMs = [long]$loaded.seen_at_ms
            if ($lastObservedVersion -eq $nextVersion -and
                $lastObservedToken -eq $token -and $seenAtMs -ge $publishedAtMs) {
                Write-Output "MONITOR_DEPLOYMENT_OBSERVED version=$nextVersion token=$token runtime=verified"
                return
            }
        } catch {
            # A concurrent Native Host write can expose a short partial-read
            # window. Retry within the existing bounded observation deadline.
        }
    }
} while ((Get-Date) -lt $deadline)

throw "Monitor deployment runtime verification timeout: expectedVersion=$nextVersion observedVersion=$lastObservedVersion expectedToken=$token observedToken=$lastObservedToken"
