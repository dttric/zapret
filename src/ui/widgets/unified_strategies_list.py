# ui/widgets/unified_strategies_list.py
"""
Единый список стратегий с группировкой по сервисам и фильтрацией.
Заменяет CategoriesTabPanel для режима direct (Zapret 2).
"""

from typing import Dict, List, Set, Optional
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal

from .filter_chip_button import FilterButtonGroup
from .collapsible_group import CollapsibleGroup
from .strategy_radio_item import StrategyRadioItem
from ui.theme import get_theme_tokens
from strategy_menu.strategies_registry import registry
from log import log


class UnifiedStrategiesList(QWidget):
    """
    Единый список стратегий с фильтрацией и группировкой.

    Структура:
    - FilterButtonGroup сверху (TCP, UDP, Discord, Voice, Games)
    - QScrollArea со сворачиваемыми группами по command_group

    Особенности:
    - Список создается ОДИН раз при загрузке
    - Фильтрация только через setVisible() - БЕЗ перестроения
    - Поддержка выбора стратегий для каждой категории

    Signals:
        strategy_selected(str, str): (category_key, strategy_id)
        selections_changed(dict): весь словарь выборов
    """

    strategy_selected = pyqtSignal(str, str)
    selections_changed = pyqtSignal(dict)

    # Маппинг command_group -> отображаемое название
    GROUP_NAMES = {
        "youtube": "YouTube",
        "discord": "Discord",
        "telegram": "Telegram",
        "messengers": "Мессенджеры",
        "obsidian": "Обсидиан",
        "social": "Социальные сети",
        "music": "Музыка",
        "games": "Игры",
        "remote": "Удалённый доступ",
        "trackers": "Торренты",
        "streaming": "Стриминг",
        "hostlists": "Хостлисты",
        "ipsets": "IPset (по IP)",
        "github": "GitHub",
        "vpn": "VPN",
        "user": "Пользовательские",
        "default": "Прочее",
    }

    # Порядок групп
    GROUP_ORDER = [
        "youtube", "discord", "telegram", "obsidian", "messengers", "social",
        "music", "streaming", "games", "remote", "trackers",
        "hostlists", "github", "ipsets", "vpn", "user", "default"
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._categories = {}  # {category_key: CategoryInfo}
        self._strategies = {}  # {category_key: {strategy_id: strategy_data}}
        self._selections = {}  # {category_key: strategy_id}
        self._filter_modes = {}  # {category_key: "hostlist"|"ipset"}
        self._groups = {}  # {group_key: CollapsibleGroup}
        self._items = {}  # {category_key: StrategyRadioItem}
        self._category_to_group = {}  # {category_key: group_key}
        self._built = False

        self._build_ui()

    def _build_ui(self):
        """Создает базовый UI (без вложенного scroll - используем scroll родителя)"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Панель фильтров
        self._filter_group = FilterButtonGroup(self)
        self._filter_group.filters_changed.connect(self._on_filters_changed)
        layout.addWidget(self._filter_group)

        # Контейнер для групп (без scroll - родитель BasePage уже scroll area)
        tokens = get_theme_tokens()
        self._content = QWidget()
        self._content.setStyleSheet(f"background: {'transparent' if tokens.is_light else 'transparent'};")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(12)
        self._content_layout.addStretch()

        layout.addWidget(self._content)

    def build_list(
        self,
        categories: Dict,
        selections: Optional[Dict[str, str]] = None,
        filter_modes: Optional[Dict[str, str]] = None,
    ):
        """
        Строит список категорий один раз.

        Args:
            categories: {category_key: CategoryInfo} - все категории
            selections: {category_key: strategy_id} - текущие выборы
        """
        if self._built:
            log("UnifiedStrategiesList: список уже построен, пропускаем", "DEBUG")
            return

        self._categories = categories
        self._selections = selections or {}
        self._filter_modes = filter_modes or {}

        # Группируем категории по command_group
        grouped = {}  # {group_key: [category_key, ...]}
        for cat_key, cat_info in categories.items():
            group_key = getattr(cat_info, 'command_group', 'default') or 'default'
            if group_key not in grouped:
                grouped[group_key] = []
            grouped[group_key].append(cat_key)
            self._category_to_group[cat_key] = group_key

        # Создаем группы в порядке GROUP_ORDER
        for group_key in self.GROUP_ORDER:
            if group_key not in grouped:
                continue

            cat_keys = grouped[group_key]
            if not cat_keys:
                continue

            # Сортируем категории внутри группы по order
            cat_keys.sort(key=lambda k: getattr(categories[k], 'order', 999))

            # Создаем группу
            group_name = self.GROUP_NAMES.get(group_key, group_key.title())
            group = CollapsibleGroup(group_key, group_name, self)
            group.toggled.connect(self._on_group_toggled)

            # Добавляем категории в группу
            for cat_key in cat_keys:
                cat_info = categories[cat_key]
                item = self._create_category_item(cat_key, cat_info)
                group.add_widget(item)
                self._items[cat_key] = item

            self._groups[group_key] = group
            # Вставляем перед stretch
            self._content_layout.insertWidget(
                self._content_layout.count() - 1, group
            )

        self._built = True
        log(f"UnifiedStrategiesList: построено {len(self._groups)} групп, "
            f"{len(self._items)} категорий", "INFO")

    def _get_strategy_name(self, cat_key: str, strategy_id: str) -> str:
        """Получает название стратегии по ID"""
        if strategy_id == 'none':
            return "Отключено"
        try:
            return registry.get_strategy_name_safe(cat_key, strategy_id)
        except:
            return strategy_id

    def _create_category_item(self, cat_key: str, cat_info) -> StrategyRadioItem:
        """Создает элемент для категории"""
        # Получаем текущую выбранную стратегию
        selected_strategy = self._selections.get(cat_key, 'none')
        strategy_name = self._get_strategy_name(cat_key, selected_strategy)

        # Формируем описание
        desc_parts = []
        if hasattr(cat_info, 'protocol') and cat_info.protocol:
            desc_parts.append(cat_info.protocol)
        if hasattr(cat_info, 'ports') and cat_info.ports:
            desc_parts.append(f"порты: {cat_info.ports}")
        description = " | ".join(desc_parts) if desc_parts else ""

        # Получаем tooltip
        tooltip = getattr(cat_info, 'tooltip', '') or ""
        # categories.txt may contain literal "\n" sequences; decode them for Qt tooltips
        if isinstance(tooltip, str) and "\\n" in tooltip:
            tooltip = tooltip.replace("\\n", "\n")

        # Determine list_type based on user's SELECTED filter mode (not availability)
        # 'ipset' if user selected ipset, 'hostlist' if user selected hostlist, None if neither available
        has_ipset = bool(getattr(cat_info, 'base_filter_ipset', ''))
        has_hostlist = bool(getattr(cat_info, 'base_filter_hostlist', ''))
        if has_ipset and has_hostlist:
            list_type = (self._filter_modes.get(cat_key) or "hostlist").strip().lower()
            if list_type not in ("hostlist", "ipset"):
                list_type = "hostlist"
        elif has_ipset:
            list_type = 'ipset'
        elif has_hostlist:
            list_type = 'hostlist'
        else:
            list_type = None

        item = StrategyRadioItem(
            category_key=cat_key,
            name=cat_info.full_name,
            description=description,
            icon_name=getattr(cat_info, 'icon_name', None),
            icon_color=getattr(cat_info, 'icon_color', '#2196F3'),
            tooltip=tooltip,
            list_type=list_type,
            parent=self
        )
        item.item_activated.connect(self._on_item_clicked)

        # Устанавливаем выбранную стратегию
        item.set_strategy(selected_strategy, strategy_name)

        return item

    def _on_item_clicked(self, category_key: str):
        """Обработчик клика по элементу категории"""
        strategy_id = self._selections.get(category_key, 'none')
        self.strategy_selected.emit(category_key, strategy_id)

    def _on_group_toggled(self, group_key: str, is_expanded: bool):
        """Обработчик сворачивания группы"""
        log(f"Группа {group_key} {'развернута' if is_expanded else 'свернута'}", "DEBUG")

    def _on_filters_changed(self, active_filters: Set[str]):
        """Обработчик изменения фильтров"""
        self._apply_filters(active_filters)

    def _apply_filters(self, active_filters: Set[str]):
        """
        Применяет фильтры к элементам (только setVisible).

        Args:
            active_filters: set с активными filter_key
        """
        if "all" in active_filters:
            # Показываем все
            for item in self._items.values():
                item.setVisible(True)
            for group in self._groups.values():
                group.setVisible(True)
            return

        # Определяем какие категории показывать
        visible_categories = set()

        for cat_key, cat_info in self._categories.items():
            show = False

            # TCP фильтр
            if "tcp" in active_filters:
                if hasattr(cat_info, 'protocol') and 'TCP' in cat_info.protocol.upper():
                    show = True

            # UDP фильтр
            if "udp" in active_filters:
                if hasattr(cat_info, 'protocol'):
                    proto = cat_info.protocol.upper()
                    if 'UDP' in proto or 'QUIC' in proto:
                        show = True

            # Discord фильтр
            if "discord" in active_filters:
                group = getattr(cat_info, 'command_group', '')
                if group == 'discord' or 'discord' in cat_key.lower():
                    show = True

            # Voice фильтр
            if "voice" in active_filters:
                strategy_type = getattr(cat_info, 'strategy_type', '')
                if strategy_type == 'discord_voice' or 'voice' in cat_key.lower():
                    show = True

            # Games фильтр
            if "games" in active_filters:
                requires_all = getattr(cat_info, 'requires_all_ports', False)
                group = getattr(cat_info, 'command_group', '')
                if requires_all or group == 'games':
                    show = True

            if show:
                visible_categories.add(cat_key)

        # Применяем видимость к элементам
        for cat_key, item in self._items.items():
            item.setVisible(cat_key in visible_categories)

        # Скрываем пустые группы
        for group_key, group in self._groups.items():
            has_visible = False
            for cat_key, item in self._items.items():
                if self._category_to_group.get(cat_key) == group_key:
                    if item.isVisible():
                        has_visible = True
                        break
            group.setVisible(has_visible)

    def update_selection(self, category_key: str, strategy_id: str):
        """
        Обновляет выбор для категории.

        Args:
            category_key: ключ категории
            strategy_id: ID выбранной стратегии
        """
        self._selections[category_key] = strategy_id

        # Обновляем отображение элемента
        item = self._items.get(category_key)
        if item:
            strategy_name = self._get_strategy_name(category_key, strategy_id)
            item.set_strategy(strategy_id, strategy_name)

        self.selections_changed.emit(self._selections)

    def update_filter_mode(self, category_key: str, filter_mode: str):
        """Updates hostlist/ipset badge for a category (UI-only)."""
        cat_info = self._categories.get(category_key)
        item = self._items.get(category_key)

        has_ipset = bool(getattr(cat_info, "base_filter_ipset", "")) if cat_info else False
        has_hostlist = bool(getattr(cat_info, "base_filter_hostlist", "")) if cat_info else False

        # If category doesn't support list-mode toggle, ensure badge is cleared.
        if not (has_ipset or has_hostlist):
            self._filter_modes.pop(category_key, None)
            if item:
                item.set_list_type(None)
            return

        # If only one mode exists, show that fixed badge (consistent with build_list()).
        if has_ipset and not has_hostlist:
            self._filter_modes[category_key] = "ipset"
            if item:
                item.set_list_type("ipset")
            return
        if has_hostlist and not has_ipset:
            self._filter_modes[category_key] = "hostlist"
            if item:
                item.set_list_type("hostlist")
            return

        # Both available: use the selected mode (fallback to hostlist).
        mode = (filter_mode or "").strip().lower()
        if mode not in ("hostlist", "ipset"):
            mode = "hostlist"
        self._filter_modes[category_key] = mode
        if item:
            item.set_list_type(mode)

    def get_selections(self) -> Dict[str, str]:
        """Возвращает текущие выборы"""
        return self._selections.copy()

    def set_selections(self, selections: Optional[Dict[str, str]]):
        """Устанавливает выборы для всех категорий"""
        selections = selections or {}

        # IMPORTANT:
        # PresetManager.get_strategy_selections() can return a sparse dict
        # (only categories present in the preset file). If we only update
        # provided keys, categories missing in the new preset keep the old
        # UI state (stale "enabled" labels). Always sync every visible item.

        new_selections: Dict[str, str] = {}
        for cat_key in (self._items or {}).keys():
            strategy_id = (selections.get(cat_key) or "none")
            new_selections[cat_key] = strategy_id

            item = self._items.get(cat_key)
            if item:
                strategy_name = self._get_strategy_name(cat_key, strategy_id)
                item.set_strategy(strategy_id, strategy_name)

        # Preserve extra keys (if any) for completeness (e.g. custom categories
        # not yet present in the current registry UI).
        for cat_key, strategy_id in selections.items():
            if cat_key not in new_selections:
                new_selections[cat_key] = strategy_id

        self._selections = new_selections

    def reset_filters(self):
        """Сбрасывает фильтры"""
        self._filter_group.reset()

    def expand_all(self):
        """Разворачивает все группы"""
        for group in self._groups.values():
            group.set_expanded(True)

    def collapse_all(self):
        """Сворачивает все группы"""
        for group in self._groups.values():
            group.set_expanded(False)

    def get_category_item(self, category_key: str) -> Optional[StrategyRadioItem]:
        """Возвращает элемент категории"""
        return self._items.get(category_key)
