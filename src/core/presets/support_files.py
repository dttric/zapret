from __future__ import annotations

from pathlib import Path
import shutil

from log import log
from .strategy_catalog_sanitizer import sanitize_strategy_catalog_dir
from .z2_template_runtime import ensure_templates_copied_to_presets, invalidate_templates_cache
from .v1_template_runtime import ensure_v1_templates_copied_to_presets, update_changed_v1_templates_in_presets


def prepare_direct_support_files(launch_method: str) -> None:
    method = str(launch_method or "").strip().lower()
    if method == "direct_zapret2":
        _prepare_direct_zapret2_support_files()
        return
    if method == "direct_zapret1":
        _prepare_direct_zapret1_support_files()
        return
    raise ValueError(f"Unsupported direct launch method: {launch_method}")


def _prepare_direct_zapret2_support_files() -> None:
    from config import MAIN_DIRECTORY
    from core.services import get_app_paths

    app_paths = get_app_paths()
    user_root = app_paths.user_root
    presets_dir = app_paths.engine_paths("winws2").ensure_directories().presets_dir
    templates_dir = user_root / "presets_v2_template"
    basic_dir = user_root / "direct_zapret2" / "basic_strategies"
    advanced_dir = user_root / "direct_zapret2" / "advanced_strategies"

    templates_dir.mkdir(parents=True, exist_ok=True)
    basic_dir.mkdir(parents=True, exist_ok=True)
    advanced_dir.mkdir(parents=True, exist_ok=True)
    presets_dir.mkdir(parents=True, exist_ok=True)

    _seed_missing_text_files(Path(MAIN_DIRECTORY) / "preset_zapret2" / "builtin_presets", templates_dir)
    try:
        invalidate_templates_cache()
    except Exception:
        pass
    ensure_templates_copied_to_presets()

    _seed_missing_strategy_files(Path(MAIN_DIRECTORY) / "preset_zapret2" / "basic_strategies", basic_dir)
    _seed_missing_strategy_files(Path(MAIN_DIRECTORY) / "preset_zapret2" / "advanced_strategies", advanced_dir)
    sanitize_strategy_catalog_dir(basic_dir)
    sanitize_strategy_catalog_dir(advanced_dir)


def _prepare_direct_zapret1_support_files() -> None:
    _ensure_v1_strategies_exist()
    update_changed_v1_templates_in_presets()
    ensure_v1_templates_copied_to_presets()


def _seed_missing_text_files(src_dir: Path, dst_dir: Path) -> None:
    if not src_dir.exists() or not src_dir.is_dir():
        return
    for path in sorted(src_dir.glob("*.txt"), key=lambda item: item.name.lower()):
        if path.name.startswith("_"):
            continue
        dst = dst_dir / path.name
        if dst.exists():
            continue
        try:
            dst.write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            log(f"Seeded support file: {dst}", "DEBUG")
        except Exception as exc:
            log(f"Failed to seed support file {path.name}: {exc}", "DEBUG")


def _seed_missing_strategy_files(src_dir: Path, dst_dir: Path) -> None:
    if not src_dir.exists() or not src_dir.is_dir():
        return
    for path in sorted(list(src_dir.glob("*.txt")) + list(src_dir.glob("*.json")), key=lambda item: item.name.lower()):
        if path.name.startswith("_"):
            continue
        dst = dst_dir / path.name
        if dst.exists():
            continue
        try:
            shutil.copy2(path, dst)
            log(f"Seeded support strategy file: {dst}", "DEBUG")
        except Exception as exc:
            log(f"Failed to seed support strategy file {path.name}: {exc}", "DEBUG")


def _ensure_v1_strategies_exist() -> bool:
    from config import MAIN_DIRECTORY, get_zapret_userdata_dir

    filenames = (
        "tcp_zapret1.txt",
        "udp_zapret1.txt",
        "http80_zapret1.txt",
        "discord_voice_zapret1.txt",
        "discord_udp_zapret1.txt",
    )

    base = (get_zapret_userdata_dir() or "").strip()
    if not base:
        raise RuntimeError("APPDATA user root is required for direct_zapret1 strategies")

    dst_dir = Path(base) / "direct_zapret1"
    dst_dir.mkdir(parents=True, exist_ok=True)

    existing = {path.name.lower() for path in dst_dir.glob("*.txt") if path.is_file()}
    missing = [name for name in filenames if name.lower() not in existing]
    if not missing:
        return True

    src_dir = Path(MAIN_DIRECTORY) / "preset_zapret1" / "basic_strategies"
    if not src_dir.exists() or not src_dir.is_dir():
        return False

    for filename in list(missing):
        src = src_dir / filename
        if not src.exists() or not src.is_file():
            continue
        dst = dst_dir / filename
        try:
            shutil.copy2(src, dst)
            missing.remove(filename)
            log(f"Seeded support strategy file: {dst}", "DEBUG")
        except Exception as exc:
            log(f"Failed to seed support strategy file {filename}: {exc}", "DEBUG")

    return not missing
