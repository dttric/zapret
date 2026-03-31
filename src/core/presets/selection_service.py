from __future__ import annotations

import json
from pathlib import Path

from core.paths import AppPaths

from .models import PresetManifest
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
        return str(payload.get("selected_file_name") or "").strip() or None

    def get_selected_manifest(self, engine: str) -> PresetManifest | None:
        file_name = self.get_selected_file_name(engine)
        if not file_name:
            return None
        return self._repository.get_manifest(engine, file_name)

    def select_preset(self, engine: str, file_name: str) -> PresetManifest:
        preset = self._repository.get_manifest(engine, file_name)
        if preset is None:
            raise ValueError(f"Preset not found: {file_name}")
        path = self._selection_path(engine)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"selected_file_name": preset.file_name}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return preset

    def select_preset_file_name_fast(self, engine: str, file_name: str) -> str:
        """Direct selection path that does not depend on preset index.json."""
        candidate = str(file_name or "").strip()
        if not candidate:
            raise ValueError("Preset file name is required")

        presets_dir = self._paths.engine_paths(engine).ensure_directories().presets_dir
        preset_path = presets_dir / candidate
        if not preset_path.exists():
            raise ValueError(f"Preset not found: {file_name}")

        path = self._selection_path(engine)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"selected_file_name": candidate}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return candidate

    def clear_selection(self, engine: str) -> None:
        try:
            self._selection_path(engine).unlink()
        except FileNotFoundError:
            pass

    def ensure_can_delete(self, engine: str, file_name: str) -> None:
        selected_file_name = self.get_selected_file_name(engine)
        if selected_file_name and selected_file_name.strip().lower() == str(file_name or "").strip().lower():
            raise ValueError("Cannot delete the selected source preset")

    def ensure_selected_manifest(self, engine: str, preferred_file_name: str | None = None) -> PresetManifest | None:
        current = self.get_selected_manifest(engine)
        if current is not None:
            return current

        preferred_key = str(preferred_file_name or "").strip()
        if preferred_key:
            preferred = self._repository.get_manifest(engine, preferred_key)
            if preferred is not None:
                return self.select_preset(engine, preferred.file_name)

        manifests = self._repository.list_manifests(engine)
        if not manifests:
            return None
        return self.select_preset(engine, manifests[0].file_name)

    def _selection_path(self, engine: str) -> Path:
        return self._paths.engine_paths(engine).ensure_directories().selected_state_path
