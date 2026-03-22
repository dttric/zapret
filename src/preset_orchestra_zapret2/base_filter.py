"""
Build category base filter lines for preset-zapret2.txt.

The GUI stores the active preset as a winws2 config-like text file where each
category block starts with a "base filter" (ports/L7 + hostlist/ipset/etc).

This module builds these base filter lines from `categories.txt` (loaded via
`preset_zapret2.catalog`) and normalizes list filenames to paths that winws2
can resolve from the app working directory (typically `lists/...`).
"""

from __future__ import annotations

import os
import re
from pathlib import PureWindowsPath
from typing import List, Optional

from log import log


def _is_windows_abs(path: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\\\/]", path)) or path.startswith("\\\\")


def _normalize_lists_value(value: str, main_directory: str, lists_folder: str) -> str:
    value = value.strip().strip('"').strip("'")
    if value.startswith("@"):
        value = value[1:]

    # Already absolute (Windows) or POSIX absolute: keep if outside the app,
    # but relativize if it's inside MAIN_DIRECTORY / lists.
    if _is_windows_abs(value) or os.path.isabs(value):
        try:
            rel_lists = PureWindowsPath(value).relative_to(PureWindowsPath(lists_folder))
        except Exception:
            rel_lists = None

        if rel_lists is not None:
            return f"lists/{rel_lists.as_posix()}"

        try:
            rel_main = PureWindowsPath(value).relative_to(PureWindowsPath(main_directory))
        except Exception:
            rel_main = None

        if rel_main is not None:
            return rel_main.as_posix()

        return str(PureWindowsPath(os.path.normpath(value)))

    # If the value already contains folders (lists/..., json/... etc), keep relative structure.
    if "/" in value or "\\" in value:
        return PureWindowsPath(value).as_posix()

    # Bare filename -> assume lists/ folder.
    return f"lists/{value}"


def _split_tokens(s: str) -> List[str]:
    return [t.strip() for t in re.split(r"\s+", s.strip()) if t.strip()]


def get_category_base_filter_template(category_key: str, filter_mode: str) -> Optional[str]:
    """
    Returns the base filter template for a category.

    Preference:
    - filter_mode == "ipset" -> base_filter_ipset
    - filter_mode == "hostlist" -> base_filter_hostlist
    - fallback -> base_filter (or any available variant)
    """
    try:
        from .catalog import load_categories
        info = load_categories().get(category_key) or {}
    except Exception as e:
        log(f"Cannot load categories for base_filter: {e}", "DEBUG")
        info = {}

    # Fallback: if the lightweight catalog couldn't find categories (e.g. running
    # from source/dev layouts), reuse the main strategy_menu loader which has
    # additional path fallbacks.
    if not info:
        try:
            from strategy_menu.strategy_loader import load_categories as _load_categories_sm

            info = _load_categories_sm().get(category_key) or {}
        except Exception as e:
            log(f"Cannot load categories (strategy_menu fallback) for base_filter: {e}", "DEBUG")
            info = {}

    filter_mode = (filter_mode or "").strip().lower()
    candidates = []
    if filter_mode == "ipset":
        candidates.append(info.get("base_filter_ipset"))
    if filter_mode == "hostlist":
        candidates.append(info.get("base_filter_hostlist"))
    candidates.append(info.get("base_filter"))
    candidates.append(info.get("base_filter_ipset"))
    candidates.append(info.get("base_filter_hostlist"))

    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
    return None


def build_category_base_filter_lines(category_key: str, filter_mode: str) -> List[str]:
    """
    Builds base filter lines (one arg per line) for writing to preset-zapret2.txt.

    Normalizes list filenames in --hostlist/--ipset/--*-exclude to `lists/...`.
    """
    template = get_category_base_filter_template(category_key, filter_mode)
    if not template:
        return []

    try:
        from config import MAIN_DIRECTORY, LISTS_FOLDER
        main_directory = MAIN_DIRECTORY
        lists_folder = LISTS_FOLDER
    except Exception:
        main_directory = ""
        lists_folder = ""

    lines: List[str] = []
    for token in _split_tokens(template):
        key, sep, value = token.partition("=")
        key_l = key.lower()

        if not sep:
            lines.append(token)
            continue

        if key_l in ("--hostlist", "--ipset", "--hostlist-exclude", "--ipset-exclude"):
            norm_value = _normalize_lists_value(value, main_directory, lists_folder)
            lines.append(f"{key}={norm_value}")
            continue

        lines.append(token)

    return lines
