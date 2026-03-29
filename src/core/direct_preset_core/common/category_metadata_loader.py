from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional


_CACHED_CATEGORIES: Optional[Dict[str, Dict]] = None


def load_categories_metadata() -> Dict[str, Dict]:
    global _CACHED_CATEGORIES
    if _CACHED_CATEGORIES is not None:
        return _CACHED_CATEGORIES

    builtin = _load_one(_categories_file_path())
    merged = dict(builtin)

    for key, data in _load_one(_user_categories_file_path()).items():
        if key in merged:
            continue
        merged[key] = data

    _CACHED_CATEGORIES = merged
    return _CACHED_CATEGORIES


def invalidate_categories_metadata_cache() -> None:
    global _CACHED_CATEGORIES
    _CACHED_CATEGORIES = None


def _categories_file_path() -> Path:
    for base in _candidate_indexjson_dirs():
        candidate = base / "strategies" / "builtin" / "categories.txt"
        if candidate.exists():
            return candidate
    return Path("__missing_categories__.txt")


def _candidate_indexjson_dirs() -> list[Path]:
    out: list[Path] = []

    env = os.environ.get("ZAPRET_INDEXJSON_FOLDER")
    if env:
        out.append(Path(env))

    try:
        from config import INDEXJSON_FOLDER  # type: ignore

        out.append(Path(INDEXJSON_FOLDER))
    except Exception:
        pass

    try:
        here = Path(__file__).resolve()
        repo_root = here.parents[5]
        out.append(repo_root / "private_zapretgui" / "dist" / "json")
        out.append(repo_root / "private_zapretgui" / "stage" / "installer_root" / "json")
        out.append(repo_root / "json")
    except Exception:
        pass

    out.append(Path.cwd() / "json")
    out.append(Path("/mnt/c/ProgramData/ZapretTwoDev/json"))
    out.append(Path("/mnt/c/ProgramData/ZapretTwo/json"))

    unique: list[Path] = []
    seen: set[str] = set()
    for path in out:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _user_categories_file_path() -> Path:
    try:
        from config import get_zapret_userdata_dir

        base = (get_zapret_userdata_dir() or "").strip()
        if base:
            return Path(base) / "user_categories.txt"
    except Exception:
        pass

    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "zapret" / "user_categories.txt"
    return Path.home() / ".config" / "zapret" / "user_categories.txt"


def _load_one(path: Path) -> Dict[str, Dict]:
    if not path.exists() or not path.is_file():
        return {}

    categories: Dict[str, Dict] = {}
    current_key: Optional[str] = None
    current: Dict[str, object] = {}
    section_index = 0

    def flush() -> None:
        nonlocal current_key, current
        if not current_key:
            return
        file_order = current.get("_file_order")
        if isinstance(file_order, int):
            current["order"] = file_order
            current["command_order"] = file_order
        categories[current_key] = dict(current)

    text = path.read_text(encoding="utf-8", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            flush()
            current_key = line[1:-1].strip().lower()
            section_index += 1
            current = {"key": current_key, "_file_order": section_index}
            continue
        if "=" not in line or current_key is None:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        if key in ("order", "command_order"):
            continue
        if key in ("needs_new_separator", "strip_payload", "requires_all_ports"):
            current[key] = value.lower() in ("true", "1", "yes", "y", "on")
            continue
        current[key] = value

    flush()
    return categories
