param(
    [ValidateSet('Inspect','FixtureTest','Cutover')][string]$Mode = 'Inspect',
    [string]$RuntimeDir = 'D:\BCT\runtime',
    [string]$Alias = 'act-control',
    [string]$McpServerUrl = 'http://127.0.0.1:18790/mcp',
    [string]$TaskName = 'BCT Tunnel Supervisor',
    [string]$V014Path = 'D:\TOOLS\OpenAI\tunnel-client\0.0.14\tunnel-client.exe',
    [string]$V016Source = 'D:\BCT\data\issue82-v0016-verification\nonoperational-cli\tunnel-client.exe',
    [string]$V016Path = 'D:\TOOLS\OpenAI\tunnel-client\0.0.16\tunnel-client.exe',
    [int]$StopTimeoutSeconds = 45,
    [int]$ReadyTimeoutSeconds = 60
)

$ErrorActionPreference = 'Stop'
$V014Sha256 = 'fcc85a69ec0ad82518e4f8964f60c45e31787957782a0fc9c1b0c44e82d61b9b'
$V016Sha256 = '4226bb74a72388147882881f29f79801b95e285d731a138071812e3aa6766571'
$PointerPath = Join-Path $RuntimeDir 'tunnel-client-current.json'
$StopFlag = Join-Path $RuntimeDir 'BCT_TUNNEL_SUPERVISOR.STOP'
$SupervisorPath = Join-Path $RuntimeDir 'ops\run_bct_tunnel_supervisor.ps1'
$ReceiptDir = Join-Path $RuntimeDir 'receipts\tunnel-cutover'
$CutoverMutex = [Threading.Mutex]::new($false, 'Local\BCT-OpenAI-Tunnel-Cutover')
$SupervisorMutex = $null
$CutoverLocked = $false
$SupervisorLocked = $false

function Get-FileSha([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return '' }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-CutoverGate {
    param(
        [bool]$OldBinaryValid,
        [bool]$NewSourceValid,
        [bool]$SupervisorValid,
        [bool]$TaskValid,
        [bool]$SingleOldTunnel,
        [bool]$SingleSupervisor,
        [bool]$NoStopFlag
    )
    return ($OldBinaryValid -and $NewSourceValid -and $SupervisorValid -and
        $TaskValid -and $SingleOldTunnel -and $SingleSupervisor -and $NoStopFlag)
}

function Get-TunnelProcesses {
    return @(Get-CimInstance Win32_Process -Filter "Name='tunnel-client.exe'" -ErrorAction Stop)
}

function Get-SupervisorProcesses {
    $items = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='pwsh.exe'" -ErrorAction Stop)
    return @($items | Where-Object {
        [string]$_.CommandLine -match 'run_bct_tunnel_supervisor\.ps1'
    })
}

function Get-TaskIdentity {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $valid = ($task.Actions.Count -eq 1 -and
        [string]$task.Actions[0].Arguments -match [regex]::Escape($SupervisorPath))
    return [pscustomobject]@{ task = $task; valid = $valid; state = [string]$task.State }
}

function Get-Preflight {
    $tunnels = Get-TunnelProcesses
    $supervisors = Get-SupervisorProcesses
    $taskIdentity = Get-TaskIdentity
    $singleOld = ($tunnels.Count -eq 1 -and
        [IO.Path]::GetFullPath([string]$tunnels[0].ExecutablePath) -eq [IO.Path]::GetFullPath($V014Path))
    $singleSupervisor = ($supervisors.Count -eq 1)
    $values = [ordered]@{
        old_binary_valid = ((Get-FileSha $V014Path) -ceq $V014Sha256)
        new_source_valid = ((Get-FileSha $V016Source) -ceq $V016Sha256)
        supervisor_valid = (Test-Path -LiteralPath $SupervisorPath -PathType Leaf)
        task_valid = [bool]$taskIdentity.valid
        single_old_tunnel = $singleOld
        single_supervisor = $singleSupervisor
        no_stop_flag = (-not (Test-Path -LiteralPath $StopFlag -PathType Leaf))
        tunnel_pids = @($tunnels | ForEach-Object { [int]$_.ProcessId })
        supervisor_pids = @($supervisors | ForEach-Object { [int]$_.ProcessId })
        task_state = $taskIdentity.state
    }
    $values.ready = Test-CutoverGate $values.old_binary_valid $values.new_source_valid `
        $values.supervisor_valid $values.task_valid $values.single_old_tunnel `
        $values.single_supervisor $values.no_stop_flag
    return [pscustomobject]$values
}

function Write-Utf8Atomic([string]$Path, [string]$Text) {
    $parent = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temp = Join-Path $parent ('.' + [IO.Path]::GetFileName($Path) + '.' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::WriteAllText($temp, $Text, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temp -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }
}

function Write-Pointer([string]$Version, [string]$Path, [string]$Sha256) {
    $payload = [ordered]@{
        schema = 'BCT_TUNNEL_CLIENT_POINTER_V1'
        version = $Version
        path = [IO.Path]::GetFullPath($Path)
        sha256 = $Sha256
        updated_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    Write-Utf8Atomic $PointerPath (($payload | ConvertTo-Json -Depth 4) + [Environment]::NewLine)
    if ((Get-Content -LiteralPath $PointerPath -Raw -Encoding UTF8 | ConvertFrom-Json).sha256 -cne $Sha256) {
        throw 'BCT_TUNNEL_POINTER_POSTCHECK_FAILED'
    }
}

function Install-V016 {
    if ((Get-FileSha $V016Source) -cne $V016Sha256) { throw 'BCT_TUNNEL_V016_SOURCE_HASH_MISMATCH' }
    if (Test-Path -LiteralPath $V016Path -PathType Leaf) {
        if ((Get-FileSha $V016Path) -cne $V016Sha256) { throw 'BCT_TUNNEL_V016_DESTINATION_HASH_MISMATCH' }
        return
    }
    $parent = Split-Path -Parent $V016Path
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temp = Join-Path $parent ('.tunnel-client.' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::Copy($V016Source, $temp, $false)
        if ((Get-FileSha $temp) -cne $V016Sha256) { throw 'BCT_TUNNEL_V016_STAGE_HASH_MISMATCH' }
        Move-Item -LiteralPath $temp -Destination $V016Path
    } finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }
    if ((Get-FileSha $V016Path) -cne $V016Sha256) { throw 'BCT_TUNNEL_V016_INSTALL_HASH_MISMATCH' }
}

function Wait-For([scriptblock]$Condition, [int]$TimeoutSeconds, [string]$ErrorCode) {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) { return }
        Start-Sleep -Milliseconds 250
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw $ErrorCode
}

function Stop-Supervisor {
    Write-Utf8Atomic $StopFlag (([DateTimeOffset]::UtcNow.ToString('o')) + [Environment]::NewLine)
    Wait-For { (Get-SupervisorProcesses).Count -eq 0 } $StopTimeoutSeconds 'BCT_TUNNEL_SUPERVISOR_STOP_TIMEOUT'
}

function Stop-RuntimeWith([string]$ClientPath) {
    if (-not (Test-Path -LiteralPath $ClientPath -PathType Leaf)) { return }
    & $ClientPath runtimes stop $Alias --json 2>$null | Out-Null
    $code = $LASTEXITCODE
    if ($code -ne 0 -and (Get-TunnelProcesses).Count -ne 0) {
        throw "BCT_TUNNEL_RUNTIME_STOP_FAILED exit=$code"
    }
    Wait-For { (Get-TunnelProcesses).Count -eq 0 } $StopTimeoutSeconds 'BCT_TUNNEL_PROCESS_STOP_TIMEOUT'
}

function Read-RuntimeStatus([string]$ClientPath) {
    $raw = & $ClientPath runtimes status $Alias --json 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) { return $null }
    try { return ($raw | ConvertFrom-Json) } catch { return $null }
}

function Test-ExactReady([string]$ClientPath) {
    $processes = Get-TunnelProcesses
    if ($processes.Count -ne 1) { return $false }
    if ([IO.Path]::GetFullPath([string]$processes[0].ExecutablePath) -ne [IO.Path]::GetFullPath($ClientPath)) {
        return $false
    }
    $status = Read-RuntimeStatus $ClientPath
    return ($null -ne $status -and $status.process_running -and $status.healthy -and
        $status.process.target_value -eq $McpServerUrl)
}

function Start-And-Verify([string]$ClientPath) {
    if (Test-Path -LiteralPath $StopFlag) { Remove-Item -LiteralPath $StopFlag -Force }
    Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Wait-For { Test-ExactReady $ClientPath } $ReadyTimeoutSeconds 'BCT_TUNNEL_READY_TIMEOUT'
}

function Write-Receipt([string]$Status, [string]$SelectedVersion, [bool]$RollbackPerformed, [string]$ErrorCode = '') {
    $processes = Get-TunnelProcesses
    $supervisors = Get-SupervisorProcesses
    $payload = [ordered]@{
        schema = 'BCT_TUNNEL_CUTOVER_RECEIPT_V1'
        status = $Status
        selected_version = $SelectedVersion
        rollback_performed = $RollbackPerformed
        error = $ErrorCode
        tunnel_pids = @($processes | ForEach-Object { [int]$_.ProcessId })
        supervisor_pids = @($supervisors | ForEach-Object { [int]$_.ProcessId })
        pointer_sha256 = Get-FileSha $PointerPath
        created_utc = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $name = 'issue82-v016-cutover-' + [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '.json'
    Write-Utf8Atomic (Join-Path $ReceiptDir $name) (($payload | ConvertTo-Json -Depth 5) + [Environment]::NewLine)
    return [pscustomobject]$payload
}

if ($Mode -eq 'FixtureTest') {
    $cases = @(
        [pscustomobject]@{ name='baseline'; values=@($true,$true,$true,$true,$true,$true,$true); expected=$true },
        [pscustomobject]@{ name='old_hash'; values=@($false,$true,$true,$true,$true,$true,$true); expected=$false },
        [pscustomobject]@{ name='new_hash'; values=@($true,$false,$true,$true,$true,$true,$true); expected=$false },
        [pscustomobject]@{ name='supervisor'; values=@($true,$true,$false,$true,$true,$true,$true); expected=$false },
        [pscustomobject]@{ name='task'; values=@($true,$true,$true,$false,$true,$true,$true); expected=$false },
        [pscustomobject]@{ name='tunnel_owner'; values=@($true,$true,$true,$true,$false,$true,$true); expected=$false },
        [pscustomobject]@{ name='supervisor_owner'; values=@($true,$true,$true,$true,$true,$false,$true); expected=$false },
        [pscustomobject]@{ name='stop_flag'; values=@($true,$true,$true,$true,$true,$true,$false); expected=$false }
    )
    $checks = foreach ($case in $cases) {
        $actual = Test-CutoverGate $case.values[0] $case.values[1] $case.values[2] `
            $case.values[3] $case.values[4] $case.values[5] $case.values[6]
        [pscustomobject]@{ name=$case.name; pass=($actual -eq $case.expected) }
    }
    $ok = @($checks | Where-Object { -not $_.pass }).Count -eq 0
    [pscustomobject]@{ schema=1; mode='FixtureTest'; status=if($ok){'PASS'}else{'FAIL'}; checks=$checks; operational_effects=$false } |
        ConvertTo-Json -Depth 4
    if (-not $ok) { exit 5 }
    exit 0
}

$preflight = Get-Preflight
if ($Mode -eq 'Inspect') {
    [pscustomobject]@{ schema='BCT_TUNNEL_CUTOVER_INSPECT_V1'; mode='READ_ONLY'; preflight=$preflight;
        pointer_present=(Test-Path -LiteralPath $PointerPath -PathType Leaf) } | ConvertTo-Json -Depth 6 -Compress
    exit 0
}

try {
    try { $CutoverLocked = $CutoverMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $CutoverLocked = $true }
    if (-not $CutoverLocked) { throw 'BCT_TUNNEL_CUTOVER_ALREADY_RUNNING' }
    if (-not $preflight.ready) { throw 'BCT_TUNNEL_CUTOVER_PREFLIGHT_FAILED' }
    Install-V016
    Stop-Supervisor
    $SupervisorMutex = [Threading.Mutex]::new($false, 'Local\BCT-OpenAI-Tunnel-Supervisor')
    try { $SupervisorLocked = $SupervisorMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $SupervisorLocked = $true }
    if (-not $SupervisorLocked) { throw 'BCT_TUNNEL_SUPERVISOR_MUTEX_NOT_AVAILABLE' }
    Stop-RuntimeWith $V014Path
    Write-Pointer '0.0.16' $V016Path $V016Sha256
    $SupervisorMutex.ReleaseMutex(); $SupervisorLocked = $false
    $SupervisorMutex.Dispose(); $SupervisorMutex = $null
    Start-And-Verify $V016Path
    (Write-Receipt 'APPLIED' '0.0.16' $false) | ConvertTo-Json -Depth 5 -Compress
    exit 0
} catch {
    $original = $_.Exception.Message
    try {
        if ($SupervisorLocked) { $SupervisorMutex.ReleaseMutex(); $SupervisorLocked = $false }
        if ($SupervisorMutex) { $SupervisorMutex.Dispose(); $SupervisorMutex = $null }
        if ((Get-SupervisorProcesses).Count -gt 0) { Stop-Supervisor }
        $SupervisorMutex = [Threading.Mutex]::new($false, 'Local\BCT-OpenAI-Tunnel-Supervisor')
        try { $SupervisorLocked = $SupervisorMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $SupervisorLocked = $true }
        if (-not $SupervisorLocked) { throw 'BCT_TUNNEL_ROLLBACK_MUTEX_NOT_AVAILABLE' }
        Stop-RuntimeWith $V016Path
        Stop-RuntimeWith $V014Path
        Write-Pointer '0.0.14' $V014Path $V014Sha256
        $SupervisorMutex.ReleaseMutex(); $SupervisorLocked = $false
        $SupervisorMutex.Dispose(); $SupervisorMutex = $null
        Start-And-Verify $V014Path
        (Write-Receipt 'ROLLED_BACK' '0.0.14' $true $original) | ConvertTo-Json -Depth 5 -Compress
    } catch {
        $rollbackError = $_.Exception.Message
        (Write-Receipt 'ROLLBACK_FAILED' 'UNKNOWN' $true ($original + ';' + $rollbackError)) |
            ConvertTo-Json -Depth 5 -Compress
    }
    exit 10
} finally {
    if ($SupervisorLocked -and $SupervisorMutex) { try { $SupervisorMutex.ReleaseMutex() } catch {} }
    if ($SupervisorMutex) { $SupervisorMutex.Dispose() }
    if ($CutoverLocked) { try { $CutoverMutex.ReleaseMutex() } catch {} }
    $CutoverMutex.Dispose()
}
