from __future__ import annotations

from ui.page_names import PageName


def setup_main_window_compatibility_attrs(window) -> None:
    """Populate backward-compatibility attributes for legacy code paths."""
    # Expose diagnostics sub-pages for backward-compat (cleanup, focus etc.)
    if PageName.BLOCKCHECK in window.pages:
        _blockcheck = window.pages[PageName.BLOCKCHECK]
        window.connection_page = getattr(_blockcheck, "connection_page", None)
        window.dns_check_page = getattr(_blockcheck, "dns_check_page", None)
    if PageName.HOSTS in window.pages:
        window.hosts_page = window.pages[PageName.HOSTS]
