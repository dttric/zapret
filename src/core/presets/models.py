from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresetManifest:
    file_name: str
    name: str
    created_at: str
    updated_at: str
    kind: str = "user"
    legacy_id: str | None = None


@dataclass(frozen=True)
class PresetDocument:
    manifest: PresetManifest
    source_text: str
