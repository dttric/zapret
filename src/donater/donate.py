# donater/donate.py
"""
Back-compat facade.

Вся бизнес-логика живет в `donater/` (storage/api/crypto/service).
Снаружи можно продолжать импортировать DonateChecker, а также использовать
`_verify_signed_response` в тестах.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from . import crypto as _crypto
from .crypto import TRUSTED_PUBLIC_KEYS_B64
from .service import PremiumService, get_premium_service
from .storage import PremiumStorage as RegistryManager


def _verify_signed_response(resp: Dict, *, expected_device_id: str, expected_nonce: Optional[str] = None) -> Optional[Dict]:
    # Important for tests: allow patching donater.donate.TRUSTED_PUBLIC_KEYS_B64 at runtime.
    return _crypto.verify_signed_response(
        resp,
        expected_device_id=expected_device_id,
        expected_nonce=expected_nonce,
        trusted_public_keys_b64=TRUSTED_PUBLIC_KEYS_B64,
    )


class DonateChecker:
    """
    Back-compat wrapper for legacy call sites.
    Internally uses a single PremiumService instance.
    """

    def __init__(self):
        self._svc = get_premium_service()
        self.device_id = self._svc.device_id

    def activate(self, key: str) -> Tuple[bool, str]:
        # Legacy flow removed: pairing code is used instead of activation keys.
        return (False, "Активация ключом больше не поддерживается. Используйте привязку устройства.")

    def pair_start(self, device_name: Optional[str] = None) -> Tuple[bool, str, Optional[str]]:
        return self._svc.pair_start(device_name=device_name)

    def check_device_activation(self, use_cache: bool = False) -> Dict[str, Any]:
        return self._svc.check_device_activation(use_cache=use_cache)

    def get_full_subscription_info(self, use_cache: bool = False) -> Dict[str, Any]:
        return self._svc.get_full_subscription_info(use_cache=use_cache)

    def check_subscription_status(self, use_cache: bool = True) -> Tuple[bool, str, Optional[int]]:
        info = self.get_full_subscription_info(use_cache=use_cache)
        return (bool(info["is_premium"]), str(info["status_msg"]), info.get("days_remaining"))

    def test_connection(self) -> Tuple[bool, str]:
        return self._svc.test_connection()

    def clear_saved_key(self) -> bool:
        # Clear token + offline cache + pending pairing code.
        return self._svc.clear_activation()


# More explicit modern names (preferred)
get_service = get_premium_service
