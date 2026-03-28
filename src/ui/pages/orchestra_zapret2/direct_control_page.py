from ui.compat_widgets import set_tooltip
from ui.pages.zapret2.direct_control_page import Zapret2DirectControlPage
from ui.text_catalog import tr as tr_catalog


class OrchestraZapret2DirectControlPage(Zapret2DirectControlPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._apply_orchestra_labels()
        self._refresh_direct_mode_label()

    def _apply_orchestra_labels(self, language: str | None = None) -> None:
        try:
            self.title_label.setText(
                tr_catalog(
                    "page.z2_orchestra_control.title",
                    language=language,
                    default="Управление Orchestra Z2",
                )
            )
            if self.subtitle_label is not None:
                self.subtitle_label.setText(
                    tr_catalog(
                        "page.z2_orchestra_control.subtitle",
                        language=language,
                        default="Управление пресетами и запуском для режима direct_zapret2_orchestra.",
                    )
                )

            if getattr(self, "control_section_label", None) is not None:
                self.control_section_label.setText(
                    tr_catalog(
                        "page.z2_orchestra_control.section.management",
                        language=language,
                        default="Управление Orchestra Z2",
                    )
                )
            if getattr(self, "preset_section_label", None) is not None:
                self.preset_section_label.setText(
                    tr_catalog(
                        "page.z2_orchestra_control.section.preset",
                        language=language,
                        default="Сменить пресет Orchestra Z2",
                    )
                )
            if getattr(self, "direct_section_label", None) is not None:
                self.direct_section_label.setText(
                    tr_catalog(
                        "page.z2_orchestra_control.section.direct_tuning",
                        language=language,
                        default="Тонкая настройка активного пресета",
                    )
                )

            if getattr(self, "presets_btn", None) is not None:
                self.presets_btn.setText(
                    tr_catalog(
                        "page.z2_orchestra_control.button.presets",
                        language=language,
                        default="Пресеты Orchestra",
                    )
                )
            if getattr(self, "direct_open_btn", None) is not None:
                self.direct_open_btn.setText(
                    tr_catalog(
                        "page.z2_orchestra_control.button.direct_open",
                        language=language,
                        default="Прямой запуск",
                    )
                )
            if getattr(self, "direct_mode_btn", None) is not None:
                self.direct_mode_btn.setVisible(False)

            if getattr(self, "direct_mode_caption", None) is not None:
                self.direct_mode_caption.setText(
                    tr_catalog(
                        "page.z2_orchestra_control.section.category_editing",
                        language=language,
                        default="Редактирование активного пресета по категориям",
                    )
                )

            if getattr(self, "wssize_toggle", None) is not None:
                self.wssize_toggle.setVisible(False)
            if getattr(self, "blobs_open_btn", None) is not None:
                self.blobs_open_btn.setText(
                    tr_catalog(
                        "page.z2_orchestra_control.button.blobs_open",
                        language=language,
                        default="Открыть блобы",
                    )
                )

        except Exception:
            pass

    def set_ui_language(self, language: str) -> None:
        super().set_ui_language(language)
        self._apply_orchestra_labels(language=language)

    def _open_direct_mode_dialog(self) -> None:
        return

    def _on_direct_launch_mode_selected(self, mode: str) -> None:
        _ = mode
        return

    def _refresh_direct_mode_label(self) -> None:
        try:
            self.direct_mode_label.setText(
                tr_catalog(
                    "page.z2_orchestra_control.mode_label",
                    language=self._ui_language,
                    default="Orchestra Z2",
                )
            )
        except Exception:
            pass

    def _on_debug_log_toggled(self, enabled: bool) -> None:
        try:
            from preset_orchestra_zapret2 import PresetManager

            PresetManager().set_debug_log_enabled(bool(enabled))
        except Exception:
            pass

        try:
            from preset_orchestra_zapret2 import PresetManager, ensure_default_preset_exists

            if not ensure_default_preset_exists():
                return
            manager = PresetManager()
            preset = manager.get_active_preset()
            if preset:
                manager.sync_preset_to_active_file(preset)
        except Exception:
            pass

    def update_strategy(self, name: str):
        super().update_strategy(name)

        try:
            if getattr(self, "strategy_label", None) is not None and self.strategy_label.text() == "Нет активных листов":
                self.strategy_label.setText(
                    tr_catalog(
                        "page.z2_orchestra_control.strategy.no_active_categories",
                        language=self._ui_language,
                        default="Нет активных категорий",
                    )
                )
        except Exception:
            pass

        active_preset_name = ""
        try:
            from preset_orchestra_zapret2 import PresetManager

            preset_manager = PresetManager()
            active_preset_name = (preset_manager.get_active_preset_name() or "").strip()
            if not active_preset_name:
                preset = preset_manager.get_active_preset()
                active_preset_name = (getattr(preset, "name", "") or "").strip()
        except Exception:
            active_preset_name = ""

        if active_preset_name:
            try:
                self.preset_name_label.setText(active_preset_name)
                set_tooltip(self.preset_name_label, active_preset_name)
            except Exception:
                pass
