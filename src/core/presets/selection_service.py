from __future__ import annotations

import json
from pathlib import Path

from core.paths import AppPaths

from .models import PresetDocument
from .repository import PresetRepository


class PresetSelectionService:
    def __init__(self, paths: AppPaths, repository: PresetRepository):
        self._paths = paths
        self._repository = repository

    def get_selected_file_name(self, engine: str) -> str | None:
        path = self._selection_path(engine)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        value = str(payload.get("selected_file_name") or "").strip()
        if value:
            return value
        legacy_id = str(payload.get("selected_preset_id") or "").strip()
        if legacy_id:
            return self._repository.resolve_legacy_id(engine, legacy_id)
        return None

    def get_selected_preset_id(self, engine: str) -> str | None:
        return self.get_selected_file_name(engine)

    def get_selected_preset(self, engine: str) -> PresetDocument | None:
        file_name = self.get_selected_file_name(engine)
        if not file_name:
            return None
        return self._repository.get_preset(engine, file_name)

    def select_preset(self, engine: str, file_name: str) -> PresetDocument:
        preset = self._repository.get_preset(engine, file_name)
        if preset is None:
            raise ValueError(f"Preset not found: {file_name}")
        path = self._selection_path(engine)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"selected_file_name": preset.manifest.file_name}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return preset

    def clear_selection(self, engine: str) -> None:
        try:
            self._selection_path(engine).unlink()
        except FileNotFoundError:
            pass

    def ensure_can_delete(self, engine: str, file_name: str) -> None:
        selected_file_name = self.get_selected_file_name(engine)
        if selected_file_name and selected_file_name.strip().lower() == str(file_name or "").strip().lower():
            raise ValueError("Cannot delete the selected preset")

    def ensure_selected_preset(self, engine: str, preferred_file_name: str | None = "Default.txt") -> PresetDocument | None:
        current = self.get_selected_preset(engine)
        if current is not None:
            return current

        preferred_key = str(preferred_file_name or "").strip()
        if preferred_key:
            preferred = self._repository.get_preset(engine, preferred_key)
            if preferred is not None:
                return self.select_preset(engine, preferred.manifest.file_name)

        presets = self._repository.list_presets(engine)
        if not presets:
            return None
        return self.select_preset(engine, presets[0].manifest.file_name)

    def _selection_path(self, engine: str) -> Path:
        return self._paths.engine_paths(engine).ensure_directories().selected_state_path
