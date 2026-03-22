from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Iterable, Optional, Set, Tuple


MarkKey = Tuple[str, str]  # (category_key, strategy_id)


def _get_direct_zapret2_dir() -> Path:
    """
    Storage dir for direct_zapret2 auxiliary data.

    Windows: %APPDATA%/zapret/direct_zapret2
    Fallback: ~/.config/zapret/direct_zapret2
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "zapret" / "direct_zapret2"
    return Path.home() / ".config" / "zapret" / "direct_zapret2"


def _parse_marks_lines(lines: Iterable[str]) -> Set[MarkKey]:
    out: Set[MarkKey] = set()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" not in line:
            continue
        cat, sid = line.split("\t", 1)
        cat = cat.strip()
        sid = sid.strip()
        if not cat or not sid:
            continue
        out.add((cat, sid))
    return out


def _format_marks_lines(keys: Set[MarkKey]) -> str:
    parts = [f"{cat}\t{sid}" for cat, sid in sorted(keys, key=lambda x: (x[0].lower(), x[1].lower()))]
    return ("\n".join(parts) + "\n") if parts else ""

def _try_load_registry_ratings() -> tuple[Set[MarkKey], Set[MarkKey]]:
    """
    Best-effort import of legacy ratings stored in registry via strategy_menu.

    Returns:
        (work_keys, notwork_keys)
    """
    try:
        from strategy_menu import get_all_strategy_ratings  # type: ignore
    except Exception:
        return set(), set()

    try:
        raw = get_all_strategy_ratings()
    except Exception:
        return set(), set()

    work: Set[MarkKey] = set()
    notwork: Set[MarkKey] = set()
    if not isinstance(raw, dict):
        return work, notwork

    for cat, per_cat in raw.items():
        if not isinstance(cat, str) or not isinstance(per_cat, dict):
            continue
        for sid, rating in per_cat.items():
            if not isinstance(sid, str):
                continue
            if rating == "working":
                work.add((cat, sid))
            elif rating == "broken":
                notwork.add((cat, sid))

    notwork.difference_update(work)
    return work, notwork


def _try_load_registry_favorites() -> Set[MarkKey]:
    """
    Best-effort import of legacy favorites stored in registry via strategy_menu.

    Returns:
        Set[(category_key, strategy_id)]
    """
    try:
        from strategy_menu import get_favorite_strategies  # type: ignore
    except Exception:
        return set()

    try:
        raw = get_favorite_strategies()
    except Exception:
        return set()

    out: Set[MarkKey] = set()
    if not isinstance(raw, dict):
        return out

    for cat, sids in raw.items():
        if not isinstance(cat, str):
            continue
        if not isinstance(sids, (list, tuple, set)):
            continue
        for sid in sids:
            if not isinstance(sid, str):
                continue
            sid = sid.strip()
            if sid:
                out.add((cat, sid))
    return out


@dataclass
class DirectZapret2MarksStore:
    """
    Marks for strategies (working / not working / unmarked).

    Stored as two plain text files:
    - work.txt
    - notwork.txt
    Each line: <category_key>\\t<strategy_id>
    """

    work_path: Path
    notwork_path: Path
    _work: Optional[Set[MarkKey]] = None
    _notwork: Optional[Set[MarkKey]] = None

    @classmethod
    def default(cls) -> "DirectZapret2MarksStore":
        base = _get_direct_zapret2_dir()
        return cls(work_path=base / "work.txt", notwork_path=base / "notwork.txt")

    def _ensure_loaded(self) -> None:
        if self._work is not None and self._notwork is not None:
            return
        self._work = set()
        self._notwork = set()

        work_exists = self.work_path.exists()
        notwork_exists = self.notwork_path.exists()

        if work_exists:
            self._work = _parse_marks_lines(self.work_path.read_text(encoding="utf-8", errors="ignore").splitlines())
        if notwork_exists:
            self._notwork = _parse_marks_lines(self.notwork_path.read_text(encoding="utf-8", errors="ignore").splitlines())

        # First-run migration from legacy registry ratings -> AppData files.
        # Only when files are missing, to avoid "resurrecting" cleared marks.
        if (not work_exists and not notwork_exists) and (not self._work and not self._notwork):
            work, notwork = _try_load_registry_ratings()
            if work or notwork:
                self._work = set(work)
                self._notwork = set(notwork)
                self._save()

        # Enforce exclusivity (prefer work if duplicates exist)
        self._notwork.difference_update(self._work)

    def get_mark(self, category_key: str, strategy_id: str) -> Optional[bool]:
        self._ensure_loaded()
        key = (category_key, strategy_id)
        if key in self._work:
            return True
        if key in self._notwork:
            return False
        return None

    def set_mark(self, category_key: str, strategy_id: str, is_working: Optional[bool]) -> None:
        self._ensure_loaded()
        key = (category_key, strategy_id)
        self._work.discard(key)
        self._notwork.discard(key)
        if is_working is True:
            self._work.add(key)
        elif is_working is False:
            self._notwork.add(key)
        self._save()

    def _save(self) -> None:
        base = self.work_path.parent
        base.mkdir(parents=True, exist_ok=True)

        self.work_path.write_text(_format_marks_lines(self._work), encoding="utf-8")
        self.notwork_path.write_text(_format_marks_lines(self._notwork), encoding="utf-8")


@dataclass
class DirectZapret2FavoritesStore:
    """
    Favorites for strategies.

    Stored as a plain text file:
    - favorites.txt
    Each line: <category_key>\\t<strategy_id>
    """

    favorites_path: Path
    _favorites: Optional[Set[MarkKey]] = None

    @classmethod
    def default(cls) -> "DirectZapret2FavoritesStore":
        base = _get_direct_zapret2_dir()
        return cls(favorites_path=base / "favorites.txt")

    def _ensure_loaded(self) -> None:
        if self._favorites is not None:
            return
        self._favorites = set()
        if self.favorites_path.exists():
            self._favorites = _parse_marks_lines(
                self.favorites_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            )
            return

        # First-run migration from legacy registry favorites -> AppData file.
        migrated = _try_load_registry_favorites()
        if migrated:
            self._favorites = set(migrated)
            self._save()

    def get_favorites(self, category_key: str) -> Set[str]:
        self._ensure_loaded()
        cat = (category_key or "").strip()
        if not cat:
            return set()
        return {sid for c, sid in self._favorites if c == cat}

    def is_favorite(self, category_key: str, strategy_id: str) -> bool:
        self._ensure_loaded()
        return (category_key, strategy_id) in self._favorites

    def set_favorite(self, category_key: str, strategy_id: str, favorite: bool) -> None:
        self._ensure_loaded()
        key = ((category_key or "").strip(), (strategy_id or "").strip())
        if not key[0] or not key[1]:
            return
        if favorite:
            self._favorites.add(key)
        else:
            self._favorites.discard(key)
        self._save()

    def _save(self) -> None:
        base = self.favorites_path.parent
        base.mkdir(parents=True, exist_ok=True)
        self.favorites_path.write_text(_format_marks_lines(self._favorites), encoding="utf-8")
