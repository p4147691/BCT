"""Fail-closed Windows security boundary for enabled P2 approvals.

This verifies DACLS/identities; it does not create accounts or modify ACLs.
Successful checks are not a substitute for a supervised dual-token test.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from bct.core.models import AuthorizationError

_SID = re.compile(r"S-1-(?:\d+-){1,14}\d+\Z")
_SYSTEM = "S-1-5-18"
_ADMINS = "S-1-5-32-544"
_BROAD = frozenset({"S-1-1-0", "S-1-5-11", "S-1-5-32-545"})
_WRITE_RIGHTS = (0x2 | 0x4 | 0x10 | 0x100 | 0x40
                 | 0x10000 | 0x40000 | 0x80000
                 | 0x10000000 | 0x40000000 | 0x02000000)


def validate_identities(section: dict[str, Any]) -> dict[str, str]:
    """Never accept self-attested same-user issuer/service/automation roles."""
    if not isinstance(section, dict) or section.get("schema") != 1:
        raise AuthorizationError("P2_BOUNDARY_MANIFEST_REQUIRED")
    allowed = {"schema", "automation_sid", "core_sid", "approver_sid",
               "issuer_executable", "issuer_key_path", "core_executable"}
    if set(section) != allowed:
        raise AuthorizationError("P2_BOUNDARY_MANIFEST_FIELDS_INVALID")
    identities = {}
    for key in ("automation_sid", "core_sid", "approver_sid"):
        value = section.get(key)
        if not isinstance(value, str) or not _SID.fullmatch(value):
            raise AuthorizationError("P2_BOUNDARY_SID_INVALID:" + key)
        if value in _BROAD or value in {_SYSTEM, _ADMINS}:
            raise AuthorizationError("P2_BOUNDARY_PRIVILEGED_ROLE_INVALID:" + key)
        identities[key] = value
    if len(set(identities.values())) != 3:
        raise AuthorizationError("P2_BOUNDARY_ACCOUNTS_NOT_SEPARATED")
    for key in ("issuer_executable", "issuer_key_path", "core_executable"):
        raw = section.get(key)
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise AuthorizationError("P2_BOUNDARY_PATH_INVALID:" + key)
        identities[key] = raw
    return identities


def _reject_reparse_chain(path: Path) -> None:
    """Sensitive paths and parents may not cross a symlink or junction."""
    for element in (path, *path.parents):
        try:
            info = os.lstat(element)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise AuthorizationError("P2_BOUNDARY_PATH_UNOBSERVABLE") from exc
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise AuthorizationError("P2_BOUNDARY_REPARSE_FORBIDDEN")


def inspect_dacl(path: Path) -> dict[str, Any]:
    """Read-only PowerShell Get-Acl: names translated to unambiguous SIDs.

    Powershell is called with a fixed script and JSON path over stdin (no
    concatenation of untrusted paths into executable script source).
    """
    if os.name != "nt":
        raise AuthorizationError("P2_BOUNDARY_WINDOWS_REQUIRED")
    script = r'''
$ErrorActionPreference = 'Stop'
$p = [Console]::In.ReadToEnd() | ConvertFrom-Json
$acl = Get-Acl -LiteralPath $p.path
$aces = @($acl.Access | ForEach-Object {
  $sid = $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
  [PSCustomObject]@{
    sid = $sid;
    mask = [int64]$_.FileSystemRights;
    allow = ($_.AccessControlType -eq 'Allow')
  }
})
$ownerSid = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
[PSCustomObject]@{ owner=$ownerSid; protected=$acl.AreAccessRulesProtected; aces=$aces } |
 ConvertTo-Json -Compress -Depth 5
'''
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile",
             "-NonInteractive", "-Command", script],
            input=json.dumps({"path": str(path)}).encode("utf-8"),
            capture_output=True, timeout=12,
        )
        if result.returncode:
            raise AuthorizationError("P2_BOUNDARY_DACL_UNOBSERVABLE")
        value = json.loads(result.stdout.decode("utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("not object")
        return value
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        raise AuthorizationError("P2_BOUNDARY_DACL_UNOBSERVABLE") from exc


def validate_acl(snapshot: dict[str, Any], *, writers: set[str],
                 forbidden: set[str]) -> None:
    """Reject writable broad/user principals even if a separate deny ACE exists."""
    if not isinstance(snapshot, dict) or snapshot.get("protected") is not True:
        raise AuthorizationError("P2_BOUNDARY_DACL_NOT_PROTECTED")
    owner = snapshot.get("owner")
    if owner not in writers:
        raise AuthorizationError("P2_BOUNDARY_OWNER_UNTRUSTED")
    aces = snapshot.get("aces")
    if not isinstance(aces, list):
        raise AuthorizationError("P2_BOUNDARY_ACE_UNOBSERVABLE")
    for ace in aces:
        if not isinstance(ace, dict) or type(ace.get("mask")) is not int:
            raise AuthorizationError("P2_BOUNDARY_ACE_UNOBSERVABLE")
        sid = ace.get("sid")
        if not isinstance(sid, str) or not _SID.fullmatch(sid):
            raise AuthorizationError("P2_BOUNDARY_ACE_UNOBSERVABLE")
        if ace.get("allow") is True and (ace["mask"] & _WRITE_RIGHTS):
            if sid in forbidden or sid in _BROAD or sid not in writers:
                raise AuthorizationError("P2_BOUNDARY_UNTRUSTED_WRITER")


def current_sid() -> str:
    if os.name != "nt":
        raise AuthorizationError("P2_BOUNDARY_WINDOWS_REQUIRED")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-Command", "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value"],
            capture_output=True, timeout=10,
        )
        sid = result.stdout.decode("utf-8-sig").strip()
        if result.returncode or not _SID.fullmatch(sid):
            raise ValueError("bad SID")
        return sid
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise AuthorizationError("P2_BOUNDARY_CURRENT_ID_UNVERIFIED") from exc


def _runtime_source_paths() -> list[Path]:
    """Every active approval/effect implementation must be admin-owned."""
    from bct import service
    from bct.core import approval, operations, policy, store
    from bct.features import pc_safe_apply, pc_process_apply
    sources = [
        Path(__file__), Path(service.__file__),
        Path(approval.__file__), Path(operations.__file__),
        Path(policy.__file__), Path(store.__file__),
        Path(pc_safe_apply.__file__), Path(pc_process_apply.__file__),
    ]
    return sources + [Path(service.__file__).parent]


def _is_isolated_python() -> bool:
    return sys.flags.isolated == 1


def require_effect_only_core_policy(actions: list[str]) -> None:
    """A privileged verifier cannot also expose arbitrary execute/write APIs."""
    safe = {"read", "system_inspect", "approval_challenge",
            "file_action_plan", "process_stop_plan"}
    if (not isinstance(actions, list)
            or not all(isinstance(action, str) for action in actions)
            or set(actions) - safe):
        raise AuthorizationError("P2_BOUNDARY_PRIVILEGED_CORE_GENERAL_EFFECTS_ENABLED")


def require_core_boundary(section: dict[str, Any], *,
                          policy_path: Path, state_path: Path) -> None:
    """Approval verifier must run as isolated Core identity, not general execute."""
    identities = validate_identities(section)
    # The protected Core token must never host a generic command/program
    # runner: those capabilities would write its own DB as the privileged SID.
    try:
        config = tomllib.loads(policy_path.read_text(encoding="utf8"))
        require_effect_only_core_policy(config["policy"]["normal_actions"])
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise AuthorizationError("P2_BOUNDARY_CORE_POLICY_UNOBSERVABLE") from exc
    if current_sid() != identities["core_sid"]:
        raise AuthorizationError("P2_BOUNDARY_WRONG_CORE_ACCOUNT")
    if Path(sys.executable).resolve(strict=False) != Path(
            identities["core_executable"]).resolve(strict=False):
        raise AuthorizationError("P2_BOUNDARY_CORE_IMAGE_MISMATCH")
    if not _is_isolated_python():
        raise AuthorizationError("P2_BOUNDARY_CORE_PYTHON_NOT_ISOLATED")
    trusted = {_SYSTEM, _ADMINS}
    core = identities["core_sid"]
    automator = identities["automation_sid"]
    approver = identities["approver_sid"]
    paths = [
        # pinned application and policy: core has read only, privileged owner.
        (policy_path, trusted),
        (policy_path.parent, trusted),
        (Path(identities["core_executable"]), trusted),
        (Path(identities["core_executable"]).parent, trusted),
        # state DB and journal: only isolated Core may modify.
        (state_path, trusted | {core}),
        (state_path.parent, trusted | {core}),
    ]
    paths.extend(
        (Path(str(state_path) + suffix), trusted | {core})
        for suffix in ("-wal", "-shm")
        if Path(str(state_path) + suffix).exists()
    )
    paths.extend((source, trusted) for source in _runtime_source_paths())
    forbidden = {automator, approver}
    for path, writers in paths:
        _reject_reparse_chain(path)
        if not path.exists():
            raise AuthorizationError("P2_BOUNDARY_PATH_MISSING_OR_REPARSE")
        validate_acl(inspect_dacl(path), writers=set(writers), forbidden=forbidden)


def require_issuer_boundary(section: dict[str, Any], *,
                            issuer_module: Path, issuer_key: Path) -> None:
    """Manual approver GUI must be launched under a separate real Windows SID."""
    identities = validate_identities(section)
    if current_sid() != identities["approver_sid"]:
        raise AuthorizationError("P2_BOUNDARY_WRONG_APPROVER_ACCOUNT")
    if not _is_isolated_python():
        raise AuthorizationError("P2_BOUNDARY_ISSUER_PYTHON_NOT_ISOLATED")
    if (issuer_module.resolve(strict=False)
            != Path(identities["issuer_executable"]).resolve(strict=False)
            or issuer_key.resolve(strict=False)
            != Path(identities["issuer_key_path"]).resolve(strict=False)):
        raise AuthorizationError("P2_BOUNDARY_ISSUER_LOCATION_MISMATCH")
    trusted = {_SYSTEM, _ADMINS}
    approver = identities["approver_sid"]
    for path, writers in [
        (issuer_module, trusted),
        (issuer_module.parent, trusted),
        (issuer_key.parent, trusted | {approver}),
    ]:
        _reject_reparse_chain(path)
        if not path.exists():
            raise AuthorizationError("P2_BOUNDARY_PATH_MISSING_OR_REPARSE")
        validate_acl(inspect_dacl(path), writers=set(writers),
                     forbidden={identities["automation_sid"], identities["core_sid"]})
    _reject_reparse_chain(issuer_key)
    if issuer_key.exists():
        validate_acl(inspect_dacl(issuer_key), writers=trusted | {approver},
                     forbidden={identities["automation_sid"], identities["core_sid"]})

def load_protected_issuer_manifest(path: Path) -> dict[str, Any]:
    """A manually provisioned system-owned manifest, never BCT's writable policy."""
    _reject_reparse_chain(path)
    if not path.is_file():
        raise AuthorizationError("P2_ISSUER_MANIFEST_NOT_PROVISIONED")
    writers = {_SYSTEM, _ADMINS}
    validate_acl(inspect_dacl(path), writers=writers, forbidden=set())
    validate_acl(inspect_dacl(path.parent), writers=writers, forbidden=set())
    try:
        return json.loads(path.read_text(encoding="utf8"))
    except (OSError, ValueError) as exc:
        raise AuthorizationError("P2_ISSUER_MANIFEST_INVALID") from exc
