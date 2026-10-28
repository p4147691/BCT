"""Independent interactive approval issuer for BCT P2 (never an MCP capability).

The encrypted Ed25519 key is created by a user interacting with the Windows
GUI, outside BCT repository/runtime. Every grant requires manual passphrase,
explicit target inspection and confirmation. No signing command-line flags.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

AUD = "bct-p2-action-v1"
CAPABILITIES = frozenset({"file_action_apply", "process_stop_apply"})
REQUIRED = frozenset({
    "principal_id", "work_id", "operation_id",
    "capability", "target", "request_sha256", "arguments", "preconditions",
})


def _b64(binary: bytes) -> str:
    return base64.urlsafe_b64encode(binary).decode("ascii").rstrip("=")


def _unb64(encoded: str) -> bytes:
    if not isinstance(encoded, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", encoded):
        raise ValueError("ISSUER_BASE64_INVALID")
    return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))


def default_identity_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if os.name != "nt" or not local_app_data:
        raise RuntimeError("ISSUER_REQUIRES_INTERACTIVE_WINDOWS_USER")
    return Path(local_app_data) / "BCTApprovalIssuer" / "identity-v1.json"


def validate_challenge(challenge: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(challenge, dict) or set(challenge) != REQUIRED:
        raise ValueError("ISSUER_CHALLENGE_FIELDS_INVALID")
    result: dict[str, Any] = {}
    for key in sorted(REQUIRED - {"arguments", "preconditions"}):
        value = challenge[key]
        if not isinstance(value, str) or not value or len(value) > 1024:
            raise ValueError("ISSUER_CHALLENGE_VALUE_INVALID:" + key)
        if "\0" in value or any(ord(ch) < 32 for ch in value):
            raise ValueError("ISSUER_CHALLENGE_CONTROL_CHARACTER")
        result[key] = value
    if result["capability"] not in CAPABILITIES:
        raise ValueError("ISSUER_CAPABILITY_NOT_SUPPORTED")
    if not re.fullmatch(r"[0-9a-f]{64}", result["request_sha256"]):
        raise ValueError("ISSUER_REQUEST_DIGEST_INVALID")
    for key in ("arguments", "preconditions"):
        if not isinstance(challenge[key], dict):
            raise ValueError("ISSUER_CHALLENGE_REQUEST_INVALID")
        result[key] = challenge[key]
    from bct.core.approval import request_hash
    expected = request_hash(
        result["work_id"], result["capability"], result["target"],
        result["arguments"], result["preconditions"],
    )
    if expected != result["request_sha256"]:
        raise ValueError("ISSUER_CHALLENGE_REQUEST_MISMATCH")
    return result


def challenge_display(challenge: dict[str, Any]) -> str:
    value = validate_challenge(challenge)
    # The user must see all source/destination or PID/mode details.
    details = json.dumps({"arguments": value["arguments"],
                          "preconditions": value["preconditions"]},
                         ensure_ascii=False, indent=2, sort_keys=True)
    details_friendly = []
    args = value["arguments"]
    if value["capability"] == "file_action_apply":
        for key, label in (
            ("operation", "파일 작업"),
            ("source", "원본 경로"),
            ("destination", "이동·복원 대상"),
        ):
            details_friendly.append(label + ": " + str(args.get(key, "")))
    else:
        for key, label in (
            ("session_id", "소유 작업 세션"),
            ("pid", "프로세스 PID"),
            ("mode", "종료 방식"),
        ):
            field = args.get("expected_identity", {}).get("pid") if key == "pid" else args.get(key, "")
            details_friendly.append(label + ": " + str(field))
        identity = args.get("expected_identity", {})
        details_friendly.append("실행 파일: " + str(identity.get("executable", "")))
    lines = [
        "BCT P2 사용자 승인 요청",
        "",
        "아래 내용과 요청한 작업을 직접 비교하세요.",
        "표시된 작업 외에는 승인하지 마세요.",
        "",
        "작업 종류: " + value["capability"],
        "사용자/주체: " + value["principal_id"],
        "작업(Work): " + value["work_id"],
        "1회 실행(Operation): " + value["operation_id"],
        "정확한 대상: " + value["target"],
        "요청 SHA-256: " + value["request_sha256"],
        "",
        *details_friendly,
        "",
        "실제 대상·원본/이동 위치·종료 모드(전문):",
        details,
        "",
        "승인 유효기간: 2분 / 사용 횟수: 1회",
        "이 화면의 승인으로 파일·프로세스 효과가 발생할 수 있습니다.",
    ]
    return "\n".join(lines)


def _reject_key_reparse(path: Path) -> None:
    """Fail closed on Windows junctions or symlinks around the signer key."""
    for candidate in (path, *path.parents):
        try:
            info = os.lstat(candidate)
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("ISSUER_KEY_REPARSE_FORBIDDEN")


class IssuerKeyStore:
    """Password-encrypted, create-once Ed25519 key. Never expose raw key."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @staticmethod
    def _derive(secret: str, salt: bytes, cost: int) -> bytes:
        if not isinstance(secret, str) or len(secret) < 16:
            raise ValueError("ISSUER_PASSPHRASE_MIN_16")
        return Scrypt(salt=salt, length=32, n=cost, r=8, p=1).derive(secret.encode("utf8"))

    def initialize(self, secret: str) -> str:
        _reject_key_reparse(self.path)
        if self.path.exists():
            raise FileExistsError("ISSUER_KEY_ALREADY_EXISTS")
        if not self.path.parent.is_dir():
            self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        _reject_key_reparse(self.path)
        key = Ed25519PrivateKey.generate()
        private_bytes = key.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        public_bytes = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )
        salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
        cost = 1 << 15
        encrypted = AESGCM(self._derive(secret, salt, cost)).encrypt(
            nonce, private_bytes, b"BCT-P2-ISSUER-KEY-v1",
        )
        body = {
            "format": "BCT_P2_ENCRYPTED_ED25519_V1",
            "public_key": _b64(public_bytes),
            "kdf": "scrypt", "kdf_n": cost,
            "salt": _b64(salt), "nonce": _b64(nonce),
            "ciphertext": _b64(encrypted),
        }
        payload = (json.dumps(body, sort_keys=True, indent=2) + "\n").encode("utf8")
        # O_EXCL means we never overwrite or reset a previously enrolled key.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            # No replacement: a failed enrollment must be manually investigated.
            raise
        return body["public_key"]

    def public_key(self) -> str:
        body = self._read()
        return body["public_key"]

    def _read(self) -> dict[str, Any]:
        _reject_key_reparse(self.path)
        if not self.path.is_file():
            raise ValueError("ISSUER_KEY_NOT_A_REGULAR_FILE")
        body = json.loads(self.path.read_text(encoding="utf8"))
        if (not isinstance(body, dict)
                or set(body) != {"format", "public_key", "kdf", "kdf_n",
                                "salt", "nonce", "ciphertext"}
                or body["format"] != "BCT_P2_ENCRYPTED_ED25519_V1"
                or body["kdf"] != "scrypt"
                or type(body["kdf_n"]) is not int
                or not (1 << 15) <= body["kdf_n"] <= (1 << 18)):
            raise ValueError("ISSUER_KEY_FORMAT_INVALID")
        return body

    def load(self, secret: str) -> Ed25519PrivateKey:
        body = self._read()
        try:
            key = self._derive(secret, _unb64(body["salt"]), body["kdf_n"])
            raw = AESGCM(key).decrypt(
                _unb64(body["nonce"]), _unb64(body["ciphertext"]),
                b"BCT-P2-ISSUER-KEY-v1",
            )
            private = Ed25519PrivateKey.from_private_bytes(raw)
            observed_public = _b64(private.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw,
            ))
            if observed_public != body["public_key"]:
                raise ValueError("ISSUER_KEY_PUBLIC_MISMATCH")
            return private
        except (InvalidTag, ValueError, TypeError) as exc:
            raise ValueError("ISSUER_PASSPHRASE_OR_KEY_INVALID") from exc


def issue_after_human_confirmation(
    challenge: dict[str, Any], store: IssuerKeyStore, secret: str,
    *, confirmed: bool, now: float | None = None,
) -> str | None:
    """Sign only after interactive approval. No grant on denial.

    This is an internal primitive, not an API endpoint, CLI, or BCT tool.
    The GUI does not expose a 'confirmed' argument to its user.
    """
    fields = validate_challenge(challenge)
    if confirmed is not True:
        return None
    issued = time.time() if now is None else float(now)
    public_fields = {key: fields[key] for key in (
        "principal_id", "work_id", "operation_id",
        "capability", "target", "request_sha256",
    )}
    claims: dict[str, Any] = {
        "aud": AUD, "user_confirmed": True,
        **public_fields, "issued_at": issued,
        "expires_at": issued + 120,
        "nonce": secrets.token_hex(16),
    }
    payload = json.dumps(claims, sort_keys=True,
                         separators=(",", ":")).encode("utf8")
    private = store.load(secret)
    return _b64(payload) + "." + _b64(private.sign(payload))


def _launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk

    # An independent, Admin-owned installed executable and manifest are
    # required. Running this source module from a writable BCT worktree,
    # or under the automation/Core SID, is not an acceptable signer.
    from bct.core.approval_boundary import (
        load_protected_issuer_manifest, require_issuer_boundary,
    )
    manifest_path = Path(os.environ.get(
        "PROGRAMFILES", r"C:\\Program Files"
    )) / "BCTApprovalIssuer" / "boundary-v1.json"
    boundary = load_protected_issuer_manifest(manifest_path)
    path = default_identity_path()
    require_issuer_boundary(boundary, issuer_module=Path(__file__),
                            issuer_key=path)
    store = IssuerKeyStore(path)
    root = tk.Tk()
    root.title("BCT — 독립 사용자 승인")
    root.geometry("840x600")
    root.minsize(690, 460)
    root.attributes("-topmost", True)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(2, weight=1)

    status = tk.StringVar(value="사용자가 직접 선택한 승인 요청 파일만 읽습니다.")
    ttk.Label(root, text="BCT P2 — 파일·프로세스 변경 사용자 승인",
              font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w", padx=16, pady=10)
    ttk.Label(root, textvariable=status, wraplength=800).grid(
        row=1, column=0, sticky="w", padx=16, pady=6)
    box = tk.Text(root, wrap="word", height=20, width=85, state="disabled")
    box.grid(row=2, column=0, padx=16, pady=6, sticky="nsew")
    btns = ttk.Frame(root)
    btns.grid(row=3, column=0, sticky="ew", padx=16, pady=12)
    selected: dict[str, str] | None = None

    def show(value: str):
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", value)
        box.configure(state="disabled")

    def initialize():
        if store.path.exists():
            messagebox.showwarning("키 존재", "이미 발급 키가 있습니다. 덮어쓰지 않습니다.", parent=root)
            return
        if not messagebox.askyesno("개인키 최초 생성",
                                   "새 사용자 승인 개인키를 생성하시겠습니까?", parent=root):
            return
        first = simpledialog.askstring("키 암호 설정", "16자 이상 암호 문구를 입력하세요.",
                                        show="*", parent=root)
        if first is None:
            return
        second = simpledialog.askstring("암호 확인", "동일한 암호 문구를 다시 입력하세요.",
                                         show="*", parent=root)
        if first != second:
            messagebox.showerror("암호 불일치", "암호 문구가 일치하지 않습니다.", parent=root)
            return
        try:
            store.initialize(first)
        except Exception as exc:
            messagebox.showerror("키 생성 실패", str(exc), parent=root)
            return
        status.set("개인키 암호화 저장 완료. 공개키는 감독관이 별도 검증 후 등록해야 합니다.")
        show("공개키 (BCT 정책에 수동으로 등록할 값):\n" + store.public_key())

    def load_request():
        nonlocal selected
        selected = None
        filename = filedialog.askopenfilename(parent=root, title="승인 요청 JSON 선택",
                                              filetypes=[("JSON", "*.json")])
        if not filename:
            status.set("요청 선택 취소 — 승인 없음")
            return
        try:
            data = Path(filename).read_bytes()
            if len(data) > 8192:
                raise ValueError("ISSUER_REQUEST_FILE_TOO_LARGE")
            fields = validate_challenge(json.loads(data.decode("utf8")))
            selected = fields
            show(challenge_display(fields))
            status.set("대상과 작업을 직접 읽은 뒤 승인 또는 거부를 선택하세요.")
        except Exception as exc:
            show("")
            status.set("승인 요청 거부: " + str(exc))

    def deny():
        nonlocal selected
        selected = None
        show("거부됨 — 승인 토큰이 발급되지 않았습니다.")
        status.set("사용자 거부: 작업 승인 없음")

    def approve():
        nonlocal selected
        if selected is None:
            messagebox.showwarning("요청 없음", "승인 요청 파일부터 선택하세요.", parent=root)
            return
        fields = selected
        # No CLI, IPC, HTTP or automatic signing path is provided.
        typed = simpledialog.askstring("작업 확인",
            "작업 ID(Operation)를 화면의 내용과 똑같이 직접 입력하세요.",
            parent=root)
        if typed != fields["operation_id"]:
            status.set("작업 ID 불일치 — 승인 없음")
            return
        secret = simpledialog.askstring("개인키 암호", "승인 개인키 암호 문구를 입력하세요.",
                                        show="*", parent=root)
        if secret is None:
            return
        if not messagebox.askyesno(
            "최종 사용자 승인",
            "표시된 대상에 실제 파일 이동 또는 프로세스 종료 효과를 승인합니까?\n"
            "한 번 승인하면 되돌릴 수 없는 효과가 발생할 수 있습니다.",
            parent=root,
        ):
            deny()
            return
        try:
            grant = issue_after_human_confirmation(fields, store, secret, confirmed=True)
        except Exception as exc:
            status.set("서명 거부: " + str(exc))
            return
        path = filedialog.asksaveasfilename(
            parent=root, title="1회용 승인 토큰 저장",
            defaultextension=".approval",
            filetypes=[("BCT 승인 토큰", "*.approval")],
        )
        if not path:
            deny()
            return
        destination = Path(path)
        try:
            with destination.open("x", encoding="ascii") as out:
                out.write(grant + "\n")
        except (FileExistsError, OSError) as exc:
            status.set("파일 저장 실패 (덮어쓰기 금지): " + str(exc))
            return
        selected = None
        show("서명 승인 토큰 저장 완료.\n" + str(destination)
             + "\n유효기간 2분, 1회 사용, BCT 작업 ID·대상·요청 해시에 고정.")
        status.set("서명 완료 — 같은 요청을 다시 승인하지 마세요.")

    ttk.Button(btns, text="처음 키 만들기", command=initialize).pack(side="left", padx=5)
    ttk.Button(btns, text="요청 파일 열기", command=load_request).pack(side="left", padx=5)
    ttk.Button(btns, text="승인하고 서명", command=approve).pack(side="left", padx=5)
    ttk.Button(btns, text="거부", command=deny).pack(side="left", padx=5)
    ttk.Button(btns, text="닫기", command=root.destroy).pack(side="right", padx=5)
    root.mainloop()


def main() -> None:
    # No '--approve', '--sign', '--secret', or other automation entrypoints.
    if len(sys.argv) != 1:
        raise SystemExit("ISSUER_GUI_ONLY_NO_AUTOMATION_ARGUMENTS")
    _launch_gui()


if __name__ == "__main__":
    main()
