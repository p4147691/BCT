from __future__ import annotations

"""Explicit Git authority mode; no remote or deploy side effects."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from bct.core.models import PreconditionError


@dataclass(frozen=True)
class GitAuthority:
    mode: str = "github"
    source_root: Path | None = None
    repository: str = ""


SYNC_IN_SYNC = "IN_SYNC"
SYNC_PENDING = "SYNC_PENDING"
SYNC_CONFLICT = "SYNC_CONFLICT"


def classify_publish_sync(*, local_sha: str, remote_sha: str | None,
                          expected_remote_sha: str | None) -> str:
    """Classify an observed publish boundary without changing either ref."""
    if remote_sha == local_sha:
        return SYNC_IN_SYNC
    if remote_sha == expected_remote_sha:
        return SYNC_PENDING
    return SYNC_CONFLICT


def read_git_authority(policy_path: str | Path | None) -> GitAuthority:
    if policy_path is None:
        return GitAuthority()
    try:
        data = tomllib.loads(Path(policy_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PreconditionError("GIT_AUTHORITY_POLICY_UNREADABLE") from exc
    config = data.get("git_authority", {})
    if not isinstance(config, dict):
        raise PreconditionError("GIT_AUTHORITY_INVALID")
    mode = config.get("mode", "github")
    if mode not in {"github", "local"}:
        raise PreconditionError("GIT_AUTHORITY_MODE_INVALID")
    if mode == "github":
        return GitAuthority()
    repository = config.get("repository")
    raw_root = config.get("source_root")
    if (not isinstance(repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or not isinstance(raw_root, str) or not raw_root.strip()):
        raise PreconditionError("GIT_AUTHORITY_LOCAL_SETTINGS_REQUIRED")
    root = Path(raw_root)
    # The versioned policy is also parsed on non-Windows CI runners where the
    # operator's canonical source path does not exist.  Validate the configured
    # identity here, then require the real directory at the mutation boundary.
    configured_absolute = root.is_absolute() or PureWindowsPath(raw_root).is_absolute()
    if not configured_absolute or (root.exists() and root.is_symlink()):
        raise PreconditionError("GIT_AUTHORITY_SOURCE_ROOT_INVALID")
    normalized = root.resolve(strict=False) if root.is_absolute() else root
    return GitAuthority(mode="local", source_root=normalized, repository=repository)


def require_local_main(policy_path: str | Path | None, root: Path) -> GitAuthority:
    authority = read_git_authority(policy_path)
    if authority.mode != "local":
        raise PreconditionError("LOCAL_MAIN_AUTHORITY_NOT_ENABLED")
    if (authority.source_root is None or not authority.source_root.is_dir()
            or authority.source_root.is_symlink()):
        raise PreconditionError("GIT_AUTHORITY_SOURCE_ROOT_UNAVAILABLE")
    if authority.source_root != root.resolve():
        raise PreconditionError("LOCAL_MAIN_SOURCE_ROOT_MISMATCH")
    return authority
