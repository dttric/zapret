from __future__ import annotations

from ui.main_window_pages import get_loaded_page
from ui.page_names import PageName


def refresh_page_if_possible(window, page_name: PageName) -> None:
    page = window._ensure_page(page_name)
    if page is None:
        return
    refresh_view = getattr(page, "refresh_presets_view_if_possible", None)
    if callable(refresh_view):
        try:
            refresh_view()
            return
        except Exception:
            pass
    loader = getattr(page, "_load_presets", None)
    if callable(loader):
        try:
            loader()
        except Exception:
            pass


def show_active_zapret2_user_presets_page(window) -> None:
    try:
        from strategy_menu import get_strategy_launch_method

        method = (get_strategy_launch_method() or "").strip().lower()
    except Exception:
        method = ""

    if method == "direct_zapret2_orchestra":
        refresh_page_if_possible(window, PageName.ZAPRET2_ORCHESTRA_USER_PRESETS)
        window.show_page(PageName.ZAPRET2_ORCHESTRA_USER_PRESETS)
    else:
        refresh_page_if_possible(window, PageName.ZAPRET2_USER_PRESETS)
        window.show_page(PageName.ZAPRET2_USER_PRESETS)


def show_zapret1_user_presets_page(window) -> None:
    refresh_page_if_possible(window, PageName.ZAPRET1_USER_PRESETS)
    window.show_page(PageName.ZAPRET1_USER_PRESETS)


def refresh_active_zapret2_user_presets_page(window) -> None:
    try:
        from strategy_menu import get_strategy_launch_method

        method = (get_strategy_launch_method() or "").strip().lower()
    except Exception:
        method = ""
    target = PageName.ZAPRET2_ORCHESTRA_USER_PRESETS if method == "direct_zapret2_orchestra" else PageName.ZAPRET2_USER_PRESETS
    refresh_page_if_possible(window, target)


def refresh_zapret1_user_presets_page(window) -> None:
    refresh_page_if_possible(window, PageName.ZAPRET1_USER_PRESETS)


def open_zapret2_preset_detail(window, preset_name: str) -> None:
    page = window._ensure_page(PageName.ZAPRET2_PRESET_DETAIL)
    if page is None:
        return
    if hasattr(page, "set_preset_file_name"):
        page.set_preset_file_name(preset_name)
    window.show_page(PageName.ZAPRET2_PRESET_DETAIL)


def open_zapret1_preset_detail(window, preset_name: str) -> None:
    page = window._ensure_page(PageName.ZAPRET1_PRESET_DETAIL)
    if page is None:
        return
    if hasattr(page, "set_preset_file_name"):
        page.set_preset_file_name(preset_name)
    window.show_page(PageName.ZAPRET1_PRESET_DETAIL)


def redirect_to_strategies_page_for_method(window, method: str) -> None:
    current = None
    try:
        current = window.stackedWidget.currentWidget() if hasattr(window, "stackedWidget") else None
    except Exception:
        current = None

    strategies_context_pages = set()
    for page_name in (
        PageName.DPI_SETTINGS,
        PageName.ZAPRET2_USER_PRESETS,
        PageName.ZAPRET2_DIRECT,
        PageName.ZAPRET2_ORCHESTRA_USER_PRESETS,
        PageName.ZAPRET2_ORCHESTRA,
        PageName.ZAPRET2_ORCHESTRA_CONTROL,
        PageName.ZAPRET1_DIRECT_CONTROL,
        PageName.ZAPRET1_DIRECT,
        PageName.ZAPRET1_USER_PRESETS,
        PageName.ZAPRET2_STRATEGY_DETAIL,
        PageName.ZAPRET2_ORCHESTRA_STRATEGY_DETAIL,
    ):
        page = get_loaded_page(window, page_name)
        if page is not None:
            strategies_context_pages.add(page)

    if current is not None and current not in strategies_context_pages:
        return

    if method == "orchestra":
        target_page = PageName.ORCHESTRA
    elif method == "direct_zapret2_orchestra":
        target_page = PageName.ZAPRET2_ORCHESTRA_CONTROL
    elif method == "direct_zapret2":
        target_page = PageName.ZAPRET2_DIRECT_CONTROL
    elif method == "direct_zapret1":
        target_page = PageName.ZAPRET1_DIRECT_CONTROL
    else:
        target_page = PageName.CONTROL

    window.show_page(target_page)


def show_autostart_page(window) -> None:
    window.show_page(PageName.AUTOSTART)


def show_hosts_page(window) -> None:
    window.show_page(PageName.HOSTS)


def show_servers_page(window) -> None:
    window.show_page(PageName.SERVERS)


def show_active_zapret2_control_page(window) -> None:
    try:
        from strategy_menu import get_strategy_launch_method

        if get_strategy_launch_method() == "direct_zapret2_orchestra":
            window.show_page(PageName.ZAPRET2_ORCHESTRA_CONTROL)
        else:
            window.show_page(PageName.ZAPRET2_DIRECT_CONTROL)
    except Exception:
        window.show_page(PageName.ZAPRET2_DIRECT_CONTROL)


def navigate_to_control(window) -> None:
    try:
        from strategy_menu import get_strategy_launch_method
        if get_strategy_launch_method() == "direct_zapret2":
            window.show_page(PageName.ZAPRET2_DIRECT_CONTROL)
            return
        if get_strategy_launch_method() == "direct_zapret2_orchestra":
            window.show_page(PageName.ZAPRET2_ORCHESTRA_CONTROL)
            return
        if get_strategy_launch_method() == "direct_zapret1":
            window.show_page(PageName.ZAPRET1_DIRECT_CONTROL)
            return
        if get_strategy_launch_method() == "orchestra":
            window.show_page(PageName.ORCHESTRA)
            return
    except Exception:
        pass
    window.show_page(PageName.CONTROL)


def navigate_to_strategies(window) -> None:
    from log import log

    try:
        from strategy_menu import get_strategy_launch_method
        method = get_strategy_launch_method()

        if method == "orchestra":
            target_page = PageName.ORCHESTRA
        elif method == "direct_zapret2_orchestra":
            target_page = PageName.ZAPRET2_ORCHESTRA_CONTROL
        elif method == "direct_zapret2":
            last_key = getattr(window, "_direct_zapret2_last_opened_target_key", None)
            want_restore = bool(getattr(window, "_direct_zapret2_restore_detail_on_open", False))

            if want_restore and last_key:
                try:
                    from core.presets.direct_facade import DirectPresetFacade

                    detail_page = window._ensure_page(PageName.ZAPRET2_STRATEGY_DETAIL)
                    facade = DirectPresetFacade.from_launch_method("direct_zapret2")
                    if facade.get_target_ui_item(last_key) and detail_page and hasattr(detail_page, "show_target"):
                        detail_page.show_target(last_key)
                        target_page = PageName.ZAPRET2_STRATEGY_DETAIL
                    else:
                        target_page = PageName.ZAPRET2_DIRECT_CONTROL
                except Exception:
                    target_page = PageName.ZAPRET2_DIRECT_CONTROL
            else:
                target_page = PageName.ZAPRET2_DIRECT_CONTROL
        elif method == "direct_zapret1":
            target_page = PageName.ZAPRET1_DIRECT_CONTROL
        else:
            target_page = PageName.CONTROL

        window.show_page(target_page)
    except Exception as e:
        log(f"Ошибка определения метода запуска стратегий: {e}", "ERROR")
        window.show_page(PageName.ZAPRET2_DIRECT)
