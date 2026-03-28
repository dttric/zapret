# preset_zapret1/preset_store.py
"""Central in-memory preset store for Zapret 1 (singleton)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from log import log


class PresetStoreV1(QObject):
    """Central in-memory preset store for Zapret 1 presets."""

    presets_changed = pyqtSignal()
    preset_switched = pyqtSignal(str)
    preset_updated = pyqtSignal(str)

    _instance: Optional[PresetStoreV1] = None

    @classmethod
    def instance(cls) -> PresetStoreV1:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._presets_by_file_name: Dict[str, "PresetV1"] = {}
        self._display_name_to_file_names: Dict[str, list[str]] = {}
        self._loaded = False
        self._active_file_name: Optional[str] = None
        self._active_name: Optional[str] = None

    def get_preset_by_file_name(self, file_name: str) -> Optional["PresetV1"]:
        self._ensure_loaded()
        return self._presets_by_file_name.get(str(file_name or "").strip())

    def get_preset_file_names(self) -> List[str]:
        self._ensure_loaded()
        return sorted(self._presets_by_file_name.keys(), key=lambda s: s.lower())

    def get_display_name(self, file_name: str) -> str:
        self._ensure_loaded()
        return self._display_name_for_file_name(file_name)

    def get_file_names_for_display_name(self, name: str) -> List[str]:
        self._ensure_loaded()
        return list(self._display_name_to_file_names.get(str(name or "").strip().lower(), []))

    def get_active_preset_file_name(self) -> Optional[str]:
        self._ensure_loaded()
        return self._active_file_name

    def refresh(self) -> None:
        self._do_full_load()
        self.presets_changed.emit()

    def notify_preset_saved(self, file_name: str) -> None:
        self._ensure_loaded()
        target_file_name = str(file_name or "").strip()
        self._reload_single_preset(target_file_name)
        self.preset_updated.emit(self.get_display_name(target_file_name))

    def notify_presets_changed(self) -> None:
        self._do_full_load()
        self.presets_changed.emit()

    def notify_preset_switched(self, file_name: str) -> None:
        target_file_name = str(file_name or "").strip() or None
        self._active_file_name = target_file_name
        self._active_name = self.get_display_name(target_file_name) if target_file_name else None
        self.preset_switched.emit(self._active_name or "")

    def notify_active_name_changed(self) -> None:
        try:
            from core.services import get_selection_service

            self._active_file_name = get_selection_service().get_selected_file_name("winws1")
            self._active_name = self._display_name_for_file_name(self._active_file_name) if self._active_file_name else None
        except Exception:
            self._active_file_name = None
            self._active_name = None

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._do_full_load()

    def _do_full_load(self) -> None:
        from core.services import get_app_paths, get_preset_repository, get_selection_service
        from .preset_storage import _load_preset_from_path_v1

        self._presets_by_file_name.clear()
        self._display_name_to_file_names.clear()
        documents = get_preset_repository().list_presets("winws1")
        for document in documents:
            file_name = str(document.manifest.file_name or "").strip()
            if not file_name:
                continue
            try:
                preset_path = get_app_paths().engine_paths("winws1").ensure_directories().presets_dir / file_name
                preset = _load_preset_from_path_v1(preset_path, Path(file_name).stem)
                if preset is not None:
                    try:
                        setattr(preset, "_source_file_name", file_name)
                    except Exception:
                        pass
                    self._presets_by_file_name[file_name] = preset
                    display_name = str(getattr(preset, "name", "") or "").strip() or Path(file_name).stem
                    self._display_name_to_file_names.setdefault(display_name.lower(), []).append(file_name)
            except Exception as e:
                log(f"PresetStoreV1: error loading preset '{file_name}': {e}", "DEBUG")
        for names in self._display_name_to_file_names.values():
            names.sort(key=lambda item: item.lower())
        try:
            self._active_file_name = get_selection_service().get_selected_file_name("winws1")
            self._active_name = self._display_name_for_file_name(self._active_file_name) if self._active_file_name else None
        except Exception:
            self._active_file_name = None
            self._active_name = None
        self._loaded = True
        log(f"PresetStoreV1: loaded {len(self._presets_by_file_name)} presets", "DEBUG")

    def _reload_single_preset(self, file_name: str) -> None:
        from core.services import get_app_paths
        from .preset_storage import _load_preset_from_path_v1
        target_file_name = str(file_name or "").strip()
        if not target_file_name:
            return
        previous = self._presets_by_file_name.get(target_file_name)
        if previous is not None:
            previous_display = str(getattr(previous, "name", "") or "").strip().lower()
            if previous_display in self._display_name_to_file_names:
                self._display_name_to_file_names[previous_display] = [
                    item for item in self._display_name_to_file_names[previous_display]
                    if item != target_file_name
                ]
                if not self._display_name_to_file_names[previous_display]:
                    self._display_name_to_file_names.pop(previous_display, None)
        try:
            preset_path = get_app_paths().engine_paths("winws1").ensure_directories().presets_dir / target_file_name
            preset = _load_preset_from_path_v1(preset_path, Path(target_file_name).stem)
            if preset is not None:
                try:
                    setattr(preset, "_source_file_name", target_file_name)
                except Exception:
                    pass
                self._presets_by_file_name[target_file_name] = preset
                display_name = str(getattr(preset, "name", "") or "").strip() or Path(target_file_name).stem
                bucket = self._display_name_to_file_names.setdefault(display_name.lower(), [])
                if target_file_name not in bucket:
                    bucket.append(target_file_name)
                    bucket.sort(key=lambda item: item.lower())
            else:
                self._presets_by_file_name.pop(target_file_name, None)
        except Exception as e:
            log(f"PresetStoreV1: error reloading preset '{target_file_name}': {e}", "DEBUG")

    def _display_name_for_file_name(self, file_name: str | None) -> str:
        candidate = str(file_name or "").strip()
        preset = self._presets_by_file_name.get(candidate)
        if preset is not None:
            return str(getattr(preset, "name", "") or "").strip() or Path(candidate).stem
        return Path(candidate).stem if candidate else ""


def get_preset_store_v1() -> PresetStoreV1:
    """Returns the global PresetStoreV1 singleton."""
    return PresetStoreV1.instance()
