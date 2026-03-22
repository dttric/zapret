"""utils/proxy_env.py

Bridge Zapret-specific proxy env vars to standard proxy env vars.

This lets the *builder* and any subprocesses use a single proxy config.

Supported inputs:
  - ZAPRET_PROXY_SCHEME: http|https|socks5|socks5h (default: socks5)
  - ZAPRET_PROXY_HOST
  - ZAPRET_PROXY_PORT
  - ZAPRET_PROXY_USER (optional)
  - ZAPRET_PROXY_PASS (optional)

Optional:
  - ZAPRET_NO_PROXY: comma-separated hosts for NO_PROXY
  - ZAPRET_PROXY_FORCE_SOCKS=1: monkeypatch socket for SOCKS (affects urllib, etc.)

Back-compat:
  - ZAPRET_TG_PROXY_SCHEME used as fallback scheme
  - ZAPRET_SOCKS5_HOST / ZAPRET_SOCKS5_PORT / ZAPRET_SOCKS5_USER / ZAPRET_SOCKS5_PASS
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _env_truthy(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ProxyConfig:
    scheme: str
    host: str
    port: int
    username: str = ""
    password: str = ""

    def is_socks(self) -> bool:
        return self.scheme.startswith("socks")

    def safe_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    def url(self, *, include_auth: bool = True) -> str:
        if include_auth and self.username:
            u = quote(self.username, safe="")
            p = quote(self.password, safe="")
            return f"{self.scheme}://{u}:{p}@{self.host}:{self.port}"
        return self.safe_url()


def load_zapret_proxy_from_env() -> Optional[ProxyConfig]:
    host = _env("ZAPRET_PROXY_HOST") or _env("ZAPRET_SOCKS5_HOST")
    port_raw = _env("ZAPRET_PROXY_PORT") or _env("ZAPRET_SOCKS5_PORT")
    if not host and not port_raw:
        return None

    scheme = (_env("ZAPRET_PROXY_SCHEME") or _env("ZAPRET_TG_PROXY_SCHEME") or "socks5").lower()
    if scheme == "https":
        # Some clients treat https-proxy as http-proxy; others accept https://.
        # Keep https in env URLs; for SOCKS schemes it does not apply.
        pass

    if not host:
        host = "127.0.0.1"

    if not port_raw:
        port_raw = "10808"

    try:
        port = int(port_raw)
    except Exception:
        raise ValueError(f"Invalid ZAPRET_PROXY_PORT={port_raw!r}")

    username = (
        _env("ZAPRET_PROXY_USER")
        or _env("ZAPRET_PROXY_USERNAME")
        or _env("ZAPRET_SOCKS5_USER")
        or _env("ZAPRET_SOCKS5_USERNAME")
    )
    password = (
        _env("ZAPRET_PROXY_PASS")
        or _env("ZAPRET_PROXY_PASSWORD")
        or _env("ZAPRET_SOCKS5_PASS")
        or _env("ZAPRET_SOCKS5_PASSWORD")
    )

    scheme = scheme.strip().lower() or "socks5"
    allowed = {"http", "https", "socks5", "socks5h", "socks4", "socks4a"}
    if scheme not in allowed:
        raise ValueError(f"Invalid ZAPRET_PROXY_SCHEME={scheme!r} (allowed: {sorted(allowed)})")

    return ProxyConfig(scheme=scheme, host=host, port=port, username=username, password=password)


def apply_proxy_env(cfg: ProxyConfig) -> None:
    """Set standard proxy environment variables for current process."""

    proxy_url = cfg.url(include_auth=True)
    # Most tools read uppercase; many Python libs read both.
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ[k] = proxy_url

    # NO_PROXY defaults to localhost to avoid breaking local calls.
    no_proxy = _env("ZAPRET_NO_PROXY") or _env("NO_PROXY")
    if not no_proxy:
        no_proxy = "localhost,127.0.0.1"
    os.environ["NO_PROXY"] = no_proxy
    os.environ["no_proxy"] = no_proxy


def maybe_force_global_socks(cfg: ProxyConfig) -> None:
    """Optional: force SOCKS for Python socket layer (urllib, etc.).

    Enabled only when:
      - cfg.scheme is socks*
      - ZAPRET_PROXY_FORCE_SOCKS=1
    """

    if not cfg.is_socks() or not _env_truthy("ZAPRET_PROXY_FORCE_SOCKS"):
        return

    try:
        import socks  # type: ignore
    except Exception:
        # If PySocks is missing, we cannot force SOCKS globally.
        return

    rdns = cfg.scheme in {"socks5h", "socks4a"}
    proxy_type = {
        "socks5": socks.SOCKS5,
        "socks5h": socks.SOCKS5,
        "socks4": socks.SOCKS4,
        "socks4a": socks.SOCKS4,
    }.get(cfg.scheme)
    if proxy_type is None:
        return

    if cfg.username:
        socks.set_default_proxy(proxy_type, cfg.host, cfg.port, rdns=rdns, username=cfg.username, password=cfg.password)
    else:
        socks.set_default_proxy(proxy_type, cfg.host, cfg.port, rdns=rdns)

    socket.socket = socks.socksocket  # type: ignore[assignment]


def apply_zapret_proxy_env() -> Optional[ProxyConfig]:
    """Apply proxy settings if ZAPRET_PROXY_* is configured."""

    cfg = load_zapret_proxy_from_env()
    if cfg is None:
        return None
    apply_proxy_env(cfg)
    maybe_force_global_socks(cfg)
    return cfg
