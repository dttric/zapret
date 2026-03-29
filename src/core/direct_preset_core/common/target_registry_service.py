from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from .target_metadata_loader import load_target_metadata


@dataclass(frozen=True)
class TargetMetadata:
    target_key: str
    base_key: str
    display_name: str
    protocol: str
    ports: str
    command_group: str
    order: int
    icon_name: str
    icon_color: str
    description: str = ""
    tooltip: str = ""
    strategy_type: str = "tcp"
    base_filter_hostlist: str = ""
    base_filter_ipset: str = ""


def _humanize_base_key(base_key: str) -> str:
    parts = [part for part in str(base_key or "").replace("-", "_").split("_") if part]
    if not parts:
        return "Target"
    return " ".join(part[:1].upper() + part[1:] for part in parts)


class TargetRegistryService:
    def _load_target_metadata(self) -> dict:
        # Canonical target registry must enrich only normal parser-derived target keys.
        return load_target_metadata()

    @staticmethod
    def base_key_from_target_key(target_key: str) -> str:
        text = str(target_key or "").strip().lower()
        for suffix in ("_tcp", "_udp", "_l7"):
            if text.endswith(suffix):
                return text[: -len(suffix)]
        return text

    @staticmethod
    def protocol_from_target_key(target_key: str) -> str:
        text = str(target_key or "").strip().lower()
        if text.endswith("_udp"):
            return "UDP"
        if text.endswith("_l7"):
            return "L7"
        return "TCP"

    def get_metadata(self, target_key: str) -> TargetMetadata:
        normalized_target_key = str(target_key or "").strip().lower()
        base_key = self.base_key_from_target_key(normalized_target_key)
        protocol = self.protocol_from_target_key(normalized_target_key)
        items = self._load_target_metadata()

        # Prefer exact protocol-specific entry (e.g. amazon_tcp, discord_udp).
        # Fall back to the base key only when the catalog defines a shared entry
        # like [youtube] for multiple protocol variants.
        raw = items.get(normalized_target_key) or items.get(base_key) or {}
        display_name = str(raw.get("full_name") or _humanize_base_key(base_key)).strip() or target_key
        ports = str(raw.get("ports") or "").strip()
        strategy_type = str(raw.get("strategy_type") or "").strip().lower() or ("udp" if protocol == "UDP" else "tcp")
        return TargetMetadata(
            target_key=normalized_target_key,
            base_key=base_key,
            display_name=display_name,
            protocol=str(raw.get("protocol") or protocol).strip() or protocol,
            ports=ports,
            command_group=str(raw.get("command_group") or "default").strip() or "default",
            order=int(raw.get("order", 999) or 999),
            icon_name=str(raw.get("icon_name") or "fa5s.globe").strip() or "fa5s.globe",
            icon_color=str(raw.get("icon_color") or "#2196F3").strip() or "#2196F3",
            description=str(raw.get("description") or "").strip(),
            tooltip=str(raw.get("tooltip") or "").replace("\\n", "\n"),
            strategy_type=strategy_type,
            base_filter_hostlist=str(raw.get("base_filter_hostlist") or "").strip(),
            base_filter_ipset=str(raw.get("base_filter_ipset") or "").strip(),
        )

    def build_ui_item(self, target_key: str):
        meta = self.get_metadata(target_key)
        return SimpleNamespace(
            key=meta.target_key,
            full_name=meta.display_name,
            description=meta.description,
            tooltip=meta.tooltip,
            protocol=meta.protocol,
            ports=meta.ports,
            order=meta.order,
            command_order=meta.order,
            command_group=meta.command_group,
            icon_name=meta.icon_name,
            icon_color=meta.icon_color,
            base_filter="",
            base_filter_hostlist=meta.base_filter_hostlist,
            base_filter_ipset=meta.base_filter_ipset,
            strategy_type=meta.strategy_type,
        )
