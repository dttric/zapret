from __future__ import annotations

from ui.page_names import PageName
from ui.main_window_pages import get_loaded_page


def setup_main_window_compatibility_attrs(window) -> None:
    """Populate backward-compatibility attributes for legacy code paths."""
    window.start_btn = window.home_page.start_btn
    window.stop_btn = window.home_page.stop_btn

    method = ""
    try:
        from strategy_menu import get_strategy_launch_method

        method = (get_strategy_launch_method() or "").strip().lower()
    except Exception:
        method = ""

    if (
        method == "direct_zapret2_orchestra"
        and hasattr(window, "orchestra_zapret2_control_page")
        and hasattr(window.orchestra_zapret2_control_page, "strategy_label")
    ):
        window.current_strategy_label = window.orchestra_zapret2_control_page.strategy_label
    elif hasattr(window, "zapret2_direct_control_page") and hasattr(window.zapret2_direct_control_page, "strategy_label"):
        window.current_strategy_label = window.zapret2_direct_control_page.strategy_label
    else:
        control_page = get_loaded_page(window, PageName.CONTROL)
        if control_page is not None and hasattr(control_page, "strategy_label"):
            window.current_strategy_label = control_page.strategy_label

    window.test_connection_btn = window.home_page.test_btn
    window.open_folder_btn = window.home_page.folder_btn
    about_page = get_loaded_page(window, PageName.ABOUT)
    window.server_status_btn = getattr(about_page, "update_btn", None)
    window.subscription_btn = getattr(about_page, "premium_btn", None)

    # Expose diagnostics sub-pages for backward-compat (cleanup, focus etc.)
    if PageName.BLOCKCHECK in window.pages:
        _blockcheck = window.pages[PageName.BLOCKCHECK]
        window.connection_page = getattr(_blockcheck, "connection_page", None)
        window.dns_check_page = getattr(_blockcheck, "dns_check_page", None)
    if PageName.HOSTS in window.pages:
        window.hosts_page = window.pages[PageName.HOSTS]
