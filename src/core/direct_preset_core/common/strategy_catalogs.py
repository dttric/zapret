from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Optional

from core.paths import AppPaths
from core.presets.strategy_catalog_sanitizer import sanitize_strategy_catalog_dir


@dataclass(frozen=True)
class StrategyEntry:
    strategy_id: str
    catalog_name: str
    name: str
    args: str


def _package_catalog_root() -> Path:
    return Path(__file__).resolve().parents[1] / "catalogs"


def _user_catalog_root(paths: AppPaths) -> Path:
    return paths.user_root / "direct_preset_core" / "catalogs"


def ensure_user_catalogs(paths: AppPaths) -> Path:
    package_root = _package_catalog_root()
    user_root = _user_catalog_root(paths)
    user_root.mkdir(parents=True, exist_ok=True)

    for src in package_root.rglob("*.txt"):
        relative = src.relative_to(package_root)
        dst = user_root / relative
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    sanitize_strategy_catalog_dir(user_root / "winws1")
    sanitize_strategy_catalog_dir(user_root / "winws2")
    return user_root


def _parse_catalog_file(path: Path, catalog_name: str) -> dict[str, StrategyEntry]:
    strategies: dict[str, StrategyEntry] = {}
    current_id: Optional[str] = None
    current_name = ""
    current_args: list[str] = []

    def _flush() -> None:
        nonlocal current_id, current_name, current_args
        if not current_id:
            return
        strategies[current_id] = StrategyEntry(
            strategy_id=current_id,
            catalog_name=catalog_name,
            name=current_name or current_id,
            args="\n".join(line for line in current_args if line).strip(),
        )

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            _flush()
            current_id = stripped[1:-1].strip()
            current_name = current_id
            current_args = []
            continue
        if current_id is None:
            continue
        if stripped.startswith("--"):
            current_args.append(stripped)
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            if key.strip().lower() == "name":
                current_name = value.strip()

    _flush()
    return strategies


def load_strategy_catalogs(paths: AppPaths, engine: str) -> dict[str, dict[str, StrategyEntry]]:
    root = ensure_user_catalogs(paths)
    engine_root = root / engine
    catalogs: dict[str, dict[str, StrategyEntry]] = {}
    for path in sorted(engine_root.glob("*.txt")):
        catalogs[path.stem.lower()] = _parse_catalog_file(path, path.stem.lower())
    return catalogs
