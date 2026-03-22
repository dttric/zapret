from __future__ import annotations

from typing import Mapping, Any


def _normalize_process_details(details: Mapping[str, Any] | None) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    if not details:
        return out
    for k, v in dict(details).items():
        name = str(k or "").lower()
        if not name:
            continue
        if isinstance(v, list):
            pids = [pid for pid in v if isinstance(pid, int)]
            out[name] = pids
        elif isinstance(v, int):
            out[name] = [v]
        else:
            out[name] = []
    return out


def format_expected_process_status(expected_process: str, process_details: Mapping[str, Any] | None) -> str:
    """
    Формирует человекочитаемый статус ожидаемого процесса.

    Args:
        expected_process: "winws.exe" или "winws2.exe"
        process_details: {"winws.exe": [pid, ...], "winws2.exe": [pid, ...]} (keys case-insensitive)
    """
    expected = (expected_process or "").lower()
    details = _normalize_process_details(process_details)

    expected_pids = details.get(expected, [])
    if expected_pids:
        pid = expected_pids[0]
        extra = f", +{len(expected_pids) - 1}" if len(expected_pids) > 1 else ""
        return f"✅ {expected_process} (PID: {pid}{extra})"

    # If another winws* process is running, mention it explicitly to avoid confusion.
    others = []
    for name in ("winws.exe", "winws2.exe"):
        if name == expected:
            continue
        pids = details.get(name, [])
        if pids:
            pid = pids[0]
            extra = f", +{len(pids) - 1}" if len(pids) > 1 else ""
            others.append(f"{name} (PID: {pid}{extra})")

    if others:
        return f"⚠️ {expected_process} не запущен (запущен {', '.join(others)})"

    return f"⚫ {expected_process} не запущен"

