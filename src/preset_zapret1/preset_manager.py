# preset_zapret1/preset_manager.py
"""High-level preset manager for Zapret 1 (direct_zapret1) mode."""

import os
import re
import shutil
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Callable, Dict, List, Optional

from log import log

from .preset_model import (
    CategoryConfigV1,
    DEFAULT_PRESET_ICON_COLOR,
    PresetV1,
    normalize_preset_icon_color_v1,
    validate_preset_v1,
)
from .preset_storage import (
    delete_preset_v1,
    get_active_preset_name_v1,
    get_active_preset_path_v1,
    get_preset_path_v1,
    get_presets_dir_v1,
    list_presets_v1,
    load_preset_v1,
    preset_exists_v1,
    rename_preset_v1,
    save_preset_v1,
    set_active_preset_name_v1,
)


class PresetManagerV1:
    """High-level manager for Zapret 1 preset operations."""

    def __init__(
        self,
        on_preset_switched: Optional[Callable[[str], None]] = None,
        on_dpi_reload_needed: Optional[Callable[[], None]] = None,
    ):
        self.on_preset_switched = on_preset_switched
        self.on_dpi_reload_needed = on_dpi_reload_needed
        self._active_preset_cache: Optional[PresetV1] = None
        self._active_preset_mtime: float = 0.0

    @staticmethod
    def _get_store():
        from .preset_store import get_preset_store_v1
        return get_preset_store_v1()

    def list_presets(self) -> List[str]:
        return self._get_store().get_preset_names()

    def preset_exists(self, name: str) -> bool:
        return self._get_store().preset_exists(name)

    def get_preset_count(self) -> int:
        return len(self._get_store().get_preset_names())

    def load_preset(self, name: str) -> Optional[PresetV1]:
        return self._get_store().get_preset(name)

    def load_all_presets(self) -> List[PresetV1]:
        store = self._get_store()
        all_presets = store.get_all_presets()
        return [all_presets[n] for n in sorted(all_presets.keys(), key=lambda s: s.lower())]

    def save_preset(self, preset: PresetV1) -> bool:
        errors = validate_preset_v1(preset)
        if errors:
            log(f"V1 preset validation failed: {errors}", "WARNING")
        result = save_preset_v1(preset)
        if result:
            self.invalidate_preset_cache(preset.name)
        return result

    def get_active_preset_name(self) -> Optional[str]:
        try:
            return self._get_store().get_active_preset_name()
        except Exception:
            return get_active_preset_name_v1()

    def get_active_preset(self) -> Optional[PresetV1]:
        if self._active_preset_cache is not None:
            current_mtime = self._get_active_file_mtime()
            if current_mtime == self._active_preset_mtime and current_mtime > 0:
                return self._active_preset_cache

        preset = self._load_from_active_file()
        if not preset:
            name = get_active_preset_name_v1()
            if name and preset_exists_v1(name):
                preset = load_preset_v1(name)

        if preset:
            self._active_preset_cache = preset
            self._active_preset_mtime = self._get_active_file_mtime()

        return preset

    def _load_from_active_file(self) -> Optional[PresetV1]:
        from preset_zapret2.txt_preset_parser import parse_preset_file
        from .preset_model import PresetV1, CategoryConfigV1

        active_path = get_active_preset_path_v1()
        if not active_path.exists():
            return None

        try:
            data = parse_preset_file(active_path)
            name = data.active_preset or data.name
            if name == "Unnamed":
                name = "Current"

            preset = PresetV1(name=name, base_args=data.base_args)
            preset.icon_color = self._extract_icon_color_from_header(data.raw_header)

            for block in data.categories:
                cat_name = block.category
                if cat_name not in preset.categories:
                    preset.categories[cat_name] = CategoryConfigV1(
                        name=cat_name,
                        filter_mode=block.filter_mode,
                    )
                cat = preset.categories[cat_name]
                if block.protocol == "tcp":
                    cat.tcp_args = block.strategy_args
                    cat.tcp_port = block.port
                    cat.tcp_enabled = True
                    cat.filter_mode = block.filter_mode
                elif block.protocol == "udp":
                    cat.udp_args = block.strategy_args
                    cat.udp_port = block.port
                    cat.udp_enabled = True
                    if not cat.filter_mode:
                        cat.filter_mode = block.filter_mode

            # Infer strategy_id
            try:
                from .strategy_inference import infer_strategy_id_from_args
                for cat_name, cat in preset.categories.items():
                    if cat.tcp_args and cat.tcp_args.strip():
                        inferred = infer_strategy_id_from_args(
                            category_key=cat_name, args=cat.tcp_args,
                            protocol="tcp",
                        )
                        if inferred != "none":
                            cat.strategy_id = inferred
                            continue
                    if cat.udp_args and cat.udp_args.strip():
                        inferred = infer_strategy_id_from_args(
                            category_key=cat_name, args=cat.udp_args,
                            protocol="udp",
                        )
                        if inferred != "none":
                            cat.strategy_id = inferred
            except Exception:
                pass

            return preset
        except Exception as e:
            log(f"Error loading V1 active file: {e}", "ERROR")
            return None

    @staticmethod
    def _extract_icon_color_from_header(header: str) -> str:
        for line in (header or "").splitlines():
            match = re.match(r"#\s*(?:IconColor|PresetIconColor):\s*(.+)", line.strip(), re.IGNORECASE)
            if match:
                return normalize_preset_icon_color_v1(match.group(1).strip())
        return DEFAULT_PRESET_ICON_COLOR

    def _get_active_file_mtime(self) -> float:
        try:
            active_path = get_active_preset_path_v1()
            if active_path.exists():
                return os.path.getmtime(str(active_path))
            return 0.0
        except Exception:
            return 0.0

    def _invalidate_active_preset_cache(self) -> None:
        self._active_preset_cache = None
        self._active_preset_mtime = 0.0

    def invalidate_preset_cache(self, name: Optional[str] = None) -> None:
        store = self._get_store()
        if name is None:
            store.refresh()
        else:
            store.notify_preset_saved(name)

    def _notify_list_changed(self) -> None:
        self._get_store().notify_presets_changed()

    def switch_preset(self, name: str, reload_dpi: bool = True) -> bool:
        preset_path = get_preset_path_v1(name)
        active_path = get_active_preset_path_v1()

        if not preset_path.exists():
            log(f"Cannot switch V1: preset '{name}' not found", "ERROR")
            return False

        try:
            temp_path = active_path.with_suffix('.tmp')
            shutil.copy2(preset_path, temp_path)
            self._add_active_preset_marker(temp_path, name)

            import time
            try:
                os.replace(str(temp_path), str(active_path))
            except PermissionError:
                last_exc = None
                delay = 0.03
                fallback_tmp = None
                for _ in range(15):
                    time.sleep(delay)
                    try:
                        os.replace(str(temp_path), str(active_path))
                        last_exc = None
                        break
                    except PermissionError as e2:
                        last_exc = e2
                        delay = min(delay * 1.6, 0.2)
                if last_exc is not None:
                    # Atomic fallback: write to a second temp, then replace
                    import tempfile
                    try:
                        fd, fallback_tmp = tempfile.mkstemp(
                            dir=str(active_path.parent), suffix='.tmp2',
                        )
                        os.close(fd)
                        shutil.copy2(str(temp_path), fallback_tmp)
                        os.replace(fallback_tmp, str(active_path))
                    except Exception:
                        # Last resort: direct copy (non-atomic but better than crash)
                        shutil.copyfile(str(temp_path), str(active_path))
                        try:
                            if fallback_tmp:
                                os.unlink(fallback_tmp)
                        except Exception:
                            pass
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass

            set_active_preset_name_v1(name)
            self._invalidate_active_preset_cache()
            self._get_store().notify_preset_switched(name)

            log(f"Switched V1 to preset '{name}'", "INFO")

            if self.on_preset_switched:
                self.on_preset_switched(name)
            if reload_dpi and self.on_dpi_reload_needed:
                self.on_dpi_reload_needed()

            return True

        except Exception as e:
            log(f"Error switching V1 preset: {e}", "ERROR")
            temp_path = active_path.with_suffix('.tmp')
            if temp_path.exists():
                temp_path.unlink()
            return False

    def _add_active_preset_marker(self, file_path: Path, preset_name: str) -> None:
        try:
            content = file_path.read_text(encoding='utf-8')
            lines = content.split('\n')
            active_idx = None
            for i, line in enumerate(lines):
                if line.strip().lower().startswith('# activepreset:'):
                    active_idx = i
                    break
            if active_idx is not None:
                lines[active_idx] = f"# ActivePreset: {preset_name}"
            else:
                insert_idx = 0
                for i, line in enumerate(lines):
                    if line.strip().lower().startswith('# preset:'):
                        insert_idx = i + 1
                        break
                lines.insert(insert_idx, f"# ActivePreset: {preset_name}")
            file_path.write_text('\n'.join(lines), encoding='utf-8')
        except Exception as e:
            log(f"Error adding V1 active preset marker: {e}", "WARNING")

    def create_preset(self, name: str, from_current: bool = True) -> Optional[PresetV1]:
        if preset_exists_v1(name):
            log(f"Cannot create V1: preset '{name}' already exists", "WARNING")
            return None
        try:
            if from_current:
                current = self._load_from_active_file()
                if current:
                    current.name = name
                    current.created = datetime.now().isoformat()
                    current.modified = datetime.now().isoformat()
                    if save_preset_v1(current):
                        self._notify_list_changed()
                        log(f"Created V1 preset '{name}' from current", "INFO")
                        return current
                    return None
                else:
                    return self.create_default_preset(name)
            else:
                return self.create_default_preset(name)
        except Exception as e:
            log(f"Error creating V1 preset: {e}", "ERROR")
            return None

    def create_default_preset(self, name: str = "Default") -> Optional[PresetV1]:
        if preset_exists_v1(name):
            log(f"Cannot create V1: preset '{name}' already exists", "WARNING")
            return None
        try:
            from .preset_defaults import get_builtin_preset_content_v1
            from preset_zapret2.txt_preset_parser import parse_preset_content, generate_preset_file

            template = get_builtin_preset_content_v1("Default")
            if not template:
                log("No V1 default template found", "ERROR")
                return None

            data = parse_preset_content(template)
            data.name = name
            data.active_preset = None
            now = datetime.now().isoformat()
            icon_color = self._extract_icon_color_from_header(data.raw_header)
            data.raw_header = f"""# Preset: {name}
# Created: {now}
# Modified: {now}
# IconColor: {icon_color}
# Description: """

            dest_path = get_preset_path_v1(name)
            if not generate_preset_file(data, dest_path, atomic=True):
                return None

            self._notify_list_changed()
            log(f"Created V1 preset '{name}' from default template", "INFO")
            return self.load_preset(name)
        except Exception as e:
            log(f"Error creating V1 default preset: {e}", "ERROR")
            return None

    def delete_preset(self, name: str) -> bool:
        active_name = get_active_preset_name_v1()
        if active_name == name:
            log(f"Cannot delete active V1 preset '{name}'", "WARNING")
            return False
        result = delete_preset_v1(name)
        if result:
            self._notify_list_changed()
        return result

    def rename_preset(self, old_name: str, new_name: str) -> bool:
        if rename_preset_v1(old_name, new_name):
            if get_active_preset_name_v1() == old_name:
                set_active_preset_name_v1(new_name)
            self._notify_list_changed()
            return True
        return False

    def duplicate_preset(self, name: str, new_name: str) -> bool:
        source_name = str(name or "").strip()
        target_name = str(new_name or "").strip()

        if not source_name or not target_name:
            log("Cannot duplicate V1 preset: empty name", "WARNING")
            return False

        if not preset_exists_v1(source_name):
            log(f"Cannot duplicate V1 preset: '{source_name}' not found", "WARNING")
            return False

        if preset_exists_v1(target_name):
            log(f"Cannot duplicate V1 preset: '{target_name}' already exists", "WARNING")
            return False

        try:
            preset = load_preset_v1(source_name)
            if preset is None:
                log(f"Cannot duplicate V1 preset: failed to load '{source_name}'", "WARNING")
                return False

            now = datetime.now().isoformat()
            preset.name = target_name
            preset.created = now
            preset.modified = now

            if not save_preset_v1(preset):
                return False

            self._notify_list_changed()
            return True
        except Exception as e:
            log(f"Error duplicating V1 preset '{source_name}' -> '{target_name}': {e}", "ERROR")
            return False

    def sync_preset_to_active_file(self, preset: PresetV1) -> bool:
        """Writes preset directly to preset-zapret1.txt."""
        import os as _os
        from preset_zapret2.txt_preset_parser import PresetData, CategoryBlock, generate_preset_file

        active_path = get_active_preset_path_v1()

        try:
            data = PresetData(
                name=preset.name,
                active_preset=preset.name,
                base_args=preset.base_args,
            )

            icon_color = normalize_preset_icon_color_v1(getattr(preset, "icon_color", DEFAULT_PRESET_ICON_COLOR))
            preset.icon_color = icon_color
            data.raw_header = f"""# Preset: {preset.name}
# ActivePreset: {preset.name}
# Modified: {datetime.now().isoformat()}
# IconColor: {icon_color}"""

            for cat_name, cat in preset.categories.items():
                from preset_zapret2.base_filter import build_category_base_filter_lines

                if cat.tcp_enabled and cat.has_tcp():
                    args_lines = build_category_base_filter_lines(cat_name, cat.filter_mode)
                    custom_port = str(cat.tcp_port or "").strip()
                    if custom_port and custom_port != "443":
                        for i, line in enumerate(args_lines):
                            if line.startswith("--filter-tcp="):
                                args_lines[i] = f"--filter-tcp={custom_port}"
                            elif line.startswith("--filter-l7="):
                                args_lines[i] = f"--filter-l7={custom_port}"
                    for raw in cat.tcp_args.splitlines():
                        line = raw.strip()
                        if line:
                            args_lines.append(line)
                    block = CategoryBlock(
                        category=cat_name, protocol="tcp",
                        filter_mode=cat.filter_mode, filter_file="",
                        port=cat.tcp_port, args='\n'.join(args_lines),
                        strategy_args=cat.tcp_args,
                    )
                    data.categories.append(block)

                if cat.udp_enabled and cat.has_udp():
                    args_lines = build_category_base_filter_lines(cat_name, cat.filter_mode)
                    custom_port = str(cat.udp_port or "").strip()
                    if custom_port and custom_port != "443":
                        for i, line in enumerate(args_lines):
                            if line.startswith("--filter-udp="):
                                args_lines[i] = f"--filter-udp={custom_port}"
                            elif line.startswith("--filter-l7="):
                                args_lines[i] = f"--filter-l7={custom_port}"
                    for raw in cat.udp_args.splitlines():
                        line = raw.strip()
                        if line:
                            args_lines.append(line)
                    block = CategoryBlock(
                        category=cat_name, protocol="udp",
                        filter_mode=cat.filter_mode, filter_file="",
                        port=cat.udp_port, args='\n'.join(args_lines),
                        strategy_args=cat.udp_args,
                    )
                    data.categories.append(block)

            data.deduplicate_categories()
            success = generate_preset_file(data, active_path, atomic=True)

            if success:
                self._invalidate_active_preset_cache()
                log("Synced V1 preset to active file", "DEBUG")
                if self.on_dpi_reload_needed:
                    self.on_dpi_reload_needed()

            return success

        except PermissionError as e:
            log(f"Cannot write V1 preset file: {e}", "ERROR")
            raise
        except Exception as e:
            log(f"Error syncing V1 preset to active file: {e}", "ERROR")
            return False

    @staticmethod
    def _render_template_for_preset(raw_template: str, target_name: str) -> str:
        """Rewrites # Preset / # ActivePreset headers for target preset name."""
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
        saw_active = False

        for raw in header:
            stripped = raw.strip().lower()
            if stripped.startswith("# preset:"):
                out_header.append(f"# Preset: {target_name}")
                saw_preset = True
                continue
            if stripped.startswith("# activepreset:"):
                out_header.append(f"# ActivePreset: {target_name}")
                saw_active = True
                continue
            out_header.append(raw.rstrip("\n"))

        if not saw_preset:
            out_header.insert(0, f"# Preset: {target_name}")
        if not saw_active:
            insert_idx = 1 if out_header and out_header[0].strip().lower().startswith("# preset:") else 0
            out_header.insert(insert_idx, f"# ActivePreset: {target_name}")

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
            if not preset_exists_v1(name):
                log(f"Cannot reset V1: preset '{name}' not found", "ERROR")
                return False

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

            preset_path = get_preset_path_v1(name)
            try:
                preset_path.parent.mkdir(parents=True, exist_ok=True)
                preset_path.write_text(rendered_content, encoding="utf-8")
            except PermissionError as e:
                log(f"Cannot write V1 preset file (locked?): {e}", "ERROR")
                raise
            except Exception as e:
                log(f"Error writing reset V1 preset '{name}': {e}", "ERROR")
                return False

            self.invalidate_preset_cache(name)

            do_sync = bool(sync_active_file)
            if do_sync and not make_active:
                try:
                    current_active = (get_active_preset_name_v1() or "").strip().lower()
                except Exception:
                    current_active = ""
                if current_active != name.lower():
                    do_sync = False

            if make_active:
                set_active_preset_name_v1(name)
                self._invalidate_active_preset_cache()

            if do_sync:
                try:
                    active_path = get_active_preset_path_v1()
                    active_path.parent.mkdir(parents=True, exist_ok=True)
                    active_path.write_text(rendered_content, encoding="utf-8")
                    self._invalidate_active_preset_cache()
                    if self.on_dpi_reload_needed:
                        self.on_dpi_reload_needed()
                except PermissionError as e:
                    log(f"Cannot write V1 active preset file (locked?): {e}", "ERROR")
                    raise
                except Exception as e:
                    log(f"Error syncing reset V1 preset '{name}' to active file: {e}", "ERROR")
                    return False

            if make_active:
                if emit_switched:
                    self._get_store().notify_preset_switched(name)
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
        active_name = (self.get_active_preset_name() or "").strip()
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

            names = sorted(self.list_presets(), key=lambda s: s.lower())
            if not names:
                return (success_count, total_count, failed)

            name_by_key = {name.lower(): name for name in names}
            original_active = (self.get_active_preset_name() or "").strip()
            active_name = name_by_key.get(original_active.lower(), "") if original_active else ""
            if not active_name:
                active_name = name_by_key.get("default", "") or names[0]

            if active_name and not self.switch_preset(active_name, reload_dpi=False):
                log(f"V1 bulk reset: failed to re-apply active preset '{active_name}'", "WARNING")

            return (success_count, total_count, failed)
        except Exception as e:
            log(f"V1 bulk reset error: {e}", "ERROR")
            return (success_count, total_count, failed)

    def set_strategy_selection(self, category_key: str, strategy_id: str, save_and_sync: bool = True) -> bool:
        category_key = str(category_key or "").strip().lower()
        preset = self.get_active_preset()
        if not preset:
            log("Cannot set V1 strategy: no active preset", "WARNING")
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
            log("Cannot update V1 filter_mode: no active preset", "WARNING")
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

        # If active preset has shared blocks with multiple hostlists in one instance,
        # parser may map only one category from that block. Keep categories visible by
        # marking additionally detected hostlist/ipset categories as custom.
        try:
            present_from_lists = self._infer_active_categories_from_lists()
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

    @staticmethod
    def _split_preset_text_sections(content: str) -> tuple[list[str], list[str], list[list[str]]]:
        text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")

        header_lines: list[str] = []
        content_start_idx = 0
        for i, raw in enumerate(lines):
            stripped = raw.strip()
            if stripped.startswith("#") or not stripped:
                header_lines.append(raw)
                content_start_idx = i + 1
                continue
            content_start_idx = i
            break
        else:
            return header_lines, [], []

        remaining = lines[content_start_idx:]
        first_filter_idx = None
        for i, raw in enumerate(remaining):
            stripped = raw.strip().lower()
            if stripped.startswith("--filter-tcp") or stripped.startswith("--filter-udp") or stripped.startswith("--filter-l7"):
                first_filter_idx = i
                break

        if first_filter_idx is None:
            base_lines = [ln.strip() for ln in remaining if ln.strip() and not ln.strip().startswith("#")]
            return header_lines, base_lines, []

        base_lines = [
            ln.strip()
            for ln in remaining[:first_filter_idx]
            if ln.strip() and not ln.strip().startswith("#")
        ]

        blocks: list[list[str]] = []
        current: list[str] = []
        for raw in remaining[first_filter_idx:]:
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "--new":
                if current:
                    blocks.append(current)
                    current = []
                continue
            current.append(stripped)

        if current:
            blocks.append(current)

        return header_lines, base_lines, blocks

    @staticmethod
    def _render_preset_text_sections(
        header_lines: list[str],
        base_lines: list[str],
        blocks: list[list[str]],
    ) -> str:
        lines: list[str] = []

        normalized_header = [str(ln or "").rstrip("\n") for ln in (header_lines or [])]
        if normalized_header:
            lines.extend(normalized_header)
            if normalized_header[-1].strip():
                lines.append("")

        normalized_base = [str(ln or "").strip() for ln in (base_lines or []) if str(ln or "").strip()]
        if normalized_base:
            lines.extend(normalized_base)
            lines.append("")

        clean_blocks = [
            [str(ln or "").strip() for ln in block if str(ln or "").strip()]
            for block in (blocks or [])
        ]
        clean_blocks = [block for block in clean_blocks if block]

        for i, block in enumerate(clean_blocks):
            lines.extend(block)
            if i < len(clean_blocks) - 1:
                lines.append("")
                lines.append("--new")
                lines.append("")

        text = "\n".join(lines).rstrip("\n")
        return text + "\n"

    @staticmethod
    def _line_list_filename(line: str) -> tuple[str, str]:
        raw = str(line or "").strip()
        if not raw.startswith("--") or "=" not in raw:
            return "", ""

        key, _sep, value = raw.partition("=")
        key_l = key.strip().lower()
        if key_l not in ("--hostlist", "--ipset"):
            return "", ""

        value = value.strip().strip('"').strip("'")
        if value.startswith("@"):
            value = value[1:]

        return key_l, PureWindowsPath(value).name.lower()

    @classmethod
    def _block_has_target_filters(cls, block_lines: list[str]) -> bool:
        for raw in (block_lines or []):
            line = str(raw or "").strip().lower()
            if line.startswith("--hostlist=") or line.startswith("--ipset="):
                return True
            if line.startswith("--hostlist-domains=") or line.startswith("--ipset-ip="):
                return True
        return False

    @classmethod
    def _block_has_filter_start(cls, block_lines: list[str]) -> bool:
        for raw in (block_lines or []):
            line = str(raw or "").strip().lower()
            if line.startswith("--filter-tcp") or line.startswith("--filter-udp") or line.startswith("--filter-l7"):
                return True
        return False

    @classmethod
    def _remove_category_from_block(
        cls,
        block_lines: list[str],
        category_filenames: set[str],
    ) -> tuple[list[str], bool]:
        if not category_filenames:
            return list(block_lines or []), False

        out: list[str] = []
        removed = False

        for raw in (block_lines or []):
            key_l, filename = cls._line_list_filename(raw)
            if key_l and filename and filename in category_filenames:
                removed = True
                continue
            out.append(str(raw or "").strip())

        out = [ln for ln in out if ln]

        if removed:
            # If category lines were removed and block no longer has valid filter target,
            # drop the block entirely to avoid invalid winws launch arguments.
            if not cls._block_has_filter_start(out):
                return [], True
            if not cls._block_has_target_filters(out):
                return [], True

        return out, removed

    def _category_filter_filenames(self, category_key: str) -> set[str]:
        from preset_zapret2.base_filter import build_category_base_filter_lines

        names: set[str] = set()
        for mode in ("hostlist", "ipset"):
            try:
                for raw in build_category_base_filter_lines(category_key, mode):
                    _k, filename = self._line_list_filename(raw)
                    if filename:
                        names.add(filename)
            except Exception:
                continue
        return names

    def _active_list_filenames(self) -> set[str]:
        path = get_active_preset_path_v1()
        if not path.exists():
            return set()

        names: set[str] = set()
        try:
            for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                _k, filename = self._line_list_filename(raw)
                if filename:
                    names.add(filename)
        except Exception:
            return set()
        return names

    def _infer_active_categories_from_lists(self) -> set[str]:
        present_files = self._active_list_filenames()
        if not present_files:
            return set()

        try:
            from preset_zapret2.catalog import load_categories

            categories = load_categories()
        except Exception:
            categories = {}

        present: set[str] = set()
        for key in categories.keys():
            cat_key = str(key or "").strip().lower()
            if not cat_key:
                continue
            cat_files = self._category_filter_filenames(cat_key)
            if cat_files and (cat_files & present_files):
                present.add(cat_key)
        return present

    @staticmethod
    def _category_is_udp_like(category_key: str) -> bool:
        try:
            from preset_zapret2.catalog import load_categories

            info = load_categories().get(category_key) or {}
            protocol = str(info.get("protocol") or "").upper()
            return any(token in protocol for token in ("UDP", "QUIC", "L7", "RAW"))
        except Exception:
            return False

    def _build_single_category_block(self, category_key: str, cat: CategoryConfigV1) -> list[str]:
        from preset_zapret2.base_filter import build_category_base_filter_lines

        tcp_args = str(getattr(cat, "tcp_args", "") or "").strip()
        udp_args = str(getattr(cat, "udp_args", "") or "").strip()

        if not tcp_args and not udp_args:
            return []

        if udp_args and not tcp_args:
            use_udp = True
            strategy_text = udp_args
            custom_port = str(getattr(cat, "udp_port", "") or "").strip()
        elif tcp_args and not udp_args:
            use_udp = False
            strategy_text = tcp_args
            custom_port = str(getattr(cat, "tcp_port", "") or "").strip()
        else:
            use_udp = self._category_is_udp_like(category_key)
            strategy_text = udp_args if use_udp else tcp_args
            custom_port = str((getattr(cat, "udp_port", "") if use_udp else getattr(cat, "tcp_port", "")) or "").strip()

        lines = build_category_base_filter_lines(category_key, getattr(cat, "filter_mode", "hostlist") or "hostlist")
        if not lines:
            log(f"V1: base_filter lines not found for category '{category_key}'", "WARNING")
            return []

        if custom_port:
            for i, line in enumerate(lines):
                low = line.lower()
                if use_udp and low.startswith("--filter-udp="):
                    lines[i] = f"--filter-udp={custom_port}"
                elif use_udp and low.startswith("--filter-l7="):
                    lines[i] = f"--filter-l7={custom_port}"
                elif (not use_udp) and low.startswith("--filter-tcp="):
                    lines[i] = f"--filter-tcp={custom_port}"

        for raw in strategy_text.splitlines():
            line = raw.strip()
            if line:
                lines.append(line)

        return lines

    def _save_and_sync_category(self, preset: PresetV1, category_key: str) -> bool:
        category_key = str(category_key or "").strip().lower()
        if not category_key:
            return False

        cat = (preset.categories or {}).get(category_key)
        active_path = get_active_preset_path_v1()

        try:
            if active_path.exists():
                content = active_path.read_text(encoding="utf-8", errors="ignore")
            else:
                content = ""

            if not content.strip():
                return self._save_and_sync_preset(preset)

            header_lines, base_lines, blocks = self._split_preset_text_sections(content)

            if not base_lines and str(getattr(preset, "base_args", "") or "").strip():
                base_lines = [ln.strip() for ln in str(preset.base_args).splitlines() if ln.strip()]

            if not header_lines:
                active_name = str(self.get_active_preset_name() or preset.name or "Current").strip() or "Current"
                header_lines = [
                    f"# Preset: {active_name}",
                    f"# ActivePreset: {active_name}",
                    f"# Modified: {datetime.now().isoformat()}",
                ]

            category_filenames = self._category_filter_filenames(category_key)
            if not category_filenames:
                log(f"V1: cannot resolve list filenames for category '{category_key}', fallback to full sync", "WARNING")
                return self._save_and_sync_preset(preset)

            new_blocks: list[list[str]] = []
            for block in blocks:
                updated_block, _removed = self._remove_category_from_block(block, category_filenames)
                if updated_block:
                    new_blocks.append(updated_block)

            if cat is not None:
                category_block = self._build_single_category_block(category_key, cat)
                if category_block:
                    new_blocks.append(category_block)

            rendered = self._render_preset_text_sections(header_lines, base_lines, new_blocks)

            active_path.parent.mkdir(parents=True, exist_ok=True)
            active_path.write_text(rendered, encoding="utf-8")

            # Persist exact active content to selected preset file to keep shared blocks intact.
            active_name = str(self.get_active_preset_name() or "").strip()
            if active_name and active_name.lower() != "current":
                preset_path = get_preset_path_v1(active_name)
                try:
                    if preset_path.resolve() != active_path.resolve():
                        shutil.copy2(active_path, preset_path)
                except Exception:
                    shutil.copy2(active_path, preset_path)
                self.invalidate_preset_cache(active_name)

            self._invalidate_active_preset_cache()
            return True

        except PermissionError as e:
            log(f"Cannot write V1 active preset file (locked?): {e}", "ERROR")
            raise
        except Exception as e:
            log(f"Error syncing single V1 category '{category_key}': {e}", "ERROR")
            return self._save_and_sync_preset(preset)

    def _save_and_sync_preset(self, preset: PresetV1) -> bool:
        if preset.name and preset.name != "Current":
            save_preset_v1(preset)
            self.invalidate_preset_cache(preset.name)
        return self.sync_preset_to_active_file(preset)

    def ensure_presets_dir(self) -> Path:
        return get_presets_dir_v1()

    def get_active_preset_path(self) -> Path:
        return get_active_preset_path_v1()
