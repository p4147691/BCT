param(
    [int]$CheckIntervalSeconds = 20,
    [int]$RestartDelaySeconds = 5,
    [string]$Alias = 'act-control',
    [string]$TunnelId = 'tunnel_6ac39655c25c8191a3f96f37c9fc2525',
    [string]$ProfileDir = 'C:\Users\시우세영\AppData\Roaming\tunnel-client',
    [string]$McpServerUrl = 'http://127.0.0.1:18790/mcp',
    [string]$TunnelClientPath = 'D:\TOOLS\OpenAI\tunnel-client\0.0.14\tunnel-client.exe',
    [string]$RuntimeDir = 'D:\BCT\runtime'
)

$ErrorActionPreference = 'Stop'
$LogDir = Join-Path $RuntimeDir 'logs'
$LockPath = Join-Path $RuntimeDir 'bct-tunnel-supervisor.lock'
$StopFlag = Join-Path $RuntimeDir 'BCT_TUNNEL_SUPERVISOR.STOP'
$HeaderReference = 'file:D:\BCT\runtime\mcp.token'
$Mutex = [Threading.Mutex]::new($false, 'Local\BCT-OpenAI-Tunnel-Supervisor')
$Lock = $null
$Acquired = $false

function Write-Event([string]$Name, [string]$Detail = '') {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $line = ((Get-Date).ToString('o') + ' ' + $Name + ' ' + $Detail).TrimEnd()
    Add-Content -LiteralPath (Join-Path $LogDir 'bct-tunnel-supervisor.log') -Value $line -Encoding UTF8
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

function Assert-ExactRuntime($Status) {
    if ($null -eq $Status -or -not $Status.process_running -or -not $Status.healthy) { return $false }
    if ($Status.process.target_value -ne $McpServerUrl) {
        throw "BCT_TUNNEL_TARGET_MISMATCH actual=$($Status.process.target_value)"
    }
    $expected = [IO.Path]::GetFullPath($TunnelClientPath)
    $actual = (Get-CimInstance Win32_Process -Filter "ProcessId=$($Status.process.pid)" -ErrorAction Stop).ExecutablePath
    if ([IO.Path]::GetFullPath($actual) -ne $expected) {
        throw "BCT_TUNNEL_EXECUTABLE_MISMATCH actual=$actual"
    }
    return $true
}

function Ensure-ProfileHeaders {
    $profilePath = Join-Path $ProfileDir ($Alias + '.yaml')
    $raw = Get-Content -LiteralPath $profilePath -Raw -ErrorAction Stop
    try { $profile = $raw | ConvertFrom-Json } catch { throw "BCT_TUNNEL_PROFILE_NOT_JSON path=$profilePath" }
    if ($null -eq $profile.mcp) { throw "BCT_TUNNEL_PROFILE_MCP_MISSING path=$profilePath" }
    $headers = [pscustomobject]@{ 'X-BCT-Token' = $HeaderReference }
    $profile.mcp | Add-Member -MemberType NoteProperty -Name extra_headers -Value $headers -Force
    $profile.mcp | Add-Member -MemberType NoteProperty -Name discovery_extra_headers -Value $headers -Force
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

try {
    try { $Acquired = $Mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $Acquired = $true }
    if (-not $Acquired) { exit 0 }
    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
    try {
        $Lock = [IO.File]::Open($LockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] { exit 0 }
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
        if (-not (Assert-ExactRuntime $status)) {
            try {
                Start-Runtime
                Start-Sleep -Seconds $RestartDelaySeconds
                $status = Get-RuntimeStatus
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
