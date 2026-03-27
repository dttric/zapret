from __future__ import annotations

from ui.pages.preset_folders_page_base import PresetFoldersPageBase


class Zapret2PresetFoldersPage(PresetFoldersPageBase):
    def _scope_key(self) -> str:
        try:
            from strategy_menu import get_strategy_launch_method

            if (get_strategy_launch_method() or "").strip().lower() == "direct_zapret2_orchestra":
                return "preset_orchestra_zapret2"
        except Exception:
            pass
        return "preset_zapret2"

    def _breadcrumb_root_label(self) -> str:
        return "Мои пресеты"
