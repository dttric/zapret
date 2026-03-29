from __future__ import annotations

from log import log


def refresh_main_window_pages_after_preset_switch(window) -> None:
    """Refresh UI fragments that depend on the active preset."""
    try:
        display_name = window._get_direct_strategy_summary()
        if display_name:
            window.update_current_strategy_display(display_name)
    except Exception as e:
        log(f"Ошибка обновления display стратегии после смены пресета: {e}", "DEBUG")
