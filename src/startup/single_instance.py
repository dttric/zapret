# single_instance.py

import ctypes

ERROR_ALREADY_EXISTS = 183
_kernel32 = ctypes.windll.kernel32

def create_mutex(name: str):
    """
    Пытаемся создать именованный mutex.
    Возвращает (handle, already_running: bool)
    """
    _kernel32.SetLastError(0)
    handle = _kernel32.CreateMutexW(None, False, name)
    last_error = _kernel32.GetLastError()
    already_running = last_error == ERROR_ALREADY_EXISTS

    if not handle:
        return None, False

    return handle, already_running

def release_mutex(handle):
    if handle:
        _kernel32.ReleaseMutex(handle)
        _kernel32.CloseHandle(handle)
