"""ICMP ping tester — extracted from blockcheck2.py."""

from __future__ import annotations

import re
import subprocess

from blockcheck.config import PING_COUNT, PING_TIMEOUT
from blockcheck.models import SingleTestResult, TestStatus, TestType


def ping_host(
    host: str,
    count: int = PING_COUNT,
    timeout: int = PING_TIMEOUT,
) -> SingleTestResult:
    """Ping a host via subprocess (Windows ping.exe)."""
    try:
        cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), host]
        output = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout * count + 10,
            encoding="cp866",
        )
        text = output.stdout

        # Russian locale
        match = re.search(r"Среднее\s*=\s*(\d+)\s*мс", text)
        if match:
            ms = float(match.group(1))
            return SingleTestResult(
                target_name=host, test_type=TestType.PING,
                status=TestStatus.OK, time_ms=ms,
                detail=f"{ms:.0f}ms",
            )

        # English locale
        match = re.search(r"Average\s*=\s*(\d+)\s*ms", text, re.IGNORECASE)
        if match:
            ms = float(match.group(1))
            return SingleTestResult(
                target_name=host, test_type=TestType.PING,
                status=TestStatus.OK, time_ms=ms,
                detail=f"{ms:.0f}ms",
            )

        # Fallback: individual times (Russian)
        times = re.findall(r"время[=<](\d+)\s*мс", text)
        if times:
            ms = sum(int(t) for t in times) / len(times)
            return SingleTestResult(
                target_name=host, test_type=TestType.PING,
                status=TestStatus.OK, time_ms=ms,
                detail=f"{ms:.0f}ms",
            )

        # Fallback: individual times (English)
        times = re.findall(r"time[=<](\d+)\s*ms", text, re.IGNORECASE)
        if times:
            ms = sum(int(t) for t in times) / len(times)
            return SingleTestResult(
                target_name=host, test_type=TestType.PING,
                status=TestStatus.OK, time_ms=ms,
                detail=f"{ms:.0f}ms",
            )

        return SingleTestResult(
            target_name=host, test_type=TestType.PING,
            status=TestStatus.TIMEOUT, error_code="NO_REPLY",
            detail="Timeout",
        )
    except subprocess.TimeoutExpired:
        return SingleTestResult(
            target_name=host, test_type=TestType.PING,
            status=TestStatus.TIMEOUT, error_code="TIMEOUT",
            detail="Timeout",
        )
    except Exception as e:
        return SingleTestResult(
            target_name=host, test_type=TestType.PING,
            status=TestStatus.ERROR, error_code="ERROR",
            detail=str(e),
        )
