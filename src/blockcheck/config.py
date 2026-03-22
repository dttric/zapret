"""BlockCheck configuration — timeouts, markers, DNS servers, errno codes."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Timeouts (seconds)
# ---------------------------------------------------------------------------
HTTPS_TIMEOUT = 10
STUN_TIMEOUT = 5
PING_TIMEOUT = 3
PING_COUNT = 2
DNS_TIMEOUT = 5
DOH_TIMEOUT = 8
ISP_PAGE_TIMEOUT = 8
TCP_16_20_TIMEOUT = 15

# ---------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------
TCP_16_20_RETRIES = 3
DNS_RETRIES = 2

# ---------------------------------------------------------------------------
# TCP target selection / health probing
# ---------------------------------------------------------------------------
TCP_TARGET_MAX_COUNT = 18
TCP_TARGETS_PER_PROVIDER = 2
TCP_HEALTH_TIMEOUT = 4
TCP_HEALTH_MAX_CANDIDATES = 36

# ---------------------------------------------------------------------------
# TCP 16-20 KB block detection
# ---------------------------------------------------------------------------
TCP_BLOCK_RANGE_MIN = 15_000   # 15 KB
TCP_BLOCK_RANGE_MAX = 21_000   # 21 KB

# ---------------------------------------------------------------------------
# ISP block page markers (body content)
# ---------------------------------------------------------------------------
ISP_BODY_MARKERS: list[str] = [
    "eais.rkn.gov.ru",
    "rkn.gov.ru",
    "nap.rkn.gov.ru",
    "blocklist.rkn.gov.ru",
    "Роскомнадзор",
    "Roskomnadzor",
    "blocked by",
    "заблокирован",
    "ограничен доступ",
    "access denied",
    "access restricted",
    "is blocked",
    "web filter",
    "content filter",
    "warning: this site",
    "этот ресурс заблокирован",
    "federalnyj-zakon",
    "149-fz",
    "zapret-info",
]

# ---------------------------------------------------------------------------
# ISP redirect markers (URL patterns)
# ---------------------------------------------------------------------------
ISP_REDIRECT_MARKERS: list[str] = [
    "warning.rt.ru",
    "block.mts.ru",
    "blocked.beeline.ru",
    "block.megafon.ru",
    "zapret.",
    "blackhole.",
    "sorm.",
]

# ---------------------------------------------------------------------------
# DNS servers for integrity check
# ---------------------------------------------------------------------------
DNS_UDP_SERVERS: list[str] = [
    "8.8.8.8",         # Google
    "1.1.1.1",         # Cloudflare
    "77.88.8.8",       # Yandex
    "9.9.9.9",         # Quad9
]

DOH_SERVERS: list[dict[str, str]] = [
    {"name": "Google", "url": "https://dns.google/resolve"},
    {"name": "Cloudflare", "url": "https://cloudflare-dns.com/dns-query"},
]

# ---------------------------------------------------------------------------
# DNS check domains
# ---------------------------------------------------------------------------
DNS_CHECK_DOMAINS: list[str] = [
    "discord.com",
    "youtube.com",
    "rutracker.org",
    "linkedin.com",
    "telegram.org",
]

# ---------------------------------------------------------------------------
# Windows errno codes for DPI classification
# ---------------------------------------------------------------------------
WINDOWS_ERRNO_RESET = 10054         # WSAECONNRESET
WINDOWS_ERRNO_TIMEOUT = 10060       # WSAETIMEDOUT
WINDOWS_ERRNO_REFUSED = 10061       # WSAECONNREFUSED
WINDOWS_ERRNO_HOST_UNREACH = 10065  # WSAEHOSTUNREACH
WINDOWS_ERRNO_NET_UNREACH = 10051   # WSAENETUNREACH

# ---------------------------------------------------------------------------
# Thread pool
# ---------------------------------------------------------------------------
DEFAULT_PARALLEL = 4

# ---------------------------------------------------------------------------
# Strategy scanner
# ---------------------------------------------------------------------------
STRATEGY_PROBE_TIMEOUT = 5        # seconds per HTTPS connect + TLS handshake
STRATEGY_RESPONSE_TIMEOUT = 3     # seconds to read HTTP response after TLS ok
STRATEGY_STARTUP_WAIT = 1.0       # seconds to wait for winws2 startup
STRATEGY_KILL_TIMEOUT = 4         # seconds to wait for winws2 shutdown
WINWS2_EXE_RELATIVE = "exe/winws2.exe"
PROBE_TEMP_PRESET = "blockcheck_probe.txt"
PROBE_TEMP_HOSTLIST = "blockcheck_probe_hosts.txt"
