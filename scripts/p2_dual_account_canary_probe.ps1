# Manual dual-token canary test for an ADMIN-PROVISIONED, ISOLATED directory.
# This file does NOT create users, alter ACLs, touch BCT LIVE, or issue grants.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$SandboxRoot,
  [Parameter(Mandatory=$true)][string]$ExpectedSid,
  [ValidateSet('automation','core','approver','other')][string]$Role='other'
)
$ErrorActionPreference='Stop'
$root=[System.IO.Path]::GetFullPath($SandboxRoot).TrimEnd('\')
$allowedPrefix=[System.IO.Path]::GetFullPath('D:\BCT\worktrees\p2-security-canary\')
if(-not ($root + '\').StartsWith($allowedPrefix,[StringComparison]::OrdinalIgnoreCase)){
  throw 'SANDBOX_OUTSIDE_PROTECTED_ISOLATED_WORKTREE'
}
$marker=Join-Path $root '.bct-p2-security-canary'
if(-not [System.IO.File]::Exists($marker)){
  throw 'CANARY_MARKER_MISSING'
}
if([System.IO.File]::ReadAllText($marker).Trim() -ne 'BCT_P2_CANARY_ONLY_V1'){
  throw 'CANARY_MARKER_INVALID'
}
$current=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if($current -ne $ExpectedSid){throw 'ACTUAL_TOKEN_SID_MISMATCH'}
# All probe names are fixed and may ONLY refer to expendable fixtures
# explicitly populated by the supervisor under SandboxRoot.
$targets=@('policy-canary.toml','state-canary.db','issuer-code-canary.py','issuer-key-canary.bin')
$rows=@()
foreach($name in $targets){
  $p=Join-Path $root $name
  if(-not [System.IO.File]::Exists($p)){throw "CANARY_FIXTURE_MISSING:$name"}
  $acl=Get-Acl -LiteralPath $p
  $writeOpen='DENIED'
  $rename='DENIED'
  try {
    $file=[System.IO.File]::Open($p,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
    $file.Dispose()
    $writeOpen='ALLOWED'
  } catch [System.UnauthorizedAccessException] {
    $writeOpen='DENIED'
  } catch [System.IO.IOException] {
    $writeOpen='BLOCKED_IO_UNVERIFIED'
  }
  # Rename tests are non-destructive and restricted to fixture names.
  $tmp=Join-Path $root ($name+'.rename-probe')
  if([System.IO.File]::Exists($tmp)){throw "RENAME_PROBE_COLLISION:$name"}
  try {
    [System.IO.File]::Move($p,$tmp)
    $rename='ALLOWED'
    [System.IO.File]::Move($tmp,$p)
  } catch [System.UnauthorizedAccessException] {
    $rename='DENIED'
  } catch [System.IO.IOException] {
    $rename='BLOCKED_IO_UNVERIFIED'
  } finally {
    if([System.IO.File]::Exists($tmp) -and -not [System.IO.File]::Exists($p)){
      [System.IO.File]::Move($tmp,$p)
    }
  }
  $rows += [PSCustomObject]@{
    role=$Role; sid=$current; fixture=$name;
    owner=$acl.Owner; aclProtected=$acl.AreAccessRulesProtected;
    writeOpen=$writeOpen; rename=$rename
  }
}
$rows|ConvertTo-Json -Depth 4
# Observe results, then supervisor evaluates expected allowed/denied matrix.
