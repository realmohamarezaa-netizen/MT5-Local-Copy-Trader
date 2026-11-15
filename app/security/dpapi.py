"""Windows DPAPI encryption for sensitive values (broker passwords).

Uses CryptProtectData / CryptUnprotectData from crypt32.dll via ctypes.
No plaintext secrets are ever written to disk; blobs are stored base64 in
the local SQLite database and can only be decrypted by the same Windows
user on the same machine.

On non-Windows systems the functions raise RuntimeError (dev environments).
"""
from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes


class DpapiError(RuntimeError):
    pass


def _require_windows() -> None:
    if sys.platform != "win32":
        raise DpapiError("DPAPI is only available on Windows")


def protect_bytes(data: bytes) -> bytes:
    """Encrypt bytes with the current Windows user scope."""
    _require_windows()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()

    ok = crypt32.CryptProtectData(
        ctypes.byref(blob_in),        # pDataIn
        "TradingCopier",              # szDataDescr
        None, None, None,             # optional entropy / prompt
        0,                            # flags: user scope (no CRYPTPROTECT_LOCAL_MACHINE)
        ctypes.byref(blob_out),       # pDataOut
    )
    if not ok:
        raise DpapiError(f"CryptProtectData failed: {kernel32.GetLastError()}")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def unprotect_bytes(blob: bytes) -> bytes:
    _require_windows()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(blob, len(blob))
    blob_in = DATA_BLOB(len(blob), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, 0, ctypes.byref(blob_out)
    )
    if not ok:
        raise DpapiError(f"CryptUnprotectData failed: {kernel32.GetLastError()}")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def protect_to_str(data: bytes) -> str:
    return base64.b64encode(protect_bytes(data)).decode("ascii")


def unprotect_from_str(value: str) -> bytes:
    return unprotect_bytes(base64.b64decode(value.encode("ascii")))
