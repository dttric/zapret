# ui/pages/zapret1/direct_zapret1_page.py
"""Zapret 1 target page with Zapret 2-style interface."""

from __future__ import annotations

import time as _time

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import QWidget, QHBoxLayout

from ui.pages.base_page import BasePage
from ui.compat_widgets import ActionButton, RefreshButton, SettingsCard
from ui.main_window_state import AppUiState, MainWindowStateStore
from ui.text_catalog import tr as tr_catalog
from ui.widgets import PresetTargetsList
from log import log

try:
    from qfluentwidgets import (
        BreadcrumbBar,
        MessageBox,
        BodyLabel,
    )
    _HAS_FLUENT = True
except ImportError:
    from PyQt6.QtWidgets import QLabel as BodyLabel  # type: ignore

    BreadcrumbBar = None  # type: ignore
    MessageBox = None  # type: ignore
    _HAS_FLUENT = False


_INFO_TEXT = (
    "Здесь выбирается стратегия обхода DPI для каждого target'а, который реально найден "
    "в выбранном source preset.\n\n"
    "То есть список строится не из старого реестра как источника истины, а из самого "
    "текущего пресета. Внешние метаданные используются только для красивых названий и иконок.\n\n"
    "Откройте target и выберите стратегию Zapret 1. "
    "Если стратегия не подходит — попробуйте другую или задайте аргументы вручную "
    "в карточке target'а."
)


def _log_startup_z1_direct_metric(section: str, elapsed_ms: float) -> None:
    try:
        rounded = int(round(float(elapsed_ms)))
    except Exception:
        rounded = 0
    log(f"⏱ Startup UI Section: ZAPRET1_DIRECT {section} {rounded}ms", "⏱ STARTUP")


class Zapret1StrategiesPage(BasePage):
    """Список target'ов Zapret 1 с breadcrumb-навигацией."""

    target_clicked = pyqtSignal(str, dict)  # target_key, target_info
    back_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(
            title="Прямой запуск Zapret 1",
            parent=parent,
            title_key="page.z1_direct.title",
        )
        self.parent_app = parent

        self._built = False
        self._build_scheduled = False
        self._breadcrumb = None
        self._back_btn = None
        self._targets_list: PresetTargetsList | None = None
        self.target_selections: dict[str, str] = {}
        self._targets: dict[str, Any] = {}
        self._expand_btn = None
        self._collapse_btn = None
        self._info_btn = None
        self._empty_state_label = None
        self._ui_state_store = None
        self._ui_state_unsubscribe = None
        self._basic_payload_cache = None

        self._setup_breadcrumb()

    # ------------------------------------------------------------------
    # Breadcrumb
    # ------------------------------------------------------------------

    def _setup_breadcrumb(self) -> None:
        if _HAS_FLUENT and BreadcrumbBar is not None:
            try:
                self._breadcrumb = BreadcrumbBar(self)
                self._rebuild_breadcrumb()
                self._breadcrumb.currentItemChanged.connect(self._on_breadcrumb_changed)
                self.layout.insertWidget(0, self._breadcrumb)
                return
            except Exception:
                pass

        try:
            back_btn = ActionButton(
                tr_catalog("page.z1_direct.back.control", language=self._ui_language, default="← Управление")
            )
            back_btn.clicked.connect(self.back_clicked.emit)
            self._back_btn = back_btn
            self.layout.insertWidget(0, back_btn)
        except Exception:
            pass

    def _rebuild_breadcrumb(self) -> None:
        if self._breadcrumb is None:
            return
        self._breadcrumb.blockSignals(True)
        try:
            self._breadcrumb.clear()
            self._breadcrumb.addItem(
                "control",
                tr_catalog("page.z1_direct.breadcrumb.control", language=self._ui_language, default="Управление"),
            )
            self._breadcrumb.addItem(
                "strategies",
                tr_catalog("page.z1_direct.title", language=self._ui_language, default="Прямой запуск Zapret 1"),
            )
        finally:
            self._breadcrumb.blockSignals(False)

    def _on_breadcrumb_changed(self, key: str) -> None:
        self._rebuild_breadcrumb()
        if key == "control":
            self.back_clicked.emit()

    # ------------------------------------------------------------------
    # Build lifecycle
    # ------------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if self._breadcrumb is not None:
            self._rebuild_breadcrumb()
        if not self._built:
            self._schedule_build()
        else:
            QTimer.singleShot(0, self._refresh_subtitles)

    def _schedule_build(self) -> None:
        if self._build_scheduled:
            return
        self._build_scheduled = True
        QTimer.singleShot(0, self._build_content)

    def _build_content(self) -> None:
        _t_total = _time.perf_counter()
        self._build_scheduled = False
        try:
            self._do_build()
        except Exception as e:
            log(f"Zapret1StrategiesPage: ошибка построения: {e}", "ERROR")
            import traceback

            log(traceback.format_exc(), "DEBUG")
        self._built = True
        _log_startup_z1_direct_metric("_build_content.total", (_time.perf_counter() - _t_total) * 1000)

    def _do_build(self) -> None:
        _t_toolbar = _time.perf_counter()
        self._clear_dynamic_widgets()
        self._empty_state_label = None

        self._build_toolbar()
        _log_startup_z1_direct_metric("_build_content.toolbar", (_time.perf_counter() - _t_toolbar) * 1000)

        _t_payload = _time.perf_counter()
        payload = self._get_basic_payload(refresh=True, startup_scope="ZAPRET1_DIRECT")
        self._targets = payload.target_items or {}
        target_views = list(payload.target_views or ())
        strategy_names_by_target = payload.strategy_names_by_target or {}
        _log_startup_z1_direct_metric("_build_content.payload", (_time.perf_counter() - _t_payload) * 1000)
        if not self._targets:
            self._empty_state_label = BodyLabel(
                tr_catalog(
                    "page.z1_direct.empty.no_categories",
                    language=self._ui_language,
                    default="Target'ы не найдены. Проверьте выбранный source preset и его содержимое.",
                )
            )
            self.add_widget(self._empty_state_label)
            return

        self.target_selections = payload.strategy_selections or {}
        self.target_selections = {
            key: self.target_selections.get(key, "none")
            for key in self._targets.keys()
        }

        filter_modes = payload.filter_modes or {}

        _t_targets = _time.perf_counter()
        self._targets_list = PresetTargetsList(
            self,
            startup_scope="ZAPRET1_DIRECT",
        )
        self._targets_list.strategy_selected.connect(self._on_target_clicked)
        self._targets_list.selections_changed.connect(self._on_selections_changed)
        self._targets_list.build_from_target_views(
            target_views,
            metadata=self._targets,
            selections=self.target_selections,
            strategy_names_by_target=strategy_names_by_target,
            filter_modes=filter_modes,
        )
        self.add_widget(self._targets_list, 1)
        _log_startup_z1_direct_metric("_build_content.targets_list", (_time.perf_counter() - _t_targets) * 1000)

    def _build_toolbar(self) -> None:
        actions_card = SettingsCard()
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)

        self._reload_btn = RefreshButton()
        self._reload_btn.clicked.connect(self._reload)
        actions_layout.addWidget(self._reload_btn)

        expand_btn = ActionButton(
            tr_catalog("page.z1_direct.toolbar.expand", language=self._ui_language, default="Развернуть"),
            "fa5s.expand-alt",
        )
        expand_btn.clicked.connect(self._expand_all)
        actions_layout.addWidget(expand_btn)
        self._expand_btn = expand_btn

        collapse_btn = ActionButton(
            tr_catalog("page.z1_direct.toolbar.collapse", language=self._ui_language, default="Свернуть"),
            "fa5s.compress-alt",
        )
        collapse_btn.clicked.connect(self._collapse_all)
        actions_layout.addWidget(collapse_btn)
        self._collapse_btn = collapse_btn

        info_btn = ActionButton(
            tr_catalog("page.z1_direct.toolbar.info", language=self._ui_language, default="Что это?"),
            "fa5s.question-circle",
            accent=False,
        )
        info_btn.clicked.connect(self._show_info)
        actions_layout.addWidget(info_btn)
        self._info_btn = info_btn

        actions_layout.addStretch()
        actions_card.add_layout(actions_layout)
        self.add_widget(actions_card)

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _get_direct_facade(self):
        from core.presets.direct_facade import DirectPresetFacade

        return DirectPresetFacade.from_launch_method("direct_zapret1")

    def _get_basic_payload(self, *, refresh: bool = False, startup_scope: str | None = None):
        if refresh or self._basic_payload_cache is None:
            self._basic_payload_cache = self._get_direct_facade().get_basic_ui_payload(startup_scope=startup_scope)
        return self._basic_payload_cache

    @staticmethod
    def _target_info_to_dict(target_key: str, target_info: Any) -> dict:
        if isinstance(target_info, dict):
            data = dict(target_info)
            data.setdefault("key", target_key)
            data.setdefault("full_name", data.get("name", target_key))
            data.setdefault("description", "")
            data.setdefault("base_filter", data.get("base_filter", ""))
            data.setdefault("base_filter_hostlist", data.get("base_filter_hostlist", ""))
            data.setdefault("base_filter_ipset", data.get("base_filter_ipset", ""))
            return data

        data = {
            "key": getattr(target_info, "key", target_key),
            "full_name": getattr(target_info, "full_name", target_key),
            "description": getattr(target_info, "description", ""),
            "protocol": getattr(target_info, "protocol", ""),
            "ports": getattr(target_info, "ports", ""),
            "icon_name": getattr(target_info, "icon_name", ""),
            "icon_color": getattr(target_info, "icon_color", "#909090"),
            "command_group": getattr(target_info, "command_group", "default"),
            "base_filter": getattr(target_info, "base_filter", ""),
            "base_filter_hostlist": getattr(target_info, "base_filter_hostlist", ""),
            "base_filter_ipset": getattr(target_info, "base_filter_ipset", ""),
        }

        data.setdefault("key", target_key)
        data.setdefault("full_name", target_key)
        data.setdefault("description", "")
        return data

    # ------------------------------------------------------------------
    # Actions / handlers
    # ------------------------------------------------------------------

    def _on_target_clicked(self, target_key: str, _strategy_id: str) -> None:
        try:
            target_info = (self._targets or {}).get(target_key)
        except Exception:
            target_info = None

        info_dict = self._target_info_to_dict(target_key, target_info)

        # Важно: отложенная навигация убирает артефакты hover/cursor в Qt.
        QTimer.singleShot(
            0,
            lambda k=target_key, info=dict(info_dict): self.target_clicked.emit(k, info),
        )

    def _on_selections_changed(self, selections: dict) -> None:
        self.target_selections = dict(selections or {})

    def _refresh_subtitles(self) -> None:
        if not self._targets_list:
            return

        payload = self._get_basic_payload(refresh=True)
        self.target_selections = payload.strategy_selections or {}
        self.target_selections = {
            key: self.target_selections.get(key, "none")
            for key in (self._targets or {}).keys()
        }
        self._targets_list.set_strategy_names_by_target(payload.strategy_names_by_target or {})
        self._targets_list.set_selections(self.target_selections)

        filter_modes = payload.filter_modes or {}
        self._targets_list.set_filter_modes(filter_modes, target_keys=(self._targets or {}).keys())

    def _reload(self, *_args) -> None:
        if hasattr(self, "_reload_btn"):
            self._reload_btn.set_loading(True)
        try:
            self._built = False
            self._basic_payload_cache = None
            self._targets_list = None
            self._schedule_build()
        finally:
            if hasattr(self, "_reload_btn"):
                self._reload_btn.set_loading(False)

    def _expand_all(self, *_args) -> None:
        if self._targets_list:
            self._targets_list.expand_all()

    def _collapse_all(self, *_args) -> None:
        if self._targets_list:
            self._targets_list.collapse_all()

    def _show_info(self, *_args) -> None:
        if _HAS_FLUENT and MessageBox is not None:
            try:
                box = MessageBox(
                    tr_catalog("page.z1_direct.info.title", language=self._ui_language, default="Прямой запуск Zapret 1"),
                    tr_catalog("page.z1_direct.info.body", language=self._ui_language, default=_INFO_TEXT),
                    self.window(),
                )
                box.hideCancelButton()
                box.yesButton.setText(tr_catalog("common.ok.got_it", language=self._ui_language, default="Понятно"))
                box.exec()
            except Exception:
                pass

    def _clear_dynamic_widgets(self) -> None:
        keep: set[QWidget] = {self.title_label}
        if self.subtitle_label:
            keep.add(self.subtitle_label)
        if self._breadcrumb:
            keep.add(self._breadcrumb)

        to_remove = []
        for i in range(self.vBoxLayout.count()):
            item = self.vBoxLayout.itemAt(i)
            w = item.widget() if item else None
            if w is not None and w not in keep:
                to_remove.append(w)

        for w in to_remove:
            self.vBoxLayout.removeWidget(w)
            w.setParent(None)

    # ------------------------------------------------------------------
    # Main-window callbacks
    # ------------------------------------------------------------------

    def reload_for_mode_change(self) -> None:
        self._built = False
        self._basic_payload_cache = None
        self._targets_list = None
        if self.isVisible():
            self._schedule_build()

    def update_current_strategy(self, name: str) -> None:
        # Direct Z1 target list page does not show a separate current-strategy label,
        # but MainWindow still calls this hook on all strategy pages.
        _ = name

    def bind_ui_state_store(self, store: MainWindowStateStore) -> None:
        if self._ui_state_store is store:
            return

        unsubscribe = getattr(self, "_ui_state_unsubscribe", None)
        if callable(unsubscribe):
            try:
                unsubscribe()
            except Exception:
                pass

        self._ui_state_store = store
        self._ui_state_unsubscribe = store.subscribe(
            self._on_ui_state_changed,
            fields={"preset_revision", "mode_revision"},
            emit_initial=True,
        )

    def _on_ui_state_changed(self, _state: AppUiState, changed_fields: frozenset[str]) -> None:
        if "preset_revision" in changed_fields or "mode_revision" in changed_fields:
            self.reload_for_mode_change()

    def set_ui_language(self, language: str) -> None:
        super().set_ui_language(language)

        self._rebuild_breadcrumb()
        if self._back_btn is not None:
            self._back_btn.setText(
                tr_catalog("page.z1_direct.back.control", language=self._ui_language, default="← Управление")
            )

        if self._expand_btn is not None:
            self._expand_btn.setText(
                tr_catalog("page.z1_direct.toolbar.expand", language=self._ui_language, default="Развернуть")
            )
        if self._collapse_btn is not None:
            self._collapse_btn.setText(
                tr_catalog("page.z1_direct.toolbar.collapse", language=self._ui_language, default="Свернуть")
            )
        if self._info_btn is not None:
            self._info_btn.setText(
                tr_catalog("page.z1_direct.toolbar.info", language=self._ui_language, default="Что это?")
            )

        if self._empty_state_label is not None:
            self._empty_state_label.setText(
                tr_catalog(
                    "page.z1_direct.empty.no_categories",
                    language=self._ui_language,
                    default="Target'ы не найдены. Проверьте выбранный source preset и его содержимое.",
                )
            )

        if self._built:
            self._refresh_subtitles()
