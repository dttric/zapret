"""TCP 16-20KB block detection — tests for DPI that drops connections at specific byte counts."""

from __future__ import annotations

import logging
import time

from blockcheck.config import (
    TCP_16_20_RETRIES,
    TCP_16_20_TIMEOUT,
    TCP_BLOCK_RANGE_MAX,
    TCP_BLOCK_RANGE_MIN,
)
from blockcheck.models import SingleTestResult, TestStatus, TestType

logger = logging.getLogger(__name__)


def probe_tcp_target_health(url: str, timeout: int = 4) -> tuple[bool, str, float]:
    """Lightweight reachability probe for TCP 16-20KB target URL.

    Returns:
        (is_healthy, detail, elapsed_ms)
    """
    start = time.time()

    try:
        import httpx
    except ImportError:
        # If httpx is unavailable, do not block target usage.
        return True, "httpx unavailable", 0.0

    try:
        with httpx.Client(
            timeout=timeout,
            verify=True,
            follow_redirects=True,
            max_redirects=4,
        ) as client:
            headers = {"User-Agent": "Mozilla/5.0", "Range": "bytes=0-1023"}

            response = client.head(url, headers=headers)
            if response.status_code in (405, 501):
                with client.stream("GET", url, headers=headers) as streamed:
                    for _ in streamed.iter_bytes(chunk_size=512):
                        break
                    response = streamed

            elapsed = (time.time() - start) * 1000
            code = int(response.status_code)

            # Treat 2xx/3xx and common protected responses as reachable.
            healthy = (200 <= code < 400) or code in (401, 403, 404)
            return healthy, f"HTTP {code}", round(elapsed, 2)

    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return False, str(e)[:100], round(elapsed, 2)


def check_tcp_16_20_single(
    url: str,
    timeout: int = TCP_16_20_TIMEOUT,
) -> SingleTestResult:
    """Single TCP 16-20KB test — download and check if connection drops in the 16-20KB range.

    Some DPI systems reset TCP connections after receiving 16-20KB of data.
    This test downloads content and checks if the transfer stops in that range.
    """
    start = time.time()

    try:
        import httpx
    except ImportError:
        return SingleTestResult(
            target_name=url, test_type=TestType.TCP_16_20,
            status=TestStatus.ERROR, error_code="NO_HTTPX",
            detail="httpx not installed",
        )

    bytes_received = 0

    try:
        with httpx.Client(
            timeout=timeout,
            verify=True,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            with client.stream("GET", url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*",
            }) as resp:
                for chunk in resp.iter_bytes(chunk_size=1024):
                    bytes_received += len(chunk)
                    # We only need to check up to 25KB
                    if bytes_received > 25_000:
                        break

        elapsed = (time.time() - start) * 1000

        if bytes_received > TCP_BLOCK_RANGE_MAX:
            return SingleTestResult(
                target_name=url, test_type=TestType.TCP_16_20,
                status=TestStatus.OK, time_ms=round(elapsed, 2),
                detail=f"Received {bytes_received}B (no 16-20KB block)",
                raw_data={"bytes_received": bytes_received},
            )
        elif TCP_BLOCK_RANGE_MIN <= bytes_received <= TCP_BLOCK_RANGE_MAX:
            return SingleTestResult(
                target_name=url, test_type=TestType.TCP_16_20,
                status=TestStatus.FAIL, error_code="TCP_16_20",
                time_ms=round(elapsed, 2),
                detail=f"Connection dropped at {bytes_received}B (16-20KB range)",
                raw_data={"bytes_received": bytes_received},
            )
        else:
            return SingleTestResult(
                target_name=url, test_type=TestType.TCP_16_20,
                status=TestStatus.OK, time_ms=round(elapsed, 2),
                detail=f"Received {bytes_received}B",
                raw_data={"bytes_received": bytes_received},
            )

    except Exception as e:
        elapsed = (time.time() - start) * 1000
        error_msg = str(e).lower()

        # Check if the connection was reset in the 16-20KB range
        if bytes_received > 0 and TCP_BLOCK_RANGE_MIN <= bytes_received <= TCP_BLOCK_RANGE_MAX:
            if "reset" in error_msg or "aborted" in error_msg:
                return SingleTestResult(
                    target_name=url, test_type=TestType.TCP_16_20,
                    status=TestStatus.FAIL, error_code="TCP_16_20",
                    time_ms=round(elapsed, 2),
                    detail=f"RST at {bytes_received}B (16-20KB DPI block)",
                    raw_data={"bytes_received": bytes_received, "error": str(e)[:80]},
                )

        return SingleTestResult(
            target_name=url, test_type=TestType.TCP_16_20,
            status=TestStatus.ERROR, error_code="TCP_ERR",
            time_ms=round(elapsed, 2),
            detail=f"{str(e)[:80]} ({bytes_received}B received)",
            raw_data={"bytes_received": bytes_received},
        )


def check_tcp_16_20(
    url: str,
    retries: int = TCP_16_20_RETRIES,
    timeout: int = TCP_16_20_TIMEOUT,
) -> SingleTestResult:
    """TCP 16-20KB test with retries and variance detection.

    Multiple attempts help distinguish real DPI from transient network issues.
    If the connection consistently drops in the 16-20KB range, it's DPI.
    """
    results: list[SingleTestResult] = []

    for attempt in range(retries):
        result = check_tcp_16_20_single(url, timeout)
        results.append(result)

        # If we got a clear OK with >20KB, no need to retry
        if result.status == TestStatus.OK and result.raw_data.get("bytes_received", 0) > TCP_BLOCK_RANGE_MAX:
            return result

    # Analyze results — check for consistent 16-20KB failures
    fail_16_20 = [r for r in results if r.error_code == "TCP_16_20"]
    if len(fail_16_20) >= 2:
        # Consistent failure — likely DPI
        bytes_vals = [r.raw_data.get("bytes_received", 0) for r in fail_16_20]
        return SingleTestResult(
            target_name=url, test_type=TestType.TCP_16_20,
            status=TestStatus.FAIL, error_code="TCP_16_20",
            time_ms=fail_16_20[0].time_ms,
            detail=f"Consistent 16-20KB block ({len(fail_16_20)}/{retries} attempts, "
                   f"bytes: {', '.join(str(b) for b in bytes_vals)})",
            raw_data={"attempts": retries, "failures": len(fail_16_20), "bytes": bytes_vals},
        )

    # Return the last result (best effort)
    return results[-1] if results else SingleTestResult(
        target_name=url, test_type=TestType.TCP_16_20,
        status=TestStatus.ERROR, error_code="NO_ATTEMPTS",
        detail="No test attempts completed",
    )
