# preset_zapret1/preset_model.py
"""Data models for Zapret 1 preset system.

Simplified version without SyndataSettings.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


DEFAULT_PRESET_ICON_COLOR = "#60cdff"
_HEX_COLOR_RGB_RE = re.compile(r"^#(?:[0-9a-fA-F]{6})$")
_HEX_COLOR_RGBA_RE = re.compile(r"^#(?:[0-9a-fA-F]{8})$")


def normalize_preset_icon_color_v1(value: Optional[str]) -> str:
    raw = str(value or "").strip()
    if _HEX_COLOR_RGB_RE.fullmatch(raw):
        return raw.lower()
    if _HEX_COLOR_RGBA_RE.fullmatch(raw):
        lowered = raw.lower()
        return f"#{lowered[1:7]}"
    return DEFAULT_PRESET_ICON_COLOR


@dataclass
class CategoryConfigV1:
    """Configuration for a single category in Zapret 1 preset.

    No SyndataSettings — Zapret 1 (winws.exe) doesn't support Lua.
    """
    name: str
    strategy_id: str = "none"
    tcp_args: str = ""
    udp_args: str = ""
    tcp_enabled: bool = True
    udp_enabled: bool = True
    filter_mode: str = "hostlist"  # "hostlist" | "ipset"
    tcp_port: str = "443"
    udp_port: str = "443"
    sort_order: str = "default"

    def get_hostlist_file(self) -> str:
        return f"lists/{self.name}.txt"

    def get_ipset_file(self) -> str:
        return f"lists/ipset-{self.name}.txt"

    def get_filter_file(self) -> str:
        if self.filter_mode == "ipset":
            return self.get_ipset_file()
        return self.get_hostlist_file()

    def has_tcp(self) -> bool:
        return bool(self.tcp_args.strip())

    def has_udp(self) -> bool:
        return bool(self.udp_args.strip())

    def get_full_tcp_args(self) -> str:
        """Returns TCP args (no syndata/send in V1)."""
        return self.tcp_args

    def get_full_udp_args(self) -> str:
        """Returns UDP args (no out-range in V1)."""
        return self.udp_args

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "strategy_id": self.strategy_id,
            "tcp_args": self.tcp_args,
            "udp_args": self.udp_args,
            "tcp_enabled": self.tcp_enabled,
            "udp_enabled": self.udp_enabled,
            "filter_mode": self.filter_mode,
            "tcp_port": self.tcp_port,
            "udp_port": self.udp_port,
            "sort_order": self.sort_order,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "CategoryConfigV1":
        return cls(
            name=data.get("name", "unknown"),
            strategy_id=data.get("strategy_id", "none"),
            tcp_args=data.get("tcp_args", ""),
            udp_args=data.get("udp_args", ""),
            tcp_enabled=data.get("tcp_enabled", True),
            udp_enabled=data.get("udp_enabled", True),
            filter_mode=data.get("filter_mode", "hostlist"),
            tcp_port=data.get("tcp_port", "443"),
            udp_port=data.get("udp_port", "443"),
            sort_order=data.get("sort_order", "default"),
        )


@dataclass
class PresetV1:
    """Complete Zapret 1 preset configuration."""
    name: str
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    modified: str = field(default_factory=lambda: datetime.now().isoformat())
    description: str = ""
    icon_color: str = DEFAULT_PRESET_ICON_COLOR
    categories: Dict[str, CategoryConfigV1] = field(default_factory=dict)
    base_args: str = ""

    # Default base args for new V1 presets (no --lua-init)
    DEFAULT_BASE_ARGS = "--wf-tcp=443\n--wf-udp=443"

    def __post_init__(self):
        self.icon_color = normalize_preset_icon_color_v1(self.icon_color)
        if not self.base_args:
            self.base_args = self.DEFAULT_BASE_ARGS

    def get_category(self, name: str) -> Optional[CategoryConfigV1]:
        return self.categories.get(name)

    def set_category(self, config: CategoryConfigV1) -> None:
        self.categories[config.name] = config
        self.touch()

    def remove_category(self, name: str) -> bool:
        if name in self.categories:
            del self.categories[name]
            self.touch()
            return True
        return False

    def list_categories(self) -> List[str]:
        return list(self.categories.keys())

    def touch(self) -> None:
        self.modified = datetime.now().isoformat()

    def get_enabled_categories(self) -> List[CategoryConfigV1]:
        result = []
        for cat in self.categories.values():
            if (cat.tcp_enabled and cat.has_tcp()) or (cat.udp_enabled and cat.has_udp()):
                result.append(cat)
        return result

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "created": self.created,
            "modified": self.modified,
            "description": self.description,
            "icon_color": self.icon_color,
            "base_args": self.base_args,
            "categories": {name: cat.to_dict() for name, cat in self.categories.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "PresetV1":
        categories = {}
        for name, cat_data in data.get("categories", {}).items():
            categories[name] = CategoryConfigV1.from_dict(cat_data)
        return cls(
            name=data.get("name", "Unnamed"),
            created=data.get("created", datetime.now().isoformat()),
            modified=data.get("modified", datetime.now().isoformat()),
            description=data.get("description", ""),
            icon_color=data.get("icon_color", DEFAULT_PRESET_ICON_COLOR),
            base_args=data.get("base_args", ""),
            categories=categories,
        )


def validate_preset_v1(preset: PresetV1) -> List[str]:
    """Validates V1 preset configuration."""
    errors = []
    if not preset.name or not preset.name.strip():
        errors.append("Preset name is required")
    if not preset.base_args or not preset.base_args.strip():
        errors.append("Base arguments are required")
    return errors
