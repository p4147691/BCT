"""Current-user Windows DPAPI envelope for bounded Bridge node message bytes."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

_MAX = 8192
_UI_FORBIDDEN = 0x1


class _Blob(ctypes.Structure):
    _fields_ = (("cbData",wintypes.DWORD),
                ("pbData",ctypes.POINTER(ctypes.c_byte)))


def _input(data):
    buf=(ctypes.c_byte*len(data)).from_buffer_copy(data)
    return _Blob(len(data),buf),buf


def _dpapi(data, context, *, encrypt):
    if os.name!="nt":
        raise RuntimeError("BRIDGE_DPAPI_WINDOWS_REQUIRED")
    if (not isinstance(data,bytes) or not 0<len(data)<=_MAX*2
            or not isinstance(context,bytes) or not 0<len(context)<=128):
        raise ValueError("BRIDGE_DPAPI_ARGUMENT_INVALID")
    crypt=ctypes.WinDLL("crypt32",use_last_error=True)
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    fn=crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    fn.restype=wintypes.BOOL
    # Signatures differ in their second arguments (description vs pointer).
    if encrypt:
        fn.argtypes=[ctypes.POINTER(_Blob),wintypes.LPCWSTR,ctypes.POINTER(_Blob),
                     wintypes.LPVOID,wintypes.LPVOID,wintypes.DWORD,ctypes.POINTER(_Blob)]
    else:
        fn.argtypes=[ctypes.POINTER(_Blob),ctypes.POINTER(wintypes.LPWSTR),ctypes.POINTER(_Blob),
                     wintypes.LPVOID,wintypes.LPVOID,wintypes.DWORD,ctypes.POINTER(_Blob)]
    kernel.LocalFree.argtypes=[wintypes.HLOCAL]
    kernel.LocalFree.restype=wintypes.HLOCAL
    value,_vbuf=_input(data)
    entropy,_ebuf=_input(context)
    out=_Blob()
    try:
        if encrypt:
            ok=fn(ctypes.byref(value),"BCT Browser Bridge node relay",
                  ctypes.byref(entropy),None,None,_UI_FORBIDDEN,ctypes.byref(out))
        else:
            ok=fn(ctypes.byref(value),None,ctypes.byref(entropy),
                  None,None,_UI_FORBIDDEN,ctypes.byref(out))
        if not ok or not out.pbData or not 0<out.cbData<=_MAX*2:
            raise RuntimeError("BRIDGE_DPAPI_OPERATION_DENIED")
        return ctypes.string_at(out.pbData,out.cbData)
    finally:
        if out.pbData:
            kernel.LocalFree(out.pbData)


class DpapiMessageCodec:
    def protect(self,plain,*,context):
        return _dpapi(plain,context,encrypt=True)

    def unprotect(self,protected,*,context):
        return _dpapi(protected,context,encrypt=False)
