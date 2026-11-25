"""Human-approved file reads share the scoped implementation and receipts."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import stat

from bct.core.models import FeatureRequest, PreconditionError
from .common import is_reparse_point
from .files import FileReadFeature

_PROTECTED_NAMES = frozenset({
    "appdata", "programdata", "windows", "system volume information", "$recycle.bin",
    ".ssh", ".aws", ".azure", ".kube", ".gnupg", ".git", ".codex",
    ".docker", ".config", ".vscode", "credentials", "secrets", "passwords",
    "windows.old", "credential manager", "keychains", ".bct-recovery", "credential-recovery",
    "ntuser.dat", "sam", "security", "login data", "cookies", "local state",
    ".git-credentials", ".netrc", "_netrc", "auth.json", "credentials.json",
})
_PROTECTED_SUFFIXES = frozenset({".key", ".pem", ".pfx", ".p12", ".kdbx", ".rdp", ".db", ".sqlite", ".sqlite3"})
_PROTECTED_PATTERN = re.compile(
    r"^(?:\.env|auth|credentials?|secrets?|passwords?|tokens?|api[_-]?keys?"
    r"|id_(?:rsa|ed25519|ecdsa|dsa)|private[_-]?keys?)(?:[._-]|$)"
)


class DesktopReadFeature(FileReadFeature):
    capability = "desktop_read"

    def __init__(self, store=None, *, protected_roots=()):
        super().__init__(store)
        self.protected_roots = tuple(Path(root).resolve() for root in protected_roots)
        self.path_guard = self._guard

    def prepare(self, *, work, arguments):
        # A challenge or an unsigned request must not enumerate or stat even
        # a single path. Sign the exact arguments, then prepare after approval.
        if len(json.dumps(arguments, ensure_ascii=False).encode("utf-8")) > 6000:
            raise PreconditionError("READ_APPROVAL_ARGUMENTS_TOO_LARGE")
        return FeatureRequest(
            self.capability, "desktop-read:" + work.work_id,
            {"request": arguments, "work_id": work.work_id, "owner": work.owner_principal_id,
             "epoch": work.assignment_epoch}, ("desktop-read:" + work.work_id.casefold(),),
        )

    def execute(self, request):
        values = request.arguments
        if self.store is None:
            raise PreconditionError("READ_WORK_STORE_UNAVAILABLE")
        work = self.store.get_work(values["work_id"])
        if (work.owner_principal_id, work.assignment_epoch, work.state) != (values["owner"], values["epoch"], "ACTIVE"):
            raise PreconditionError("WORK_ASSIGNMENT_CHANGED")
        try:
            scoped = super().prepare(work=work, arguments=values["request"])
            return super().execute(scoped)
        except PermissionError as exc:
            raise PreconditionError("READ_ACCESS_DENIED") from exc
        except FileNotFoundError as exc:
            raise PreconditionError("TARGET_NOT_FOUND") from exc
        except UnicodeError as exc:
            raise PreconditionError("READ_TARGET_NOT_UTF8") from exc
        except OSError as exc:
            raise PreconditionError("READ_IO_FAILED") from exc

    def _resolve(self, work, value, *, must_exist):
        if not isinstance(value, str) or not value.strip():
            raise PreconditionError("TARGET_REQUIRED")
        path = Path(value)
        self._guard(path)
        # Keep the approved spelling. A junction introduced after the check
        # must never replace the signed path carried into execution.
        return path

    def _guard(self, path: Path, fd=None):
        if (not path.is_absolute() or ".." in path.parts
                or (os.name == "nt" and not re.fullmatch(r"[a-zA-Z]:\\", path.anchor))):
            raise PreconditionError("READ_LOCAL_ABSOLUTE_PATH_REQUIRED")
        if os.name == "nt":
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(path.anchor)
            if drive_type not in {2, 3, 5, 6}:
                raise PreconditionError("READ_LOCAL_DRIVE_REQUIRED")
        for part in path.parts[1:]:
            if ":" in part or part != part.rstrip(" .") or "~" in part or path.is_reserved():
                raise PreconditionError("READ_LOCAL_PATH_UNSUPPORTED")
            name = part.casefold()
            if name in _PROTECTED_NAMES or Path(name).suffix in _PROTECTED_SUFFIXES or _PROTECTED_PATTERN.match(name):
                raise PreconditionError("READ_PROTECTED_FILE")
        if any(path.is_relative_to(root) for root in self.protected_roots):
            raise PreconditionError("READ_PROTECTED_FILE")
        try:
            if any(is_reparse_point(entry) for entry in (*path.parents, path)):
                raise PreconditionError("READ_REPARSE_POINT_FORBIDDEN")
            metadata = path.stat()
        except FileNotFoundError as exc:
            raise PreconditionError("TARGET_NOT_FOUND") from exc
        except PermissionError as exc:
            raise PreconditionError("READ_ACCESS_DENIED") from exc
        if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
            raise PreconditionError("READ_LOCAL_PATH_UNSUPPORTED")
        if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1:
            raise PreconditionError("READ_PROTECTED_FILE")
        if fd is not None:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)):
                raise PreconditionError("READ_TARGET_CHANGED")
            if os.name == "nt":
                import msvcrt

                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                final_path = kernel.GetFinalPathNameByHandleW
                final_path.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
                final_path.restype = ctypes.c_uint32
                buffer = ctypes.create_unicode_buffer(32768)
                size = final_path(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
                prefix = "\\\\?\\"
                if not 0 < size < len(buffer) or not buffer.value.startswith(prefix):
                    raise PreconditionError("READ_TARGET_CHANGED")
                if Path(buffer.value[len(prefix):]) != path:
                    raise PreconditionError("READ_TARGET_CHANGED")

