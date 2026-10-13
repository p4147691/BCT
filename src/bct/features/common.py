from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from bct.core.models import PreconditionError, Work


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_in_work(work: Work, value: str, *, must_exist: bool) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise PreconditionError("TARGET_REQUIRED")
    target = Path(value).resolve(strict=False)
    roots = [Path(root).resolve(strict=True) for root in work.roots]
    root = next((item for item in roots if target == item or target.is_relative_to(item)), None)
    if root is None:
        raise PreconditionError("TARGET_OUTSIDE_WORK_SCOPE")
    if must_exist and not target.exists():
        raise PreconditionError("TARGET_NOT_FOUND")
    _reject_reparse(root, target)
    return target


def _reject_reparse(root: Path, target: Path) -> None:
    current = root
    relative = target.relative_to(root)
    paths = [root]
    for part in relative.parts:
        current = current / part
        paths.append(current)
    for path in paths:
        if is_reparse_point(path):
            raise PreconditionError("REPARSE_POINT_FORBIDDEN:" + str(path))


def is_reparse_point(path: Path) -> bool:
    """Return whether *path* must not be followed during a scoped file operation."""
    if not path.exists() and not path.is_symlink():
        return False
    info = os.lstat(path)
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(
        stat.S_ISLNK(info.st_mode)
        or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def relative_git_path(root: Path, target: Path) -> str:
    try:
        return target.relative_to(root).as_posix()
    except ValueError as exc:
        raise PreconditionError("PATH_OUTSIDE_REPOSITORY") from exc

