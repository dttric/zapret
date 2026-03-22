# ui/pages/hosts_page.py
"""Страница управления Hosts файлом - разблокировка сервисов"""

import os
import re
from string import Template
from PyQt6.QtCore import Qt, QThread, QObject, QTimer, QEvent, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QLayout, QCheckBox
)
import qtawesome as qta

from .base_page import BasePage
from ui.compat_widgets import SettingsCard
from ui.text_catalog import tr as tr_catalog

from log import log
from utils import get_system32_path
from ui.theme import get_theme_tokens
from ui.theme_semantic import get_semantic_palette

try:
    from qfluentwidgets import (
        BodyLabel, CaptionLabel, StrongBodyLabel,
        PushButton, ComboBox, InfoBar, MessageBox, SwitchButton,
    )
    _HAS_FLUENT = True
except ImportError:
    _HAS_FLUENT = False
    BodyLabel = QLabel  # type: ignore[misc,assignment]
    CaptionLabel = QLabel  # type: ignore[misc,assignment]
    StrongBodyLabel = QLabel  # type: ignore[misc,assignment]
    PushButton = QPushButton  # type: ignore[misc,assignment]
    ComboBox = None  # type: ignore[misc,assignment]
    InfoBar = None  # type: ignore[misc,assignment]
    MessageBox = None  # type: ignore[misc,assignment]
    SwitchButton = None  # type: ignore[misc,assignment]

try:
    # Simple Win11 toggle without text (QCheckBox-based).
    from ui.pages.dpi_settings_page import Win11ToggleSwitch as Win11ToggleSwitchNoText
except Exception:
    Win11ToggleSwitchNoText = QCheckBox  # type: ignore[misc,assignment]


_FLUENT_CHIP_STYLE_TEMPLATE = Template(
    """
QPushButton {
    background-color: transparent;
    border: none;
    color: $fg_muted;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 500;
    font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif;
    text-decoration: none;
}
QPushButton:hover {
    color: $accent_hex;
    text-decoration: underline;
}
QPushButton:pressed {
    color: rgba($accent_rgb, 0.85);
}
QPushButton:disabled {
    color: $fg_faint;
}
"""
)


def _get_fluent_chip_style(tokens=None) -> str:
    tokens = tokens or get_theme_tokens()
    return _FLUENT_CHIP_STYLE_TEMPLATE.substitute(
        fg_muted=tokens.fg_muted,
        fg_faint=tokens.fg_faint,
        accent_hex=tokens.accent_hex,
        accent_rgb=tokens.accent_rgb_str,
    )

_DNS_PROFILE_IP_SUFFIX = re.compile(r"\s*\(\s*(?:\d{1,3}\.){3}\d{1,3}\s*\)\s*$")


def _format_dns_profile_label(profile_name: str) -> str:
    label = (profile_name or "").strip()
    if not label:
        return ""
    return _DNS_PROFILE_IP_SUFFIX.sub("", label).strip()


# Импортируем сервисы и домены
try:
    from hosts.proxy_domains import (
        QUICK_SERVICES,
        ensure_ipv6_catalog_sections_if_available,
        get_dns_profiles,
        get_all_services,
        get_service_has_geohide_ips,
        get_service_available_dns_profiles,
        get_service_domain_ip_map,
        get_service_domain_names,
        get_service_domains,
        get_hosts_catalog_signature,
        invalidate_hosts_catalog_cache,
        load_user_hosts_selection,
        save_user_hosts_selection,
    )
except ImportError:
    QUICK_SERVICES = []

    def ensure_ipv6_catalog_sections_if_available() -> tuple[bool, bool]:
        return (False, False)

    def get_dns_profiles() -> list[str]:
        return []

    def get_all_services() -> list[str]:
        return []

    def get_service_has_geohide_ips(service_name: str) -> bool:
        return False

    def get_service_available_dns_profiles(service_name: str) -> list[str]:
        return []

    def get_service_domain_ip_map(*args, **kwargs) -> dict[str, str]:
        return {}

    def get_service_domain_names(service_name: str) -> list[str]:
        return []

    def get_service_domains(service_name: str) -> dict[str, str]:
        return {}

    def get_hosts_catalog_signature() -> tuple[str, int, int] | None:
        return None

    def invalidate_hosts_catalog_cache() -> None:
        return None

    def load_user_hosts_selection() -> dict[str, str]:
        return {}

    def save_user_hosts_selection(selected_profiles: dict[str, str]) -> bool:
        return False



class HostsWorker(QObject):
    """Воркер для асинхронных операций с hosts файлом"""
    finished = pyqtSignal(bool, str)

    def __init__(self, hosts_manager, operation, payload=None):
        super().__init__()
        self.hosts_manager = hosts_manager
        self.operation = operation
        self.payload = payload

    def run(self):
        try:
            success = False
            message = ""

            if self.operation == 'apply_selection':
                service_dns = self.payload or {}
                success = self.hosts_manager.apply_service_dns_selections(service_dns)
                if success:
                    message = "Применено"
                else:
                    message = getattr(self.hosts_manager, "last_status", None) or "Ошибка"

            elif self.operation == 'clear_all':
                success = self.hosts_manager.clear_hosts_file()
                if success:
                    message = "Hosts очищен"
                else:
                    message = getattr(self.hosts_manager, "last_status", None) or "Ошибка"

            elif self.operation == 'adobe_add':
                success = self.hosts_manager.add_adobe_domains()
                if success:
                    message = "Adobe заблокирован"
                else:
                    message = getattr(self.hosts_manager, "last_status", None) or "Ошибка"

            elif self.operation == 'adobe_remove':
                success = self.hosts_manager.remove_adobe_domains()
                if success:
                    message = "Adobe разблокирован"
                else:
                    message = getattr(self.hosts_manager, "last_status", None) or "Ошибка"

            self.finished.emit(success, message)

        except Exception as e:
            log(f"Ошибка в HostsWorker: {e}", "ERROR")
            self.finished.emit(False, str(e))


def _is_fluent_combo(obj) -> bool:
    """Проверяет, является ли объект qfluentwidgets ComboBox."""
    if ComboBox is not None and isinstance(obj, ComboBox):
        return True
    return False


class HostsPage(BasePage):
    """Страница управления Hosts файлом"""

    def __init__(self, parent=None):
        super().__init__(
            "Hosts",
            "Управление разблокировкой сервисов через hosts файл",
            parent,
            title_key="page.hosts.title",
            subtitle_key="page.hosts.subtitle",
        )

        self.hosts_manager = None
        self.service_combos = {}
        self.service_icon_labels = {}
        self.service_name_labels = {}
        self.service_icon_base_colors = {}
        self._services_section_title_labels = []
        self._service_group_title_labels = []
        self._service_group_chips_scrolls = []
        self._service_group_chip_buttons = []
        self._open_hosts_button = None
        self._close_error_button = None
        self._info_text_label = None
        self._browser_warning_label = None
        self._adobe_desc_label = None
        self._adobe_title_label = None
        self._restoring_permissions = False

        self._services_container = None
        self._services_layout = None
        self._catalog_sig = None
        self._catalog_watch_timer = None
        self._main_window = None
        self._app_parent = parent
        self._worker = None
        self._thread = None
        self._applying = False
        self._active_domains_cache = None  # Кеш активных доменов
        self._last_error = None  # Последняя ошибка
        self.error_panel = None  # Панель ошибок
        self._current_operation = None
        self._startup_initialized = False
        self._service_dns_selection = load_user_hosts_selection()
        self._ipv6_infobar_shown = False

        from qfluentwidgets import qconfig
        qconfig.themeChanged.connect(lambda _: self._apply_theme())
        qconfig.themeColorChanged.connect(lambda _: self._apply_theme())

        self._build_ui()

        # Apply tokens to remaining custom inline-styled widgets.
        self._apply_theme()

    def _tr(self, key: str, default: str, **kwargs) -> str:
        text = tr_catalog(key, language=self._ui_language, default=default)
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    def _apply_theme(self) -> None:
        """Applies theme tokens to widgets that still use raw setStyleSheet."""
        tokens = get_theme_tokens()

        # Section title labels (plain QLabel kept for layout/padding control).
        for label in list(self._services_section_title_labels):
            try:
                label.setStyleSheet(
                    f"color: {tokens.fg_muted}; font-size: 13px; font-weight: 600; padding-top: 8px; padding-bottom: 4px;"
                )
            except Exception:
                pass

        # Chip scroll areas (plain QScrollArea, no Fluent equivalent).
        chips_qss = (
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea QWidget { background: transparent; }"
            "QScrollBar:horizontal { height: 4px; background: transparent; margin: 0px; }"
            f"QScrollBar::handle:horizontal {{ background: {tokens.scrollbar_handle}; border-radius: 2px; min-width: 24px; }}"
            f"QScrollBar::handle:horizontal:hover {{ background: {tokens.scrollbar_handle_hover}; }}"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; height: 0px; background: transparent; border: none; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }"
        )
        for scroll in list(self._service_group_chips_scrolls):
            try:
                scroll.setStyleSheet(chips_qss)
            except Exception:
                pass

        # Chip buttons (plain QPushButton link-style, no direct Fluent equivalent).
        chip_qss = _get_fluent_chip_style(tokens)
        for btn in list(self._service_group_chip_buttons):
            try:
                btn.setStyleSheet(chip_qss)
            except Exception:
                pass

        # Close-error icon button (tiny 20x20, stays plain QPushButton).
        if self._close_error_button is not None:
            try:
                self._close_error_button.setIcon(qta.icon('fa5s.times', color=tokens.fg_faint))
                self._close_error_button.setStyleSheet(
                    f"""
                    QPushButton {{
                        background: transparent;
                        border: none;
                    }}
                    QPushButton:hover {{
                        background: {tokens.surface_bg_hover};
                        border-radius: 10px;
                    }}
                    """
                )
            except Exception:
                pass

        try:
            self._update_ui()
        except Exception:
            pass

    def showEvent(self, event):  # noqa: N802 (Qt naming)
        super().showEvent(event)
        self._install_main_window_event_filter()
        # Не запускаем тяжёлые операции при системном восстановлении окна (из трея/свёрнутого).
        if event.spontaneous():
            return

        ipv6_catalog_changed, _ = self._ensure_ipv6_catalog_sections()

        # Лениво инициализируем тяжёлые части страницы только при первом открытии вкладки.
        if not self._startup_initialized:
            if self.hosts_manager is None:
                self._init_hosts_manager()
            self._check_hosts_access()
            self._rebuild_services_selectors()
            self._startup_initialized = True

        self._start_catalog_watcher()
        if ipv6_catalog_changed:
            self._refresh_catalog_if_needed(trigger="ipv6")
        self._refresh_catalog_if_needed(trigger="tab")

        # После инициализации/пересборки селекторов обновляем статус по реальному hosts.
        self._invalidate_cache()
        self._update_ui()

    def hideEvent(self, event):  # noqa: N802 (Qt naming)
        self._close_service_combo_popups()
        self._stop_catalog_watcher()
        super().hideEvent(event)

    def _install_main_window_event_filter(self) -> None:
        try:
            w = self.window()
        except Exception:
            w = None
        if not w or w is self._main_window:
            return

        if self._main_window is not None:
            try:
                self._main_window.removeEventFilter(self)
            except Exception:
                pass

        self._main_window = w
        try:
            w.installEventFilter(self)
        except Exception:
            pass

    def _close_service_combo_popups(self) -> None:
        """Close all service profile dropdown popups if they are open."""
        for control in list(self.service_combos.values()):
            if control is None:
                continue
            try:
                if hasattr(control, "_closeComboMenu"):
                    control._closeComboMenu()
                elif hasattr(control, "hidePopup"):
                    control.hidePopup()
            except Exception:
                pass

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        try:
            if obj is self._main_window and event is not None:
                et = event.type()
                if et in (
                    QEvent.Type.Hide,
                    QEvent.Type.Close,
                    QEvent.Type.WindowDeactivate,
                    QEvent.Type.WindowStateChange,
                ):
                    self._close_service_combo_popups()
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def set_ui_language(self, language: str) -> None:
        super().set_ui_language(language)

        if hasattr(self, "restore_btn") and self.restore_btn is not None:
            if self._restoring_permissions:
                self.restore_btn.setText(
                    self._tr("page.hosts.button.restoring_access", " Восстановление...")
                )
            else:
                self.restore_btn.setText(
                    self._tr("page.hosts.button.restore_access", " Восстановить права доступа")
                )

        if hasattr(self, "clear_btn") and self.clear_btn is not None:
            self.clear_btn.setText(self._tr("page.hosts.button.clear", " Очистить"))

        if self._open_hosts_button is not None:
            self._open_hosts_button.setText(self._tr("page.hosts.button.open", " Открыть"))

        if self._info_text_label is not None:
            self._info_text_label.setText(
                self._tr(
                    "page.hosts.info.note",
                    "Некоторые сервисы (ChatGPT, Spotify и др.) сами блокируют доступ из России — это не блокировка РКН. Решается не через Zapret, а через проксирование: домены направляются через отдельный прокси-сервер в файле hosts.",
                )
            )

        if self._browser_warning_label is not None:
            self._browser_warning_label.setText(
                self._tr(
                    "page.hosts.warning.browser_restart",
                    "После добавления или удаления доменов необходимо перезапустить браузер, чтобы изменения вступили в силу.",
                )
            )

        if self._adobe_desc_label is not None:
            self._adobe_desc_label.setText(
                self._tr(
                    "page.hosts.adobe.description",
                    "⚠️ Блокирует серверы проверки активации Adobe. Включите, если у вас установлена пиратская версия.",
                )
            )
        if self._adobe_title_label is not None:
            self._adobe_title_label.setText(self._tr("page.hosts.adobe.title", "Блокировка Adobe"))

        if self._startup_initialized and not self._applying:
            self._rebuild_services_selectors()
            self._check_hosts_access()

        self._update_ui()

    def _init_hosts_manager(self):
        if self.hosts_manager is not None:
            return

        try:
            app_hosts_manager = None
            parent_app = getattr(self, "parent_app", None)
            if parent_app is not None:
                app_hosts_manager = getattr(parent_app, "hosts_manager", None)
            if app_hosts_manager is None and self._app_parent is not None:
                app_hosts_manager = getattr(self._app_parent, "hosts_manager", None)

            if app_hosts_manager is not None:
                self.hosts_manager = app_hosts_manager
                log("HostsPage: используем общий HostsManager приложения", "DEBUG")
                return
        except Exception:
            pass

        try:
            from hosts.hosts import HostsManager
            self.hosts_manager = HostsManager(status_callback=lambda m: log(f"Hosts: {m}", "INFO"))
        except Exception as e:
            log(f"Ошибка инициализации HostsManager: {e}", "ERROR")

    def _invalidate_cache(self):
        """Сбрасывает кеш активных доменов"""
        self._active_domains_cache = None

    def _get_hosts_path_str(self) -> str:
        try:
            if os.name == "nt":
                sys_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
                if sys_root:
                    return os.path.join(sys_root, "System32", "drivers", "etc", "hosts")
            return os.path.join(get_system32_path(), "drivers", "etc", "hosts")
        except Exception:
            return os.path.join(get_system32_path(), "drivers", "etc", "hosts")

    def _sync_selections_from_hosts(self) -> None:
        """
        Делает UI «источником истины» = реальный hosts.
        Сбрасывает combo/конфиг к тому, что реально присутствует в hosts сейчас.
        """
        if not self.hosts_manager:
            return

        try:
            active_domains_map = self.hosts_manager.get_active_domains_map() or {}
        except Exception:
            active_domains_map = {}

        def infer_profile_from_hosts(service_name: str, available_profiles: list[str]) -> str | None:
            if not active_domains_map or not available_profiles:
                return None

            best_profile: str | None = None
            best_matches = -1
            best_present = -1
            best_total = 0

            for profile_name in available_profiles:
                try:
                    domain_map = get_service_domain_ip_map(service_name, profile_name) or {}
                except Exception:
                    domain_map = {}
                if not domain_map:
                    continue

                total = len(domain_map)
                present = 0
                matches = 0
                for domain, ip in domain_map.items():
                    active_ip = active_domains_map.get(domain)
                    if active_ip is None:
                        continue
                    present += 1
                    if (active_ip or "").strip() == (ip or "").strip():
                        matches += 1

                if total and matches == total:
                    return profile_name

                if matches > best_matches or (matches == best_matches and present > best_present):
                    best_profile = profile_name
                    best_matches = matches
                    best_present = present
                    best_total = total

            if not best_profile:
                return None

            # Direct-only services: if at least one domain is present in hosts, keep them enabled.
            if len(available_profiles) == 1 and best_present > 0:
                return best_profile

            # Otherwise, require a reasonably confident match.
            if best_total and best_matches > 0 and (best_matches / best_total) >= 0.6:
                return best_profile

            return None

        def infer_direct_toggle_from_hosts(service_name: str) -> bool:
            """Для direct-only сервисов: включено, если хотя бы один домен сервиса есть в hosts."""
            try:
                for domain in (get_service_domain_names(service_name) or []):
                    if domain in active_domains_map:
                        return True
            except Exception:
                pass
            return False

        direct_profile = self._get_direct_profile_name()

        new_selection: dict[str, str] = {}

        was_building = getattr(self, "_building_services_ui", False)
        self._building_services_ui = True
        try:
            for service_name, combo in list(self.service_combos.items()):
                direct_only = not get_service_has_geohide_ips(service_name)

                available = list(get_service_available_dns_profiles(service_name) or [])
                inferred: str | None = None

                if direct_only:
                    enabled = infer_direct_toggle_from_hosts(service_name)
                    if isinstance(combo, QCheckBox):
                        can_toggle = bool(direct_profile and direct_profile in available)
                        combo.setEnabled(can_toggle)
                        combo.setChecked(bool(enabled and can_toggle))
                        if combo.isChecked() and direct_profile:
                            new_selection[service_name] = direct_profile
                        self._update_profile_row_visual(service_name)
                        continue
                    if enabled and direct_profile and direct_profile in available:
                        inferred = direct_profile
                else:
                    inferred = infer_profile_from_hosts(service_name, available)

                if inferred:
                    if _is_fluent_combo(combo):
                        idx = combo.findData(inferred)
                        if idx >= 0:
                            combo.blockSignals(True)
                            combo.setCurrentIndex(idx)
                            combo.blockSignals(False)
                            new_selection[service_name] = inferred
                        else:
                            combo.blockSignals(True)
                            combo.setCurrentIndex(0)
                            combo.blockSignals(False)
                else:
                    if _is_fluent_combo(combo):
                        combo.blockSignals(True)
                        combo.setCurrentIndex(0)
                        combo.blockSignals(False)
                    elif isinstance(combo, QCheckBox):
                        combo.setChecked(False)

                self._update_profile_row_visual(service_name)
        finally:
            self._building_services_ui = was_building

        self._service_dns_selection = new_selection
        save_user_hosts_selection(self._service_dns_selection)

    def _get_active_domains(self) -> set:
        """Возвращает активные домены с кешированием (чтобы не читать hosts 28 раз)"""
        if self._active_domains_cache is not None:
            return self._active_domains_cache
        if self.hosts_manager:
            try:
                writable = self.hosts_manager.is_hosts_file_accessible()
                if not writable:
                    hosts_path = self._get_hosts_path_str()
                    self._show_error(
                        self._tr(
                            "page.hosts.error.no_access.long",
                            "Нет доступа для изменения файла hosts.\nЕсли файл редактируется вручную, возможно защитник/антивирус блокирует запись.\nПуть: {path}",
                            path=hosts_path,
                        )
                    )
                else:
                    self._hide_error()

                # Даже если запись запрещена — чтение может работать: показываем реальное состояние.
                self._active_domains_cache = self.hosts_manager.get_active_domains()
                return self._active_domains_cache
            except Exception as e:
                self._show_error(
                    self._tr("page.hosts.error.read_hosts", "Ошибка чтения hosts: {error}", error=e)
                )
                return set()
        return set()

    def _build_ui(self):
        # Панель ошибок (скрыта по умолчанию)
        self._build_error_panel()

        # Информационная заметка
        self._build_info_note()
        self.add_spacing(4)

        # Предупреждение о браузере
        self._build_browser_warning()
        self.add_spacing(6)

        # Статус
        self._build_status_section()
        self.add_spacing(6)

        # Сервисы (выбор DNS-профиля по каждому сервису)
        self._build_services_container()
        self.add_spacing(6)

        # Adobe
        self._build_adobe_section()
        self.add_spacing(6)


    def _build_services_container(self) -> None:
        self._services_container = QWidget()
        self._services_layout = QVBoxLayout(self._services_container)
        self._services_layout.setContentsMargins(0, 0, 0, 0)
        self._services_layout.setSpacing(16)
        self.add_widget(self._services_container)

    def _clear_layout(self, layout: QLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if not item:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout(child_layout)

    def _start_catalog_watcher(self) -> None:
        if self._catalog_watch_timer is None:
            self._catalog_watch_timer = QTimer(self)
            self._catalog_watch_timer.setInterval(5000)
            self._catalog_watch_timer.timeout.connect(lambda: self._refresh_catalog_if_needed(trigger="watcher"))
        if not self._catalog_watch_timer.isActive():
            self._catalog_watch_timer.start()

    def _ensure_ipv6_catalog_sections(self) -> tuple[bool, bool]:
        """Добавляет managed IPv6 секции в hosts.ini при доступном IPv6."""
        try:
            changed, ipv6_available = ensure_ipv6_catalog_sections_if_available()
            if changed:
                log("Hosts: обнаружен IPv6, каталог hosts.ini дополнен IPv6 секциями", "INFO")
                if InfoBar is not None and not self._ipv6_infobar_shown:
                    self._ipv6_infobar_shown = True
                    InfoBar.success(
                        title=self._tr("page.hosts.ipv6.infobar.title", "IPv6"),
                        content=self._tr(
                            "page.hosts.ipv6.infobar.content",
                            "У провайдера обнаружен IPv6. В hosts.ini добавлены IPv6 разделы DNS-провайдеров.",
                        ),
                        parent=self.window(),
                    )
            return (bool(changed), bool(ipv6_available))
        except Exception as e:
            log(f"Hosts: ошибка проверки IPv6 для hosts.ini: {e}", "DEBUG")
            return (False, False)

    def _stop_catalog_watcher(self) -> None:
        if self._catalog_watch_timer is not None and self._catalog_watch_timer.isActive():
            self._catalog_watch_timer.stop()

    def _refresh_catalog_if_needed(self, trigger: str) -> None:
        try:
            sig = get_hosts_catalog_signature()
        except Exception:
            sig = None

        if sig == self._catalog_sig:
            return

        # Сбросим кэш парсинга, чтобы следующий доступ точно перечитал файл.
        try:
            invalidate_hosts_catalog_cache()
        except Exception:
            pass

        if self._services_layout is None:
            self._catalog_sig = sig
            return

        if self._catalog_sig is not None:
            log(f"Hosts: hosts.ini изменился ({trigger}) — обновляем список сервисов", "INFO")

        self._rebuild_services_selectors()
        self._catalog_sig = sig

    def _services_add_section_title(self, text: str) -> None:
        if self._services_layout is None:
            return
        label = QLabel(text)
        self._services_section_title_labels.append(label)
        tokens = get_theme_tokens()
        label.setStyleSheet(
            f"color: {tokens.fg_muted}; font-size: 13px; font-weight: 600; padding-top: 8px; padding-bottom: 4px;"
        )
        self._services_layout.addWidget(label)

    def _services_add_widget(self, widget: QWidget) -> None:
        if self._services_layout is None:
            return
        self._services_layout.addWidget(widget)

    def _rebuild_services_selectors(self) -> None:
        if self._services_layout is None:
            return
        self._clear_layout(self._services_layout)
        self.service_combos = {}
        self.service_icon_labels = {}
        self.service_name_labels = {}
        self.service_icon_base_colors = {}
        self._services_section_title_labels = []
        self._service_group_title_labels = []
        self._service_group_chips_scrolls = []
        self._service_group_chip_buttons = []
        self._build_services_selectors()
        try:
            self._catalog_sig = get_hosts_catalog_signature()
        except Exception:
            self._catalog_sig = None

    def _build_error_panel(self):
        """Панель для отображения ошибок доступа к hosts"""
        semantic = get_semantic_palette()
        self.error_panel = QWidget()
        error_layout = QVBoxLayout(self.error_panel)
        error_layout.setContentsMargins(12, 10, 12, 10)
        error_layout.setSpacing(8)

        # Верхняя строка с иконкой, текстом и кнопкой закрытия
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # Иконка ошибки (QLabel с pixmap — оставляем как есть)
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('fa5s.exclamation-triangle', color=semantic.error).pixmap(20, 20))
        top_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        # Текст ошибки
        self.error_text = BodyLabel()
        self.error_text.setWordWrap(True)
        self.error_text.setStyleSheet(f"color: {semantic.error}; font-size: 12px; background: transparent;")
        top_row.addWidget(self.error_text, 1)

        # Кнопка закрыть (иконочная, 20x20 — plain QPushButton)
        close_btn = QPushButton()
        self._close_error_button = close_btn
        tokens = get_theme_tokens()
        close_btn.setIcon(qta.icon('fa5s.times', color=tokens.fg_faint))
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                border: none;
            }}
            QPushButton:hover {{
                background: {tokens.surface_bg_hover};
                border-radius: 10px;
            }}
            """
        )
        close_btn.clicked.connect(lambda: self.error_panel.hide() if self.error_panel is not None else None)
        top_row.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)

        error_layout.addLayout(top_row)

        # Кнопка восстановления прав
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(30, 0, 0, 0)  # Отступ слева под иконку

        self.restore_btn = PushButton()
        self.restore_btn.setText(
            self._tr("page.hosts.button.restore_access", " Восстановить права доступа")
        )
        self.restore_btn.setIcon(qta.icon('fa5s.wrench', color=tokens.fg))
        self.restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restore_btn.setFixedHeight(32)
        self.restore_btn.clicked.connect(self._restore_hosts_permissions)
        btn_row.addWidget(self.restore_btn)
        btn_row.addStretch()

        error_layout.addLayout(btn_row)

        if self.error_panel is None:
            return

        self.error_panel.setStyleSheet(
            f"""
            QWidget {{
                background-color: {semantic.error_soft_bg};
                border: 1px solid {semantic.error_soft_border};
                border-radius: 8px;
            }}
            """
        )

        self.error_panel.hide()  # Скрыта по умолчанию
        self.add_widget(self.error_panel)

    def _show_error(self, message: str):
        """Показывает ошибку на панели"""
        self._last_error = message
        self.error_text.setText(message)
        if self.error_panel is not None:
            self.error_panel.show()

    def _hide_error(self):
        """Скрывает панель ошибок"""
        self._last_error = None
        if self.error_panel is not None:
            self.error_panel.hide()

    def _restore_hosts_permissions(self):
        """Восстанавливает права доступа к файлу hosts"""
        self._restoring_permissions = True
        self.restore_btn.setEnabled(False)
        self.restore_btn.setText(
            self._tr("page.hosts.button.restoring_access", " Восстановление...")
        )

        try:
            from hosts.hosts import restore_hosts_permissions
            success, message = restore_hosts_permissions()

            if success:
                self._hide_error()
                self._invalidate_cache()
                self._update_ui()
                self._sync_selections_from_hosts()
                if InfoBar:
                    InfoBar.success(
                        title=self._tr("page.hosts.permissions.restore.success.title", "Успех"),
                        content=self._tr(
                            "page.hosts.permissions.restore.success.content",
                            "Права доступа к файлу hosts успешно восстановлены!",
                        ),
                        parent=self.window(),
                    )
            else:
                self._show_error(message)
                if InfoBar:
                    InfoBar.warning(
                        title=self._tr("page.hosts.permissions.restore.fail.title", "Ошибка"),
                        content=self._tr(
                            "page.hosts.permissions.restore.fail.content",
                            "Не удалось восстановить права:\n{message}\n\nПопробуйте временно отключить защиту файла hosts в настройках антивируса (Kaspersky, Dr.Web и т.д.)",
                            message=message,
                        ),
                        parent=self.window(),
                    )
        except Exception as e:
            log(f"Ошибка при восстановлении прав: {e}", "ERROR")
            self._show_error(self._tr("page.hosts.error.generic", "Ошибка: {error}", error=e))
        finally:
            self._restoring_permissions = False
            self.restore_btn.setEnabled(True)
            self.restore_btn.setText(
                self._tr("page.hosts.button.restore_access", " Восстановить права доступа")
            )

    def _check_hosts_access(self):
        """Проверяет доступ к hosts файлу при загрузке страницы"""
        try:
            if self.hosts_manager and self.hosts_manager.is_hosts_file_accessible():
                self._hide_error()
            else:
                hosts_path = self._get_hosts_path_str()
                self._show_error(
                    self._tr(
                        "page.hosts.error.no_access.short",
                        "Нет доступа для изменения файла hosts. Скорее всего защитник/антивирус заблокировал запись.\nПуть: {path}",
                        path=hosts_path,
                    )
                )
        except Exception as e:
            self._show_error(self._tr("page.hosts.error.read_hosts", "Ошибка чтения hosts: {error}", error=e))

    def _build_info_note(self):
        """Информационная заметка о том, зачем нужен hosts"""
        semantic = get_semantic_palette()
        info_card = SettingsCard()

        info_layout = QHBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(10)

        # Иконка лампочки (QLabel с pixmap — оставляем)
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('fa5s.lightbulb', color=semantic.warning).pixmap(20, 20))
        icon_label.setFixedSize(24, 24)
        info_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        # Текст пояснения
        self._info_text_label = CaptionLabel(
            self._tr(
                "page.hosts.info.note",
                "Некоторые сервисы (ChatGPT, Spotify и др.) сами блокируют доступ из России — это не блокировка РКН. Решается не через Zapret, а через проксирование: домены направляются через отдельный прокси-сервер в файле hosts.",
            )
        )
        self._info_text_label.setWordWrap(True)
        info_layout.addWidget(self._info_text_label, 1)

        info_card.add_layout(info_layout)
        self.add_widget(info_card)

    def _build_browser_warning(self):
        """Предупреждение о необходимости перезапуска браузера"""
        semantic = get_semantic_palette()
        warning_layout = QHBoxLayout()
        warning_layout.setContentsMargins(12, 4, 12, 4)
        warning_layout.setSpacing(10)

        # Иконка предупреждения (QLabel с pixmap — оставляем)
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('fa5s.sync-alt', color=semantic.warning).pixmap(16, 16))
        warning_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        # Текст предупреждения
        self._browser_warning_label = CaptionLabel(
            self._tr(
                "page.hosts.warning.browser_restart",
                "После добавления или удаления доменов необходимо перезапустить браузер, чтобы изменения вступили в силу.",
            )
        )
        self._browser_warning_label.setWordWrap(True)
        self._browser_warning_label.setStyleSheet(
            f"color: {semantic.warning_soft}; font-size: 11px; background: transparent;"
        )
        warning_layout.addWidget(self._browser_warning_label, 1)

        # Простой контейнер без фона
        warning_widget = QWidget()
        warning_widget.setLayout(warning_layout)
        warning_widget.setStyleSheet("background: transparent;")

        self.add_widget(warning_widget)

    def _build_status_section(self):
        status_card = SettingsCard()
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(10)

        active = self._get_active_domains()
        tokens = get_theme_tokens()
        semantic = get_semantic_palette()

        # status_dot — цветной символ «●», оставляем plain QLabel для управления цветом
        self.status_dot = QLabel("●")
        dot_color = semantic.success if active else tokens.fg_faint
        self.status_dot.setStyleSheet(f"color: {dot_color}; font-size: 12px;")
        status_layout.addWidget(self.status_dot)

        self.status_label = BodyLabel(
            self._tr("page.hosts.status.active_domains", "Активно {count} доменов", count=len(active))
            if active
            else self._tr("page.hosts.status.none_active", "Нет активных")
        )
        self.status_label.setProperty("tone", "primary")
        status_layout.addWidget(self.status_label, 1)

        self.clear_btn = PushButton()
        self.clear_btn.setIcon(qta.icon('fa5s.trash-alt', color=tokens.fg_muted))
        self.clear_btn.setText(self._tr("page.hosts.button.clear", " Очистить"))
        self.clear_btn.setFixedHeight(32)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        status_layout.addWidget(self.clear_btn)

        self._open_hosts_button = PushButton()
        self._open_hosts_button.setIcon(qta.icon('fa5s.external-link-alt', color=tokens.fg))
        self._open_hosts_button.setText(self._tr("page.hosts.button.open", " Открыть"))
        self._open_hosts_button.setFixedHeight(32)
        self._open_hosts_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_hosts_button.clicked.connect(self._open_hosts_file)
        status_layout.addWidget(self._open_hosts_button)

        status_card.add_layout(status_layout)
        self.add_widget(status_card)

    def _make_fluent_chip(self, label: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(24)
        btn.setStyleSheet(_get_fluent_chip_style())
        return btn

    def _bulk_apply_dns_profile(self, service_names: list[str], profile_name: str | None) -> None:
        if self._applying:
            return

        target_profile = (profile_name or "").strip()

        # Для массового применения по группе используем строгую логику:
        # профиль должен быть доступен для КАЖДОГО сервиса в группе,
        # иначе отменяем операцию целиком (без частичного применения).
        if target_profile:
            unavailable = [
                service_name
                for service_name in service_names
                if target_profile not in (get_service_available_dns_profiles(service_name) or [])
            ]
            if unavailable:
                log(
                    f"Hosts: массовое применение отменено — профиль '{target_profile}' недоступен для: "
                    + ", ".join(unavailable[:8])
                    + ("…" if len(unavailable) > 8 else ""),
                    "DEBUG",
                )
                return

        changed = False
        skipped: list[str] = []
        for service_name in service_names:
            control = self.service_combos.get(service_name)
            if not control:
                continue

            if _is_fluent_combo(control):
                if target_profile:
                    target_idx = control.findData(target_profile)
                    if target_idx < 0:
                        skipped.append(service_name)
                        continue
                else:
                    target_idx = 0

                if control.currentIndex() != target_idx:
                    control.blockSignals(True)
                    control.setCurrentIndex(target_idx)
                    control.blockSignals(False)
                    changed = True
            elif isinstance(control, QCheckBox):
                desired = bool(target_profile)
                if control.isChecked() != desired:
                    was_building = getattr(self, "_building_services_ui", False)
                    self._building_services_ui = True
                    try:
                        control.setChecked(desired)
                    finally:
                        self._building_services_ui = was_building
                    changed = True
            else:
                continue

            if not target_profile:
                if service_name in self._service_dns_selection:
                    self._service_dns_selection.pop(service_name, None)
                    changed = True
            else:
                if self._service_dns_selection.get(service_name) != target_profile:
                    self._service_dns_selection[service_name] = target_profile
                    changed = True

            self._update_profile_row_visual(service_name)

        if not changed:
            if skipped:
                log(
                    "Hosts: профиль недоступен для: "
                    + ", ".join(skipped[:8])
                    + ("…" if len(skipped) > 8 else ""),
                    "DEBUG",
                )
            return

        self._apply_current_selection()

    def _build_services_selectors(self):
        OFF_LABEL = self._tr("page.hosts.services.off", "Откл.")
        all_dns_profiles = [p for p in (get_dns_profiles() or []) if isinstance(p, str) and p.strip()]

        # Карта иконок/цветов по сервису (если есть в QUICK_SERVICES)
        ui_map = {name: (icon_name, icon_color) for icon_name, name, icon_color in QUICK_SERVICES}

        # Все сервисы (с выбором DNS)
        all_services = list(get_all_services() or [])
        ordered_services: list[str] = []
        for _icon, name, _color in QUICK_SERVICES:
            if name in all_services and name not in ordered_services:
                ordered_services.append(name)
        for name in all_services:
            if name not in ordered_services:
                ordered_services.append(name)

        def is_ai_service(name: str) -> bool:
            s = (name or "").strip().lower()
            return any(
                k in s
                for k in (
                    "chatgpt",
                    "openai",
                    "gemini",
                    "claude",
                    "copilot",
                    "grok",
                    "manus",
                )
            )

        no_geohide: list[str] = []
        ai: list[str] = []
        other: list[str] = []
        for service_name in ordered_services:
            if not get_service_has_geohide_ips(service_name):
                no_geohide.append(service_name)
            elif is_ai_service(service_name):
                ai.append(service_name)
            else:
                other.append(service_name)

        def get_common_dns_profiles(service_names: list[str]) -> list[str]:
            """
            Возвращает DNS-профили, которые доступны ДЛЯ КАЖДОГО сервиса в группе.
            Нужно для group-chips, чтобы не показывать провайдеры, недоступные
            хотя бы для одного сервиса в этой группе.
            """
            common: set[str] | None = None

            for service_name in service_names:
                available = {
                    p
                    for p in (get_service_available_dns_profiles(service_name) or [])
                    if isinstance(p, str) and p.strip()
                }
                if common is None:
                    common = available
                else:
                    common &= available

                if not common:
                    return []

            if not common:
                return []

            # Сохраняем порядок как в общем списке [DNS].
            return [profile for profile in all_dns_profiles if profile in common]

        self._services_add_section_title(
            tr_catalog("page.hosts.section.services", language=self._ui_language, default="Сервисы")
        )

        self._building_services_ui = True
        selection_migrated = False
        try:
            active_domains_map: dict[str, str] = {}
            try:
                if self.hosts_manager:
                    active_domains_map = self.hosts_manager.get_active_domains_map() or {}
            except Exception:
                active_domains_map = {}

            def normalize_profile_name(profile_name: str) -> str:
                return _format_dns_profile_label(profile_name).strip().lower()

            def infer_profile_from_hosts(service_name: str, available_profiles: list[str]) -> str | None:
                if not active_domains_map:
                    return None
                if not available_profiles:
                    return None

                best_profile: str | None = None
                best_matches = -1
                best_present = -1
                best_total = 0

                for profile_name in available_profiles:
                    try:
                        domain_map = get_service_domain_ip_map(service_name, profile_name) or {}
                    except Exception:
                        domain_map = {}
                    if not domain_map:
                        continue

                    total = len(domain_map)
                    present = 0
                    matches = 0
                    for domain, ip in domain_map.items():
                        active_ip = active_domains_map.get(domain)
                        if active_ip is None:
                            continue
                        present += 1
                        if (active_ip or "").strip() == (ip or "").strip():
                            matches += 1

                    if total and matches == total:
                        return profile_name

                    if matches > best_matches or (matches == best_matches and present > best_present):
                        best_profile = profile_name
                        best_matches = matches
                        best_present = present
                        best_total = total

                if not best_profile:
                    return None

                # Direct-only services: if at least one domain is present in hosts, keep them enabled.
                if len(available_profiles) == 1 and best_present > 0:
                    return best_profile

                # Otherwise, require a reasonably confident match.
                if best_total and best_matches > 0 and (best_matches / best_total) >= 0.6:
                    return best_profile

                return None

            direct_profile = self._get_direct_profile_name()

            def add_group(title: str, names: list[str], direct_only: bool = False) -> None:
                nonlocal selection_migrated
                if not names:
                    return

                card = SettingsCard()

                header = QHBoxLayout()
                header.setContentsMargins(0, 0, 0, 0)
                header.setSpacing(10)

                title_label = StrongBodyLabel(title)
                self._service_group_title_labels.append(title_label)
                header.addWidget(title_label, 0, Qt.AlignmentFlag.AlignVCenter)

                if not direct_only:
                    chips = QWidget()
                    chips_layout = QHBoxLayout(chips)
                    chips_layout.setContentsMargins(0, 0, 0, 0)
                    chips_layout.setSpacing(4)
                    chips_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
                    chips_layout.addStretch(1)

                    off_btn = self._make_fluent_chip(OFF_LABEL)
                    self._service_group_chip_buttons.append(off_btn)
                    off_btn.clicked.connect(
                        lambda _checked=False, n=tuple(names): self._bulk_apply_dns_profile(list(n), None)
                    )
                    chips_layout.addWidget(off_btn)

                    for profile_name in get_common_dns_profiles(names):
                        label = _format_dns_profile_label(profile_name)
                        if not label:
                            continue
                        btn = self._make_fluent_chip(label)
                        self._service_group_chip_buttons.append(btn)
                        btn.clicked.connect(
                            lambda _checked=False, n=tuple(names), p=profile_name: self._bulk_apply_dns_profile(list(n), p)
                        )
                        chips_layout.addWidget(btn)

                    chips_scroll = QScrollArea()
                    chips_scroll.setFrameShape(QFrame.Shape.NoFrame)
                    chips_scroll.setWidgetResizable(True)
                    chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                    chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                    chips_scroll.setFixedHeight(30)
                    self._service_group_chips_scrolls.append(chips_scroll)
                    tokens = get_theme_tokens()
                    chips_scroll.setStyleSheet(
                        (
                            "QScrollArea { background: transparent; border: none; }"
                            "QScrollArea QWidget { background: transparent; }"
                            "QScrollBar:horizontal { height: 4px; background: transparent; margin: 0px; }"
                            f"QScrollBar::handle:horizontal {{ background: {tokens.scrollbar_handle}; border-radius: 2px; min-width: 24px; }}"
                            f"QScrollBar::handle:horizontal:hover {{ background: {tokens.scrollbar_handle_hover}; }}"
                            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; height: 0px; background: transparent; border: none; }"
                            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }"
                        )
                    )
                    chips_scroll.setWidget(chips)

                    header.addWidget(chips_scroll, 1, Qt.AlignmentFlag.AlignVCenter)
                else:
                    header.addStretch(1)

                card.add_layout(header)

                for service_name in names:
                    row = QHBoxLayout()
                    row.setContentsMargins(0, 0, 0, 0)
                    row.setSpacing(10)

                    icon_name, icon_color = ui_map.get(service_name, ("fa5s.globe", None))

                    # Иконка сервиса (QLabel с pixmap — оставляем)
                    icon_label = QLabel()
                    icon_label.setFixedSize(20, 20)
                    row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

                    name_label = BodyLabel(service_name)
                    self.service_name_labels[service_name] = name_label
                    row.addWidget(name_label, 1, Qt.AlignmentFlag.AlignVCenter)

                    # Откл. + доступные профили
                    available = get_service_available_dns_profiles(service_name) or []

                    is_direct_only = not get_service_has_geohide_ips(service_name)
                    if is_direct_only:
                        toggle = Win11ToggleSwitchNoText()
                        can_toggle = bool(direct_profile and direct_profile in available)
                        toggle.setEnabled(can_toggle)

                        # Источник истины = реальный hosts: выбор в UI должен отражать то, что реально записано.
                        enabled = False
                        if can_toggle:
                            try:
                                enabled = any(
                                    (domain in active_domains_map)
                                    for domain in (get_service_domain_names(service_name) or [])
                                )
                            except Exception:
                                enabled = False

                        toggle.setChecked(bool(enabled and can_toggle))

                        if toggle.isChecked():
                            if self._service_dns_selection.get(service_name) != direct_profile:
                                self._service_dns_selection[service_name] = direct_profile  # type: ignore[arg-type]
                                selection_migrated = True
                        else:
                            if service_name in self._service_dns_selection:
                                self._service_dns_selection.pop(service_name, None)
                                selection_migrated = True

                        toggle.toggled.connect(
                            lambda checked, s=service_name: self._on_direct_toggle_changed(s, checked)
                        )

                        row.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)
                        card.add_layout(row)
                        self.service_combos[service_name] = toggle
                    else:
                        if _HAS_FLUENT and ComboBox is not None:
                            combo = ComboBox()
                        else:
                            from PyQt6.QtWidgets import QComboBox as _QComboBox
                            combo = _QComboBox()
                        combo.setFixedHeight(32)
                        combo.setCursor(Qt.CursorShape.PointingHandCursor)
                        combo.setMinimumWidth(220)
                        combo.addItem(OFF_LABEL, userData=None)
                        for profile_name in available:
                            combo.addItem(_format_dns_profile_label(profile_name), userData=profile_name)

                        # Источник истины = реальный hosts: выбор в UI должен отражать то, что реально записано.
                        inferred = infer_profile_from_hosts(service_name, available)

                        if inferred:
                            inferred_idx = combo.findData(inferred)
                            if inferred_idx >= 0:
                                combo.setCurrentIndex(inferred_idx)
                                if self._service_dns_selection.get(service_name) != inferred:
                                    self._service_dns_selection[service_name] = inferred
                                    selection_migrated = True
                            else:
                                combo.setCurrentIndex(0)
                                if service_name in self._service_dns_selection:
                                    self._service_dns_selection.pop(service_name, None)
                                    selection_migrated = True
                        else:
                            combo.setCurrentIndex(0)
                            if service_name in self._service_dns_selection:
                                self._service_dns_selection.pop(service_name, None)
                                selection_migrated = True

                        combo.currentIndexChanged.connect(
                            lambda _idx, s=service_name, c=combo: self._on_profile_changed(s, c.currentData())
                        )
                        row.addWidget(combo, 0, Qt.AlignmentFlag.AlignVCenter)

                        card.add_layout(row)
                        self.service_combos[service_name] = combo
                    self.service_icon_labels[service_name] = icon_label
                    self.service_icon_base_colors[service_name] = icon_color

                    self._update_profile_row_visual(service_name)

                self._services_add_widget(card)

            add_group(self._tr("page.hosts.group.direct", "Напрямую из hosts"), no_geohide, direct_only=True)
            add_group(self._tr("page.hosts.group.ai", "ИИ"), ai)
            add_group(self._tr("page.hosts.group.other", "Остальные"), other)

            if selection_migrated:
                save_user_hosts_selection(self._service_dns_selection)
        finally:
            self._building_services_ui = False

    def _get_direct_profile_name(self) -> str | None:
        """
        Профиль "direct"/"Вкл. (активировать hosts)" из каталога DNS.
        Нужен для сервисов без proxy/geohide IP (они должны работать как toggle).
        """
        try:
            for profile in (get_dns_profiles() or []):
                p = (profile or "").strip().lower()
                if not p:
                    continue
                if ("вкл. (активировать hosts)" in p) or ("direct" in p) or ("no proxy" in p):
                    return profile
        except Exception:
            pass
        return None

    def _on_direct_toggle_changed(self, service_name: str, checked: bool) -> None:
        if getattr(self, "_building_services_ui", False):
            self._update_profile_row_visual(service_name)
            return
        if self._applying:
            self._update_profile_row_visual(service_name)
            return

        direct_profile = self._get_direct_profile_name()
        if not direct_profile:
            # Strict: without an explicit "direct"/"Вкл. (активировать hosts)" profile we can never apply hosts.
            control = self.service_combos.get(service_name)
            if isinstance(control, QCheckBox):
                was_building = getattr(self, "_building_services_ui", False)
                self._building_services_ui = True
                try:
                    control.setChecked(False)
                finally:
                    self._building_services_ui = was_building
                control.setEnabled(False)
            self._service_dns_selection.pop(service_name, None)
            self._update_profile_row_visual(service_name)
            return

        if checked:
            self._service_dns_selection[service_name] = direct_profile
        else:
            self._service_dns_selection.pop(service_name, None)

        self._update_profile_row_visual(service_name)
        self._apply_current_selection()

    def _build_adobe_section(self):
        self.add_section_title(text_key="page.hosts.section.additional")

        adobe_card = SettingsCard()

        self._adobe_desc_label = CaptionLabel(
            self._tr(
                "page.hosts.adobe.description",
                "⚠️ Блокирует серверы проверки активации Adobe. Включите, если у вас установлена пиратская версия.",
            )
        )
        self._adobe_desc_label.setWordWrap(True)
        adobe_card.add_widget(self._adobe_desc_label)

        adobe_layout = QHBoxLayout()
        adobe_layout.setContentsMargins(0, 0, 0, 0)
        adobe_layout.setSpacing(8)

        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('fa5s.puzzle-piece', color='#ff0000').pixmap(20, 20))
        adobe_layout.addWidget(icon_label)

        self._adobe_title_label = StrongBodyLabel(self._tr("page.hosts.adobe.title", "Блокировка Adobe"))
        adobe_layout.addWidget(self._adobe_title_label, 1)

        is_adobe_active = self.hosts_manager.is_adobe_domains_active() if self.hosts_manager else False

        if SwitchButton is not None:
            self.adobe_switch = SwitchButton()
            self.adobe_switch.setChecked(is_adobe_active)
            self.adobe_switch.checkedChanged.connect(self._toggle_adobe)
        else:
            from PyQt6.QtWidgets import QCheckBox
            self.adobe_switch = QCheckBox()
            self.adobe_switch.setChecked(is_adobe_active)
            self.adobe_switch.toggled.connect(self._toggle_adobe)
        adobe_layout.addWidget(self.adobe_switch)

        adobe_card.add_layout(adobe_layout)
        self.add_widget(adobe_card)

    # ═══════════════════════════════════════════════════════════════
    # ОБРАБОТЧИКИ
    # ═══════════════════════════════════════════════════════════════

    def _on_profile_changed(self, service_name: str, selected_profile: object):
        if getattr(self, "_building_services_ui", False):
            self._update_profile_row_visual(service_name)
            return
        if self._applying:
            self._update_profile_row_visual(service_name)
            return

        profile_name = selected_profile.strip() if isinstance(selected_profile, str) else ""
        if not profile_name:
            self._service_dns_selection.pop(service_name, None)
        else:
            self._service_dns_selection[service_name] = profile_name

        self._update_profile_row_visual(service_name)
        self._apply_current_selection()

    def _update_profile_row_visual(self, service_name: str):
        combo = self.service_combos.get(service_name)
        icon_label = self.service_icon_labels.get(service_name)
        tokens = get_theme_tokens()
        base_color = self.service_icon_base_colors.get(service_name)
        if not base_color:
            base_color = tokens.accent_hex
        if not combo or not icon_label:
            return

        enabled = False
        if _is_fluent_combo(combo):
            enabled = combo.currentData() is not None
        elif isinstance(combo, QCheckBox):
            enabled = bool(combo.isChecked())
        color = base_color if enabled else tokens.fg_faint
        icon_name = None
        for i_name, n, _c in QUICK_SERVICES:
            if n == service_name:
                icon_name = i_name
                break
        try:
            icon = qta.icon(icon_name or "fa5s.globe", color=color)
        except Exception:
            icon = qta.icon("fa5s.globe", color=color)
        icon_label.setPixmap(icon.pixmap(18, 18))

    def _apply_current_selection(self):
        if self._applying:
            return
        self._run_operation('apply_selection', dict(self._service_dns_selection))

    def _on_clear_clicked(self):
        if self._applying:
            return
        if MessageBox is not None:
            box = MessageBox(
                self._tr("page.hosts.dialog.clear.title", "Очистить hosts?"),
                self._tr(
                    "page.hosts.dialog.clear.body",
                    "Это полностью сбросит файл hosts к стандартному содержимому Windows и удалит ВСЕ записи, включая добавленные вручную.",
                ),
                self.window(),
            )
            if not box.exec():
                return
        self._clear_hosts()

    def _clear_hosts(self):
        """Очищает hosts"""
        if self._applying:
            return

        self._run_operation('clear_all')

    def _open_hosts_file(self):
        try:
            import ctypes
            import os
            hosts_path = self._get_hosts_path_str()
            if os.path.exists(hosts_path):
                ctypes.windll.shell32.ShellExecuteW(None, "runas", "notepad.exe", hosts_path, None, 1)
        except Exception as e:
            if InfoBar:
                InfoBar.warning(
                    title=self._tr("page.hosts.open.error.title", "Ошибка"),
                    content=self._tr("page.hosts.open.error.content", "Не удалось открыть: {error}", error=e),
                    parent=self.window(),
                )

    def _toggle_adobe(self, checked: bool):
        if self._applying:
            # Revert the switch without re-triggering the signal
            self.adobe_switch.blockSignals(True)
            self.adobe_switch.setChecked(not checked)
            self.adobe_switch.blockSignals(False)
            return
        self._run_operation('adobe_add' if checked else 'adobe_remove')

    def _run_operation(self, operation: str, payload=None):
        if not self.hosts_manager or self._applying:
            return

        self._applying = True
        self._current_operation = operation

        self._worker = HostsWorker(self.hosts_manager, operation, payload)
        self._thread = QThread()

        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_operation_complete)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _on_operation_complete(self, success: bool, message: str):
        operation = self._current_operation
        self._current_operation = None
        self._applying = False

        # Сбрасываем кеш и обновляем UI
        self._invalidate_cache()
        self._update_ui()
        self._sync_selections_from_hosts()

        if success and operation == "clear_all":
            self._reset_all_service_profiles()

        if success:
            self._hide_error()
        else:
            hosts_path = self._get_hosts_path_str()
            self._show_error(
                self._tr("page.hosts.error.operation_with_path", "{message}\nПуть: {path}", message=message, path=hosts_path)
            )

    def _reset_all_service_profiles(self) -> None:
        """Сбрасывает выбор профилей в UI и user_hosts.ini (после очистки hosts)."""
        self._service_dns_selection = {}
        save_user_hosts_selection(self._service_dns_selection)

        was_building = getattr(self, "_building_services_ui", False)
        self._building_services_ui = True
        try:
            for control in self.service_combos.values():
                if _is_fluent_combo(control):
                    control.blockSignals(True)
                    control.setCurrentIndex(0)
                    control.blockSignals(False)
                elif isinstance(control, QCheckBox):
                    control.setChecked(False)
        finally:
            self._building_services_ui = was_building

        for service_name in list(self.service_combos.keys()):
            self._update_profile_row_visual(service_name)

    def _update_ui(self):
        """Обновляет весь UI"""
        active = self._get_active_domains()
        tokens = get_theme_tokens()
        semantic = get_semantic_palette()

        # Статус
        if active:
            self.status_dot.setStyleSheet(f"color: {semantic.success}; font-size: 12px;")
            self.status_label.setText(
                self._tr("page.hosts.status.active_domains", "Активно {count} доменов", count=len(active))
            )
        else:
            self.status_dot.setStyleSheet(f"color: {tokens.fg_faint}; font-size: 12px;")
            self.status_label.setText(self._tr("page.hosts.status.none_active", "Нет активных"))

        # Обновляем иконки под текущие выборы
        for name in list(self.service_combos.keys()):
            self._update_profile_row_visual(name)

        # Adobe
        is_adobe = self.hosts_manager.is_adobe_domains_active() if self.hosts_manager else False
        self.adobe_switch.blockSignals(True)
        self.adobe_switch.setChecked(is_adobe)
        self.adobe_switch.blockSignals(False)

    def refresh(self):
        """Обновляет страницу (сбрасывает кеш и перечитывает hosts)"""
        self._invalidate_cache()
        self._update_ui()

    def cleanup(self):
        """Очистка потоков при закрытии"""
        from log import log
        try:
            if self._main_window is not None:
                try:
                    self._main_window.removeEventFilter(self)
                except Exception:
                    pass
                self._main_window = None

            if self._thread and self._thread.isRunning():
                log("Останавливаем hosts worker...", "DEBUG")
                self._thread.quit()
                if not self._thread.wait(2000):
                    log("⚠ Hosts worker не завершился, принудительно завершаем", "WARNING")
                    try:
                        self._thread.terminate()
                        self._thread.wait(500)
                    except:
                        pass
        except Exception as e:
            log(f"Ошибка при очистке hosts_page: {e}", "DEBUG")
