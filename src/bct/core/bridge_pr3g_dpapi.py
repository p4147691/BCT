"""PR3-g: Windows DPAPI byte codec for a future Bridge-only secret store.

This module does not choose a persistent location, create credentials, or
start IPC.  It only protects an in-memory 32-byte value with caller-supplied,
non-secret binding context.  A future storage provider remains opt-in.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


_UI_FORBIDDEN = 0x1
_MAX_BLOB = 64 * 1024


class _DataBlob(ctypes.Structure):
    _fields_ = (("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte)))


def _valid_context(context: object) -> bool:
    return isinstance(context, bytes) and 1 <= len(context) <= 1024


def _blob(value: bytes):
    buffer = (ctypes.c_byte * len(value)).from_buffer_copy(value)
    return _DataBlob(len(value), buffer), buffer


def _api():
    if os.name != "nt":
        raise RuntimeError("DPAPI_UNAVAILABLE")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = (
        ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
        wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(_DataBlob))
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = (
        ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_DataBlob),
        wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(_DataBlob))
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL
    return crypt32, kernel32


def _copy_and_free(kernel32, value: _DataBlob) -> bytes:
    try:
        if not value.pbData or not 0 < value.cbData <= _MAX_BLOB:
            raise RuntimeError("DPAPI_DENIED")
        return ctypes.string_at(value.pbData, value.cbData)
    finally:
        if value.pbData:
            kernel32.LocalFree(value.pbData)


def protect(secret: bytes, *, context: bytes) -> bytes:
    """Protect exactly one Bridge secret without UI or a persistent side effect."""
    if not isinstance(secret, bytes) or len(secret) != 32 or not _valid_context(context):
        raise ValueError("DPAPI_ARGUMENT_INVALID")
    crypt32, kernel32 = _api()
    plain, _plain_buffer = _blob(secret)
    entropy, _entropy_buffer = _blob(context)
    encrypted = _DataBlob()
    if not crypt32.CryptProtectData(ctypes.byref(plain), "BCT Browser Bridge",
                                    ctypes.byref(entropy), None, None, _UI_FORBIDDEN,
                                    ctypes.byref(encrypted)):
        if encrypted.pbData:
            kernel32.LocalFree(encrypted.pbData)
        raise RuntimeError("DPAPI_DENIED")
    return _copy_and_free(kernel32, encrypted)


def unprotect(protected: bytes, *, context: bytes) -> bytes:
    """Unprotect one Bridge secret; malformed or wrong-context blobs fail closed."""
    if (not isinstance(protected, bytes) or not 0 < len(protected) <= _MAX_BLOB
            or not _valid_context(context)):
        raise ValueError("DPAPI_ARGUMENT_INVALID")
    crypt32, kernel32 = _api()
    encrypted, _encrypted_buffer = _blob(protected)
    entropy, _entropy_buffer = _blob(context)
    plain = _DataBlob()
    if not crypt32.CryptUnprotectData(ctypes.byref(encrypted), None, ctypes.byref(entropy),
                                      None, None, _UI_FORBIDDEN, ctypes.byref(plain)):
        # The API normally leaves no output on failure, but defensively free
        # any reported allocation before returning the generic denial.
        if plain.pbData:
            kernel32.LocalFree(plain.pbData)
        raise RuntimeError("DPAPI_DENIED")
    result = _copy_and_free(kernel32, plain)
    if len(result) != 32:
        raise RuntimeError("DPAPI_DENIED")
    return result
