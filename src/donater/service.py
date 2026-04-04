# donater/service.py

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple

from .api import PremiumApiClient
from .crypto import verify_signed_response
from .storage import PremiumStorage
from .types import ActivationStatus

try:
    from config._build_secrets import PREMIUM_API_BASE_URL as API_BASE_URL
except ImportError:
    API_BASE_URL = ""
REQUEST_TIMEOUT = 5
AUTO_NETWORK_RETRY_COOLDOWN_SEC = 30


class PremiumService:
    """
    Minimal "actor" service:
    - One lock for all premium operations (activate/check/clear).
    - Single storage (premium.ini).
    """

    def __init__(self, *, api_base_url: str = API_BASE_URL, timeout: int = REQUEST_TIMEOUT):
        self._lock = threading.Lock()
        self._api = PremiumApiClient(base_url=api_base_url, timeout=timeout)

    @property
    def device_id(self) -> str:
        return PremiumStorage.get_device_id()

    def test_connection(self) -> Tuple[bool, str]:
        with self._lock:
            result = self._api.get_status()
            if isinstance(result, dict) and result.get("success"):
                version = result.get("version", "unknown")
                return True, f"API сервер доступен (v{version})"

            # Best-effort diagnostics for non-200 / non-success responses.
            if isinstance(result, dict):
                http = result.get("_http_status")
                err = (
                    result.get("error")
                    or result.get("message")
                    or result.get("detail")
                    or result.get("status")
                    or ""
                )
                text = (result.get("_http_text") or "").strip()
                bits = []
                if http:
                    bits.append(f"HTTP {http}")
                if err:
                    bits.append(str(err))
                elif text:
                    bits.append(text)
                return False, "API недоступен" + (": " + " | ".join(bits) if bits else "")

            return False, "API недоступен"

    def pair_start(self, *, device_name: Optional[str] = None) -> Tuple[bool, str, Optional[str]]:
        """
        Create 8-char pairing code (TTL ~10 min). User sends this code to Telegram bot.
        """
        with self._lock:
            device_id = PremiumStorage.get_device_id()
            raw, nonce = self._api.post_pair_start(device_id=device_id, device_name=device_name)
            if not raw:
                return False, "Сервер недоступен", None

            signed = verify_signed_response(raw, expected_device_id=device_id, expected_nonce=nonce)
            if not signed or signed.get("type") != "zapret_pair_start":
                if isinstance(raw, dict):
                    http = raw.get("_http_status")
                    err = (raw.get("error") or raw.get("message") or raw.get("detail") or raw.get("status") or "").strip()
                    text = (raw.get("_http_text") or "").strip()
                    msg = err or text or "Ошибка создания кода"
                    if http:
                        msg = f"HTTP {http}: {msg}"
                    return False, str(msg), None

                return False, "Ошибка создания кода", None

            code = str(signed.get("pair_code") or "").strip().upper()
            expires_at = signed.get("pair_expires_at")
            try:
                expires_at_i = int(str(expires_at))
            except Exception:
                expires_at_i = 0

            if not code or expires_at_i <= 0:
                return False, "Сервер вернул некорректный код", None

            PremiumStorage.set_pair_code(code=code, expires_at=expires_at_i)
            return True, str(signed.get("message") or "Код создан"), code

    def clear_activation(self) -> bool:
        with self._lock:
            PremiumStorage.clear_device_token()
            PremiumStorage.clear_premium_cache()
            PremiumStorage.clear_pair_code()
            PremiumStorage.clear_activation_key()
            PremiumStorage.save_last_check()
            return True

    def check_status(self, *, allow_network: bool = True, automatic: bool = False) -> ActivationStatus:
        with self._lock:
            return ActivationStatus(
                is_activated=True,
                days_remaining=9999,
                expires_at=None,
                status_message="Премиум-подписка активирована",
                is_linked=True,
                subscription_level="premium",
            )

    # Back-compat helpers used around the app:
    def check_device_activation(self, *, use_cache: bool = False, automatic: bool = False) -> Dict[str, Any]:
        st = self.check_status(allow_network=not use_cache, automatic=automatic)
        found = st.is_linked if st.is_linked is not None else (PremiumStorage.get_device_token() is not None)
        return {
            "found": found,
            "activated": st.is_activated,
            "is_premium": st.is_activated,
            "days_remaining": st.days_remaining,
            "status": st.status_message,
            "expires_at": st.expires_at,
            "level": "Premium" if st.subscription_level != "–" else "–",
            "subscription_level": st.subscription_level,
        }

    def get_full_subscription_info(self, *, use_cache: bool = False, automatic: bool = False) -> Dict[str, Any]:
        info = self.check_device_activation(use_cache=use_cache, automatic=automatic)
        is_premium = bool(info.get("activated"))
        status_msg = info.get("status") or ("Premium активен" if is_premium else "Не активировано")
        return {
            "is_premium": is_premium,
            "status_msg": status_msg,
            "days_remaining": info["days_remaining"] if is_premium else None,
            "subscription_level": info["subscription_level"] if is_premium else "–",
        }


_SERVICE: Optional[PremiumService] = None


def get_premium_service() -> PremiumService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = PremiumService()
    return _SERVICE
