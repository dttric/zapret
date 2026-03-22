"""
Minimal winreg stub for non-Windows environments.

This project targets Windows, but some modules are imported in development
environments where the stdlib `winreg` module is unavailable (Linux/macOS).

On Windows, Python provides a native `winreg` module and it will be imported
instead of this file.
"""

from __future__ import annotations


class _NotSupportedOSError(OSError):
    pass


# Common constants used by the codebase.
HKEY_CURRENT_USER = 0x80000001
HKEY_LOCAL_MACHINE = 0x80000002

REG_SZ = 1
REG_DWORD = 4
REG_BINARY = 3

KEY_READ = 0x20019
KEY_SET_VALUE = 0x0002


def _raise() -> None:
    raise _NotSupportedOSError("winreg is not supported on this platform")


def OpenKey(*_a, **_kw):  # noqa: N802
    _raise()


def CreateKey(*_a, **_kw):  # noqa: N802
    _raise()


def CreateKeyEx(*_a, **_kw):  # noqa: N802
    _raise()


def QueryValueEx(*_a, **_kw):  # noqa: N802
    _raise()


def SetValueEx(*_a, **_kw):  # noqa: N802
    _raise()


def DeleteValue(*_a, **_kw):  # noqa: N802
    _raise()


def CloseKey(*_a, **_kw):  # noqa: N802
    return None

