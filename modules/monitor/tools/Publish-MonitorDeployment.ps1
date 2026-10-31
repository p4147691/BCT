[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [ValidateRange(1, 120)]
    [int]$TimeoutSeconds = 15,
    [switch]$WaitForObservation,
    [string]$InstalledRoot = '',
    [string]$ExpectedInstalledPayloadSha256 = '',
    [string]$ExpectedInstalledVersion = ''
)

# Publish either this exact source tree in place, or install it into a separately
# guarded DesktopWindow Monitor runtime. External installation is a complete
# extension-directory cutover: it never mixes selected source files with an
# older installed monitor.js/module set.
$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$sourceExt = Join-Path $sourceRoot 'extension'
$checkerPath = Join-Path $sourceRoot 'tools\check_monitor_structure.py'
$runtimeTelemetryPath = Join-Path $env:LOCALAPPDATA 'DesktopWindowMonitor\shared-runtime.json'
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

if (!(Test-Path -LiteralPath $sourceExt -PathType Container)) {
    throw "DesktopWindow Monitor source extension directory not found: $sourceExt"
}
if (!(Test-Path -LiteralPath $checkerPath -PathType Leaf)) {
    throw "Monitor pre-publish gate checker not found: $checkerPath"
}
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) {
    throw 'Monitor pre-publish gate cannot run: python not found'
}
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if ($null -eq $nodeCommand) {
    throw 'Monitor candidate validation cannot run: node not found'
}

function Invoke-MonitorStructureGate {
    $gateOutput = @(& $pythonCommand.Source $checkerPath --root $sourceRoot 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw ("Monitor pre-publish gate failed:" + [Environment]::NewLine + ($gateOutput -join [Environment]::NewLine))
    }
}

function Get-MonitorNextVersion([string]$CurrentVersion) {
    $match = [regex]::Match($CurrentVersion, '^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$')
    if (!$match.Success) {
        throw "Monitor manifest version must have three or four numeric components: $CurrentVersion"
    }
    $parts = @($match.Groups[1..3] | ForEach-Object { [int]$_.Value })
    if ($match.Groups[4].Success) { $parts += [int]$match.Groups[4].Value }
    if ($parts | Where-Object { $_ -gt 65535 }) {
        throw "Monitor manifest version component exceeds Chrome limit: $CurrentVersion"
    }
    if ($parts[-1] -ge 65535) {
        throw "Monitor final version component is exhausted; choose a reviewed base version before publishing: $CurrentVersion"
    }
    if ($parts.Count -eq 3) {
        return "$($parts[0]).$($parts[1]).$($parts[2] + 1)"
    }
    return "$($parts[0]).$($parts[1]).$($parts[2]).$($parts[3] + 1)"
}

function Get-MonitorExtensionPayloadSha256([string]$ExtensionPath) {
    $resolved = (Resolve-Path -LiteralPath $ExtensionPath).Path.TrimEnd('\')
    $rows = foreach ($file in Get-ChildItem -LiteralPath $resolved -Recurse -File | Sort-Object FullName) {
        $relative = $file.FullName.Substring($resolved.Length).TrimStart('\').Replace('\', '/')
        if ($relative -in @('.reload-token', '.reload-ack')) { continue }
        if ($relative -like '.manifest-stage-*' -or $relative -like '.manifest-backup-*') { continue }
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
        "$relative`0$hash"
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes(($rows -join "`n"))
    # Windows PowerShell 5.1/.NET Framework has no static SHA256.HashData.
    # Use the compatible instance API so the guarded installer works on the
    # same Windows host that runs the Monitor.
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant())
    } finally {
        $sha256.Dispose()
    }
}

function Set-MonitorManifestVersion([string]$ManifestPath, [string]$Version) {
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    $manifest.version = $Version
    [System.IO.File]::WriteAllText(
        $ManifestPath,
        (($manifest | ConvertTo-Json -Depth 20) + [Environment]::NewLine),
        $utf8NoBom)
    $observed = [string]((Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json).version)
    if ($observed -ne $Version) {
        throw "Staged manifest version verification failed: expected $Version, got $observed"
    }
}

function Assert-MonitorExtensionIdentity([string]$SourceManifestPath, [string]$InstalledManifestPath) {
    $source = Get-Content -LiteralPath $SourceManifestPath -Raw | ConvertFrom-Json
    $installed = Get-Content -LiteralPath $InstalledManifestPath -Raw | ConvertFrom-Json
    foreach ($field in @('manifest_version', 'name', 'key')) {
        if ([string]$source.$field -ne [string]$installed.$field) {
            throw "Monitor extension identity mismatch at manifest field '$field'"
        }
    }
}

function Test-MonitorExtensionCandidate([string]$CandidateExt) {
    $manifestPath = Join-Path $CandidateExt 'manifest.json'
    $desktopPath = Join-Path $CandidateExt 'desktop.html'
    if (!(Test-Path -LiteralPath $manifestPath -PathType Leaf) -or
        !(Test-Path -LiteralPath $desktopPath -PathType Leaf)) {
        throw 'Monitor candidate is missing manifest.json or desktop.html'
    }

    $candidateRoot = [System.IO.Path]::GetFullPath($CandidateExt).TrimEnd('\') + '\'
    $desktopHtml = Get-Content -LiteralPath $desktopPath -Raw
    $relativeScripts = @([regex]::Matches($desktopHtml, '<script\s+src="([^"]+)"') |
        ForEach-Object { $_.Groups[1].Value })
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.background.service_worker) { $relativeScripts += [string]$manifest.background.service_worker }

    foreach ($relative in ($relativeScripts | Sort-Object -Unique)) {
        $candidate = [System.IO.Path]::GetFullPath((Join-Path $CandidateExt $relative))
        if (!$candidate.StartsWith($candidateRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Monitor candidate script escapes extension root: $relative"
        }
        if (!(Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "Monitor candidate script missing: $relative"
        }
        $syntax = @(& $nodeCommand.Source --check $candidate 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw ("Monitor candidate JavaScript syntax failed: $relative" + [Environment]::NewLine + ($syntax -join [Environment]::NewLine))
        }
    }
}

function Assert-MonitorInstalledGuard([string]$TargetExt, [string]$ExpectedVersion, [string]$ExpectedPayload) {
    $manifestPath = Join-Path $TargetExt 'manifest.json'
    if (!(Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Installed Monitor manifest not found: $manifestPath"
    }
    $observedVersion = [string]((Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json).version)
    $observedPayload = Get-MonitorExtensionPayloadSha256 $TargetExt
    if ($observedVersion -ne $ExpectedVersion) {
        throw "Installed Monitor version guard failed: expected=$ExpectedVersion observed=$observedVersion"
    }
    if ($observedPayload -ne $ExpectedPayload.ToLowerInvariant()) {
        throw "Installed Monitor payload guard failed: expected=$ExpectedPayload observed=$observedPayload"
    }
    return $observedPayload
}

Invoke-MonitorStructureGate

# Prevent publishing an extension whose file and control Native Messaging
# manifests both point at the newer control-only executable. No writes occur.
$nativeRoleChecker = Join-Path $sourceRoot 'tools\check_monitor_native_host_roles.py'
if (!(Test-Path -LiteralPath $nativeRoleChecker -PathType Leaf)) {
    throw 'Monitor Native host role preflight missing'
}
$nativeRoleResult = @(& $pythonCommand.Source $nativeRoleChecker --root $sourceRoot --probe 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw ("Monitor Native host role preflight failed:" + [Environment]::NewLine + ($nativeRoleResult -join [Environment]::NewLine))
}

$externalInstall = ![string]::IsNullOrWhiteSpace($InstalledRoot)
if ($externalInstall) {
    if ([string]::IsNullOrWhiteSpace($ExpectedInstalledPayloadSha256) -or
        [string]::IsNullOrWhiteSpace($ExpectedInstalledVersion)) {
        throw 'External Monitor installation requires ExpectedInstalledPayloadSha256 and ExpectedInstalledVersion'
    }
    $targetRoot = (Resolve-Path -LiteralPath $InstalledRoot).Path
    if ($targetRoot -eq $sourceRoot) { throw 'InstalledRoot must be separate from the source root' }
} else {
    $targetRoot = $sourceRoot
}

$targetExt = Join-Path $targetRoot 'extension'
$manifestPath = Join-Path $targetExt 'manifest.json'
$tokenPath = Join-Path $targetExt '.reload-token'
$ackPath = Join-Path $targetExt '.reload-ack'
if (!(Test-Path -LiteralPath $targetExt -PathType Container)) {
    throw "DesktopWindow Monitor target extension directory not found: $targetExt"
}

$currentVersion = [string]((Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json).version)
$nextVersion = Get-MonitorNextVersion $currentVersion
$observedInstalledPayload = ''
if ($externalInstall) {
    $observedInstalledPayload = Assert-MonitorInstalledGuard $targetExt $ExpectedInstalledVersion $ExpectedInstalledPayloadSha256
    Assert-MonitorExtensionIdentity (Join-Path $sourceExt 'manifest.json') $manifestPath
}

$actionTarget = if ($externalInstall) { $targetExt } else { $manifestPath }
$action = if ($externalInstall) {
    "install complete guarded Monitor payload version $currentVersion -> $nextVersion"
} else {
    "publish Monitor extension version $currentVersion -> $nextVersion"
}
if (!$PSCmdlet.ShouldProcess($actionTarget, $action)) {
    $payloadText = if ($externalInstall) { " installedPayload=$observedInstalledPayload" } else { '' }
    Write-Output "MONITOR_DEPLOYMENT_PREVIEW version=$nextVersion$payloadText"
    return
}

$backupPath = ''
$publishedPayload = ''
if ($externalInstall) {
    $stageRoot = Join-Path $targetRoot ('.monitor-deployment-stage-' + [guid]::NewGuid().ToString('N'))
    $stageExt = Join-Path $stageRoot 'extension'
    $backupRoot = Join-Path $targetRoot 'backup'
    $backupName = 'monitor-live-pre-' + $nextVersion + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
    $backupPath = Join-Path $backupRoot $backupName
    $failedCandidatePath = $backupPath + '-failed-candidate'
    $oldMoved = $false
    try {
        New-Item -ItemType Directory -Path $stageRoot | Out-Null
        Copy-Item -LiteralPath $sourceExt -Destination $stageExt -Recurse
        Set-MonitorManifestVersion (Join-Path $stageExt 'manifest.json') $nextVersion
        foreach ($marker in @('.reload-token', '.reload-ack')) {
            $existingMarker = Join-Path $targetExt $marker
            if (Test-Path -LiteralPath $existingMarker -PathType Leaf) {
                Copy-Item -LiteralPath $existingMarker -Destination (Join-Path $stageExt $marker) -Force
            }
        }
        Assert-MonitorExtensionIdentity (Join-Path $sourceExt 'manifest.json') (Join-Path $stageExt 'manifest.json')
        Test-MonitorExtensionCandidate $stageExt
        $publishedPayload = Get-MonitorExtensionPayloadSha256 $stageExt

        # Recheck immediately before the directory swap so a concurrent writer
        # cannot be silently overwritten after the earlier inspection.
        [void](Assert-MonitorInstalledGuard $targetExt $ExpectedInstalledVersion $ExpectedInstalledPayloadSha256)
        New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
        if (Test-Path -LiteralPath $backupPath) { throw "Monitor backup path already exists: $backupPath" }
        Move-Item -LiteralPath $targetExt -Destination $backupPath
        $oldMoved = $true
        Move-Item -LiteralPath $stageExt -Destination $targetExt
        $oldMoved = $false

        Test-MonitorExtensionCandidate $targetExt
        $installedPayload = Get-MonitorExtensionPayloadSha256 $targetExt
        if ($installedPayload -ne $publishedPayload) {
            throw "Installed Monitor candidate hash mismatch: expected=$publishedPayload observed=$installedPayload"
        }
    } catch {
        if ($oldMoved -or (!(Test-Path -LiteralPath $targetExt) -and (Test-Path -LiteralPath $backupPath))) {
            if (Test-Path -LiteralPath $targetExt) {
                Move-Item -LiteralPath $targetExt -Destination $failedCandidatePath
            }
            Move-Item -LiteralPath $backupPath -Destination $targetExt
        } elseif ((Test-Path -LiteralPath $targetExt) -and (Test-Path -LiteralPath $backupPath)) {
            Move-Item -LiteralPath $targetExt -Destination $failedCandidatePath
            Move-Item -LiteralPath $backupPath -Destination $targetExt
        }
        throw
    } finally {
        if (Test-Path -LiteralPath $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force }
    }
} else {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $manifest.version = $nextVersion
    $stagedManifest = Join-Path $targetExt ('.manifest-stage-' + [guid]::NewGuid().ToString('N'))
    $replacementBackup = Join-Path $targetExt ('.manifest-backup-' + [guid]::NewGuid().ToString('N'))
    try {
        [System.IO.File]::WriteAllText($stagedManifest, (($manifest | ConvertTo-Json -Depth 20) + [Environment]::NewLine), $utf8NoBom)
        $stagedVersion = [string]((Get-Content -LiteralPath $stagedManifest -Raw | ConvertFrom-Json).version)
        if ($stagedVersion -ne $nextVersion) {
            throw "Staged manifest version verification failed: expected $nextVersion, got $stagedVersion"
        }
        [System.IO.File]::Replace($stagedManifest, $manifestPath, $replacementBackup)
    } finally {
        if (Test-Path -LiteralPath $stagedManifest) { Remove-Item -LiteralPath $stagedManifest -Force }
        if (Test-Path -LiteralPath $replacementBackup) { Remove-Item -LiteralPath $replacementBackup -Force }
    }
    $publishedPayload = Get-MonitorExtensionPayloadSha256 $targetExt
}

# Re-run the fail-closed source gate after the candidate installation. A token
# is never published when the authoritative source no longer passes its gate.
Invoke-MonitorStructureGate
Test-MonitorExtensionCandidate $targetExt

$token = [guid]::NewGuid().ToString('N')
$publishedAtMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
[System.IO.File]::WriteAllText($tokenPath, $token + [Environment]::NewLine, $utf8NoBom)
$backupText = if ($backupPath) { " backup=$backupPath" } else { '' }
Write-Output "MONITOR_DEPLOYMENT_PUBLISHED version=$nextVersion token=$token payload=$publishedPayload$backupText"

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
