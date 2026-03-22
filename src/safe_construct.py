"""safe_construct.py

Work around a rare constructor crash:

    TypeError: __init__() should return None, not 'X'

In a normal CPython runtime this error means a buggy __init__ that returned a
value. In some frozen/compiled builds (observed in this project) the same
TypeError can be raised even for well-behaved classes (stdlib, PyQt, etc.).

To keep the app functional, we retry construction by calling __new__ + __init__
manually and ignoring the __init__ return value (bypassing the interpreter
check that triggers the error).

The fallback is only activated for the specific "__init__() should return None"
TypeError message.
"""

from __future__ import annotations

from typing import Any, TypeVar, cast


T = TypeVar("T")


_BROKEN_CTORS: set[type[Any]] = set()


def _looks_like_init_return_bug(exc: TypeError) -> bool:
    return "__init__() should return None" in str(exc)


def _construct_without_init_return_check(cls: type[T], *args: Any, **kwargs: Any) -> T:
    """Constructs an instance without relying on type.__call__ return checking."""

    # Some types accept args in __new__, others don't; try the most faithful
    # call first, then fall back to a bare __new__.
    try:
        obj = cls.__new__(cls, *args, **kwargs)  # type: ignore[misc]
    except TypeError:
        obj = cls.__new__(cls)  # type: ignore[misc]

    # Mirror type.__call__: if __new__ returns a different type, do not call __init__.
    if not isinstance(obj, cls):
        return cast(T, obj)

    # Manually call __init__ and ignore its return value.
    cls.__init__(obj, *args, **kwargs)  # type: ignore[misc]
    return cast(T, obj)


def safe_construct(cls: type[T], *args: Any, **kwargs: Any) -> T:
    """Calls cls(*args, **kwargs) with a targeted fallback for the init-return bug."""

    if cls in _BROKEN_CTORS:
        return _construct_without_init_return_check(cls, *args, **kwargs)

    try:
        return cls(*args, **kwargs)
    except TypeError as exc:
        if not _looks_like_init_return_bug(exc):
            raise

        _BROKEN_CTORS.add(cls)
        return _construct_without_init_return_check(cls, *args, **kwargs)
