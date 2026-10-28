[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+\.\d+-[a-z0-9-]+$')]
    [string]$VersionName,
    [Parameter(Mandatory = $true)]
    [string]$InstalledRoot,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-fA-F0-9]{64}$')]
    [string]$ExpectedInstalledControlSha256
)

# Builds and cuts over only the Monitor control Native Messaging host.  The
# file-shell host and the NativeMessagingHosts registry key are intentionally
# untouched: Chrome continues to resolve the same installed manifest path.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$installed = (Resolve-Path -LiteralPath $InstalledRoot).Path
$sourceNative = Join-Path $root 'native'
$installedNative = Join-Path $installed 'native'
$sourceManifest = Join-Path $sourceNative 'com.pas40.desktop_window_monitor_control.json'
$installedManifest = Join-Path $installedNative 'com.pas40.desktop_window_monitor_control.json'
$checker = Join-Path $root 'tools\check_monitor_native_host_roles.py'
$build = Join-Path $PSScriptRoot 'Build-MonitorCore.ps1'
$python = (Get-Command python -ErrorAction Stop).Source
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

foreach ($path in @($sourceManifest, $installedManifest, $checker, $build)) {
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required Monitor control-host file is missing: $path" }
}
if ($installed -eq $root) { throw 'InstalledRoot must be separate from the Monitor source root' }

$installedManifestBefore = [System.IO.File]::ReadAllText($installedManifest)
$sourceManifestBefore = [System.IO.File]::ReadAllText($sourceManifest)
$installedObject = $installedManifestBefore | ConvertFrom-Json
$installedCurrent = [string]$installedObject.path
if (!(Test-Path -LiteralPath $installedCurrent -PathType Leaf)) { throw "Registered control-host binary is missing: $installedCurrent" }
$observedHash = (Get-FileHash -LiteralPath $installedCurrent -Algorithm SHA256).Hash.ToLowerInvariant()
if ($observedHash -ne $ExpectedInstalledControlSha256.ToLowerInvariant()) {
    throw "Installed control-host guard failed: expected=$ExpectedInstalledControlSha256 observed=$observedHash"
}

$sourceOutput = Join-Path $sourceNative $VersionName
$installedOutput = Join-Path $installedNative $VersionName
if (Test-Path -LiteralPath $installedOutput) { throw "Installed Native version already exists: $installedOutput" }

if (!$PSCmdlet.ShouldProcess($installedManifest, "build and atomically register Monitor control host $VersionName")) {
    Write-Output "MONITOR_CONTROL_HOST_PREVIEW version=$VersionName current=$installedCurrent"
    return
}

if (Test-Path -LiteralPath $sourceOutput) {
    Write-Output "MONITOR_CONTROL_HOST_REUSING_BUILT_OUTPUT version=$VersionName"
} else {
    & $build -VersionName $VersionName
    if ($LASTEXITCODE -ne 0) { throw "Monitor control-host build failed: $LASTEXITCODE" }
}
$sourceExe = Join-Path $sourceOutput 'DesktopWindowMonitorControlHost.exe'
foreach ($name in @('DesktopWindowMonitorControlHost.exe', 'DesktopWindowMonitorWgcSnapshot.exe', 'VirtualDesktopAccessor.dll')) {
    if (!(Test-Path -LiteralPath (Join-Path $sourceOutput $name) -PathType Leaf)) { throw "Built Native runtime asset is missing: $name" }
}

$stage = Join-Path $installedNative ('.control-host-stage-' + [guid]::NewGuid().ToString('N'))
$installedManifestStage = Join-Path $installedNative ('.control-manifest-stage-' + [guid]::NewGuid().ToString('N'))
$sourceManifestStage = Join-Path $sourceNative ('.control-manifest-stage-' + [guid]::NewGuid().ToString('N'))
$history = Join-Path $installedNative 'backup'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$installedBackup = Join-Path $history ("control-manifest-pre-$VersionName-$stamp.json")
$sourceBackup = Join-Path $sourceNative (".control-manifest-backup-$stamp")
$installedPublished = $false
$sourcePublished = $false
try {
    New-Item -ItemType Directory -Path $stage | Out-Null
    Get-ChildItem -LiteralPath $sourceOutput -Force | Copy-Item -Destination $stage -Recurse -Force
    $stageExe = Join-Path $stage 'DesktopWindowMonitorControlHost.exe'
    $sourceHash = (Get-FileHash -LiteralPath $sourceExe -Algorithm SHA256).Hash.ToLowerInvariant()
    $stageHash = (Get-FileHash -LiteralPath $stageExe -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sourceHash -ne $stageHash) { throw "Staged control-host hash mismatch: source=$sourceHash stage=$stageHash" }

    $next = $installedObject.PSObject.Copy()
    $next.path = (Join-Path $installedOutput 'DesktopWindowMonitorControlHost.exe')
    $nextText = ((($next | ConvertTo-Json -Depth 20) -replace "`r?`n", "`n") + "`n")
    [System.IO.File]::WriteAllText($installedManifestStage, $nextText, $utf8NoBom)
    [System.IO.File]::WriteAllText($sourceManifestStage, $nextText, $utf8NoBom)
    $stagedPath = [string]((Get-Content -LiteralPath $installedManifestStage -Raw | ConvertFrom-Json).path)
    if ($stagedPath -ne $next.path) { throw 'Staged control manifest path verification failed' }

    # Recheck immediately before the cutover; a concurrent deploy must win
    # rather than being silently overwritten.
    $recheckHash = (Get-FileHash -LiteralPath $installedCurrent -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($recheckHash -ne $observedHash) { throw "Installed control-host changed during deployment: before=$observedHash after=$recheckHash" }
    New-Item -ItemType Directory -Path $history -Force | Out-Null
    if (Test-Path -LiteralPath $installedBackup) { throw "Control-host manifest backup path already exists: $installedBackup" }
    Copy-Item -LiteralPath $installedManifest -Destination $installedBackup
    Move-Item -LiteralPath $stage -Destination $installedOutput
    [System.IO.File]::Replace($installedManifestStage, $installedManifest, (Join-Path $history ("control-manifest-replace-$VersionName-$stamp.bak")))
    $installedPublished = $true
    [System.IO.File]::Replace($sourceManifestStage, $sourceManifest, $sourceBackup)
    $sourcePublished = $true

    $sourceCheck = @(& $python $checker --root $root --probe 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Source Native-role verification failed:`n$($sourceCheck -join [Environment]::NewLine)" }
    $installedCheck = @(& $python $checker --root $installed --probe 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Installed Native-role verification failed:`n$($installedCheck -join [Environment]::NewLine)" }
    Write-Output "MONITOR_CONTROL_HOST_PUBLISHED version=$VersionName sha256=$sourceHash previous=$installedCurrent backup=$installedBackup"
} catch {
    if ($sourcePublished) { [System.IO.File]::WriteAllText($sourceManifest, $sourceManifestBefore, $utf8NoBom) }
    if ($installedPublished) { [System.IO.File]::WriteAllText($installedManifest, $installedManifestBefore, $utf8NoBom) }
    throw
} finally {
    foreach ($path in @($stage, $installedManifestStage, $sourceManifestStage, $sourceBackup)) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
    }
}
