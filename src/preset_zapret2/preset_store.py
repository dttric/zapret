# preset_zapret2/preset_store.py
"""
Central in-memory preset store (singleton).

Provides a single source of truth for all preset data across the application.
All UI pages and backend modules should use this store instead of creating
independent PresetManager instances.

Features:
- All presets loaded into memory once, refreshed only when files change
- Qt signals for preset lifecycle events (change, switch, create, delete)
- Thread-safe singleton access via get_preset_store()

Usage:
    from preset_zapret2.preset_store import get_preset_store

    store = get_preset_store()

    # Read presets (from memory, instant)
    file_names = store.get_preset_file_names()
    preset = store.get_preset_by_file_name("Default.txt")

    # Listen for changes
    store.presets_changed.connect(my_handler)
    store.preset_switched.connect(on_switched)
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from log import log


class PresetStore(QObject):
    """
    Central in-memory preset store (singleton).

    Holds all parsed Preset objects in memory.
    Emits Qt signals when preset data changes.
    """

    # ── Signals ──────────────────────────────────────────────────────────
    # Emitted when the preset list or content changes (add/delete/rename/import/reset).
    presets_changed = pyqtSignal()

    # Emitted when the selected source preset is switched. Argument: new preset name.
    preset_switched = pyqtSignal(str)

    # Emitted when a single preset's content is updated (save/sync).
    preset_updated = pyqtSignal(str)

    # ── Singleton ────────────────────────────────────────────────────────
    _instance: Optional[PresetStore] = None

    @classmethod
    def instance(cls) -> PresetStore:
        """Returns the singleton PresetStore instance, creating it if needed."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # {file_name: Preset}
        self._presets_by_file_name: Dict[str, "Preset"] = {}
        self._display_name_to_file_names: Dict[str, list[str]] = {}

        # Flag: initial load done?
        self._loaded = False

        # Cached selected source preset identity from direct core state.
        self._active_file_name: Optional[str] = None
        self._active_name: Optional[str] = None

    # ── Public API: Read ─────────────────────────────────────────────────

    def get_preset_by_file_name(self, file_name: str) -> Optional["Preset"]:
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

    def get_selected_source_preset_file_name(self) -> Optional[str]:
        self._ensure_loaded()
        return self._active_file_name

    # ── Public API: Mutate ───────────────────────────────────────────────

    def refresh(self) -> None:
        """
        Full reload from disk. Clears all in-memory state and re-reads.
        Emits presets_changed after reload.
        """
        self._do_full_load()
        self.presets_changed.emit()

    def notify_preset_saved(self, name: str) -> None:
        """
        Called after a preset file is saved/modified on disk.
        Re-reads that single preset and emits preset_updated.
        """
        self._ensure_loaded()
        file_name = self._resolve_file_name(name) or str(name or "").strip()
        self._reload_single_preset(file_name)
        self.preset_updated.emit(self.get_display_name(file_name))

    def notify_presets_changed(self) -> None:
        """
        Called after an operation that changes the preset list
        (create, delete, rename, duplicate, import).
        Performs a full reload and emits presets_changed.
        """
        self._do_full_load()
        self.presets_changed.emit()

    def notify_preset_switched(self, name: str) -> None:
        """
        Called after the selected source preset is switched.
        Updates the cached selected name and emits preset_switched.
        """
        file_name = self._resolve_file_name(name) or str(name or "").strip() or None
        self._active_file_name = file_name
        self._active_name = self.get_display_name(file_name) if file_name else None
        self.preset_switched.emit(self._active_name or "")

    def notify_active_name_changed(self) -> None:
        try:
            from core.services import get_selection_service

            self._active_file_name = get_selection_service().get_selected_file_name("winws2")
            self._active_name = self._display_name_for_file_name(self._active_file_name) if self._active_file_name else None
        except Exception:
            self._active_file_name = None
            self._active_name = None

    # ── Internal ─────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        """Loads all presets from disk on first access."""
        if not self._loaded:
            self._do_full_load()

    def _do_full_load(self) -> None:
        """Reads all presets from disk into memory."""
        from core.services import get_preset_repository, get_selection_service
        from .preset_storage import load_preset

        self._presets_by_file_name.clear()
        self._display_name_to_file_names.clear()

        documents = get_preset_repository().list_presets("winws2")
        for document in documents:
            file_name = str(document.manifest.file_name or "").strip()
            stem_name = Path(file_name).stem
            if not file_name or not stem_name:
                continue
            try:
                preset = load_preset(stem_name)
                if preset is not None:
                    try:
                        setattr(preset, "_source_file_name", file_name)
                    except Exception:
                        pass
                    self._presets_by_file_name[file_name] = preset
                    display_name = str(getattr(preset, "name", "") or "").strip() or stem_name
                    self._display_name_to_file_names.setdefault(display_name.lower(), []).append(file_name)
            except Exception as e:
                log(f"PresetStore: error loading preset '{file_name}': {e}", "DEBUG")

        for names in self._display_name_to_file_names.values():
            names.sort(key=lambda item: item.lower())

        try:
            self._active_file_name = get_selection_service().get_selected_file_name("winws2")
            self._active_name = self._display_name_for_file_name(self._active_file_name) if self._active_file_name else None
        except Exception:
            self._active_file_name = None
            self._active_name = None
        self._loaded = True

        log(f"PresetStore: loaded {len(self._presets_by_file_name)} presets", "DEBUG")

    def _reload_single_preset(self, file_name: str) -> None:
        """Re-reads a single preset from disk into the store."""
        from .preset_storage import load_preset

        target_file_name = str(file_name or "").strip()
        if not target_file_name:
            return
        stem_name = Path(target_file_name).stem

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
            preset = load_preset(stem_name)
            if preset is not None:
                try:
                    setattr(preset, "_source_file_name", target_file_name)
                except Exception:
                    pass
                self._presets_by_file_name[target_file_name] = preset
                display_name = str(getattr(preset, "name", "") or "").strip() or stem_name
                bucket = self._display_name_to_file_names.setdefault(display_name.lower(), [])
                if target_file_name not in bucket:
                    bucket.append(target_file_name)
                    bucket.sort(key=lambda item: item.lower())
            else:
                # Preset was deleted or became unreadable
                self._presets_by_file_name.pop(target_file_name, None)
        except Exception as e:
            log(f"PresetStore: error reloading preset '{target_file_name}': {e}", "DEBUG")

    def _resolve_file_name(self, reference: str) -> Optional[str]:
        candidate = str(reference or "").strip()
        if not candidate:
            return None
        if candidate in self._presets_by_file_name:
            return candidate
        file_names = self._display_name_to_file_names.get(candidate.lower(), [])
        if not file_names:
            return None
        return file_names[0]

    def _display_name_for_file_name(self, file_name: str | None) -> str:
        candidate = str(file_name or "").strip()
        preset = self._presets_by_file_name.get(candidate)
        if preset is not None:
            return str(getattr(preset, "name", "") or "").strip() or Path(candidate).stem
        return Path(candidate).stem if candidate else ""


def get_preset_store() -> PresetStore:
    """Returns the global PresetStore singleton."""
    return PresetStore.instance()
