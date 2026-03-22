# preset_zapret1/strategies_loader.py
"""Self-contained V1 strategy loader for Zapret 1 (direct_zapret1) mode.

No dependency on strategy_menu/. Reads from %APPDATA%/zapret/direct_zapret1/.

Usage:
    from preset_zapret1.strategies_loader import load_v1_strategies
    strategies = load_v1_strategies("youtube")  # -> {id: {...}, ...}
"""

from __future__ import annotations

import os
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from log import log


_V1_STRATEGY_FILENAMES = (
    "tcp_zapret1.txt",
    "udp_zapret1.txt",
    "http80_zapret1.txt",
    "discord_voice_zapret1.txt",
    "discord_udp_zapret1.txt",
)

# Candidate directories checked in order:
# 1) External folder near app root (single canonical source for V1 strategies)
_SOURCE_DIRS_CACHE: list[Path] | None = None
_MISSING_SOURCE_WARNED = False


def _contains_internal_segment(path: Path) -> bool:
    try:
        return any(part.strip().lower() == "_internal" for part in path.parts)
    except Exception:
        return "\\_internal\\" in str(path).lower().replace("/", "\\")


def get_v1_strategies_dir() -> Path:
    """Canonical directory for direct_zapret1 strategies.

    Only valid runtime location:
      %APPDATA%\\zapret\\direct_zapret1
    """
    try:
        from config import get_zapret_userdata_dir

        base = (get_zapret_userdata_dir() or "").strip()
        if base:
            return Path(base) / "direct_zapret1"
    except Exception:
        pass

    appdata = (os.environ.get("APPDATA") or "").strip()
    if appdata:
        return Path(appdata) / "zapret" / "direct_zapret1"

    return Path.home() / "AppData" / "Roaming" / "zapret" / "direct_zapret1"


def _seed_source_dirs() -> list[Path]:
    dirs: list[Path] = []

    try:
        from config import MAIN_DIRECTORY

        candidate = Path(MAIN_DIRECTORY) / "preset_zapret1" / "basic_strategies"
        if not _contains_internal_segment(candidate):
            dirs.append(candidate)
    except Exception:
        pass

    unique: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        key = str(d)
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


def ensure_v1_strategies_exist() -> bool:
    """Ensure direct_zapret1 strategies exist in the canonical AppData directory."""
    dst_dir = get_v1_strategies_dir()
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log(f"V1 strategies_loader: cannot create {dst_dir}: {e}", "ERROR")
        return False

    existing = {f.name.lower() for f in dst_dir.glob("*.txt") if f.is_file()}
    missing = [name for name in _V1_STRATEGY_FILENAMES if name.lower() not in existing]
    if not missing:
        return True

    copied = 0
    for src_dir in _seed_source_dirs():
        if not src_dir.is_dir():
            continue
        for filename in list(missing):
            src = src_dir / filename
            if not src.exists() or not src.is_file():
                continue

            dst = dst_dir / filename
            try:
                shutil.copy2(src, dst)
                copied += 1
                missing.remove(filename)
                log(f"V1 strategies_loader: seeded {dst}", "DEBUG")
            except Exception as e:
                log(f"V1 strategies_loader: failed to seed {filename}: {e}", "DEBUG")

        if not missing:
            break

    return copied > 0 or not missing


# Backward-compatible export name.
BASIC_STRATEGIES_DIR = get_v1_strategies_dir()

# Кеш: cache_key -> (mtime_ns, size, data)
_CACHE: Dict[str, tuple[int, int, Any]] = {}

# Допустимые значения label
_LABEL_MAP = {
    "recommended": "recommended",
    "stable":      "stable",
    "experimental":"experimental",
    "game":        "game",
    "caution":     "caution",
}


def _strategy_dirs() -> list[Path]:
    """Resolve canonical directory where V1 strategy txt files should exist."""
    global _SOURCE_DIRS_CACHE
    if _SOURCE_DIRS_CACHE is not None:
        return _SOURCE_DIRS_CACHE

    canonical = get_v1_strategies_dir()
    try:
        canonical.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    _SOURCE_DIRS_CACHE = [canonical]
    return _SOURCE_DIRS_CACHE


def _resolve_strategy_file(filename: str) -> Path | None:
    for d in _strategy_dirs():
        try:
            p = d / filename
            if _contains_internal_segment(p):
                continue
            if p.exists() and p.is_file():
                return p
        except Exception:
            continue
    return None


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path)


def _file_sig(path: Path) -> tuple[int, int]:
    st = path.stat()
    mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))
    return mtime_ns, int(st.st_size)


# ── TXT parser ────────────────────────────────────────────────────────────────

def _load_txt(filepath: Path) -> Optional[Dict]:
    """Parse INI-style TXT file → {'strategies': [...]}.

    Format:
        [strategy_id]
        name = Название
        label = recommended|stable|experimental|game|caution
        description = Описание
        --dpi-desync=fake
        --dpi-desync-fake-tls=...
    """
    if not filepath.exists():
        return None

    key = _cache_key(filepath)

    try:
        sig = _file_sig(filepath)
    except Exception:
        sig = (0, 0)

    cached = _CACHE.get(key)
    if cached and (cached[0], cached[1]) == sig:
        return deepcopy(cached[2])

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        log(f"V1 strategies_loader: cannot read {filepath.name}: {e}", "ERROR")
        return None

    strategies = []
    current: Optional[dict] = None
    current_args: list[str] = []

    for line in content.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("[") and line.endswith("]"):
            if current is not None:
                current["args"] = "\n".join(current_args)
                strategies.append(current)
            sid = line[1:-1].strip()
            current = {
                "id": sid, "name": sid,
                "description": "", "label": None, "args": "",
            }
            current_args = []
            continue

        if current is None:
            continue

        if line.startswith("--"):
            current_args.append(line)
            continue

        if "=" in line:
            k, _, v = line.partition("=")
            k = k.strip().lower()
            v = v.strip()
            if k == "name":
                current["name"] = v
            elif k == "label":
                current["label"] = v or None
            elif k == "description":
                current["description"] = v

    if current is not None:
        current["args"] = "\n".join(current_args)
        strategies.append(current)

    result = {"strategies": strategies}
    _CACHE[key] = (sig[0], sig[1], deepcopy(result))
    log(f"V1 strategies_loader: loaded {len(strategies)} from {filepath.name}", "DEBUG")
    return result


# ── Normalization ─────────────────────────────────────────────────────────────

def _normalize(raw: dict) -> dict:
    label_raw = str(raw.get("label") or "").lower()
    return {
        "id":          raw.get("id", ""),
        "name":        raw.get("name", "Без названия"),
        "description": raw.get("description", ""),
        "label":       _LABEL_MAP.get(label_raw),
        "args":        raw.get("args", "").strip(),
        "_source":     "builtin",
    }


def _is_valid_id(sid: str) -> bool:
    return bool(sid) and all(c.isalnum() or c == "_" for c in sid)


# ── Public API ────────────────────────────────────────────────────────────────

def load_v1_strategies(category: str) -> Dict[str, Dict]:
    """Return {strategy_id: strategy_dict} for the given V1 category.

    Maps category name → file in %APPDATA%/zapret/direct_zapret1/:
        udp_* / *_udp       → udp_zapret1.txt
        discord_voice_*     → discord_voice_zapret1.txt (fallback udp_zapret1.txt)
        http80_* / *_http80 → http80_zapret1.txt (fallback tcp_zapret1.txt)
        everything else     → tcp_zapret1.txt
    """
    global _MISSING_SOURCE_WARNED

    ensure_v1_strategies_exist()

    cat = category.lower()
    if cat == "udp" or cat.endswith("_udp") or cat.startswith("udp_"):
        candidates = ["udp_zapret1"]
    elif "discord_voice" in cat or cat.endswith("_voice"):
        candidates = ["discord_voice_zapret1", "udp_zapret1"]
    elif cat == "http80" or cat.endswith("_http80"):
        candidates = ["http80_zapret1", "tcp_zapret1"]
    else:
        candidates = ["tcp_zapret1"]

    raw_data: Optional[Dict] = None
    for basename in candidates:
        file_path = _resolve_strategy_file(f"{basename}.txt")
        if not file_path:
            continue

        raw_data = _load_txt(file_path)
        if raw_data:
            log(
                f"V1: '{category}' → {file_path.name} "
                f"({len(raw_data.get('strategies', []))} стратегий)",
                "DEBUG",
            )
            break

    if not raw_data:
        if not _MISSING_SOURCE_WARNED:
            _MISSING_SOURCE_WARNED = True
            dirs = ", ".join(str(p) for p in _strategy_dirs())
            log(
                "V1 strategies_loader: files not found in known locations: "
                f"{dirs}",
                "WARNING",
            )
        return {}

    result: Dict[str, Dict] = {}
    for strat in raw_data.get("strategies", []):
        sid = strat.get("id", "").strip()
        if not _is_valid_id(sid):
            continue
        result[sid] = _normalize(strat)

    return result


def invalidate_cache(filepath: Optional[Path] = None) -> None:
    """Invalidate cache for a specific file (or clear all if None)."""
    if filepath is None:
        _CACHE.clear()
    else:
        _CACHE.pop(_cache_key(filepath), None)
