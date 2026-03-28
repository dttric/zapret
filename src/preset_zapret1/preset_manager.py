# preset_zapret1/preset_manager.py
"""Mutation shell for direct_zapret1 source presets and launch-ready source flow."""

import os
import re
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Callable, List, Optional

from log import log
from core.services import get_app_paths

from .preset_model import (
    CategoryConfigV1,
    DEFAULT_PRESET_ICON_COLOR,
    PresetV1,
    normalize_preset_icon_color_v1,
    validate_preset_v1,
)
from .preset_storage import save_preset_v1


class PresetManagerV1:
    """Direct mutation shell over selected source preset state for Zapret 1."""

    def __init__(
        self,
        on_preset_switched: Optional[Callable[[str], None]] = None,
        on_dpi_reload_needed: Optional[Callable[[], None]] = None,
    ):
        self.on_preset_switched = on_preset_switched
        self.on_dpi_reload_needed = on_dpi_reload_needed
        self._active_preset_cache: Optional[PresetV1] = None
        self._active_preset_mtime: float = 0.0
        self._sync_layer = None

    @staticmethod
    def _get_store():
        from .preset_store import get_preset_store_v1
        return get_preset_store_v1()

    def _get_sync_layer(self):
        if self._sync_layer is None:
            from .sync_layer import Zapret1PresetSyncLayer

            self._sync_layer = Zapret1PresetSyncLayer(
                on_dpi_reload_needed=self.on_dpi_reload_needed,
                invalidate_cache=self._invalidate_active_preset_cache,
                get_selected_file_name=lambda: str(self.get_active_preset_file_name() or ""),
            )
        return self._sync_layer

    def _get_facade(self):
        from core.presets.direct_facade import DirectPresetFacade

        return DirectPresetFacade.from_launch_method("direct_zapret1")

    def list_presets(self) -> List[str]:
        store = self._get_store()
        return [store.get_display_name(file_name) for file_name in store.get_preset_file_names()]

    def list_preset_file_names(self) -> List[str]:
        return self._get_store().get_preset_file_names()

    def load_all_presets(self) -> List[PresetV1]:
        store = self._get_store()
        names = store.get_preset_file_names()
        result: List[PresetV1] = []
        for file_name in names:
            preset = store.get_preset_by_file_name(file_name)
            if preset is not None:
                result.append(preset)
        return result

    def save_preset(self, preset: PresetV1) -> bool:
        errors = validate_preset_v1(preset)
        if errors:
            log(f"V1 preset validation failed: {errors}", "WARNING")
        result = save_preset_v1(preset)
        if result:
            source_file_name = str(getattr(preset, "_source_file_name", "") or "").strip()
            self.invalidate_preset_cache(source_file_name or None)
        return result

    def delete_preset_by_file_name(self, file_name: str) -> bool:
        try:
            document = self._get_facade().get_document_by_file_name(file_name)
            active_file_name = self.get_active_preset_file_name()
            if document is not None and active_file_name and document.manifest.file_name == active_file_name:
                log(f"Cannot delete active V1 preset '{file_name}'", "WARNING")
                return False
            self._get_facade().delete_by_file_name(file_name)
            self._notify_list_changed()
            return True
        except Exception as e:
            log(f"Error deleting V1 preset '{file_name}': {e}", "ERROR")
            return False

    def rename_preset_by_file_name(self, file_name: str, new_name: str) -> bool:
        try:
            document = self._get_facade().get_document_by_file_name(file_name)
            active_file_name = self.get_active_preset_file_name()
            was_selected = bool(document is not None and active_file_name and document.manifest.file_name == active_file_name)
            updated = self._get_facade().rename_by_file_name(file_name, new_name)
            if was_selected:
                self._get_store().notify_preset_switched(updated.manifest.file_name)
            self._notify_list_changed()
            return True
        except Exception as e:
            log(f"Error renaming V1 preset '{file_name}' -> '{new_name}': {e}", "ERROR")
            return False

    def duplicate_preset_by_file_name(self, file_name: str, new_name: str) -> bool:
        try:
            self._get_facade().duplicate_by_file_name(file_name, new_name)
            self._notify_list_changed()
            return True
        except Exception as e:
            log(f"Error duplicating V1 preset '{file_name}' -> '{new_name}': {e}", "ERROR")
            return False

    def export_preset_by_file_name(self, file_name: str, dest_path: Path) -> bool:
        try:
            self._get_facade().export_plain_text_by_file_name(file_name, dest_path)
            return True
        except Exception as e:
            log(f"Error exporting V1 preset '{file_name}' to '{dest_path}': {e}", "ERROR")
            return False

    def get_active_preset_file_name(self) -> Optional[str]:
        try:
            from core.services import get_direct_flow_coordinator

            return get_direct_flow_coordinator().get_selected_source_file_name("direct_zapret1")
        except Exception:
            try:
                return self._get_store().get_active_preset_file_name()
            except Exception:
                return None

    def get_active_preset(self) -> Optional[PresetV1]:
        """Loads the currently selected source preset with caching."""
        if self._active_preset_cache is not None:
            current_mtime = self._get_active_file_mtime()
            if current_mtime == self._active_preset_mtime and current_mtime > 0:
                return self._active_preset_cache

        file_name = self.get_active_preset_file_name()
        preset = None
        if file_name:
            preset = self._get_store().get_preset_by_file_name(file_name)

        if preset:
            self._active_preset_cache = preset
            self._active_preset_mtime = self._get_active_file_mtime()

        return preset

    @staticmethod
    def _extract_icon_color_from_header(header: str) -> str:
        for line in (header or "").splitlines():
            match = re.match(r"#\s*(?:IconColor|PresetIconColor):\s*(.+)", line.strip(), re.IGNORECASE)
            if match:
                return normalize_preset_icon_color_v1(match.group(1).strip())
        return DEFAULT_PRESET_ICON_COLOR

    def _get_active_file_mtime(self) -> float:
        """Gets mtime of the selected source preset file."""
        try:
            from core.services import get_direct_flow_coordinator

            preset_path = get_direct_flow_coordinator().get_selected_source_path("direct_zapret1")
            if preset_path.exists():
                return os.path.getmtime(str(preset_path))
            return 0.0
        except Exception:
            return 0.0

    def _invalidate_active_preset_cache(self) -> None:
        self._active_preset_cache = None
        self._active_preset_mtime = 0.0

    def _select_source_preset_file_name(self, file_name: str) -> bool:
        try:
            from core.services import get_selection_service

            get_selection_service().select_preset("winws1", str(file_name or "").strip())
            self._invalidate_active_preset_cache()
            return True
        except Exception as e:
            log(f"Error selecting V1 source preset file '{file_name}': {e}", "ERROR")
            return False

    def invalidate_preset_cache(self, file_name: Optional[str] = None) -> None:
        store = self._get_store()
        if file_name is None:
            store.refresh()
        else:
            store.notify_preset_saved(file_name)

    def _notify_list_changed(self) -> None:
        self._get_store().notify_presets_changed()

    def create_preset(self, name: str, from_current: bool = True) -> Optional[PresetV1]:
        try:
            created = self._get_facade().create(name, from_current=from_current)
            self._notify_list_changed()
            log(f"Created V1 preset '{name}'", "INFO")
            return self._get_store().get_preset_by_file_name(created.manifest.file_name)
        except Exception as e:
            log(f"Error creating V1 preset: {e}", "ERROR")
            return None

    def sync_preset_to_active_file(self, preset: PresetV1) -> bool:
        """
        Saves the selected Zapret 1 source preset in launch-ready form.

        For the selected preset we must preserve the raw source text, because
        imported multi-block presets are already launch-ready and a parse +
        regenerate cycle can drop unsupported layout/details. Only fall back to
        model-based sync for non-selected presets.
        """
        preset_name = str(getattr(preset, "name", "") or "").strip()
        try:
            selected_name = str(getattr(self.get_active_preset(), "name", "") or "").strip()
        except Exception:
            selected_name = ""

        if preset_name and selected_name and preset_name.lower() == selected_name.lower():
            try:
                self._invalidate_active_preset_cache()
                return True
            except PermissionError:
                raise
            except Exception as e:
                log(f"Error updating selected V1 source preset state: {e}", "ERROR")
                return False

        return self._get_sync_layer().sync_preset(preset)

    @staticmethod
    def _render_template_for_preset(raw_template: str, target_name: str) -> str:
        """Rewrites # Preset header for target preset name."""
        text = (raw_template or "").replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")

        header_end = 0
        for i, raw in enumerate(lines):
            stripped = raw.strip()
            if stripped and not stripped.startswith("#"):
                header_end = i
                break
        else:
            header_end = len(lines)

        header = lines[:header_end]
        body = lines[header_end:]

        out_header: list[str] = []
        saw_preset = False
        for raw in header:
            stripped = raw.strip().lower()
            if stripped.startswith("# preset:"):
                out_header.append(f"# Preset: {target_name}")
                saw_preset = True
                continue
            if stripped.startswith("# builtinversion:"):
                out_header.append(raw.rstrip("\n"))
                continue
            if stripped.startswith("# created:") or stripped.startswith("# modified:") or stripped.startswith("# iconcolor:") or stripped.startswith("# description:"):
                out_header.append(raw.rstrip("\n"))
                continue
            if stripped.startswith("#"):
                continue
            out_header.append(raw.rstrip("\n"))

        if not saw_preset:
            out_header.insert(0, f"# Preset: {target_name}")

        return "\n".join(out_header + body).rstrip("\n") + "\n"

    def reset_preset_to_default_template(
        self,
        preset_name: str,
        *,
        make_active: bool = True,
        sync_active_file: bool = True,
        emit_switched: bool = True,
        invalidate_templates: bool = True,
    ) -> bool:
        """Force-resets a preset to matching content from presets_v1_template/."""
        from .preset_defaults import (
            get_template_content_v1,
            get_default_template_content_v1,
            get_builtin_preset_content_v1,
            get_builtin_base_from_copy_name_v1,
            invalidate_templates_cache_v1,
        )

        name = (preset_name or "").strip()
        if not name:
            return False

        try:
            document = self._get_facade().get_document(name)
            if document is None:
                log(f"Cannot reset V1: preset '{name}' not found", "ERROR")
                return False
            target_file_name = document.manifest.file_name

            if invalidate_templates:
                try:
                    invalidate_templates_cache_v1()
                except Exception:
                    pass

            template_content = get_template_content_v1(name)
            if not template_content:
                base = get_builtin_base_from_copy_name_v1(name)
                if base:
                    template_content = get_template_content_v1(base)
            if not template_content:
                template_content = get_default_template_content_v1()
            if not template_content:
                template_content = get_builtin_preset_content_v1("Default")
            if not template_content:
                log(
                    "Cannot reset V1 preset: no templates found. "
                    "Expected at least one file in presets_v1_template/.",
                    "ERROR",
                )
                return False

            rendered_content = self._render_template_for_preset(template_content, name)

            preset_path = get_app_paths().engine_paths("winws1").ensure_directories().presets_dir / target_file_name
            try:
                preset_path.parent.mkdir(parents=True, exist_ok=True)
                preset_path.write_text(rendered_content, encoding="utf-8")
            except PermissionError as e:
                log(f"Cannot write V1 preset file (locked?): {e}", "ERROR")
                raise
            except Exception as e:
                log(f"Error writing reset V1 preset '{name}': {e}", "ERROR")
                return False

            self.invalidate_preset_cache(target_file_name)

            do_sync = bool(sync_active_file)
            if do_sync and not make_active:
                try:
                    current_active = str(getattr(self.get_active_preset(), "name", "") or "").strip().lower()
                except Exception:
                    current_active = ""
                if current_active != name.lower():
                    do_sync = False

            if make_active:
                if not self._select_source_preset_file_name(target_file_name):
                    return False

            if do_sync:
                try:
                    document = self._get_facade().get_document(name)
                    preset = self._get_store().get_preset_by_file_name(document.manifest.file_name) if document is not None else None
                    if preset is None:
                        log(f"Cannot sync reset V1 preset '{name}': failed to reload source preset", "ERROR")
                        return False
                    if not self.sync_preset_to_active_file(preset):
                        return False
                except PermissionError as e:
                    log(f"Cannot write selected V1 source preset (locked?): {e}", "ERROR")
                    raise
                except Exception as e:
                    log(f"Error saving reset V1 preset '{name}' into selected source preset: {e}", "ERROR")
                    return False

            if make_active:
                if emit_switched:
                    self._get_store().notify_preset_switched(target_file_name)
                    if self.on_preset_switched:
                        try:
                            self.on_preset_switched(name)
                        except Exception:
                            pass
                else:
                    try:
                        self._get_store().notify_active_name_changed()
                    except Exception:
                        pass

            return True

        except Exception as e:
            log(f"Error resetting V1 preset '{name}' to template: {e}", "ERROR")
            return False

    def reset_active_preset_to_default_template(self) -> bool:
        """Resets currently active V1 preset to its matching template."""
        active_name = str(getattr(self.get_active_preset(), "name", "") or "").strip()
        if not active_name:
            return False
        return self.reset_preset_to_default_template(
            active_name,
            make_active=True,
            sync_active_file=True,
            emit_switched=True,
            invalidate_templates=True,
        )

    def reset_all_presets_to_default_templates(self) -> tuple[int, int, list[str]]:
        """Overwrites V1 presets from templates and reapplies the active one."""
        from .preset_defaults import invalidate_templates_cache_v1, overwrite_v1_templates_to_presets

        success_count = 0
        total_count = 0
        failed: list[str] = []

        try:
            try:
                invalidate_templates_cache_v1()
                success_count, total_count, failed = overwrite_v1_templates_to_presets()
            except Exception as e:
                log(f"V1 bulk reset: template overwrite error: {e}", "DEBUG")

            try:
                self.invalidate_preset_cache(None)
            except Exception:
                pass

            file_names = sorted(self.list_preset_file_names(), key=lambda s: s.lower())
            if not file_names:
                return (success_count, total_count, failed)

            original_active_file_name = (self.get_active_preset_file_name() or "").strip()
            active_file_name = original_active_file_name if original_active_file_name in file_names else ""
            if not active_file_name:
                active_file_name = "Default.txt" if "Default.txt" in file_names else file_names[0]

            if active_file_name:
                try:
                    from core.services import get_direct_flow_coordinator

                    profile = get_direct_flow_coordinator().select_preset_file_name("direct_zapret1", active_file_name)
                    self._invalidate_active_preset_cache()
                    self._get_store().notify_preset_switched(profile.preset_file_name)
                    if self.on_preset_switched:
                        try:
                            self.on_preset_switched(profile.preset_name)
                        except Exception:
                            pass
                except Exception as e:
                    log(f"V1 bulk reset: failed to re-apply selected preset '{active_file_name}': {e}", "WARNING")

            return (success_count, total_count, failed)
        except Exception as e:
            log(f"V1 bulk reset error: {e}", "ERROR")
            return (success_count, total_count, failed)

    def set_strategy_selection(self, category_key: str, strategy_id: str, save_and_sync: bool = True) -> bool:
        category_key = str(category_key or "").strip().lower()
        preset = self.get_active_preset()
        if not preset:
            log("Cannot set V1 strategy: no selected preset", "WARNING")
            return False

        if category_key not in preset.categories:
            preset.categories[category_key] = CategoryConfigV1(name=category_key)

        preset.categories[category_key].strategy_id = strategy_id
        self._update_category_args_from_strategy(preset, category_key, strategy_id)
        preset.touch()

        if save_and_sync:
            return self._save_and_sync_category(preset, category_key)
        return True

    def get_category_filter_mode(self, category_key: str) -> str:
        category_key = str(category_key or "").strip().lower()
        preset = self.get_active_preset()
        if not preset:
            return "hostlist"

        category = preset.categories.get(category_key)
        if not category:
            return "hostlist"

        mode = str(getattr(category, "filter_mode", "") or "").strip().lower()
        if mode in ("hostlist", "ipset"):
            return mode
        return "hostlist"

    def update_category_filter_mode(
        self,
        category_key: str,
        filter_mode: str,
        save_and_sync: bool = True,
    ) -> bool:
        category_key = str(category_key or "").strip().lower()
        filter_mode = str(filter_mode or "").strip().lower()

        if filter_mode not in ("hostlist", "ipset"):
            log(f"Invalid V1 filter_mode: {filter_mode}", "WARNING")
            return False

        preset = self.get_active_preset()
        if not preset:
            log("Cannot update V1 filter_mode: no selected preset", "WARNING")
            return False

        if category_key not in preset.categories:
            preset.categories[category_key] = CategoryConfigV1(name=category_key)

        preset.categories[category_key].filter_mode = filter_mode
        preset.touch()

        if save_and_sync:
            return self._save_and_sync_category(preset, category_key)
        return True

    @staticmethod
    def _selection_id_from_category(cat: CategoryConfigV1) -> str:
        """Return stable selection id for UI from category config."""
        sid = str(getattr(cat, "strategy_id", "") or "").strip().lower() or "none"
        if sid == "none":
            has_args = bool((getattr(cat, "tcp_args", "") or "").strip() or (getattr(cat, "udp_args", "") or "").strip())
            if has_args:
                # Args exist but strategy id couldn't be matched -> treat as custom.
                return "custom"
        return sid

    def get_strategy_selections(self) -> dict:
        preset = self.get_active_preset()
        if not preset:
            return {}

        raw: dict[str, str] = {}
        for key, cat in (preset.categories or {}).items():
            norm_key = str(key or "").strip().lower()
            if not norm_key:
                continue
            raw[norm_key] = self._selection_id_from_category(cat)

        # If the selected preset has shared blocks with multiple hostlists in one instance,
        # parser may map only one category from that block. Keep categories visible by
        # marking additionally detected hostlist/ipset categories as custom.
        try:
            present_from_lists = self._get_sync_layer().infer_active_categories_from_launch_config()
            for key in present_from_lists:
                if raw.get(key, "none") == "none":
                    raw[key] = "custom"
        except Exception:
            pass

        return raw

    def _update_category_args_from_strategy(self, preset: PresetV1, category_key: str, strategy_id: str) -> None:
        cat = preset.categories.get(category_key)
        if not cat:
            return
        if strategy_id == "none":
            cat.tcp_args = ""
            cat.udp_args = ""
            return

        from preset_zapret2.catalog import load_categories
        from preset_zapret1.strategies_loader import load_v1_strategies

        categories = load_categories()
        category_info = categories.get(category_key) or {}

        strategies = load_v1_strategies(category_key)
        args = (strategies.get(strategy_id) or {}).get("args", "") or ""

        if args:
            protocol = (category_info.get("protocol") or "").upper()
            is_udp = any(t in protocol for t in ("UDP", "QUIC", "L7", "RAW"))
            if is_udp:
                cat.udp_args = args
                cat.tcp_args = ""
            else:
                cat.tcp_args = args
                cat.udp_args = ""

    def _save_and_sync_category(self, preset: PresetV1, category_key: str) -> bool:
        return self._get_sync_layer().sync_category_preserving_layout(preset, category_key)

    def _save_and_sync_preset(self, preset: PresetV1) -> bool:
        if preset.name and preset.name != "Current":
            if not str(getattr(preset, "_source_file_name", "") or "").strip():
                try:
                    current_file_name = str(self.get_active_preset_file_name() or "").strip()
                except Exception:
                    current_file_name = ""
                if current_file_name:
                    try:
                        setattr(preset, "_source_file_name", current_file_name)
                    except Exception:
                        pass
            save_preset_v1(preset)
            source_file_name = str(getattr(preset, "_source_file_name", "") or "").strip()
            self.invalidate_preset_cache(source_file_name or None)
        return self.sync_preset_to_active_file(preset)
