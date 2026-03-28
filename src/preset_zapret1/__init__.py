# preset_zapret1/__init__.py
"""Preset management for Zapret 1 (winws.exe) mode.

Simplified version of preset_zapret2 without a separate SyndataSettings model.

Zapret 1 still supports many syndata/autottl-like flags, but they live directly
inside raw strategy args rather than in a dedicated structured state layer.
"""

from .preset_model import CategoryConfigV1, PresetV1, validate_preset_v1
from .preset_manager import PresetManagerV1
from .preset_storage import (
    get_presets_dir_v1,
    get_active_preset_path_v1,
    save_preset_v1,
)
from .preset_store import PresetStoreV1, get_preset_store_v1
from .preset_defaults import (
    clear_all_deleted_presets_v1,
    get_builtin_preset_content_v1,
    get_deleted_preset_names_v1,
    get_default_builtin_preset_name_v1,
    get_all_builtin_preset_names_v1,
    get_template_content_v1,
    get_default_template_content_v1,
    get_builtin_base_from_copy_name_v1,
    invalidate_templates_cache_v1,
    mark_preset_deleted_v1,
    ensure_default_preset_exists_v1,
    ensure_v1_templates_copied_to_presets,
    unmark_preset_deleted_v1,
    update_changed_v1_templates_in_presets,
)
from .strategies_loader import (
    load_v1_strategies,
    ensure_v1_strategies_exist,
    get_v1_strategies_dir,
    BASIC_STRATEGIES_DIR,
)

__all__ = [
    "CategoryConfigV1",
    "PresetV1",
    "validate_preset_v1",
    "PresetManagerV1",
    "get_presets_dir_v1",
    "get_active_preset_path_v1",
    "save_preset_v1",
    "PresetStoreV1",
    "get_preset_store_v1",
    "get_builtin_preset_content_v1",
    "get_deleted_preset_names_v1",
    "get_default_builtin_preset_name_v1",
    "get_all_builtin_preset_names_v1",
    "get_template_content_v1",
    "get_default_template_content_v1",
    "get_builtin_base_from_copy_name_v1",
    "invalidate_templates_cache_v1",
    "mark_preset_deleted_v1",
    "clear_all_deleted_presets_v1",
    "ensure_default_preset_exists_v1",
    "ensure_v1_templates_copied_to_presets",
    "unmark_preset_deleted_v1",
    "update_changed_v1_templates_in_presets",
    "load_v1_strategies",
    "ensure_v1_strategies_exist",
    "get_v1_strategies_dir",
    "BASIC_STRATEGIES_DIR",
]
