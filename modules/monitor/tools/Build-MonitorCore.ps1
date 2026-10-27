param(
    [Parameter(Mandatory = $true)]
    [string]$VersionName
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root "native\src"
$output = Join-Path $root ("native\" + $VersionName)
$previousManifest = Get-Content -Raw (Join-Path $root "native\com.pas40.desktop_window_monitor.json") | ConvertFrom-Json
$previousDirectory = Split-Path -Parent $previousManifest.path
$controlManifest = Get-Content -Raw (Join-Path $root "native\com.pas40.desktop_window_monitor_control.json") | ConvertFrom-Json
$controlDirectory = Split-Path -Parent $controlManifest.path
$framework = "C:\Program Files (x86)\Reference Assemblies\Microsoft\Framework\.NETFramework\v4.0"
$compiler = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

New-Item -ItemType Directory -Force -Path $output | Out-Null
$outputExe = Join-Path $output "DesktopWindowMonitorHost.exe"
$hostSource = Join-Path $source "MonitorDesktopHost.cs"
$visualSource = Join-Path $source "DesktopVisualSnapshot.cs"
$backgroundStateSource = Join-Path $source "DesktopBackgroundStateSource.cs"
$dragPreviewSource = Join-Path $source "MonitorDragPreviewOverlay.cs"
$wallpaperWatchSource = Join-Path $source "MonitorWallpaperRegistryWatcher.cs"
$automationClient = Join-Path $framework "UIAutomationClient.dll"
$automationTypes = Join-Path $framework "UIAutomationTypes.dll"
& $compiler /nologo /target:exe /platform:anycpu /optimize+ `
    "/out:$outputExe" `
    $hostSource `
    $visualSource `
    $backgroundStateSource `
    $dragPreviewSource `
    $wallpaperWatchSource `
    /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll `
    /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll `
    "/reference:$automationClient" `
    "/reference:$automationTypes"
if ($LASTEXITCODE -ne 0) { throw "Monitor Core compilation failed: $LASTEXITCODE" }

$controlOutputExe = Join-Path $output "DesktopWindowMonitorControlHost.exe"
Copy-Item -LiteralPath $outputExe -Destination $controlOutputExe -Force

function Resolve-NativeAsset {
    param([Parameter(Mandatory = $true)][string]$Name)

    $candidateDirectories = @($previousDirectory, $controlDirectory) |
        Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
        Select-Object -Unique

    foreach ($directory in $candidateDirectories) {
        $candidate = Join-Path $directory $Name
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }

    $fallback = Get-ChildItem -LiteralPath (Join-Path $root "native") -Filter $Name -File -Recurse |
        Where-Object { $_.DirectoryName -ne $output } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($fallback) { return $fallback.FullName }

    throw "Required native runtime asset is missing: $Name"
}

$helperSource = Resolve-NativeAsset "DesktopWindowMonitorWgcSnapshot.exe"
$accessorSource = Resolve-NativeAsset "VirtualDesktopAccessor.dll"
$helperTarget = Join-Path $output "DesktopWindowMonitorWgcSnapshot.exe"
$accessorTarget = Join-Path $output "VirtualDesktopAccessor.dll"
Copy-Item -LiteralPath $helperSource -Destination $helperTarget -Force
Copy-Item -LiteralPath $accessorSource -Destination $accessorTarget -Force

foreach ($requiredPath in @($outputExe, $controlOutputExe, $helperTarget, $accessorTarget)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Native runtime bundle is incomplete: $requiredPath"
    }
}
Write-Output $output
