from __future__ import annotations

from ui.pages.preset_folders_page_base import PresetFoldersPageBase


class Zapret1PresetFoldersPage(PresetFoldersPageBase):
    def _scope_key(self) -> str:
        return "preset_zapret1"

    def _breadcrumb_root_label(self) -> str:
        return "Мои пресеты Z1"
