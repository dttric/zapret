from __future__ import annotations

from log import log
from ui.page_names import PageName
from ui.main_window_pages import get_loaded_page


def get_direct_strategy_summary(window, max_items: int = 2) -> str:
    try:
        from strategy_menu import get_strategy_launch_method
        from core.presets.direct_facade import DirectPresetFacade

        method = (get_strategy_launch_method() or "").strip().lower()
        if method == "direct_zapret2_orchestra":
            from legacy_registry_launch.selection_store import get_direct_strategy_selections
            from legacy_registry_launch.strategies_registry import registry

            selections = get_direct_strategy_selections() or {}
            active_names: list[str] = []
            for target_key in registry.get_all_target_keys_by_command_order():
                sid = selections.get(target_key, "none") or "none"
                if sid == "none":
                    continue
                info = registry.get_target_info(target_key)
                active_names.append(getattr(info, "full_name", None) or target_key)

            if not active_names:
                return "Не выбрана"
            if len(active_names) <= max_items:
                return " • ".join(active_names)
            return " • ".join(active_names[:max_items]) + f" +{len(active_names) - max_items} ещё"

        if method not in ("direct_zapret1", "direct_zapret2"):
            return "Прямой запуск"

        facade = DirectPresetFacade.from_launch_method(method)
        selections = facade.get_strategy_selections() or {}
        target_items = facade.get_target_ui_items() or {}
        ordered_targets = sorted(
            target_items.items(),
            key=lambda item: (
                getattr(item[1], "order", 999),
                str(getattr(item[1], "full_name", item[0]) or item[0]).lower(),
                item[0],
            ),
        )

        active_names: list[str] = []
        for target_key, target_info in ordered_targets:
            sid = selections.get(target_key, "none") or "none"
            if sid == "none":
                continue
            active_names.append(getattr(target_info, "full_name", None) or target_key)

        if not active_names:
            return "Не выбрана"
        if len(active_names) <= max_items:
            return " • ".join(active_names)
        return " • ".join(active_names[:max_items]) + f" +{len(active_names) - max_items} ещё"
    except Exception:
        return "Прямой запуск"


def update_current_strategy_display(window, strategy_name: str) -> None:
    launch_method = None
    try:
        from strategy_menu import get_strategy_launch_method
        launch_method = get_strategy_launch_method()
        if launch_method in ("direct_zapret2", "direct_zapret2_orchestra", "direct_zapret1"):
            strategy_name = get_direct_strategy_summary(window)
    except Exception:
        pass

    control_page = get_loaded_page(window, PageName.CONTROL)
    if control_page is not None and hasattr(control_page, "update_strategy"):
        control_page.update_strategy(strategy_name)
    try:
        page = getattr(window, "zapret2_direct_control_page", None)
        if page and hasattr(page, "update_strategy"):
            page.update_strategy(strategy_name)
    except Exception:
        pass

    for page_attr in (
        'zapret2_direct_control_page', 'orchestra_zapret2_control_page',
        'zapret2_strategies_page', 'zapret2_orchestra_strategies_page',
        'orchestra_zapret2_user_presets_page', 'zapret1_direct_control_page',
        'zapret1_strategies_page',
    ):
        page = getattr(window, page_attr, None)
        if page and hasattr(page, 'update_current_strategy'):
            page.update_current_strategy(strategy_name)

    if hasattr(window.home_page, "update_launch_method_card"):
        window.home_page.update_launch_method_card()


def update_autostart_display(window, enabled: bool, strategy_name: str = None) -> None:
    window.home_page.update_autostart_status(enabled)
    autostart_page = get_loaded_page(window, PageName.AUTOSTART)
    if autostart_page is not None and hasattr(autostart_page, "update_status"):
        autostart_page.update_status(enabled, strategy_name)


def update_subscription_display(window, is_premium: bool, days: int = None) -> None:
    window.home_page.update_subscription_status(is_premium, days)
    about_page = get_loaded_page(window, PageName.ABOUT)
    if about_page is not None and hasattr(about_page, "update_subscription_status"):
        about_page.update_subscription_status(is_premium, days)


def set_status_text(window, text: str, status: str = "neutral") -> None:
    window.home_page.set_status(text, status)


def open_subscription_dialog(window) -> None:
    window.show_page(PageName.PREMIUM)


def on_autostart_enabled(window) -> None:
    log("Автозапуск включён через страницу настроек", "INFO")
    update_autostart_display(window, True)


def on_autostart_disabled(window) -> None:
    log("Автозапуск отключён через страницу настроек", "INFO")
    update_autostart_display(window, False)


def on_subscription_updated(window, is_premium: bool, days_remaining: int) -> None:
    log(f"Статус подписки обновлён: premium={is_premium}, days={days_remaining}", "INFO")
    update_subscription_display(window, is_premium, days_remaining)
