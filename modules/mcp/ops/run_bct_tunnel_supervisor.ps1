param(
    [int]$CheckIntervalSeconds = 20,
    [int]$RestartDelaySeconds = 5,
    [string]$Alias = 'act-control',
    [string]$TunnelId = 'tunnel_6ac39655c25c8191a3f96f37c9fc2525',
    # Windows PowerShell 5.1 can parse a UTF-8 script without a BOM through an
    # ANSI code page. Resolve the account-specific paths at runtime so a
    # non-ASCII Windows profile cannot prevent the supervisor from starting.
    [string]$ProfileDir = (Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)) 'tunnel-client'),
    [string]$McpServerUrl = 'http://127.0.0.1:18790/mcp',
    [string]$TunnelClientPath = '',
    [string]$TunnelClientPointerPath = '',
    [string]$RuntimeDir = 'D:\BCT\runtime',
    [string]$HealthUrlFile = (Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)) '.local\state\tunnel-client\health\act-control.url'),
    [switch]$RepairHealthOnly,
    [int]$RepairProcessId = 0
)

$ErrorActionPreference = 'Stop'
$LogDir = Join-Path $RuntimeDir 'logs'
$LockPath = Join-Path $RuntimeDir 'bct-tunnel-supervisor.lock'
$StopFlag = Join-Path $RuntimeDir 'BCT_TUNNEL_SUPERVISOR.STOP'
$HeaderReference = 'file:' + (Join-Path $RuntimeDir 'mcp.token')
$FallbackTunnelClientPath = 'D:\TOOLS\OpenAI\tunnel-client\0.0.14\tunnel-client.exe'
if ([string]::IsNullOrWhiteSpace($TunnelClientPointerPath)) {
    $TunnelClientPointerPath = Join-Path $RuntimeDir 'tunnel-client-current.json'
}
$Mutex = [Threading.Mutex]::new($false, 'Local\BCT-OpenAI-Tunnel-Supervisor')
$Lock = $null
$Acquired = $false

function Write-Event([string]$Name, [string]$Detail = '') {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $line = ((Get-Date).ToString('o') + ' ' + $Name + ' ' + $Detail).TrimEnd()
    Add-Content -LiteralPath (Join-Path $LogDir 'bct-tunnel-supervisor.log') -Value $line -Encoding UTF8
}

function Read-StrictUtf8Text([string]$Path) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        return [Text.UTF8Encoding]::new($false, $true).GetString($bytes, 3, $bytes.Length - 3)
    }
    return [Text.UTF8Encoding]::new($false, $true).GetString($bytes)
}

function Resolve-TunnelClientPath {
    if (-not [string]::IsNullOrWhiteSpace($TunnelClientPath)) {
        return [IO.Path]::GetFullPath($TunnelClientPath)
    }
    if (-not (Test-Path -LiteralPath $TunnelClientPointerPath -PathType Leaf)) {
        return $FallbackTunnelClientPath
    }
    try {
        $pointer = (Read-StrictUtf8Text $TunnelClientPointerPath) | ConvertFrom-Json
    } catch {
        throw "BCT_TUNNEL_CLIENT_POINTER_INVALID path=$TunnelClientPointerPath"
    }
    if ($pointer.schema -cne 'BCT_TUNNEL_CLIENT_POINTER_V1') {
        throw "BCT_TUNNEL_CLIENT_POINTER_SCHEMA_INVALID path=$TunnelClientPointerPath"
    }
    $selected = [IO.Path]::GetFullPath([string]$pointer.path)
    $allowedRoot = [IO.Path]::GetFullPath('D:\TOOLS\OpenAI\tunnel-client')
    if (-not $selected.StartsWith($allowedRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw "BCT_TUNNEL_CLIENT_POINTER_PATH_INVALID path=$selected"
    }
    if (-not (Test-Path -LiteralPath $selected -PathType Leaf)) {
        throw "BCT_TUNNEL_CLIENT_NOT_FOUND path=$selected"
    }
    $expectedHash = ([string]$pointer.sha256).Trim().ToLowerInvariant()
    if ($expectedHash -notmatch '^[a-f0-9]{64}$') {
        throw 'BCT_TUNNEL_CLIENT_POINTER_HASH_INVALID'
    }
    $actualHash = (Get-FileHash -LiteralPath $selected -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -cne $expectedHash) {
        throw "BCT_TUNNEL_CLIENT_HASH_MISMATCH path=$selected"
    }
    return $selected
}

function Set-RuntimeEnvironment {
    $key = [Environment]::GetEnvironmentVariable('CONTROL_PLANE_API_KEY', 'User')
    if ([string]::IsNullOrWhiteSpace($key)) { throw 'BCT_TUNNEL_RUNTIME_KEY_MISSING' }
    $env:CONTROL_PLANE_API_KEY = $key
    $env:MCP_EXTRA_HEADERS = "X-BCT-Token: $HeaderReference"
    $env:MCP_DISCOVERY_EXTRA_HEADERS = "X-BCT-Token: $HeaderReference"
}

function Get-RuntimeStatus {
    $raw = & $TunnelClientPath runtimes status $Alias --json 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) { return $null }
    try { return ($raw | ConvertFrom-Json) } catch { return $null }
}

function Assert-ExactProcess($Status) {
    if ($null -eq $Status -or -not $Status.process_running) { return $false }
    if ($Status.process.target_value -ne $McpServerUrl) {
        throw "BCT_TUNNEL_TARGET_MISMATCH actual=$($Status.process.target_value)"
    }
    if ($Status.process.tunnel_id -ne $TunnelId) {
        throw "BCT_TUNNEL_ID_MISMATCH actual=$($Status.process.tunnel_id)"
    }
    $expected = [IO.Path]::GetFullPath($TunnelClientPath)
    $actual = (Get-CimInstance Win32_Process -Filter "ProcessId=$($Status.process.pid)" -ErrorAction Stop).ExecutablePath
    if ([IO.Path]::GetFullPath($actual) -ne $expected) {
        throw "BCT_TUNNEL_EXECUTABLE_MISMATCH actual=$actual"
    }
    return $true
}

function Assert-ExactRuntime($Status) {
    if (-not (Assert-ExactProcess $Status)) { return $false }
    return [bool]$Status.healthy
}

function Test-HealthEndpoint([string]$BaseUrl) {
    try {
        $health = Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + '/healthz') -TimeoutSec 2
        $ready = Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + '/readyz') -TimeoutSec 2
        return (
            [int]$health.StatusCode -eq 200 -and $health.Content.Trim() -eq 'live' -and
            [int]$ready.StatusCode -eq 200 -and $ready.Content.Trim() -eq 'ready'
        )
    } catch {
        return $false
    }
}

function Read-TunnelProfileText([string]$Path) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        return [Text.UTF8Encoding]::new($false, $true).GetString($bytes, 3, $bytes.Length - 3)
    }
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        return [Text.Encoding]::Unicode.GetString($bytes, 2, $bytes.Length - 2)
    }
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
        return [Text.Encoding]::BigEndianUnicode.GetString($bytes, 2, $bytes.Length - 2)
    }
    try {
        return [Text.UTF8Encoding]::new($false, $true).GetString($bytes)
    } catch [Text.DecoderFallbackException] {
        # Legacy Windows profiles can be ANSI-encoded.  Decode them using the
        # current Windows code page, then normalize the next write to UTF-8.
        return [Text.Encoding]::Default.GetString($bytes)
    }
}

function Repair-HealthUrlFile([int]$ProcessId) {
    if ($ProcessId -le 0) { throw 'BCT_TUNNEL_HEALTH_REPAIR_PID_INVALID' }
    $listeners = @(
        Get-NetTCPConnection -State Listen -OwningProcess $ProcessId -ErrorAction Stop |
            Where-Object { $_.LocalAddress -eq '127.0.0.1' } |
            Select-Object -ExpandProperty LocalPort -Unique
    )
    $healthy = @()
    foreach ($port in $listeners) {
        $candidate = 'http://127.0.0.1:' + [int]$port
        if (Test-HealthEndpoint $candidate) { $healthy += $candidate }
    }
    if ($healthy.Count -ne 1) {
        throw "BCT_TUNNEL_HEALTH_ENDPOINT_AMBIGUOUS count=$($healthy.Count)"
    }
    $parent = Split-Path -Parent $HealthUrlFile
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temp = Join-Path $parent ('.' + [IO.Path]::GetFileName($HealthUrlFile) + '.' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::WriteAllText($temp, $healthy[0] + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temp -Destination $HealthUrlFile -Force
    } finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }
    return $healthy[0]
}

function Ensure-ProfileHeaders {
    $profilePath = Join-Path $ProfileDir ($Alias + '.yaml')
    # Prefer strict UTF-8, but accept legacy Windows profile encodings and
    # normalize them to UTF-8 on the next atomic write.
    $raw = Read-TunnelProfileText $profilePath
    try { $profile = $raw | ConvertFrom-Json } catch { throw "BCT_TUNNEL_PROFILE_NOT_JSON path=$profilePath" }
    if ($null -eq $profile.mcp) { throw "BCT_TUNNEL_PROFILE_MCP_MISSING path=$profilePath" }
    if ($null -eq $profile.health -or $profile.health.url_file -ne $HealthUrlFile) {
        throw "BCT_TUNNEL_HEALTH_FILE_MISMATCH actual=$($profile.health.url_file)"
    }
    if ($profile.health.listen_addr -ne '127.0.0.1:0') {
        throw "BCT_TUNNEL_HEALTH_LISTEN_MISMATCH actual=$($profile.health.listen_addr)"
    }
    $headers = [pscustomobject]@{ 'X-BCT-Token' = $HeaderReference }
    $profile.mcp | Add-Member -MemberType NoteProperty -Name extra_headers -Value $headers -Force
    $profile.mcp | Add-Member -MemberType NoteProperty -Name discovery_extra_headers -Value $headers -Force
    # v0.0.16 can forward W3C trace context, but production remains explicitly
    # opt-out until the receiver and privacy boundary are separately accepted.
    $profile.mcp | Add-Member -MemberType NoteProperty -Name forward_trace_context -Value $false -Force
    $next = $profile | ConvertTo-Json -Depth 20
    if ($next -eq $raw.TrimEnd()) { return }
    $temp = Join-Path $ProfileDir ('.' + $Alias + '.' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::WriteAllText($temp, $next + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temp -Destination $profilePath -Force
    } finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }
}

function Start-Runtime {
    Write-Event 'BCT_TUNNEL_STARTING' "alias=$Alias target=$McpServerUrl"
    & $TunnelClientPath runtimes connect --alias $Alias --profile $Alias --profile-dir $ProfileDir `
        --tunnel-id $TunnelId --mcp-server-url $McpServerUrl `
        --runtime-api-key 'env:CONTROL_PLANE_API_KEY' --json 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "BCT_TUNNEL_CONNECT_FAILED exit=$LASTEXITCODE" }
    Ensure-ProfileHeaders
}

if ($RepairHealthOnly) {
    $probe = [pscustomobject]@{
        process_running = $true
        process = [pscustomobject]@{
            pid = $RepairProcessId
            target_value = $McpServerUrl
            tunnel_id = $TunnelId
        }
    }
    if (-not (Assert-ExactProcess $probe)) { throw 'BCT_TUNNEL_HEALTH_REPAIR_PROCESS_MISSING' }
    $recoveredUrl = Repair-HealthUrlFile $RepairProcessId
    [pscustomobject]@{ repaired = $true; health_url = $recoveredUrl } | ConvertTo-Json -Compress
    exit 0
}

try {
    try { $Acquired = $Mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $Acquired = $true }
    if (-not $Acquired) { exit 0 }
    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
    try {
        $Lock = [IO.File]::Open($LockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] { exit 0 }
    $TunnelClientPath = Resolve-TunnelClientPath
    if (-not (Test-Path -LiteralPath $TunnelClientPath -PathType Leaf)) {
        throw "BCT_TUNNEL_CLIENT_NOT_FOUND path=$TunnelClientPath"
    }
    Set-RuntimeEnvironment
    Ensure-ProfileHeaders
    Write-Event 'BCT_TUNNEL_SUPERVISOR_START' "pid=$PID alias=$Alias"
    while ($true) {
        if (Test-Path -LiteralPath $StopFlag) { Write-Event 'BCT_TUNNEL_EXPLICIT_STOP'; exit 0 }
        Set-RuntimeEnvironment
        $status = Get-RuntimeStatus
        $exactProcess = Assert-ExactProcess $status
        if ($exactProcess -and -not $status.healthy) {
            try {
                $recoveredUrl = Repair-HealthUrlFile ([int]$status.process.pid)
                $status = Get-RuntimeStatus
                if (-not (Assert-ExactRuntime $status)) { throw 'BCT_TUNNEL_HEALTH_REPAIR_NOT_VISIBLE' }
                Write-Event 'BCT_TUNNEL_HEALTH_RECOVERED' "pid=$($status.process.pid) url=$recoveredUrl"
            } catch {
                Write-Event 'BCT_TUNNEL_DEGRADED' "pid=$($status.process.pid) reason=$($_.Exception.Message)"
                Start-Sleep -Seconds ([Math]::Max($CheckIntervalSeconds, 30))
                continue
            }
        } elseif (-not $exactProcess) {
            try {
                Start-Runtime
                Start-Sleep -Seconds $RestartDelaySeconds
                $status = Get-RuntimeStatus
                if ((Assert-ExactProcess $status) -and -not $status.healthy) {
                    $recoveredUrl = Repair-HealthUrlFile ([int]$status.process.pid)
                    $status = Get-RuntimeStatus
                    Write-Event 'BCT_TUNNEL_HEALTH_RECOVERED' "pid=$($status.process.pid) url=$recoveredUrl"
                }
                if (-not (Assert-ExactRuntime $status)) { throw 'BCT_TUNNEL_NOT_READY_AFTER_CONNECT' }
            } catch {
                Write-Event 'BCT_TUNNEL_START_FAILED' $_.Exception.Message
                Start-Sleep -Seconds ([Math]::Max($RestartDelaySeconds, 30))
                continue
            }
        }
        Ensure-ProfileHeaders
        Write-Event 'BCT_TUNNEL_READY' "pid=$($status.process.pid) target=$($status.process.target_value)"
        Start-Sleep -Seconds $CheckIntervalSeconds
    }
} finally {
    if ($Lock) { $Lock.Dispose() }
    if ($Acquired) { try { $Mutex.ReleaseMutex() } catch {} }
    $Mutex.Dispose()
}
