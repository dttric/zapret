from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from log import log
from core.presets.models import PresetManifest


class DirectFlowError(RuntimeError):
    """Raised when the direct-launch selected source preset flow cannot be prepared."""


@dataclass(frozen=True)
class DirectLaunchProfile:
    launch_method: str
    engine: str
    preset_file_name: str
    preset_name: str
    launch_config_path: Path
    display_name: str

    def to_selected_mode(self) -> dict[str, object]:
        return {
            "is_preset_file": True,
            "name": self.display_name,
            "preset_path": str(self.launch_config_path),
        }


class DirectFlowCoordinator:
    PRESETS_DOWNLOAD_URL = "https://github.com/youtubediscord/zapret/discussions/categories/presets"

    _METHOD_TO_ENGINE = {
        "direct_zapret1": "winws1",
        "direct_zapret2": "winws2",
    }
    _PRESET_HEADER_RE = re.compile(r"^\s*#\s*Preset:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    _TEMPLATE_ORIGIN_RE = re.compile(r"^\s*#\s*TemplateOrigin:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)

    def ensure_launch_profile(
        self,
        launch_method: str,
        *,
        require_filters: bool = False,
    ) -> DirectLaunchProfile:
        method = self._normalize_method(launch_method)
        selected = self._ensure_selected_source_manifest(method)

        launch_config_path = self.get_selected_source_path(method)
        if not launch_config_path.exists():
            raise DirectFlowError(f"Selected source preset not found: {launch_config_path}")

        text = ""
        try:
            text = launch_config_path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            raise DirectFlowError(f"Failed to read selected source preset: {exc}") from exc

        if require_filters and not self._has_required_filters(method, text):
            raise DirectFlowError("Выберите хотя бы одну категорию для запуска")

        return DirectLaunchProfile(
            launch_method=method,
            engine=self._METHOD_TO_ENGINE[method],
            preset_file_name=selected.file_name,
            preset_name=selected.name,
            launch_config_path=launch_config_path,
            display_name=f"Пресет: {selected.name}",
        )

    def build_selected_mode(
        self,
        launch_method: str,
        *,
        require_filters: bool = False,
    ) -> dict[str, object]:
        return self.ensure_launch_profile(
            launch_method,
            require_filters=require_filters,
        ).to_selected_mode()

    def get_selected_source_manifest(self, launch_method: str) -> PresetManifest:
        return self._ensure_selected_source_manifest(launch_method)

    def get_selected_source_file_name(self, launch_method: str) -> str:
        return self.get_selected_source_manifest(launch_method).file_name

    def get_selected_source_path(self, launch_method: str) -> Path:
        selected = self.get_selected_source_manifest(launch_method)
        from core.services import get_app_paths

        engine = self._METHOD_TO_ENGINE[self._normalize_method(launch_method)]
        return get_app_paths().engine_paths(engine).ensure_directories().presets_dir / selected.file_name

    def ensure_selected_source_path(self, launch_method: str) -> Path:
        return self.ensure_launch_profile(launch_method, require_filters=False).launch_config_path

    def is_selected_preset(self, launch_method: str, preset_name: str) -> bool:
        try:
            current = (self.get_selected_source_manifest(launch_method).name or "").strip().lower()
        except Exception:
            current = ""
        target = str(preset_name or "").strip().lower()
        return bool(current and target and current == target)

    def select_preset_file_name(self, launch_method: str, file_name: str) -> DirectLaunchProfile:
        method = self._normalize_method(launch_method)
        engine = self._METHOD_TO_ENGINE[method]
        self._ensure_support_files(method)

        from core.services import get_selection_service

        selected_file_name = get_selection_service().select_preset_file_name_fast(engine, file_name)
        selected_path = self.get_selected_source_path(method)
        display_name = self._read_display_name_from_source(selected_path, fallback=Path(selected_file_name).stem)
        return DirectLaunchProfile(
            launch_method=method,
            engine=engine,
            preset_file_name=selected_file_name,
            preset_name=display_name,
            launch_config_path=selected_path,
            display_name=f"Пресет: {display_name}",
        )

    def refresh_selected_launch_profile(self, launch_method: str) -> DirectLaunchProfile:
        return self.ensure_launch_profile(launch_method, require_filters=False)

    def _normalize_method(self, launch_method: str) -> str:
        method = str(launch_method or "").strip().lower()
        if method not in self._METHOD_TO_ENGINE:
            raise DirectFlowError(f"Unsupported direct launch method: {launch_method}")
        return method

    def _ensure_selected_source_manifest(self, launch_method: str) -> PresetManifest:
        method = self._normalize_method(launch_method)
        engine = self._METHOD_TO_ENGINE[method]

        self._ensure_support_files(method)

        from core.services import get_selection_service

        selection = get_selection_service()
        preset_paths = self._list_source_preset_paths(engine)
        if not preset_paths:
            raise DirectFlowError(
                "Пресеты не найдены. Скачайте файлы пресетов вручную: "
                f"{self.PRESETS_DOWNLOAD_URL}"
            )

        selected_file_name = str(selection.get_selected_file_name(engine) or "").strip()
        if selected_file_name:
            selected_path = self._get_source_preset_path(engine, selected_file_name)
            if selected_path.exists():
                return self._manifest_from_source_path(engine, selected_path)

        default_path = self._get_source_preset_path(engine, "Default.txt")
        if default_path.exists():
            selected_file_name = selection.select_preset_file_name_fast(engine, default_path.name)
            return self._manifest_from_source_path(engine, self._get_source_preset_path(engine, selected_file_name))

        first_path = preset_paths[0]
        selected_file_name = selection.select_preset_file_name_fast(engine, first_path.name)
        selected_path = self._get_source_preset_path(engine, selected_file_name)
        if selected_path.exists():
            return self._manifest_from_source_path(engine, selected_path)

        if not selected_file_name:
            raise DirectFlowError("Не удалось определить выбранный пресет")
        raise DirectFlowError(f"Выбранный пресет не найден: {selected_file_name}")

    @staticmethod
    def _has_required_filters(launch_method: str, text: str) -> bool:
        content = str(text or "")
        if launch_method == "direct_zapret1":
            return any(flag in content for flag in ("--wf-tcp=", "--wf-udp="))
        return any(flag in content for flag in ("--wf-tcp-out", "--wf-udp-out", "--wf-raw-part"))

    @staticmethod
    def _ensure_support_files(launch_method: str) -> None:
        try:
            from core.presets.support_files import prepare_direct_support_files

            prepare_direct_support_files(launch_method)
        except Exception as exc:
            log(f"Failed to prepare direct support files for {launch_method}: {exc}", "DEBUG")

    @classmethod
    def _read_display_name_from_source(cls, path: Path, *, fallback: str) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return str(fallback or "Preset").strip() or "Preset"

        match = cls._PRESET_HEADER_RE.search(text or "")
        if match:
            value = str(match.group(1) or "").strip()
            if value:
                return value
        return str(fallback or "Preset").strip() or "Preset"

    @classmethod
    def _read_template_origin_from_source(cls, path: Path) -> str | None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

        match = cls._TEMPLATE_ORIGIN_RE.search(text or "")
        if match:
            value = str(match.group(1) or "").strip()
            if value:
                return value
        return None

    def _get_source_preset_path(self, engine: str, file_name: str) -> Path:
        from core.services import get_app_paths

        return get_app_paths().engine_paths(engine).ensure_directories().presets_dir / str(file_name or "").strip()

    def _list_source_preset_paths(self, engine: str) -> list[Path]:
        from core.services import get_app_paths

        presets_dir = get_app_paths().engine_paths(engine).ensure_directories().presets_dir
        return sorted(
            (path for path in presets_dir.glob("*.txt") if path.is_file()),
            key=lambda path: path.name.lower(),
        )

    @staticmethod
    def _file_time_to_iso(path: Path) -> str:
        try:
            value = float(path.stat().st_mtime)
        except Exception:
            value = 0.0
        if value <= 0:
            return ""
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _manifest_from_source_path(self, engine: str, path: Path) -> PresetManifest:
        file_name = path.name
        display_name = self._read_display_name_from_source(path, fallback=path.stem)
        template_origin = self._read_template_origin_from_source(path)
        timestamp = self._file_time_to_iso(path)
        kind = "builtin" if self._is_builtin_preset(engine, path, template_origin) else "user"
        return PresetManifest(
            file_name=file_name,
            name=display_name,
            template_origin=template_origin,
            created_at=timestamp,
            updated_at=timestamp,
            kind=kind,
        )

    @staticmethod
    def _is_builtin_preset(engine: str, path: Path, template_origin: str | None) -> bool:
        origin = str(template_origin or "").strip()
        if not origin:
            return False
        try:
            from core.presets.template_support import template_canonical_name

            canonical = template_canonical_name(engine, origin)
        except Exception:
            canonical = None
        return bool(canonical and path.stem.casefold() == str(canonical).casefold())
