"""DPI classification engine — error taxonomy and aggregation."""

from __future__ import annotations

import re
import ssl

from blockcheck.config import (
    WINDOWS_ERRNO_HOST_UNREACH,
    WINDOWS_ERRNO_NET_UNREACH,
    WINDOWS_ERRNO_REFUSED,
    WINDOWS_ERRNO_RESET,
    WINDOWS_ERRNO_TIMEOUT,
)
from blockcheck.models import (
    DPIClassification,
    SingleTestResult,
    TargetResult,
    TestStatus,
    TestType,
)


# ---------------------------------------------------------------------------
# SSL / TLS error classification
# ---------------------------------------------------------------------------

def classify_ssl_error(error: Exception, bytes_read: int = 0) -> tuple[str, str, int]:
    """Classify an ssl.SSLError into (label, detail, bytes_read).

    Returns a tuple of:
    - label: short error classification string
    - detail: human-readable description
    - bytes_read: estimated bytes transferred before error
    """
    msg = str(error).lower()

    # Connection reset during TLS handshake — classic DPI signature
    if "connection reset" in msg or "connection was reset" in msg:
        return "TLS_RESET", "TCP RST during TLS handshake (DPI)", 0

    # EOF during handshake — another DPI pattern
    if "eof occurred" in msg or "unexpected eof" in msg:
        if bytes_read == 0:
            return "TLS_EOF_EARLY", "EOF during handshake (DPI or firewall)", 0
        return "TLS_EOF_DATA", "EOF after partial data", bytes_read

    # Certificate errors — MITM detection
    if "certificate verify failed" in msg:
        if "self signed" in msg or "self-signed" in msg:
            return "TLS_MITM_SELF", "Self-signed cert (possible MITM proxy)", 0
        if "unable to get local issuer" in msg:
            return "TLS_MITM_UNKNOWN_CA", "Unknown CA (possible MITM)", 0
        return "TLS_CERT_ERR", "Certificate verification failed", 0

    # Version / cipher mismatch
    if "unsupported" in msg or "no protocols available" in msg:
        return "TLS_UNSUPPORTED", "TLS version not supported by server", 0
    if "version" in msg:
        return "TLS_VERSION", "TLS version mismatch", 0
    if "handshake failure" in msg or "sslv3 alert handshake" in msg:
        return "TLS_HANDSHAKE", "Handshake failure", 0

    # Alert-based
    if "alert" in msg:
        if "internal error" in msg:
            return "TLS_ALERT_INTERNAL", "Server internal error alert", 0
        if "unrecognized_name" in msg:
            return "TLS_SNI_REJECT", "SNI rejected by server", 0
        return "TLS_ALERT", f"TLS alert: {msg[:80]}", 0

    # Timeout during SSL
    if "timed out" in msg:
        return "TLS_TIMEOUT", "TLS handshake timeout (possible DPI)", 0

    return "TLS_ERR", f"SSL error: {msg[:100]}", bytes_read


# ---------------------------------------------------------------------------
# TCP connect error classification
# ---------------------------------------------------------------------------

def classify_connect_error(error: Exception, bytes_read: int = 0) -> tuple[str, str, int]:
    """Classify a connection-level error."""
    msg = str(error).lower()
    errno = getattr(error, "errno", None) or getattr(error, "winerror", 0)

    if isinstance(error, ConnectionResetError) or errno == WINDOWS_ERRNO_RESET:
        return "TCP_RESET", "Connection reset by remote (DPI or firewall)", 0

    if isinstance(error, ConnectionRefusedError) or errno == WINDOWS_ERRNO_REFUSED:
        return "TCP_REFUSED", "Connection refused", 0

    if errno == WINDOWS_ERRNO_TIMEOUT or "timed out" in msg:
        return "TCP_TIMEOUT", "TCP connection timeout", 0

    if errno == WINDOWS_ERRNO_HOST_UNREACH:
        return "HOST_UNREACH", "Host unreachable", 0

    if errno == WINDOWS_ERRNO_NET_UNREACH:
        return "NET_UNREACH", "Network unreachable", 0

    if "connection aborted" in msg:
        return "TCP_ABORT", "Connection aborted", 0

    return "CONNECT_ERR", f"Connection error: {msg[:100]}", bytes_read


# ---------------------------------------------------------------------------
# Read / response error classification
# ---------------------------------------------------------------------------

def classify_read_error(error: Exception, bytes_read: int = 0) -> tuple[str, str, int]:
    """Classify an error during response reading."""
    msg = str(error).lower()

    if "reset" in msg:
        return "READ_RESET", f"Reset after {bytes_read}B read (DPI mid-stream)", bytes_read

    if "timed out" in msg:
        return "READ_TIMEOUT", f"Read timeout after {bytes_read}B", bytes_read

    if "broken pipe" in msg or "connection aborted" in msg:
        return "READ_BROKEN", f"Broken pipe after {bytes_read}B", bytes_read

    return "READ_ERR", f"Read error: {msg[:80]}", bytes_read


# ---------------------------------------------------------------------------
# Aggregate DPI classification
# ---------------------------------------------------------------------------

class DPIClassifier:
    """Aggregate test results for a target into a DPI classification."""

    @staticmethod
    def classify(result: TargetResult) -> tuple[DPIClassification, str]:
        """Analyze all tests for a target and return (classification, detail)."""
        tests = result.tests
        if not tests:
            return DPIClassification.NONE, "No tests performed"

        # Collect test results by type
        by_type: dict[TestType, list[SingleTestResult]] = {}
        for t in tests:
            by_type.setdefault(t.test_type, []).append(t)

        # DNS evidence is evaluated as a fallback signal.
        dns_tests = by_type.get(TestType.DNS_UDP, []) + by_type.get(TestType.DNS_DOH, [])
        dns_stub = any(t.error_code == "STUB" for t in dns_tests)

        # Check for ISP page injection
        isp_tests = by_type.get(TestType.ISP_PAGE, [])
        if any(t.status == TestStatus.FAIL and t.error_code == "ISP_PAGE" for t in isp_tests):
            return DPIClassification.ISP_PAGE, "ISP block page detected"

        if any(t.status == TestStatus.FAIL and t.error_code == "HTTP_INJECT" for t in isp_tests):
            return DPIClassification.HTTP_INJECT, "HTTP injection detected"

        # Check TLS results
        tls_tests = (
            by_type.get(TestType.TLS_12, [])
            + by_type.get(TestType.TLS_13, [])
            + by_type.get(TestType.HTTP, [])
        )
        tls_fails = [t for t in tls_tests if t.status != TestStatus.OK]

        # TLS MITM
        if any(t.error_code and "MITM" in t.error_code for t in tls_fails):
            return DPIClassification.TLS_MITM, "TLS MITM proxy detected"

        # TCP RST during TLS — classic DPI
        if any(t.error_code in ("TLS_RESET", "TCP_RESET", "TLS_EOF_EARLY") for t in tls_fails):
            return DPIClassification.TLS_DPI, "TCP RST/EOF during TLS handshake"

        # Timeout-only HTTPS/TLS failures while connectivity exists.
        # Typical DPI-drop pattern: :443 hangs, but ping or plain HTTP still works.
        timeout_codes = {"TIMEOUT", "TCP_TIMEOUT", "TLS_TIMEOUT", "READ_TIMEOUT"}
        tls_relevant = [t for t in tls_tests if t.status != TestStatus.UNSUPPORTED]
        tls_timeout_like = [
            t for t in tls_relevant
            if t.status == TestStatus.TIMEOUT or (t.error_code in timeout_codes)
        ]
        tls_ok = any(t.status == TestStatus.OK for t in tls_relevant)
        if tls_relevant and not tls_ok and len(tls_timeout_like) == len(tls_relevant):
            ping_tests = by_type.get(TestType.PING, [])
            isp_connectivity = any(t.status == TestStatus.OK for t in isp_tests)
            ping_connectivity = any(t.status == TestStatus.OK for t in ping_tests)
            if isp_connectivity or ping_connectivity:
                return DPIClassification.TLS_DPI, "HTTPS/TLS timeouts while connectivity exists"

        # TCP 16-20KB block
        tcp_tests = by_type.get(TestType.TCP_16_20, [])
        if any(t.status == TestStatus.FAIL and t.error_code == "TCP_16_20" for t in tcp_tests):
            return DPIClassification.TCP_16_20, "TCP block at 16-20KB boundary"

        # STUN block
        stun_tests = by_type.get(TestType.STUN, [])
        stun_all_fail = stun_tests and all(t.status != TestStatus.OK for t in stun_tests)
        if stun_all_fail:
            # Only classify as STUN_BLOCK if other protocols work
            http_ok = any(t.status == TestStatus.OK for t in tls_tests)
            if http_ok:
                return DPIClassification.STUN_BLOCK, "STUN/UDP blocked while HTTPS works"

        # Full block — all core web probes fail.
        all_tests = [
            t for t in tests
            if t.test_type not in (TestType.PING, TestType.DNS_UDP, TestType.DNS_DOH)
        ]
        web_probe_types = {TestType.HTTP, TestType.TLS_12, TestType.TLS_13, TestType.ISP_PAGE}
        has_web_probe = any(t.test_type in web_probe_types for t in all_tests)
        if has_web_probe and len(all_tests) >= 3 and all(t.status != TestStatus.OK for t in all_tests):
            return DPIClassification.FULL_BLOCK, "All protocols blocked"

        # TCP reset but no TLS
        if any(t.error_code == "TCP_RESET" for t in tls_fails) and not any(
            t.error_code and "TLS" in t.error_code for t in tls_fails
        ):
            return DPIClassification.TCP_RESET, "TCP RST (non-TLS)"

        if dns_stub:
            return DPIClassification.DNS_FAKE, "DNS stub IP detected"

        return DPIClassification.NONE, "No DPI detected"
