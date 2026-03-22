# preset_orchestra_zapret2/__init__.py
"""
Preset system for direct_zapret2_orchestra mode.

Presets are stored as txt files in
  %APPDATA%/zapret/orchestra_zapret2/presets_orchestra_zapret2/
Each preset contains:
- Metadata (name, created, modified)
- Base arguments (lua-init, wf-*, blobs)
- Category configurations (youtube, discord, etc.)

Switching presets = writing preset content to preset-zapret2-orchestra.txt + DPI reload.

Usage:
    from preset_orchestra_zapret2 import PresetManager, Preset

    manager = PresetManager()

    # List available presets
    presets = manager.list_presets()

    # Switch to a preset
    manager.switch_preset("Gaming")

    # Get current preset
    preset = manager.get_active_preset()

    # Create new preset from current configuration
    manager.create_preset_from_current("My Backup")

    # Edit preset
    preset = manager.load_preset("Default")
    preset.categories["youtube"].tcp_args = "--lua-desync=multisplit:pos=1"
    manager.save_preset(preset)

Low-level API:
    from preset_orchestra_zapret2 import (
        get_presets_dir,
        list_presets,
        load_preset,
        save_preset,
        delete_preset,
        rename_preset,
    )

Parser API (for txt files):
    from preset_orchestra_zapret2.txt_preset_parser import (
        parse_preset_file,
        generate_preset_file,
        PresetData,
        CategoryBlock,
    )
"""

from pathlib import Path

from utils.circular_strategy_numbering import (
    renumber_circular_strategies,
    strip_strategy_tags,
)

# Model classes
from .preset_model import CategoryConfig, Preset, SyndataSettings, validate_preset

# Storage functions (low-level)
from .preset_storage import (
    delete_preset,
    duplicate_preset,
    export_preset,
    get_active_preset_name,
    get_active_preset_path,
    get_preset_path,
    get_presets_dir,
    get_user_settings_path,
    import_preset,
    list_presets,
    load_preset,
    preset_exists,
    rename_preset,
    save_preset,
    set_active_preset_name,
)

# High-level manager
from .preset_manager import PresetManager

# Central in-memory store (singleton)
from .preset_store import PresetStore, get_preset_store

# Txt parser (for advanced usage)
from .txt_preset_parser import (
    CategoryBlock,
    PresetData,
    extract_category_from_args,
    extract_protocol_and_port,
    extract_strategy_args,
    invalidate_category_inference_cache,
    generate_preset_content,
    generate_preset_file,
    parse_preset_content,
    parse_preset_file,
    update_category_in_preset,
)

# Default settings parser & template functions
from .preset_defaults import (
    get_default_category_settings,
    get_category_default_filter_mode,
    get_category_default_syndata,
    parse_syndata_from_args,
    get_default_template_content,
    get_default_template_name,
    get_template_content,
    get_template_canonical_name,
    invalidate_templates_cache,
    ensure_templates_copied_to_presets,
)

# Strategy inference (for loading presets)
from .strategy_inference import (
    infer_strategy_id_from_args,
    infer_strategy_ids_batch,
    normalize_args,
)


def _renumber_circular_strategies(content: str) -> str:
    """Backward-compatible wrapper for shared numbering utility."""
    return renumber_circular_strategies(content)


def _atomic_write_text(path, content: str, *, encoding: str = "utf-8") -> None:
    """Writes text via temp file + replace to avoid partial files."""
    import os
    import tempfile
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    if not data.endswith("\n"):
        data += "\n"

    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{path.stem}_",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp_name, str(path))
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except Exception:
            pass

def ensure_builtin_presets_exist() -> bool:
    """
    Ensures that preset templates directory (presets_v2_template/) exists and
    syncs templates to presets/ (including version-based auto-updates).

    In dev mode, seeds templates from the repo folder
    `preset_zapret2/builtin_presets/*.txt` into `presets_v2_template/`.

    Returns:
        True if presets exist or were created successfully.
    """
    from log import log
    from .preset_defaults import (
        invalidate_templates_cache,
        ensure_templates_copied_to_presets,
    )

    try:
        # Ensure orchestra templates directory exists
        try:
            from config import get_zapret_orchestra_presets_template_dir

            templates_dir = Path(get_zapret_orchestra_presets_template_dir())
        except Exception:
            templates_dir = get_presets_dir().parent / "presets_orchestra_zapret2_template"
        templates_dir.mkdir(parents=True, exist_ok=True)

        # Dev convenience: seed templates from the repo (if present)
        try:
            from config import MAIN_DIRECTORY

            src_candidates = [
                # Canonical repo source for orchestra preset templates.
                Path(MAIN_DIRECTORY) / "preset_orchestra_zapret2" / "builtin_presets",
                # Backward-compat for older dev layouts.
                Path(MAIN_DIRECTORY) / "orchestra_zapret2" / "presets_orchestra_zapret2_template",
                Path(MAIN_DIRECTORY) / "preset_orchestra_zapret2" / "presets_orchestra_zapret2_template",
            ]

            src_dir = next((p for p in src_candidates if p.exists() and p.is_dir()), None)
            if src_dir is not None:
                for p in sorted(src_dir.glob("*.txt"), key=lambda x: x.name.lower()):
                    if p.name.startswith("_"):
                        continue
                    dst = templates_dir / p.name
                    if dst.exists():
                        continue
                    try:
                        dst.write_text(p.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
                        log(f"Seeded preset template: {dst}", "DEBUG")
                    except Exception:
                        pass
        except Exception:
            pass

        # Templates may have just been seeded from the repo; refresh cache.
        try:
            invalidate_templates_cache()
        except Exception:
            pass

        # Sync templates to presets/ (create missing + version-based overwrite)
        ensure_templates_copied_to_presets()
        return True

    except Exception as e:
        log(f"Error ensuring built-in presets: {e}", "ERROR")
        import traceback
        log(traceback.format_exc(), "DEBUG")
        return False


def ensure_default_preset_exists() -> bool:
    """
    Ensures that a default preset exists for direct_zapret2 mode.

    Checks if preset-zapret2.txt exists. If not:
    1. Generates active preset from the default template.

    This function should be called during application startup
    when running in direct_zapret2 mode.

    Returns:
        True if preset exists or was created successfully
    """
    from log import log
    from .preset_defaults import get_default_template_content, get_default_template_name

    active_path = get_active_preset_path()

    # Ensure templates exist and are copied to presets/.
    ensure_builtin_presets_exist()

    # Check if active preset file already exists
    if active_path.exists():
        # Keep active preset clean: strip legacy :strategy=N tags if present.
        try:
            raw = active_path.read_text(encoding="utf-8", errors="replace")
            cleaned = strip_strategy_tags(raw)
            if cleaned != raw:
                _atomic_write_text(active_path, cleaned, encoding="utf-8")
                log("Removed legacy :strategy=N tags from active preset", "INFO")
        except Exception:
            pass
        log("Active preset file already exists", "DEBUG")
        return True

    log("Active preset file not found, creating from default template...", "INFO")

    try:
        template_name = get_default_template_name() or "Default"
        template = get_default_template_content()
        if not template:
            log(
                "Cannot create preset-zapret2-orchestra.txt: no preset templates found. "
                "Expected at least one file in: %APPDATA%/zapret/orchestra_zapret2/presets_orchestra_zapret2_template/*.txt",
                "ERROR",
            )
            return False
        template = strip_strategy_tags(template)
        _atomic_write_text(active_path, template, encoding="utf-8")
        log(f"Created active preset from template at {active_path}", "DEBUG")

        # Persist active preset name
        set_active_preset_name(template_name)

        log("Active preset created from template successfully", "INFO")
        return True

    except Exception as e:
        log(f"Error creating default preset: {e}", "ERROR")
        import traceback
        log(traceback.format_exc(), "DEBUG")
        return False


def restore_builtin_preset(preset_name: str) -> bool:
    """
    Restores a preset from the template in presets_v2_template/.

    Overwrites the preset in presets/ with the template content.
    If the preset is currently active, also updates preset-zapret2.txt.

    Returns:
        True if restore was successful, False otherwise
    """
    from log import log
    from .preset_defaults import get_template_content, get_template_canonical_name

    try:
        canonical = get_template_canonical_name(preset_name)
        content = get_template_content(preset_name)
        if not canonical or content is None:
            log(f"Unknown preset template '{preset_name}'", "ERROR")
            return False
        content = strip_strategy_tags(content)

        # Overwrite the presets/ file with template content
        preset_path = get_preset_path(canonical)
        preset_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(preset_path, content, encoding="utf-8")
        log(f"Restored preset '{canonical}' from template to {preset_path}", "INFO")

        # If this preset is currently active, update preset-zapret2.txt
        active_name = (get_active_preset_name() or "").strip()
        if active_name and active_name.lower() == canonical.lower():
            active_path = get_active_preset_path()
            _atomic_write_text(active_path, content, encoding="utf-8")
            log(f"Also updated active preset at {active_path}", "SUCCESS")

        return True

    except Exception as e:
        log(f"Error restoring preset '{preset_name}' from template: {e}", "ERROR")
        import traceback
        log(traceback.format_exc(), "DEBUG")
        return False


def restore_default_preset() -> bool:
    """
    Restores Default preset from the built-in template.

    This function can be used to:
    1. Fix a corrupted Default.txt
    2. Reset Default.txt to factory settings
    3. Recover from accidental modifications

    Returns:
        True if restore was successful, False otherwise
    """
    return restore_builtin_preset("Default")


def restore_gaming_preset() -> bool:
    """
    Restores Gaming.txt preset from the built-in code template.

    Returns:
        True if restore was successful, False otherwise
    """
    return restore_builtin_preset("Gaming")


__all__ = [
    # Model
    "Preset",
    "CategoryConfig",
    "SyndataSettings",
    "validate_preset",
    # Storage functions
    "get_presets_dir",
    "get_preset_path",
    "get_active_preset_path",
    "get_user_settings_path",
    "list_presets",
    "preset_exists",
    "load_preset",
    "save_preset",
    "delete_preset",
    "rename_preset",
    "duplicate_preset",
    "export_preset",
    "import_preset",
    "get_active_preset_name",
    "set_active_preset_name",
    # Manager
    "PresetManager",
    # Central store
    "PresetStore",
    "get_preset_store",
    # Utility functions
    "ensure_builtin_presets_exist",
    "ensure_default_preset_exists",
    "restore_builtin_preset",
    "restore_default_preset",
    "restore_gaming_preset",
    "get_default_category_settings",
    "get_category_default_filter_mode",
    "get_category_default_syndata",
    "parse_syndata_from_args",
    # Template functions
    "get_default_template_content",
    "get_default_template_name",
    "get_template_content",
    "get_template_canonical_name",
    "invalidate_templates_cache",
    "ensure_templates_copied_to_presets",
    # Parser
    "PresetData",
    "CategoryBlock",
    "parse_preset_file",
    "parse_preset_content",
    "generate_preset_file",
    "generate_preset_content",
    "extract_category_from_args",
    "extract_protocol_and_port",
    "extract_strategy_args",
    "update_category_in_preset",
    # Strategy inference
    "infer_strategy_id_from_args",
    "infer_strategy_ids_batch",
    "normalize_args",
]
