param(
    [int]$CheckIntervalSeconds = 20,
    [string]$RuntimeDir = 'D:\BCT\runtime',
    [string]$Profile = 'bct_runtime_v1',
    # Do not embed a user-profile literal here. Windows PowerShell 5.1 treats
    # UTF-8 files without a BOM as an ANSI code page, which corrupts a Korean
    # profile name before this supervisor can write its own diagnostics.
    [string]$PythonPath = (Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)) 'Programs\Python\Python312\python.exe')
)

$ErrorActionPreference = 'Stop'
$LogDir = Join-Path $RuntimeDir 'logs'
$LockPath = Join-Path $RuntimeDir 'bct-core-supervisor.lock'
$StopFlag = Join-Path $RuntimeDir 'BCT_CORE_SUPERVISOR.STOP'
$Mutex = [Threading.Mutex]::new($false, 'Local\BCT-Core-Supervisor')
$Lock = $null
$Acquired = $false

function Write-Event([string]$Name, [string]$Detail = '') {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $line = ((Get-Date).ToString('o') + ' ' + $Name + ' ' + $Detail).TrimEnd()
    Add-Content -LiteralPath (Join-Path $LogDir 'bct-core-supervisor.log') -Value $line -Encoding UTF8
}

function Invoke-Ensure {
    $currentPath = Join-Path $RuntimeDir 'current.json'
    $current = Get-Content -LiteralPath $currentPath -Raw -ErrorAction Stop | ConvertFrom-Json
    $releaseRoot = [IO.Path]::GetFullPath([string]$current.release_path)
    $expectedRoot = [IO.Path]::GetFullPath((Join-Path (Join-Path $RuntimeDir 'releases') ([string]$current.source_head)))
    if ($releaseRoot -ne $expectedRoot) { throw 'BCT_SUPERVISOR_RELEASE_PATH_MISMATCH' }
    $module = Join-Path $releaseRoot 'src\bct\supervisor.py'
    if (-not (Test-Path -LiteralPath $module -PathType Leaf)) { throw 'BCT_SUPERVISOR_MODULE_MISSING' }
    $env:PYTHONPATH = Join-Path $releaseRoot 'src'
    $output = & $PythonPath -m bct.supervisor --runtime-root $RuntimeDir --profile $Profile 2>&1
    if ($LASTEXITCODE -ne 0) { throw ('BCT_CORE_ENSURE_FAILED ' + ($output -join ' ')) }
    Write-Event 'BCT_CORE_READY' ($output -join ' ')
}

try {
    try { $Acquired = $Mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $Acquired = $true }
    if (-not $Acquired) { exit 0 }
    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
    try {
        $Lock = [IO.File]::Open($LockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] { exit 0 }
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'BCT_PYTHON_NOT_FOUND' }
    Write-Event 'BCT_CORE_SUPERVISOR_START' "pid=$PID"
    while ($true) {
        if (Test-Path -LiteralPath $StopFlag) { Write-Event 'BCT_CORE_EXPLICIT_STOP'; exit 0 }
        try { Invoke-Ensure } catch { Write-Event 'BCT_CORE_ENSURE_FAILED' $_.Exception.Message }
        Start-Sleep -Seconds $CheckIntervalSeconds
    }
} finally {
    if ($Lock) { $Lock.Dispose() }
    if ($Acquired) { try { $Mutex.ReleaseMutex() } catch {} }
    $Mutex.Dispose()
}
