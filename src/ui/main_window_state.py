from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock
from typing import Callable, Iterable


@dataclass(frozen=True, slots=True)
class AppUiState:
    dpi_running: bool = False
    dpi_busy: bool = False
    dpi_busy_text: str = ""
    launch_method: str = ""
    current_strategy_summary: str = ""
    autostart_enabled: bool = False
    autostart_type: str = ""
    subscription_is_premium: bool = False
    subscription_days_remaining: int | None = None
    status_text: str = ""
    status_kind: str = "neutral"


UiStateCallback = Callable[[AppUiState, frozenset[str]], None]


class MainWindowStateStore:
    """Единый store состояния окна без зависимости от QWidget/QObject."""

    def __init__(self, initial_state: AppUiState | None = None) -> None:
        self._state = initial_state or AppUiState()
        self._lock = RLock()
        self._subscribers: list[tuple[frozenset[str] | None, UiStateCallback]] = []

    def snapshot(self) -> AppUiState:
        with self._lock:
            return replace(self._state)

    def subscribe(
        self,
        callback: UiStateCallback,
        *,
        fields: Iterable[str] | None = None,
        emit_initial: bool = False,
    ) -> Callable[[], None]:
        watched_fields = frozenset(fields) if fields is not None else None
        with self._lock:
            self._subscribers.append((watched_fields, callback))

        if emit_initial:
            callback(self.snapshot(), frozenset())

        def _unsubscribe() -> None:
            with self._lock:
                try:
                    self._subscribers.remove((watched_fields, callback))
                except ValueError:
                    pass

        return _unsubscribe

    def update(self, **changes) -> bool:
        if not changes:
            return False

        with self._lock:
            state = self._state
            real_changes = {}
            for field_name, value in changes.items():
                if not hasattr(state, field_name):
                    continue
                if getattr(state, field_name) != value:
                    real_changes[field_name] = value

            if not real_changes:
                return False

            self._state = replace(state, **real_changes)
            snapshot = replace(self._state)
            subscribers = list(self._subscribers)

        changed_fields = frozenset(real_changes.keys())
        for watched_fields, callback in subscribers:
            if watched_fields is None or watched_fields & changed_fields:
                callback(snapshot, changed_fields)

        return True

    def set_dpi_running(self, running: bool) -> bool:
        return self.update(dpi_running=bool(running))

    def set_dpi_busy(self, busy: bool, text: str = "") -> bool:
        if not busy:
            text = ""
        return self.update(dpi_busy=bool(busy), dpi_busy_text=str(text or ""))

    def set_launch_method(self, method: str) -> bool:
        return self.update(launch_method=str(method or "").strip().lower())

    def set_current_strategy_summary(self, summary: str) -> bool:
        return self.update(current_strategy_summary=str(summary or ""))

    def set_autostart(self, enabled: bool, autostart_type: str | None = None) -> bool:
        resolved_type = str(autostart_type or "")
        return self.update(
            autostart_enabled=bool(enabled),
            autostart_type=resolved_type if enabled else "",
        )

    def set_subscription(self, is_premium: bool, days_remaining: int | None = None) -> bool:
        normalized_days = None if not is_premium else days_remaining
        return self.update(
            subscription_is_premium=bool(is_premium),
            subscription_days_remaining=normalized_days,
        )

    def set_status_message(self, text: str, kind: str = "neutral") -> bool:
        return self.update(status_text=str(text or ""), status_kind=str(kind or "neutral"))
