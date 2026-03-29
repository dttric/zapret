from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .direct_facade_backend import DirectPresetFacadeBackend


@dataclass(frozen=True)
class DirectPresetFacade:
    engine: str
    launch_method: str
    on_dpi_reload_needed: Optional[Callable[[], None]] = None

    @classmethod
    def from_launch_method(
        cls,
        launch_method: str,
        *,
        on_dpi_reload_needed: Optional[Callable[[], None]] = None,
    ) -> "DirectPresetFacade":
        method = str(launch_method or "").strip().lower()
        if method == "direct_zapret2":
            return cls(engine="winws2", launch_method=method, on_dpi_reload_needed=on_dpi_reload_needed)
        if method == "direct_zapret1":
            return cls(engine="winws1", launch_method=method, on_dpi_reload_needed=on_dpi_reload_needed)
        raise ValueError(f"Unsupported launch method for direct preset facade: {launch_method}")

    def _backend(self) -> DirectPresetFacadeBackend:
        return DirectPresetFacadeBackend(
            engine=self.engine,
            launch_method=self.launch_method,
            on_dpi_reload_needed=self.on_dpi_reload_needed,
        )

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._backend(), name)
