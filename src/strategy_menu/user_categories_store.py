from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Dict, Optional

from log import log


def get_user_categories_file_path() -> Path:
    """
    Single user categories file shared across direct modes.

    Windows: %APPDATA%/zapret/user_categories.txt
    Fallback: ~/.config/zapret/user_categories.txt
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "zapret" / "user_categories.txt"
    return Path.home() / ".config" / "zapret" / "user_categories.txt"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _encode_value(value: str) -> str:
    # Keep categories.txt format: newlines inside values are stored as literal "\n"
    return (value or "").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def parse_categories_txt(content: str) -> Optional[dict]:
    """
    Parses categories.txt (INI-like) content into:
      {'version': str, 'description': str, 'categories': [dict, ...]}
    """
    try:
        categories = []
        file_version = "1.0"
        file_description = ""
        current_category = None

        for raw_line in (content or "").splitlines():
            line = raw_line.strip()

            # Comments / empty
            if not line or line.startswith("#"):
                continue

            # Section header
            if line.startswith("[") and line.endswith("]"):
                if current_category is not None:
                    categories.append(current_category)
                key = line[1:-1].strip()
                current_category = {"key": key}
                continue

            # key=value
            if "=" in line:
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip()

                if current_category is None:
                    # Global metadata
                    if k == "version":
                        file_version = v
                    elif k == "description":
                        file_description = v
                    continue

                # Category metadata
                if k in ("description", "tooltip", "full_name"):
                    # Keep raw value (tooltips may contain literal "\n" sequences)
                    current_category[k] = v
                elif k in ("order", "command_order"):
                    try:
                        current_category[k] = int(v)
                    except ValueError:
                        current_category[k] = 0
                elif k in ("needs_new_separator", "strip_payload", "requires_all_ports"):
                    current_category[k] = v.lower() in ("true", "1", "yes", "y", "on")
                else:
                    current_category[k] = v

        if current_category is not None:
            categories.append(current_category)

        return {"version": file_version, "description": file_description, "categories": categories}
    except Exception as e:
        log(f"parse_categories_txt failed: {e}", "WARNING")
        return None


def dump_categories_txt(
    categories: Dict[str, dict],
    *,
    version: str = "1.0",
    description: str = "Пользовательские категории сервисов",
) -> str:
    lines = []
    lines.append("# User categories configuration")
    lines.append(f"version = {version}")
    lines.append(f"description = {_encode_value(description)}")
    lines.append("")

    for key in sorted(categories.keys(), key=lambda x: x.lower()):
        data = categories[key] or {}
        cat_key = str(data.get("key") or key).strip()
        if not cat_key:
            continue
        lines.append(f"[{cat_key}]")

        # Keep a stable-ish order for common keys, then add the rest.
        preferred = [
            "full_name",
            "description",
            "tooltip",
            "color",
            "default_strategy",
            "ports",
            "protocol",
            "order",
            "command_order",
            "needs_new_separator",
            "command_group",
            "icon_name",
            "icon_color",
            "base_filter",
            "base_filter_ipset",
            "base_filter_hostlist",
            "strategy_type",
            "strip_payload",
            "requires_all_ports",
        ]

        emitted = set()
        for k in preferred:
            if k in data and data.get(k) is not None and k != "key":
                v = data.get(k)
                if isinstance(v, bool):
                    vv = "true" if v else "false"
                else:
                    vv = str(v)
                    if k in ("full_name", "description", "tooltip"):
                        vv = _encode_value(vv)
                lines.append(f"{k} = {vv}")
                emitted.add(k)

        for k in sorted(data.keys(), key=lambda x: str(x).lower()):
            if k in emitted or k == "key" or k.startswith("_"):
                continue
            v = data.get(k)
            if v is None:
                continue
            if isinstance(v, bool):
                vv = "true" if v else "false"
            else:
                vv = str(v)
            lines.append(f"{k} = {vv}")

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def load_user_categories() -> Dict[str, dict]:
    path = get_user_categories_file_path()
    if not path.exists():
        return {}

    data = parse_categories_txt(_read_text(path))
    if not data or "categories" not in data:
        return {}

    out: Dict[str, dict] = {}
    for cat in data.get("categories") or []:
        try:
            key = str(cat.get("key") or "").strip()
        except Exception:
            key = ""
        if not key:
            continue
        cat = dict(cat)
        cat["_source"] = "user"
        out[key] = cat
    return out


def save_user_categories(categories: Dict[str, dict]) -> tuple[bool, str]:
    path = get_user_categories_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, f"Не удалось создать папку: {e}"

    text = dump_categories_txt(categories)
    try:
        path.write_text(text, encoding="utf-8", errors="replace")
        return True, ""
    except Exception as e:
        return False, f"Ошибка записи файла: {e}"


def upsert_user_category(category: dict, *, system_keys: set[str]) -> tuple[bool, str]:
    key = str((category or {}).get("key") or "").strip()
    if not key:
        return False, "Введите ключ категории"

    if key in (system_keys or set()):
        return False, f"Ключ '{key}' занят системной категорией"

    cats = load_user_categories()
    cat = dict(category)
    cat["_source"] = "user"
    cats[key] = cat
    return save_user_categories(cats)


def delete_user_category(key: str) -> tuple[bool, str]:
    key = str(key or "").strip()
    if not key:
        return False, "Отсутствует key категории"

    cats = load_user_categories()
    if key not in cats:
        return False, f"Категория '{key}' не найдена"
    cats.pop(key, None)
    return save_user_categories(cats)
