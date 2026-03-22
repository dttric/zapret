"""tgram/tg_log_bot.py

Upload log files to ZapretHub Support via HTTP.

Security goal:
  - No shared secrets (bot tokens, static API keys) embedded in the client.
  - No long-lived session token stored on disk by default.
  - Each upload can be authorized with a short one-time code confirmed via the
    Telegram bot and passed as X-Auth-Code.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import time

import requests


TIMEOUT = 30
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


# Use a dedicated session to avoid broken system proxy settings.
# Most users don't need an HTTP proxy; if they do, they can set
# ZAPRET_HUB_TRUST_ENV=1 to let requests use HTTP(S)_PROXY env vars.
_SESSION_DIRECT = requests.Session()
_SESSION_DIRECT.trust_env = False

_SESSION_ENV = requests.Session()
_SESSION_ENV.trust_env = True


def _use_env_proxy() -> bool:
    return (os.getenv("ZAPRET_HUB_TRUST_ENV") or "").strip() in ("1", "true", "yes")


def _request(method: str, url: str, *, timeout: float | tuple[float, float], **kwargs):
    """HTTP request with proxy-safe fallback."""

    if _use_env_proxy():
        return _SESSION_ENV.request(method, url, timeout=timeout, **kwargs)

    # Direct first (ignores proxies), then fallback to env proxies
    try:
        return _SESSION_DIRECT.request(method, url, timeout=timeout, **kwargs)
    except requests.exceptions.ProxyError:
        # Shouldn't happen with trust_env=False, but keep a safe fallback.
        return _SESSION_ENV.request(method, url, timeout=timeout, **kwargs)
    except requests.exceptions.ConnectionError:
        return _SESSION_ENV.request(method, url, timeout=timeout, **kwargs)


# Default can be overridden with env var ZAPRET_LOG_UPLOAD_URL.
# Example:
#   https://zapret-tracker.duckdns.org/api/logs/upload
DEFAULT_UPLOAD_URL = "https://zapret-tracker.duckdns.org/api/logs/upload"


def _base_url_from_upload_url(upload_url: str) -> str:
    url = (upload_url or "").strip().rstrip("/")
    if url.endswith("/api/logs/upload"):
        return url[: -len("/api/logs/upload")]
    if "/api/" in url:
        return url.split("/api/", 1)[0]
    return url


def _get_upload_url() -> str:
    url = (os.getenv("ZAPRET_LOG_UPLOAD_URL") or DEFAULT_UPLOAD_URL or "").strip()
    return url.rstrip("/")


def _get_bearer_token() -> str:
    """Optional dev override: provide a session token via env var.

    Prefer using one-time X-Auth-Code instead.
    """
    token = (os.getenv("ZAPRET_HUB_TOKEN") or "").strip()
    if not token:
        token = (os.getenv("ZAPRET_LOG_UPLOAD_TOKEN") or "").strip()  # legacy
    return token.replace("Bearer ", "").strip()


def _source_from_topic(topic_id: Optional[int]) -> str:
    """Map legacy forum topic IDs to panel sources."""
    if topic_id == 43927:
        return "orchestrator"
    if topic_id == 10852:
        return "connection_test"
    return "dev_logs"


def _shorten(text: str, limit: int = 200) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _ping_url(upload_url: str) -> str:
    if upload_url.endswith("/api/logs/upload"):
        return upload_url[: -len("/api/logs/upload")] + "/api/ping"
    return upload_url.rstrip("/") + "/api/ping"


def request_upload_code(upload_url: str | None = None) -> tuple[bool, str, str, str]:
    """Request a short one-time code for log upload.

    Server will accept this code only for /api/logs/upload (X-Auth-Code).

    Returns:
      (ok, code, bot_username, bot_link)
    """
    u = (upload_url or _get_upload_url()).strip()
    base = _base_url_from_upload_url(u)
    if not base:
        return False, "", "", ""
    try:
        resp = _request("POST", base.rstrip("/") + "/api/logs/auth/code", timeout=(5, TIMEOUT))
        if not (200 <= resp.status_code < 300):
            return False, "", "", ""
        js = resp.json() or {}
        return True, (js.get("code") or ""), (js.get("botUsername") or ""), (js.get("botLink") or base)
    except Exception:
        return False, "", "", ""


def poll_upload_code(code: str, upload_url: str | None = None, timeout_seconds: int = 300) -> tuple[bool, str]:
    """Poll the upload code until confirmed.

    Returns:
      (ok, error_message)
    """
    u = (upload_url or _get_upload_url()).strip()
    base = _base_url_from_upload_url(u)
    if not base:
        return False, "Не настроен адрес панели (ZAPRET_LOG_UPLOAD_URL)"

    deadline = time.time() + max(5, int(timeout_seconds))
    while time.time() < deadline:
        try:
            resp = _request("GET", base.rstrip("/") + f"/api/logs/auth/check/{code}", timeout=(5, TIMEOUT))
            js = resp.json() or {}
            if js.get("expired"):
                return False, "Код устарел. Запросите новый код и попробуйте снова."
            if js.get("confirmed") is True:
                return True, ""
        except Exception:
            pass
        time.sleep(1.0)

    return False, "Время ожидания истекло. Попробуйте снова."


def send_log_file(
    file_path: str | Path,
    caption: str = "",
    topic_id: int | None = None,
    auth_code: str | None = None,
) -> tuple[bool, Optional[str]]:
    """Upload a log file to the support panel.

    Args:
        file_path: path to log file
        caption: extra text
        topic_id: legacy topic id (mapped to a source)

    Returns:
        (success, error_message)
    """

    upload_url = _get_upload_url()
    if not upload_url:
        return False, "Не настроен адрес панели (ZAPRET_LOG_UPLOAD_URL)"

    path = Path(file_path)
    if not path.exists():
        return False, f"Файл лога не найден: {path.name}"

    file_size = path.stat().st_size
    if file_size == 0:
        return False, "Файл лога пуст"
    if file_size > MAX_FILE_SIZE:
        size_mb = file_size / (1024 * 1024)
        return False, f"Файл слишком большой ({size_mb:.1f} МБ). Максимум: 50 МБ"

    source = _source_from_topic(topic_id)
    headers = {}
    if auth_code:
        headers["X-Auth-Code"] = str(auth_code).strip()
    else:
        token = _get_bearer_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

    try:
        with path.open("rb") as fh:
            files = {"document": (path.name, fh)}
            data = {
                "source": source,
                "caption": (caption or "")[:2000],
            }
            resp = _request("POST", upload_url, data=data, files=files, headers=headers, timeout=(10, TIMEOUT))

        if resp.status_code == 401:
            return False, "Требуется авторизация. Запросите код и подтвердите его в Telegram-боте поддержки."

        if 200 <= resp.status_code < 300:
            try:
                js = resp.json()
                if js.get("ok") is True:
                    return True, None
            except Exception:
                pass
            return True, None

        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = resp.text
        return False, f"Ошибка панели ({resp.status_code}): {_shorten(str(detail or ''), 220)}"

    except requests.Timeout:
        return False, "Панель не отвечает (timeout)"
    except requests.ConnectionError as e:
        return False, f"Не удалось подключиться к панели: {_shorten(str(e), 220)}"
    except Exception as e:
        return False, f"Ошибка: {_shorten(str(e), 220)}"


def check_bot_connection() -> bool:
    try:
        ok, _ = check_bot_connection_detailed()
        return ok
    except Exception:
        return False


def check_bot_connection_detailed() -> tuple[bool, str]:
    upload_url = _get_upload_url()
    if not upload_url:
        return False, "Адрес панели не настроен (ZAPRET_LOG_UPLOAD_URL)"

    try:
        r = _request("GET", _ping_url(upload_url), timeout=(5, 10))
        if 200 <= r.status_code < 300:
            return True, ""
        return False, f"Панель недоступна (HTTP {r.status_code})"
    except requests.Timeout:
        return False, "Панель не отвечает (timeout)"
    except Exception as e:
        return False, f"Ошибка подключения к панели: {_shorten(str(e), 180)}"


def get_bot_connection_info() -> tuple[bool, str, str]:
    ok, error_msg = check_bot_connection_detailed()
    if ok:
        return True, "", "unknown"

    msg = (error_msg or "").lower()

    # Config errors
    if "zapret_log_upload_url" in msg or "не настроен адрес панели" in msg or "адрес панели не настроен" in msg:
        return False, error_msg, "config"

    # Proxy-ish errors
    if "proxyerror" in msg or "connect to proxy" in msg or "unable to connect to proxy" in msg:
        return False, error_msg, "proxy"

    return False, error_msg, "network"
