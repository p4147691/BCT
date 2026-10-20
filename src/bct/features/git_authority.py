from __future__ import annotations

"""Explicit Git authority mode; no remote or deploy side effects."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from bct.core.models import PreconditionError


@dataclass(frozen=True)
class GitAuthority:
    mode: str = "github"
    source_root: Path | None = None
    repository: str = ""


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
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise PreconditionError("GIT_AUTHORITY_SOURCE_ROOT_INVALID")
    return GitAuthority(mode="local", source_root=root.resolve(), repository=repository)


def require_local_main(policy_path: str | Path | None, root: Path) -> GitAuthority:
    authority = read_git_authority(policy_path)
    if authority.mode != "local":
        raise PreconditionError("LOCAL_MAIN_AUTHORITY_NOT_ENABLED")
    if authority.source_root != root.resolve():
        raise PreconditionError("LOCAL_MAIN_SOURCE_ROOT_MISMATCH")
    return authority
