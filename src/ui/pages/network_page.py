# ui/pages/network_page.py
"""Страница сетевых настроек - DNS, hosts, proxy"""

from __future__ import annotations
import threading
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QEvent, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QRadioButton, QButtonGroup,
    QLineEdit, QCheckBox, QProgressBar,
)
import qtawesome as qta

try:
    from qfluentwidgets import (
        BodyLabel, CaptionLabel, StrongBodyLabel,
        CheckBox, IndeterminateProgressBar, LineEdit, InfoBar,
    )
    _HAS_FLUENT_LABELS = True
except ImportError:
    CheckBox = QCheckBox
    IndeterminateProgressBar = QProgressBar
    LineEdit = QLineEdit
    InfoBar = None
    _HAS_FLUENT_LABELS = False

from .base_page import BasePage
from .dpi_settings_page import Win11ToggleRow
from ui.compat_widgets import SettingsCard, ActionButton
from ui.pages.strategies_page_base import ResetActionButton
from ui.theme import get_theme_tokens
from ui.text_catalog import tr as tr_catalog
from log import log
from dns import DNS_PROVIDERS, DNSForceManager

if TYPE_CHECKING:
    from main import LupiDPIApp

class DNSProviderCard(SettingsCard):
    """Компактная карточка DNS провайдера"""
    
    selected = pyqtSignal(str, dict)  # name, data
    
    @staticmethod
    def _indicator_off() -> str:
        tokens = get_theme_tokens()
        return f"""
            background-color: {tokens.toggle_off_bg};
            border: 2px solid {tokens.toggle_off_border};
            border-radius: 8px;
        """

    @staticmethod
    def _indicator_on() -> str:
        tokens = get_theme_tokens()
        return f"""
            background-color: {tokens.accent_hex};
            border: 2px solid {tokens.accent_hex};
            border-radius: 8px;
        """
    
    def __init__(
        self,
        name: str,
        data: dict,
        is_current: bool = False,
        show_ipv6: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.name = name
        self.data = data
        self.is_current = is_current
        self.show_ipv6 = bool(show_ipv6)
        self._is_selected = False
        self.setObjectName("dnsCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_ui()

    @staticmethod
    def _normalize_ip_list(value) -> list[str]:
        if isinstance(value, str):
            return [x.strip() for x in value.replace(',', ' ').split() if x.strip()]
        if isinstance(value, list):
            out: list[str] = []
            for item in value:
                item_s = str(item).strip()
                if item_s:
                    out.append(item_s)
            return out
        return []

    def _provider_ip_text(self) -> str:
        ipv4 = self._normalize_ip_list(self.data.get('ipv4', []))
        primary_v4 = ipv4[0] if ipv4 else ""

        if not self.show_ipv6:
            return primary_v4 or "-"

        ipv6 = self._normalize_ip_list(self.data.get('ipv6', []))
        primary_v6 = ipv6[0] if ipv6 else ""

        if primary_v4 and primary_v6:
            return f"v4 {primary_v4} | v6 {primary_v6}"
        if primary_v4:
            return primary_v4
        if primary_v6:
            return primary_v6
        return "-"
        
    def _setup_ui(self):
        tokens = get_theme_tokens()
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 6, 12, 6)
        layout.setSpacing(10)
        
        # Индикатор выбора
        self.indicator = QFrame()
        self.indicator.setFixedSize(16, 16)
        self.indicator.setStyleSheet(self._indicator_off())
        layout.addWidget(self.indicator)
        
        # Иконка провайдера
        icon_color = self.data.get('color') or tokens.accent_hex
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon(
            self.data.get('icon', 'fa5s.server'), 
            color=icon_color
        ).pixmap(18, 18))
        icon_label.setFixedSize(20, 20)
        layout.addWidget(icon_label)
        
        # Название
        if _HAS_FLUENT_LABELS:
            name_label = StrongBodyLabel(self.name)
        else:
            name_label = QLabel(self.name)
            name_label.setStyleSheet(f"color: {tokens.fg}; font-size: 12px; font-weight: 500;")
        layout.addWidget(name_label)

        # Описание
        if _HAS_FLUENT_LABELS:
            desc_label = CaptionLabel(f"· {self.data.get('desc', '')}")
        else:
            desc_label = QLabel(f"· {self.data.get('desc', '')}")
            desc_label.setStyleSheet(f"color: {tokens.fg_faint}; font-size: 11px;")
        layout.addWidget(desc_label)

        layout.addStretch()

        # IP адрес
        ip_text = self._provider_ip_text()
        if _HAS_FLUENT_LABELS:
            ip_label = CaptionLabel(ip_text)
        else:
            ip_label = QLabel(ip_text)
            ip_label.setStyleSheet(f"color: {tokens.fg_muted}; font-size: 11px; font-family: monospace;")
        layout.addWidget(ip_label)
        
        self.add_layout(layout)
    
    def set_selected(self, selected: bool):
        """Устанавливает визуальное состояние выбора"""
        self._is_selected = selected
        self.setProperty("selected", bool(selected))
        style = self.style()
        if style is not None:
            try:
                style.unpolish(self)
                style.polish(self)
            except Exception:
                pass
        self.update()

        if selected:
            self.indicator.setStyleSheet(self._indicator_on())
        else:
            self.indicator.setStyleSheet(self._indicator_off())
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.name, self.data)
        super().mousePressEvent(event)


class AdapterCard(SettingsCard):
    """Компактная карточка сетевого адаптера"""
    
    def __init__(self, name: str, dns_info: dict, parent=None):
        super().__init__(parent)
        self.adapter_name = name
        self.dns_info = dns_info
        self.dns_label = None  # Сохраняем ссылку для обновления
        self._setup_ui()
    
    def _setup_ui(self):
        tokens = get_theme_tokens()
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 6, 12, 6)
        layout.setSpacing(10)
        
        # Кастомный чекбокс через иконку
        self.checkbox = CheckBox()
        self.checkbox.setChecked(True)
        self.checkbox.hide()  # Скрываем стандартный чекбокс
        
        # Иконка-чекбокс
        self.check_icon = QLabel()
        self.check_icon.setFixedSize(20, 20)
        self.check_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_check_icon()
        self.check_icon.mousePressEvent = lambda e: self._toggle_checkbox()
        layout.addWidget(self.check_icon)
        
        # Связываем изменение чекбокса с обновлением иконки
        self.checkbox.stateChanged.connect(self._update_check_icon)
        
        # Иконка
        icon_label = QLabel()
        self._network_icon_label = icon_label
        icon_label.setPixmap(qta.icon('fa5s.network-wired', color=tokens.accent_hex).pixmap(16, 16))
        layout.addWidget(icon_label)
        
        # Название
        if _HAS_FLUENT_LABELS:
            name_label = StrongBodyLabel(self.adapter_name)
        else:
            name_label = QLabel(self.adapter_name)
            name_label.setStyleSheet(f"color: {tokens.fg}; font-size: 12px; font-weight: 500;")
        layout.addWidget(name_label)
        
        layout.addStretch()
        
        # Текущий DNS
        current_dns_v4 = self._normalize_dns_list(self.dns_info.get("ipv4", []))
        current_dns_v6 = self._normalize_dns_list(self.dns_info.get("ipv6", []))
        dns_text = self._format_dns_text(current_dns_v4, current_dns_v6)
        
        if _HAS_FLUENT_LABELS:
            self.dns_label = CaptionLabel(dns_text)
        else:
            self.dns_label = QLabel(dns_text)
            self.dns_label.setStyleSheet(f"color: {tokens.fg_faint}; font-size: 11px; font-family: monospace;")
        layout.addWidget(self.dns_label)
        
        self.add_layout(layout)
    
    @staticmethod
    def _normalize_dns_list(value) -> list:
        """Нормализует DNS в список адресов"""
        if isinstance(value, str):
            return [x.strip() for x in value.replace(',', ' ').split() if x.strip()]
        if isinstance(value, list):
            result = []
            for item in value:
                if isinstance(item, str):
                    result.extend([x.strip() for x in item.replace(',', ' ').split() if x.strip()])
                else:
                    result.append(str(item))
            return result
        return []

    @staticmethod
    def _format_dns_pair(dns_list: list[str]) -> str:
        if not dns_list:
            return ""
        primary = dns_list[0]
        secondary = dns_list[1] if len(dns_list) > 1 else None
        if secondary:
            return f"{primary}, {secondary}"
        return primary

    @classmethod
    def _format_dns_text(cls, ipv4_list: list[str], ipv6_list: list[str]) -> str:
        v4 = cls._format_dns_pair(ipv4_list)
        v6 = cls._format_dns_pair(ipv6_list)

        if v4 and v6:
            return f"v4 {v4} | v6 {v6}"
        if v4:
            return f"v4 {v4}"
        if v6:
            return f"v6 {v6}"
        return "DHCP"
    
    def update_dns_display(self, dns_v4, dns_v6=None):
        """Обновляет отображение текущего DNS"""
        if self.dns_label:
            ipv4 = self._normalize_dns_list(dns_v4)
            ipv6 = self._normalize_dns_list(dns_v6 or [])
            dns_text = self._format_dns_text(ipv4, ipv6)
            self.dns_label.setText(dns_text)
    
    def _toggle_checkbox(self):
        """Переключает состояние чекбокса"""
        self.checkbox.setChecked(not self.checkbox.isChecked())
    
    def _update_check_icon(self, state=None):
        """Обновляет иконку чекбокса"""
        tokens = get_theme_tokens()
        if self.checkbox.isChecked():
            self.check_icon.setPixmap(qta.icon('mdi.checkbox-marked', color=tokens.accent_hex).pixmap(18, 18))
        else:
            self.check_icon.setPixmap(qta.icon('mdi.checkbox-blank-outline', color=tokens.fg_faint).pixmap(18, 18))

    def changeEvent(self, event):  # noqa: N802
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            if getattr(self, '_network_icon_label', None) is not None:
                tokens = get_theme_tokens()
                self._network_icon_label.setPixmap(
                    qta.icon('fa5s.network-wired', color=tokens.accent_hex).pixmap(16, 16)
                )
            self._update_check_icon()
        super().changeEvent(event)


class NetworkPage(BasePage):
    """Страница сетевых настроек с интегрированным DNS"""

    adapters_loaded = pyqtSignal(list)
    dns_info_loaded = pyqtSignal(dict)
    test_completed = pyqtSignal(list)  # Результаты теста соединения
    
    def __init__(self, parent=None):
        super().__init__(
            "Сеть",
            "Настройки DNS и доступа к сервисам",
            parent,
            title_key="page.network.title",
            subtitle_key="page.network.subtitle",
        )
        
        self._dns_manager = None
        self._adapters = []
        self._dns_info = {}
        self._is_loading = True
        self._selected_provider = None
        self._ui_built = False  # Флаг чтобы UI строился только один раз
        self._force_dns_active = False
        self._ipv6_available = False
        self._test_in_progress = False
        self._force_dns_status_enabled = False
        self._force_dns_status_details_key: str | None = None
        self._force_dns_status_details_kwargs: dict = {}
        self._force_dns_status_details_fallback = ""
        
        self.dns_cards = {}
        self.adapter_cards = []
        self._page_initialized = False

    def _tr(self, key: str, default: str) -> str:
        return tr_catalog(key, language=self._ui_language, default=default)

    def _set_reset_button_texts(
        self,
        button,
        text_key: str,
        text_default: str,
        confirm_key: str,
        confirm_default: str,
    ) -> None:
        try:
            button._default_text = self._tr(text_key, text_default)
            button._confirm_text = self._tr(confirm_key, confirm_default)
            button.setText(button._default_text)
        except Exception:
            pass

    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)
        if event.spontaneous():
            return
        if not self._page_initialized:
            self._page_initialized = True
            self._build_ui()
            self._start_loading()

    def set_ui_language(self, language: str) -> None:
        super().set_ui_language(language)

        if hasattr(self, "loading_label"):
            self.loading_label.setText(self._tr("page.network.loading", "⏳ Загрузка..."))

        if hasattr(self, "custom_label"):
            self.custom_label.setText(self._tr("page.network.custom.label", "Свой:"))
        if hasattr(self, "custom_apply_btn"):
            self.custom_apply_btn.setText(self._tr("page.network.custom.apply", "OK"))

        if hasattr(self, "test_btn"):
            if self._test_in_progress:
                self.test_btn.setText(self._tr("page.network.button.test.in_progress", "Проверка..."))
            else:
                self.test_btn.setText(self._tr("page.network.button.test", "Тест соединения"))

        if hasattr(self, "dns_flush_btn"):
            self._set_reset_button_texts(
                self.dns_flush_btn,
                "page.network.button.flush_dns_cache",
                "Сбросить DNS кэш",
                "page.network.button.flush_dns_cache.confirm",
                "Сбросить?",
            )

        if hasattr(self, "auto_label"):
            self.auto_label.setText(self._tr("page.network.dns.auto", "Автоматически (DHCP)"))

        if hasattr(self, "force_dns_card"):
            self.force_dns_card.set_title(
                self._tr(
                    "page.network.force_dns.card.title",
                    "Принудительно прописывает Google DNS для обхода блокировок",
                )
            )
        if hasattr(self, "force_dns_toggle"):
            self.force_dns_toggle.set_texts(
                self._tr("page.network.force_dns.toggle.title", "Принудительный DNS"),
                self._tr(
                    "page.network.force_dns.toggle.description",
                    "Устанавливает Google DNS на активные адаптеры",
                ),
            )
        if hasattr(self, "force_dns_reset_dhcp_btn"):
            self._set_reset_button_texts(
                self.force_dns_reset_dhcp_btn,
                "page.network.force_dns.reset.button",
                "Сбросить DNS на DHCP",
                "page.network.force_dns.reset.confirm",
                "Отключить Force DNS и сбросить DNS на DHCP для всех адаптеров?",
            )

        if hasattr(self, "force_dns_status_label"):
            self._update_force_dns_status(
                self._force_dns_status_enabled,
                self._force_dns_status_details_key,
                details_kwargs=self._force_dns_status_details_kwargs,
                details_fallback=self._force_dns_status_details_fallback,
            )
        
    def _build_ui(self):
        """Строит интерфейс страницы"""
        tokens = get_theme_tokens()
        
        # ═══════════════════════════════════════════════════════════════
        # ПРИНУДИТЕЛЬНЫЙ DNS
        # ═══════════════════════════════════════════════════════════════
        self._build_force_dns_card()
        
        self.add_spacing(12)
        
        # ═══════════════════════════════════════════════════════════════
        # DNS СЕРВЕРЫ
        # ═══════════════════════════════════════════════════════════════
        self.add_section_title(text_key="page.network.section.dns_servers")
        
        # Индикатор загрузки
        self.loading_card = SettingsCard()
        loading_layout = QVBoxLayout()
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        if _HAS_FLUENT_LABELS:
            self.loading_label = BodyLabel(self._tr("page.network.loading", "⏳ Загрузка..."))
        else:
            self.loading_label = QLabel(self._tr("page.network.loading", "⏳ Загрузка..."))
            self.loading_label.setStyleSheet(f"color: {tokens.fg_muted}; font-size: 12px;")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(self.loading_label)
        
        self.loading_bar = IndeterminateProgressBar(self)
        self.loading_bar.setFixedHeight(4)
        self.loading_bar.setMaximumWidth(150)
        if _HAS_FLUENT_LABELS:
            self.loading_bar.start()
        else:
            self.loading_bar.setRange(0, 0)
            self.loading_bar.setTextVisible(False)
        loading_layout.addWidget(self.loading_bar, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.loading_card.add_layout(loading_layout)
        self.add_widget(self.loading_card)
        
        # Контейнер для DNS карточек
        self.dns_cards_container = QWidget()
        self.dns_cards_layout = QVBoxLayout(self.dns_cards_container)
        self.dns_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.dns_cards_layout.setSpacing(4)
        self.dns_cards_container.hide()
        self.add_widget(self.dns_cards_container)
        
        self.add_spacing(6)
        
        # Пользовательский DNS
        self.custom_card = SettingsCard()
        self.custom_card.setObjectName("dnsCard")
        self.custom_card.setProperty("selected", False)
        custom_layout = QHBoxLayout()
        custom_layout.setContentsMargins(10, 6, 12, 6)
        custom_layout.setSpacing(8)
        
        # Индикатор
        self.custom_indicator = QFrame()
        self.custom_indicator.setFixedSize(16, 16)
        self.custom_indicator.setStyleSheet(DNSProviderCard._indicator_off())
        custom_layout.addWidget(self.custom_indicator)
        
        if _HAS_FLUENT_LABELS:
            self.custom_label = BodyLabel(self._tr("page.network.custom.label", "Свой:"))
        else:
            self.custom_label = QLabel(self._tr("page.network.custom.label", "Свой:"))
            self.custom_label.setStyleSheet(f"color: {tokens.fg_muted}; font-size: 12px;")
        custom_layout.addWidget(self.custom_label)
        
        self.custom_primary = LineEdit()
        self.custom_primary.setPlaceholderText("8.8.8.8")
        self.custom_primary.setFixedWidth(110)
        self.custom_primary.returnPressed.connect(self._apply_custom_dns_quick)
        custom_layout.addWidget(self.custom_primary)

        self.custom_secondary = LineEdit()
        self.custom_secondary.setPlaceholderText("8.8.4.4")
        self.custom_secondary.setFixedWidth(110)
        self.custom_secondary.returnPressed.connect(self._apply_custom_dns_quick)
        custom_layout.addWidget(self.custom_secondary)
        
        self.custom_apply_btn = ActionButton(self._tr("page.network.custom.apply", "OK"), "fa5s.check")
        self.custom_apply_btn.setFixedSize(70, 26)
        self.custom_apply_btn.clicked.connect(self._apply_custom_dns_quick)
        custom_layout.addWidget(self.custom_apply_btn)
        
        custom_layout.addStretch()
        
        self.custom_card.add_layout(custom_layout)
        self.custom_card.hide()
        self.add_widget(self.custom_card)
        
        self.add_spacing(12)
        
        # ═══════════════════════════════════════════════════════════════
        # СЕТЕВЫЕ АДАПТЕРЫ
        # ═══════════════════════════════════════════════════════════════
        self.add_section_title(text_key="page.network.section.adapters")
        
        # Контейнер для адаптеров
        self.adapters_container = QWidget()
        self.adapters_layout = QVBoxLayout(self.adapters_container)
        self.adapters_layout.setContentsMargins(0, 0, 0, 0)
        self.adapters_layout.setSpacing(4)
        self.adapters_container.hide()
        self.add_widget(self.adapters_container)
        
        self.add_spacing(12)
        
        # ═══════════════════════════════════════════════════════════════
        # ДИАГНОСТИКА
        # ═══════════════════════════════════════════════════════════════
        self.add_section_title(text_key="page.network.section.tools")
        
        tools_card = SettingsCard()
        tools_layout = QHBoxLayout()
        tools_layout.setContentsMargins(10, 8, 12, 8)
        tools_layout.setSpacing(8)
        
        self.test_btn = ActionButton(self._tr("page.network.button.test", "Тест соединения"), "fa5s.wifi")
        self.test_btn.setFixedHeight(28)
        self.test_btn.clicked.connect(self._test_connection)
        tools_layout.addWidget(self.test_btn)
        
        self.dns_flush_btn = ResetActionButton(
            self._tr("page.network.button.flush_dns_cache", "Сбросить DNS кэш"),
            confirm_text=self._tr("page.network.button.flush_dns_cache.confirm", "Сбросить?"),
        )
        self.dns_flush_btn.setFixedHeight(28)
        self.dns_flush_btn.reset_confirmed.connect(self._flush_dns_cache)
        tools_layout.addWidget(self.dns_flush_btn)
        
        tools_layout.addStretch()
        
        tools_card.add_layout(tools_layout)
        self.add_widget(tools_card)
        
        # Подключаем сигналы
        self.adapters_loaded.connect(self._on_adapters_loaded)
        self.dns_info_loaded.connect(self._on_dns_info_loaded)
    
    def _start_loading(self):
        """Запускает асинхронную загрузку данных"""
        thread = threading.Thread(target=self._load_data, daemon=True)
        thread.start()

    @staticmethod
    def _detect_ipv6_availability() -> bool:
        try:
            return bool(DNSForceManager.check_ipv6_connectivity())
        except Exception as e:
            log(f"Ошибка проверки IPv6 у провайдера: {e}", "DEBUG")
            return False
    
    def _load_data(self):
        """Загружает данные в фоне"""
        try:
            from dns.dns_core import DNSManager, _normalize_alias, refresh_exclusion_cache

            self._ipv6_available = self._detect_ipv6_availability()
            
            refresh_exclusion_cache()
            self._dns_manager = DNSManager()
            
            all_adapters = self._dns_manager.get_network_adapters_fast(
                include_ignored=True,
                include_disconnected=True
            )
            
            filtered = [
                (name, desc) for name, desc in all_adapters
                if not self._dns_manager.should_ignore_adapter(name, desc)
            ]
            
            self._adapters = filtered
            self.adapters_loaded.emit(filtered)
            
            adapter_names = [name for name, _ in all_adapters]
            dns_info = self._dns_manager.get_all_dns_info_fast(adapter_names)
            
            self._dns_info = dns_info
            self.dns_info_loaded.emit(dns_info)
            
        except Exception as e:
            log(f"Ошибка загрузки DNS данных: {e}", "ERROR")
    
    def _on_adapters_loaded(self, adapters):
        self._adapters = adapters
        if self._dns_info and not self._ui_built:
            self._build_dynamic_ui()
    
    def _on_dns_info_loaded(self, dns_info):
        self._dns_info = dns_info
        if self._adapters and not self._ui_built:
            self._build_dynamic_ui()
    
    def _build_dynamic_ui(self):
        """Строит UI после загрузки данных"""
        if self._ui_built:
            return
        self._ui_built = True
        tokens = get_theme_tokens()
        
        from dns.dns_core import _normalize_alias
        
        self._is_loading = False
        self.loading_card.hide()
        self.dns_cards_container.show()
        self.custom_card.show()
        self.adapters_container.show()
        
        # Получаем текущий DNS
        current_dns_v4 = []
        current_dns_v6 = []
        if self._adapters:
            first_adapter = self._adapters[0][0]
            clean = _normalize_alias(first_adapter)
            dns_data = self._dns_info.get(clean, {"ipv4": [], "ipv6": []})
            current_dns_v4 = AdapterCard._normalize_dns_list(dns_data.get("ipv4", []))
            current_dns_v6 = AdapterCard._normalize_dns_list(dns_data.get("ipv6", []))
        
        # Добавляем "Автоматически (DHCP)"
        auto_card = SettingsCard()
        auto_card.setObjectName("dnsCard")
        auto_card.setCursor(Qt.CursorShape.PointingHandCursor)
        auto_card.setProperty("selected", False)
        auto_layout = QHBoxLayout()
        auto_layout.setContentsMargins(10, 6, 12, 6)
        auto_layout.setSpacing(10)
        
        self.auto_indicator = QFrame()
        self.auto_indicator.setFixedSize(16, 16)
        self.auto_indicator.setStyleSheet(DNSProviderCard._indicator_off())
        auto_layout.addWidget(self.auto_indicator)
        
        auto_icon = QLabel()
        auto_icon.setPixmap(qta.icon('fa5s.sync', color=tokens.fg_faint).pixmap(16, 16))
        auto_layout.addWidget(auto_icon)
        
        if _HAS_FLUENT_LABELS:
            self.auto_label = StrongBodyLabel(self._tr("page.network.dns.auto", "Автоматически (DHCP)"))
        else:
            self.auto_label = QLabel(self._tr("page.network.dns.auto", "Автоматически (DHCP)"))
            self.auto_label.setStyleSheet(f"color: {tokens.fg}; font-size: 12px; font-weight: 500;")
        auto_layout.addWidget(self.auto_label)
        
        auto_layout.addStretch()
        
        auto_card.add_layout(auto_layout)
        auto_card.mousePressEvent = lambda e: self._select_auto_dns()
        self.dns_cards_layout.addWidget(auto_card)
        self.auto_card = auto_card
        
        # Добавляем провайдеров
        for category, providers in DNS_PROVIDERS.items():
            if _HAS_FLUENT_LABELS:
                cat_label = CaptionLabel(category)
            else:
                cat_label = QLabel(category)
                cat_label.setStyleSheet(f"""
                    color: {tokens.fg_faint};
                    font-size: 10px;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    padding: 8px 0 4px 4px;
                """)
            self.dns_cards_layout.addWidget(cat_label)
            
            for name, data in providers.items():
                is_current = self._is_current_dns(data['ipv4'], current_dns_v4)
                card = DNSProviderCard(name, data, is_current, show_ipv6=self._ipv6_available)
                card.selected.connect(self._on_dns_selected)
                self.dns_cards[name] = card
                
                if is_current:
                    card.set_selected(True)
                    self._selected_provider = name
                
                self.dns_cards_layout.addWidget(card)

        if self._selected_provider is None and not current_dns_v4 and not current_dns_v6:
            self.auto_indicator.setStyleSheet(DNSProviderCard._indicator_on())
            self._set_dns_card_selected(self.auto_card, True)
            self._selected_provider = None
        
        # Адаптеры
        for name, desc in self._adapters:
            clean = _normalize_alias(name)
            dns_data = self._dns_info.get(clean, {"ipv4": [], "ipv6": []})
            
            card = AdapterCard(name, dns_data)
            card.checkbox.stateChanged.connect(self._sync_selected_dns_card)
            self.adapter_cards.append(card)
            self.adapters_layout.addWidget(card)

        self._sync_selected_dns_card()
    
    def _is_current_dns(self, provider_ips: list, current_ips: list) -> bool:
        return (len(provider_ips) > 0 and 
                len(current_ips) > 0 and 
                provider_ips[0] == current_ips[0])

    def _get_selected_adapter_dns(self) -> tuple[list[str], list[str]] | None:
        from dns.dns_core import _normalize_alias

        selected = self._get_selected_adapters()
        if not selected:
            return None

        clean = _normalize_alias(selected[0])
        dns_data = self._dns_info.get(clean, {"ipv4": [], "ipv6": []})
        current_dns_v4 = AdapterCard._normalize_dns_list(dns_data.get("ipv4", []))
        current_dns_v6 = AdapterCard._normalize_dns_list(dns_data.get("ipv6", []))
        return current_dns_v4, current_dns_v6

    def _sync_selected_dns_card(self, *_):
        if not self.adapter_cards:
            return

        selected_dns = self._get_selected_adapter_dns()
        if selected_dns is None:
            return

        current_dns_v4, current_dns_v6 = selected_dns
        if not current_dns_v4 and not current_dns_v6:
            self._clear_selection()
            if hasattr(self, 'auto_indicator'):
                self.auto_indicator.setStyleSheet(DNSProviderCard._indicator_on())
            if hasattr(self, 'auto_card'):
                self._set_dns_card_selected(self.auto_card, True)
            self._selected_provider = None
            return

        self._clear_selection()
        for name, card in self.dns_cards.items():
            if self._is_current_dns(card.data.get('ipv4', []), current_dns_v4):
                card.set_selected(True)
                self._selected_provider = name
                return

        if hasattr(self, 'custom_indicator'):
            self.custom_indicator.setStyleSheet(DNSProviderCard._indicator_on())
        if hasattr(self, 'custom_card'):
            self._set_dns_card_selected(self.custom_card, True)
        if hasattr(self, 'custom_primary'):
            self.custom_primary.setText(current_dns_v4[0] if current_dns_v4 else "")
        if hasattr(self, 'custom_secondary'):
            self.custom_secondary.setText(current_dns_v4[1] if len(current_dns_v4) > 1 else "")

        self._selected_provider = None
    
    def _clear_selection(self):
        """Сбрасывает все выделения"""
        for card in self.dns_cards.values():
            card.set_selected(False)
        
        if hasattr(self, 'auto_indicator'):
            self.auto_indicator.setStyleSheet(DNSProviderCard._indicator_off())
            if hasattr(self, 'auto_card'):
                self._set_dns_card_selected(self.auto_card, False)
        
        self.custom_indicator.setStyleSheet(DNSProviderCard._indicator_off())
        self._set_dns_card_selected(self.custom_card, False)

    def _set_dns_card_selected(self, card: QWidget | None, selected: bool) -> None:
        if card is None:
            return
        try:
            card.setProperty("selected", bool(selected))
            style = card.style()
            if style is not None:
                style.unpolish(card)
                style.polish(card)
            card.update()
        except Exception:
            pass
    
    def _on_dns_selected(self, name: str, data: dict):
        """Обработчик выбора DNS - сразу применяем"""
        # Если Force DNS активен - подсвечиваем карточку Force DNS
        if self._force_dns_active:
            self._highlight_force_dns()
            return
        
        self._clear_selection()
        self.dns_cards[name].set_selected(True)
        self._selected_provider = name
        
        # Применяем
        self._apply_provider_dns_quick(name, data)
    
    def _select_auto_dns(self):
        """Выбор автоматического DNS"""
        # Если Force DNS активен - подсвечиваем карточку Force DNS
        if self._force_dns_active:
            self._highlight_force_dns()
            return
        
        self._clear_selection()
        self.auto_indicator.setStyleSheet(DNSProviderCard._indicator_on())
        self._set_dns_card_selected(self.auto_card, True)
        self._selected_provider = None
        
        # Применяем
        self._apply_auto_dns_quick()
    
    def _get_selected_adapters(self) -> list:
        """Возвращает выбранные адаптеры"""
        return [card.adapter_name for card in self.adapter_cards if card.checkbox.isChecked()]
    
    def _apply_auto_dns_quick(self):
        """Быстрое применение автоматического DNS (IPv4 + IPv6)"""
        if not self._dns_manager:
            return
        
        adapters = self._get_selected_adapters()
        if not adapters:
            return
        
        success = 0
        for adapter in adapters:
            # Сбрасываем и IPv4, и IPv6
            ok_v4, _ = self._dns_manager.set_auto_dns(adapter, "IPv4")
            ok_v6, _ = self._dns_manager.set_auto_dns(adapter, "IPv6")
            if ok_v4 and ok_v6:
                success += 1
        
        self._dns_manager.flush_dns_cache()
        
        if success == len(adapters):
            log(f"DNS: Автоматический (IPv4+IPv6) применён к {success} адаптерам", "INFO")
        
        # Обновляем отображение DNS у адаптеров
        self._refresh_adapters_dns()
    
    def _apply_provider_dns_quick(self, name: str, data: dict):
        """Быстрое применение DNS провайдера"""
        if not self._dns_manager:
            return
        
        adapters = self._get_selected_adapters()
        if not adapters:
            return
        
        ipv4 = AdapterCard._normalize_dns_list(data.get('ipv4', []))
        if not ipv4:
            log(f"DNS: у провайдера {name} нет IPv4 адресов", "WARNING")
            return

        ipv6 = AdapterCard._normalize_dns_list(data.get('ipv6', []))
        success = 0
        
        for adapter in adapters:
            ok_v4, _ = self._dns_manager.set_custom_dns(
                adapter, 
                ipv4[0], 
                ipv4[1] if len(ipv4) > 1 else None,
                "IPv4"
            )

            ok_v6 = True
            if self._ipv6_available and ipv6:
                ok_v6, _ = self._dns_manager.set_custom_dns(
                    adapter,
                    ipv6[0],
                    ipv6[1] if len(ipv6) > 1 else None,
                    "IPv6"
                )

            if ok_v4 and ok_v6:
                success += 1
        
        self._dns_manager.flush_dns_cache()
        
        if success == len(adapters):
            if self._ipv6_available and ipv6:
                log(f"DNS: {name} (IPv4+IPv6) применён к {success} адаптерам", "INFO")
            else:
                log(f"DNS: {name} применён к {success} адаптерам", "INFO")
        
        # Обновляем отображение DNS у адаптеров
        self._refresh_adapters_dns()
    
    def _apply_custom_dns_quick(self):
        """Быстрое применение пользовательского DNS"""
        # Если Force DNS активен - подсвечиваем карточку Force DNS
        if self._force_dns_active:
            self._highlight_force_dns()
            return
        
        if not self._dns_manager:
            return
        
        primary = self.custom_primary.text().strip()
        if not primary:
            return
        
        secondary = self.custom_secondary.text().strip() or None
        
        self._clear_selection()
        self.custom_indicator.setStyleSheet(DNSProviderCard._indicator_on())
        self._set_dns_card_selected(self.custom_card, True)
        
        adapters = self._get_selected_adapters()
        if not adapters:
            return
        
        success = 0
        for adapter in adapters:
            ok, _ = self._dns_manager.set_custom_dns(adapter, primary, secondary, "IPv4")
            if ok:
                success += 1
        
        self._dns_manager.flush_dns_cache()
        
        if success == len(adapters):
            log(f"DNS: {primary} применён к {success} адаптерам", "INFO")
        
        # Обновляем отображение DNS у адаптеров
        self._refresh_adapters_dns()
    
    def _refresh_adapters_dns(self):
        """Обновляет отображение DNS у всех адаптеров"""
        try:
            if not self._dns_manager:
                log("DNS Manager не инициализирован", "DEBUG")
                return
            
            if not self.adapter_cards:
                log("Нет карточек адаптеров для обновления", "DEBUG")
                return
            
            from dns.dns_core import _normalize_alias
            
            # Собираем имена адаптеров
            adapter_names = [card.adapter_name for card in self.adapter_cards]
            
            # Получаем свежую информацию о DNS
            dns_info = self._dns_manager.get_all_dns_info_fast(adapter_names)
            self._dns_info = dns_info
            
            # Обновляем каждый адаптер
            for card in self.adapter_cards:
                clean_name = _normalize_alias(card.adapter_name)
                adapter_data = dns_info.get(clean_name, {})
                adapter_dns_v4 = adapter_data.get("ipv4", [])
                adapter_dns_v6 = adapter_data.get("ipv6", [])
                card.dns_info = adapter_data
                card.update_dns_display(adapter_dns_v4, adapter_dns_v6)

            self._sync_selected_dns_card()
                
            log("DNS информация адаптеров обновлена", "DEBUG")
            
        except Exception as e:
            log(f"Ошибка обновления DNS адаптеров: {e}", "WARNING")
            import traceback
            log(traceback.format_exc(), "DEBUG")
    
    def _build_force_dns_card(self):
        """Строит виджет принудительного DNS в стиле DPI страницы"""
        from dns import DNSForceManager, ensure_default_force_dns
        tokens = get_theme_tokens()
        
        ensure_default_force_dns()
        manager = DNSForceManager()
        self._force_dns_active = manager.is_force_dns_enabled()
        
        # Секция DNS
        self.add_section_title(text_key="page.network.section.force_dns")
        
        # Карточка
        self.force_dns_card = SettingsCard(
            self._tr(
                "page.network.force_dns.card.title",
                "Принудительно прописывает Google DNS для обхода блокировок",
            )
        )
        dns_layout = QVBoxLayout()
        dns_layout.setSpacing(8)
        
        # Toggle row в стиле Win11
        self.force_dns_toggle = Win11ToggleRow(
            "fa5s.shield-alt",
            self._tr("page.network.force_dns.toggle.title", "Принудительный DNS"),
            self._tr(
                "page.network.force_dns.toggle.description",
                "Устанавливает Google DNS на активные адаптеры",
            ),
            tokens.accent_hex
        )
        self.force_dns_toggle.setChecked(self._force_dns_active)
        self.force_dns_toggle.toggled.connect(self._on_force_dns_toggled)
        dns_layout.addWidget(self.force_dns_toggle)
        
        # Статус
        if _HAS_FLUENT_LABELS:
            self.force_dns_status_label = CaptionLabel("")
        else:
            self.force_dns_status_label = QLabel("")
            self.force_dns_status_label.setStyleSheet(f"color: {tokens.fg_muted}; font-size: 11px;")
        dns_layout.addWidget(self.force_dns_status_label)

        self.force_dns_reset_dhcp_btn = ResetActionButton(
            self._tr("page.network.force_dns.reset.button", "Сбросить DNS на DHCP"),
            confirm_text=self._tr(
                "page.network.force_dns.reset.confirm",
                "Отключить Force DNS и сбросить DNS на DHCP для всех адаптеров?",
            ),
        )
        self.force_dns_reset_dhcp_btn.setFixedHeight(30)
        self.force_dns_reset_dhcp_btn.reset_confirmed.connect(self._reset_dns_to_dhcp)
        dns_layout.addWidget(self.force_dns_reset_dhcp_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        
        self.force_dns_card.add_layout(dns_layout)
        self.add_widget(self.force_dns_card)
        
        # Обновляем статус
        self._update_force_dns_status(self._force_dns_active)
        self._update_dns_selection_state()
    
    def _on_force_dns_toggled(self, enabled: bool):
        """Обработчик переключения принудительного DNS"""
        try:
            from dns import DNSForceManager
            manager = DNSForceManager()
            
            current_state = manager.is_force_dns_enabled()
            if enabled == current_state:
                self._update_force_dns_status(enabled)
                self._update_dns_selection_state()
                return
            
            if enabled:
                success, ok_count, total, message = manager.enable_force_dns(include_disconnected=False)
                log(message, "DNS")
                
                if success:
                    self._force_dns_active = True
                    self._update_force_dns_status(
                        True,
                        "page.network.force_dns.status.details.adapters_applied",
                        details_kwargs={"ok_count": ok_count, "total": total},
                        details_fallback=f"{ok_count}/{total} адаптеров",
                    )
                else:
                    self._set_force_dns_toggle(False)
                    self._update_force_dns_status(
                        False,
                        "page.network.force_dns.status.details.enable_failed",
                    )
            else:
                success, message = manager.disable_force_dns(reset_to_auto=False)
                log(message, "DNS")

                if success:
                    self._force_dns_active = False
                    self._update_force_dns_status(
                        False,
                        "page.network.force_dns.status.details.dns_saved",
                    )
                else:
                    self._set_force_dns_toggle(True)
                    self._update_force_dns_status(
                        True,
                        "page.network.force_dns.status.details.disable_failed",
                    )
            
            self._update_dns_selection_state()
            self._refresh_adapters_dns()
                    
        except Exception as e:
            log(f"Ошибка переключения Force DNS: {e}", "ERROR")
            self._set_force_dns_toggle(not enabled)
            self._update_force_dns_status(
                not enabled,
                "page.network.force_dns.status.details.apply_error",
            )
    
    def _set_force_dns_toggle(self, checked: bool):
        """Устанавливает состояние переключателя без триггера сигналов"""
        self.force_dns_toggle.toggle.blockSignals(True)
        self.force_dns_toggle.setChecked(checked)
        self.force_dns_toggle.toggle.blockSignals(False)
    
    def _update_force_dns_status(
        self,
        enabled: bool,
        details_key: str | None = None,
        *,
        details_kwargs: dict | None = None,
        details_fallback: str = "",
    ):
        """Обновляет текст статуса для принудительного DNS"""
        if not hasattr(self, "force_dns_status_label"):
            return

        self._force_dns_status_enabled = bool(enabled)
        self._force_dns_status_details_key = details_key
        self._force_dns_status_details_kwargs = dict(details_kwargs or {})
        self._force_dns_status_details_fallback = details_fallback or ""
        
        status = (
            self._tr("page.network.force_dns.status.enabled", "Принудительный DNS включен")
            if enabled
            else self._tr("page.network.force_dns.status.disabled", "Принудительный DNS отключен")
        )

        details_text = ""
        if details_key:
            details_default = details_fallback or ""
            try:
                details_text = self._tr(details_key, details_default).format(**(details_kwargs or {}))
            except Exception:
                details_text = self._tr(details_key, details_default)
        elif details_fallback:
            details_text = details_fallback

        if details_text:
            status = f"{status} ({details_text})"
        self.force_dns_status_label.setText(status)
    
    def _update_dns_selection_state(self):
        """Обновляет состояние выбора DNS в зависимости от Force DNS"""
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        
        is_blocked = self._force_dns_active
        
        # Применяем эффект прозрачности к DNS карточкам (делает серыми и иконки тоже)
        if hasattr(self, 'dns_cards_container'):
            if is_blocked:
                effect = QGraphicsOpacityEffect()
                effect.setOpacity(0.35)
                self.dns_cards_container.setGraphicsEffect(effect)
            else:
                self.dns_cards_container.setGraphicsEffect(None)
        
        if hasattr(self, 'custom_card'):
            if is_blocked:
                effect = QGraphicsOpacityEffect()
                effect.setOpacity(0.35)
                self.custom_card.setGraphicsEffect(effect)
            else:
                self.custom_card.setGraphicsEffect(None)
    
    def _highlight_force_dns(self):
        """Подсвечивает карточку принудительного DNS при попытке изменить DNS"""
        if not hasattr(self, 'force_dns_card'):
            return
        
        from PyQt6.QtCore import QTimer
        tokens = get_theme_tokens()
        
        # Применяем яркий стиль
        highlight_style = f"""
            SettingsCard {{
                background-color: {tokens.accent_soft_bg_hover};
                border: 2px solid {tokens.accent_hex};
                border-radius: 10px;
            }}
        """
        original_style = self.force_dns_card.styleSheet()
        self.force_dns_card.setStyleSheet(highlight_style)
        
        # Возвращаем оригинальный стиль через 700мс
        QTimer.singleShot(700, lambda: self.force_dns_card.setStyleSheet(original_style))
    
    def _flush_dns_cache(self):
        """Сбрасывает DNS кэш"""
        try:
            from dns.dns_core import DNSManager
            manager = DNSManager()
            manager.flush_dns_cache()
        except Exception as e:
            if InfoBar:
                InfoBar.warning(
                    title=self._tr("page.network.error.title", "Ошибка"),
                    content=self._tr(
                        "page.network.error.flush_cache_failed",
                        "Не удалось очистить кэш: {error}",
                    ).format(error=e),
                    parent=self.window(),
                )

    def _reset_dns_to_dhcp(self):
        """Явно сбрасывает DNS на DHCP и отключает Force DNS"""
        try:
            from dns import DNSForceManager
            manager = DNSForceManager()

            success, message = manager.disable_force_dns(reset_to_auto=True)
            log(message, "DNS")

            self._force_dns_active = manager.is_force_dns_enabled()
            self._set_force_dns_toggle(self._force_dns_active)

            if not self._force_dns_active:
                self._clear_selection()
                if hasattr(self, 'auto_indicator'):
                    self.auto_indicator.setStyleSheet(DNSProviderCard._indicator_on())
                if hasattr(self, 'auto_card'):
                    self._set_dns_card_selected(self.auto_card, True)
                self._selected_provider = None

            if success:
                self._update_force_dns_status(
                    False,
                    "page.network.force_dns.status.details.dhcp_reset",
                )
            else:
                self._update_force_dns_status(
                    False,
                    "page.network.force_dns.status.details.dhcp_not_applied",
                )

            self._update_dns_selection_state()
            self._refresh_adapters_dns()

            if InfoBar:
                if success:
                    InfoBar.success(
                        title=self._tr("page.network.info.title", "DNS"),
                        content=self._tr(
                            "page.network.info.dhcp_reset_all",
                            "DNS сброшен на DHCP для всех адаптеров",
                        ),
                        parent=self.window(),
                    )
                else:
                    InfoBar.warning(
                        title=self._tr("page.network.info.title", "DNS"),
                        content=message,
                        parent=self.window(),
                    )

        except Exception as e:
            log(f"Ошибка сброса DNS на DHCP: {e}", "ERROR")
            if InfoBar:
                InfoBar.warning(
                    title=self._tr("page.network.error.title", "Ошибка"),
                    content=self._tr(
                        "page.network.error.reset_dhcp_failed",
                        "Не удалось сбросить DNS: {error}",
                    ).format(error=e),
                    parent=self.window(),
                )

    def _test_connection(self):
        """Тестирует соединение с интернетом"""
        import subprocess

        self._test_in_progress = True
        self.test_btn.setEnabled(False)
        self.test_btn.setText(self._tr("page.network.button.test.in_progress", "Проверка..."))

        # Подключаем сигнал (однократно)
        try:
            self.test_completed.disconnect()
        except TypeError:
            pass
        self.test_completed.connect(self._on_test_complete)

        def run_test():
            results = []
            test_hosts = [
                (self._tr("page.network.test.host.google_dns", "Google DNS"), "8.8.8.8"),
                (self._tr("page.network.test.host.cloudflare_dns", "Cloudflare DNS"), "1.1.1.1"),
                ("google.com", "google.com"),
                ("youtube.com", "youtube.com"),
            ]

            for name, host in test_hosts:
                try:
                    # ping с таймаутом 2 секунды
                    result = subprocess.run(
                        ["ping", "-n", "1", "-w", "2000", host],
                        capture_output=True,
                        text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    success = result.returncode == 0
                    results.append((name, host, success))
                except Exception:
                    results.append((name, host, False))

            return results

        def thread_func():
            results = run_test()
            self.test_completed.emit(results)

        thread = threading.Thread(target=thread_func, daemon=True)
        thread.start()

    def _on_test_complete(self, results: list):
        """Вызывается из главного потока после завершения теста"""
        self._test_in_progress = False
        self.test_btn.setEnabled(True)
        self.test_btn.setText(self._tr("page.network.button.test", "Тест соединения"))

        # Формируем отчёт
        report_lines = []
        all_ok = True
        for name, host, success in results:
            status = "✓" if success else "✗"
            report_lines.append(f"{status} {name} ({host})")
            if not success:
                all_ok = False

        report = "\n".join(report_lines)

        if all_ok:
            if InfoBar:
                InfoBar.success(
                    title=self._tr("page.network.test.infobar.title", "Тест соединения"),
                    content=self._tr(
                        "page.network.test.infobar.all_ok",
                        "Все проверки пройдены:\n\n{report}",
                    ).format(report=report),
                    parent=self.window(),
                )
        else:
            if InfoBar:
                InfoBar.warning(
                    title=self._tr("page.network.test.infobar.title", "Тест соединения"),
                    content=self._tr(
                        "page.network.test.infobar.partial",
                        "Некоторые проверки не пройдены:\n\n{report}",
                    ).format(report=report),
                    parent=self.window(),
                )
    
