# donater/types.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ActivationStatus:
    is_activated: bool
    days_remaining: Optional[int]
    expires_at: Optional[str]
    status_message: str
    # When known from server response: whether device is linked/recognized.
    # None means "unknown" (client will fallback to local token presence).
    is_linked: Optional[bool] = None
    subscription_level: str = "–"

    def get_formatted_expiry(self) -> str:
        if not self.is_activated:
            return "Не активировано"
        if self.days_remaining is None:
            return "Активировано"
        if self.days_remaining == 0:
            return "Истекает сегодня"
        if self.days_remaining == 1:
            return "1 день"
        return f"{self.days_remaining} дн."
