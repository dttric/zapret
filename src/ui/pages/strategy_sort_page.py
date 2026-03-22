"""
Strategy sort and filter page with toggle buttons.

Windows 11 Fluent Design style UI page for sorting and filtering strategies
using toggle buttons instead of combo boxes.
"""

from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt

from ui.pages.base_page import BasePage
from strategy_menu.filter_engine import SearchQuery
from config.reg import reg
from config import REGISTRY_PATH_GUI
from ui.theme import get_theme_tokens
from ui.text_catalog import tr as tr_catalog


class ToggleButton(QPushButton):
    """
    Toggle button with Windows 11 Fluent Design style.

    Supports active/inactive states with distinct visual styles.
    """

    @staticmethod
    def _style_inactive() -> str:
        tokens = get_theme_tokens()
        return f"""
            QPushButton {{
                background-color: {tokens.surface_bg};
                border: 1px solid {tokens.surface_border};
                border-radius: 6px;
                color: {tokens.fg_muted};
                padding: 8px 16px;
                font-size: 12px;
                font-family: {tokens.font_family_qss};
            }}
            QPushButton:hover {{
                background-color: {tokens.surface_bg_hover};
                border: 1px solid {tokens.surface_border_hover};
            }}
            QPushButton:pressed {{
                background-color: {tokens.surface_bg_pressed};
            }}
        """

    @staticmethod
    def _style_active() -> str:
        tokens = get_theme_tokens()
        return f"""
            QPushButton {{
                background-color: {tokens.accent_soft_bg};
                border: 1px solid rgba({tokens.accent_rgb_str}, 0.40);
                border-radius: 6px;
                color: {tokens.accent_hex};
                padding: 8px 16px;
                font-size: 12px;
                font-weight: 600;
                font-family: {tokens.font_family_qss};
            }}
            QPushButton:hover {{
                background-color: {tokens.accent_soft_bg_hover};
                border: 1px solid rgba({tokens.accent_rgb_str}, 0.50);
            }}
            QPushButton:pressed {{
                background-color: {tokens.accent_soft_bg_hover};
            }}
        """

    def __init__(self, text: str, value: str, parent: QWidget = None):
        """
        Initialize toggle button.

        Args:
            text: Display text for the button
            value: Internal value associated with the button
            parent: Parent widget
        """
        super().__init__(text, parent)
        self._value = value
        self._active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._update_style()

    @property
    def value(self) -> str:
        """Get the button's internal value."""
        return self._value

    @property
    def active(self) -> bool:
        """Check if button is active."""
        return self._active

    @active.setter
    def active(self, state: bool):
        """Set button active state."""
        if self._active != state:
            self._active = state
            self._update_style()

    def _update_style(self):
        """Update button style based on active state."""
        self.setStyleSheet(self._style_active() if self._active else self._style_inactive())


class ToggleButtonGroup(QWidget):
    """
    Group of toggle buttons with single or multi-select behavior.

    Emits signal when selection changes.
    """

    # Emitted when selection changes. Payload is list of selected values.
    selection_changed = pyqtSignal(list)

    def __init__(
        self,
        options: list,
        multi_select: bool = False,
        parent: QWidget = None
    ):
        """
        Initialize toggle button group.

        Args:
            options: List of (display_text, icon_name, value) tuples
            multi_select: If True, allow multiple selections. If False, radio-button behavior.
            parent: Parent widget
        """
        super().__init__(parent)
        self._multi_select = multi_select
        self._buttons: list[ToggleButton] = []
        self._setup_ui(options)

    def _setup_ui(self, options: list):
        """Set up UI with toggle buttons."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        for display_text, icon_name, value in options:
            button = ToggleButton(display_text, value, self)
            button.clicked.connect(lambda checked, b=button: self._on_button_clicked(b))
            self._buttons.append(button)
            layout.addWidget(button)

        # Add stretch to push buttons to the left
        layout.addStretch()

        # Select first button by default if single-select
        if not self._multi_select and self._buttons:
            self._buttons[0].active = True

    def _on_button_clicked(self, clicked_button: ToggleButton):
        """Handle button click."""
        if self._multi_select:
            # Multi-select: toggle clicked button
            # Special case: "All" button (empty value) deselects others
            if clicked_button.value == "":
                # "All" clicked - deselect all others, select "All"
                for button in self._buttons:
                    button.active = (button == clicked_button)
            else:
                # Non-"All" clicked - toggle it
                clicked_button.active = not clicked_button.active

                # If any non-"All" is selected, deselect "All"
                all_button = self._get_button_by_value("")
                if all_button:
                    if clicked_button.active:
                        all_button.active = False
                    else:
                        # If nothing is selected, select "All"
                        if not self.get_selected_values():
                            all_button.active = True
        else:
            # Single-select: only one can be active
            for button in self._buttons:
                button.active = (button == clicked_button)

        self.selection_changed.emit(self.get_selected_values())

    def _get_button_by_value(self, value: str) -> ToggleButton | None:
        """Get button by its value."""
        for button in self._buttons:
            if button.value == value:
                return button
        return None

    def get_selected_values(self) -> list[str]:
        """Get list of selected values."""
        return [b.value for b in self._buttons if b.active and b.value]

    def set_selected_values(self, values: list[str]):
        """
        Set selected values.

        Args:
            values: List of values to select
        """
        if not values or values == [""]:
            # Select "All" (empty value)
            for button in self._buttons:
                button.active = (button.value == "")
        else:
            for button in self._buttons:
                if self._multi_select:
                    button.active = button.value in values
                else:
                    # Single-select: only first match
                    button.active = button.value == values[0] if values else button.value == ""

    def get_single_selected_value(self) -> str:
        """Get single selected value (for single-select mode)."""
        selected = self.get_selected_values()
        return selected[0] if selected else ""


class StrategySortPage(BasePage):
    """
    Strategy sorting and filtering page with toggle buttons.

    Provides UI for filtering strategies by label, desync technique,
    and sorting options using Windows 11 Fluent Design toggle buttons.
    """

    # Signals
    filters_changed = pyqtSignal(object)  # SearchQuery
    sort_changed = pyqtSignal(str, bool)  # (sort_key, reverse)

    # Label filter options: (translation_key, fallback_text, icon_name, value)
    LABEL_OPTIONS = [
        ("page.strategy_sort.option.all", "Все", "fa5s.layer-group", ""),
        ("page.strategy_sort.option.recommended", "Рекоменд.", "fa5s.star", "recommended"),
        ("page.strategy_sort.option.experimental", "Эксперим.", "fa5s.flask", "experimental"),
        ("page.strategy_sort.option.game", "Игровые", "fa5s.gamepad", "game"),
        ("page.strategy_sort.option.deprecated", "Устаревш.", "fa5s.archive", "deprecated"),
    ]

    # Desync technique filter options: (translation_key, fallback_text, icon_name, value)
    DESYNC_OPTIONS = [
        ("page.strategy_sort.option.all", "Все", "fa5s.layer-group", ""),
        ("page.strategy_sort.option.fake", "Fake", "fa5s.mask", "fake"),
        ("page.strategy_sort.option.split", "Split", "fa5s.cut", "split"),
        ("page.strategy_sort.option.syn", "SYN", "fa5s.bolt", "syn"),
        ("page.strategy_sort.option.http", "HTTP", "fa5s.globe", "http"),
        ("page.strategy_sort.option.rst", "RST", "fa5s.ban", "rst"),
        ("page.strategy_sort.option.wsize", "WSize", "fa5s.arrows-alt-h", "wsize"),
    ]

    # Map desync category to actual technique names
    DESYNC_TECHNIQUE_MAP = {
        "fake": ["fake", "fakedsplit", "fakeddisorder", "hostfakesplit"],
        "split": ["multisplit", "multidisorder", "tcpseg", "split", "disorder"],
        "syn": ["syndata", "synack", "synack_split"],
        "http": ["http_domcase", "http_hostcase", "http_methodeol"],
        "rst": ["rst"],
        "wsize": ["wsize", "wssize"],
    }

    # Sort options: (translation_key, fallback_text, icon_name, value)
    SORT_OPTIONS = [
        ("page.strategy_sort.option.default", "По умолчанию", "fa5s.sort", "default"),
        ("page.strategy_sort.option.name_asc", "А-Я", "fa5s.sort-alpha-down", "name"),
        ("page.strategy_sort.option.name_desc", "Я-А", "fa5s.sort-alpha-up", "name_desc"),
        ("page.strategy_sort.option.rating", "Рейтинг", "fa5s.sort-amount-down", "rating"),
    ]

    # Registry keys for persistence
    REG_LABEL_FILTER = "StrategyLabelFilter"
    REG_DESYNC_FILTER = "StrategyDesyncFilter"  # Comma-separated list
    REG_SORT_KEY = "StrategySortKey"

    def __init__(self, parent=None):
        """
        Initialize the strategy sort page.

        Args:
            parent: Parent widget
        """
        super().__init__(
            title="Сортировка",
            subtitle="Фильтры и сортировка стратегий",
            parent=parent,
            title_key="page.strategy_sort.title",
            subtitle_key="page.strategy_sort.subtitle",
        )
        self._sections_meta: list[dict] = []
        self._setup_sections()
        self._load_settings()

    def _tr(self, key: str, default: str, **kwargs) -> str:
        text = tr_catalog(key, language=self._ui_language, default=default)
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    def _build_options(self, option_defs: list[tuple[str, str, str, str]]) -> list[tuple[str, str, str]]:
        options: list[tuple[str, str, str]] = []
        for text_key, fallback, icon_name, value in option_defs:
            options.append((self._tr(text_key, fallback), icon_name, value))
        return options

    def _update_group_texts(self, group: ToggleButtonGroup, option_defs: list[tuple[str, str, str, str]]) -> None:
        text_by_value = {
            value: self._tr(text_key, fallback)
            for text_key, fallback, _icon_name, value in option_defs
        }
        for button in getattr(group, "_buttons", []):
            button.setText(text_by_value.get(button.value, button.text()))

    def _setup_sections(self):
        """Set up filter and sort sections."""
        # Section: Label filter (single-select)
        self._add_section(
            title_key="page.strategy_sort.section.strategy_type.title",
            title_default="Тип стратегии",
            description_key="page.strategy_sort.section.strategy_type.desc",
            description_default="Выберите тип стратегии для фильтрации",
        )
        self._label_group = ToggleButtonGroup(
            options=self._build_options(self.LABEL_OPTIONS),
            multi_select=False,
            parent=self
        )
        self._label_group.selection_changed.connect(self._on_label_changed)
        self.add_widget(self._label_group)

        self.add_spacing(24)

        # Section: Desync technique filter (multi-select)
        self._add_section(
            title_key="page.strategy_sort.section.desync.title",
            title_default="Техника обхода",
            description_key="page.strategy_sort.section.desync.desc",
            description_default="Можно выбрать несколько техник одновременно",
        )
        self._desync_group = ToggleButtonGroup(
            options=self._build_options(self.DESYNC_OPTIONS),
            multi_select=True,
            parent=self
        )
        self._desync_group.selection_changed.connect(self._on_desync_changed)
        self.add_widget(self._desync_group)

        self.add_spacing(24)

        # Section: Sort options (single-select)
        self._add_section(
            title_key="page.strategy_sort.section.sort.title",
            title_default="Сортировка",
            description_key="page.strategy_sort.section.sort.desc",
            description_default="Порядок отображения стратегий в списке",
        )
        self._sort_group = ToggleButtonGroup(
            options=self._build_options(self.SORT_OPTIONS),
            multi_select=False,
            parent=self
        )
        self._sort_group.selection_changed.connect(self._on_sort_changed)
        self.add_widget(self._sort_group)

        # Add stretch at the bottom
        self.layout.addStretch()

    def _add_section(
        self,
        *,
        title_key: str,
        title_default: str,
        description_key: str = "",
        description_default: str = "",
    ):
        """
        Add a section with title and optional description.

        Args:
            title_key: Translation key for section title
            title_default: Fallback section title
            description_key: Translation key for description
            description_default: Fallback description
        """
        # Section title
        tokens = get_theme_tokens()
        title_label = QLabel(self._tr(title_key, title_default))
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {tokens.fg};
                font-size: 14px;
                font-weight: 600;
                font-family: {tokens.font_family_qss};
                padding-top: 4px;
            }}
        """)
        self.add_widget(title_label)

        section_meta = {
            "title_label": title_label,
            "title_key": title_key,
            "title_default": title_default,
            "desc_label": None,
            "desc_key": description_key,
            "desc_default": description_default,
        }

        # Section description
        if description_key or description_default:
            desc_label = QLabel(self._tr(description_key, description_default))
            desc_label.setStyleSheet(f"""
                QLabel {{
                    color: {tokens.fg_faint};
                    font-size: 12px;
                    font-family: {tokens.font_family_qss};
                    padding-bottom: 8px;
                }}
            """)
            desc_label.setWordWrap(True)
            self.add_widget(desc_label)
            section_meta["desc_label"] = desc_label

        self._sections_meta.append(section_meta)

    def _load_settings(self):
        """Load saved filter and sort settings from registry."""
        try:
            # Load label filter
            label_value = reg(REGISTRY_PATH_GUI, self.REG_LABEL_FILTER)
            if label_value:
                self._label_group.set_selected_values([label_value])

            # Load desync filter (comma-separated)
            desync_value = reg(REGISTRY_PATH_GUI, self.REG_DESYNC_FILTER)
            if desync_value:
                desync_list = [v.strip() for v in desync_value.split(",") if v.strip()]
                self._desync_group.set_selected_values(desync_list)

            # Load sort key
            sort_key = reg(REGISTRY_PATH_GUI, self.REG_SORT_KEY)
            if sort_key:
                self._sort_group.set_selected_values([sort_key])
        except Exception:
            pass  # Use defaults if registry read fails

    def _save_label_filter(self, value: str):
        """Save label filter to registry."""
        try:
            reg(REGISTRY_PATH_GUI, self.REG_LABEL_FILTER, value)
        except Exception:
            pass

    def _save_desync_filter(self, values: list[str]):
        """Save desync filter to registry."""
        try:
            value_str = ",".join(values)
            reg(REGISTRY_PATH_GUI, self.REG_DESYNC_FILTER, value_str)
        except Exception:
            pass

    def _save_sort_key(self, value: str):
        """Save sort key to registry."""
        try:
            reg(REGISTRY_PATH_GUI, self.REG_SORT_KEY, value)
        except Exception:
            pass

    def _on_label_changed(self, selected: list[str]):
        """Handle label filter change."""
        value = selected[0] if selected else ""
        self._save_label_filter(value)
        self._emit_filters_changed()

    def _on_desync_changed(self, selected: list[str]):
        """Handle desync filter change."""
        self._save_desync_filter(selected)
        self._emit_filters_changed()

    def _on_sort_changed(self, selected: list[str]):
        """Handle sort option change."""
        sort_value = selected[0] if selected else "default"
        self._save_sort_key(sort_value)

        # Determine sort key and reverse flag
        reverse = sort_value == "name_desc"
        sort_key = "name" if sort_value == "name_desc" else sort_value

        self.sort_changed.emit(sort_key, reverse)
        self._emit_filters_changed()

    def _emit_filters_changed(self):
        """Emit filters_changed signal with current SearchQuery."""
        query = self.get_query()
        self.filters_changed.emit(query)

    def get_query(self) -> SearchQuery:
        """
        Get current search query based on UI state.

        Returns:
            SearchQuery object with current filter criteria
        """
        query = SearchQuery()

        # Label filter
        label_value = self._label_group.get_single_selected_value()
        if label_value:
            query.labels = [label_value]

        # Desync technique filter
        desync_values = self._desync_group.get_selected_values()
        if desync_values:
            # Map categories to actual technique names
            techniques = []
            for value in desync_values:
                techniques.extend(self.DESYNC_TECHNIQUE_MAP.get(value, []))
            if techniques:
                query.techniques = techniques

        return query

    def get_sort_key(self) -> tuple[str, bool]:
        """
        Get current sort key and direction.

        Returns:
            Tuple of (sort_key, reverse)
        """
        sort_value = self._sort_group.get_single_selected_value()
        if not sort_value:
            sort_value = "default"

        reverse = sort_value == "name_desc"
        sort_key = "name" if sort_value == "name_desc" else sort_value
        return sort_key, reverse

    def clear_filters(self):
        """Reset all filters to default state."""
        self._label_group.set_selected_values([""])
        self._desync_group.set_selected_values([""])
        self._sort_group.set_selected_values(["default"])

        self._save_label_filter("")
        self._save_desync_filter([])
        self._save_sort_key("default")

        self._emit_filters_changed()
        self.sort_changed.emit("default", False)

    def set_ui_language(self, language: str) -> None:
        super().set_ui_language(language)

        for meta in self._sections_meta:
            title_label = meta.get("title_label")
            if title_label is not None:
                title_label.setText(
                    self._tr(meta.get("title_key") or "", meta.get("title_default") or "")
                )
            desc_label = meta.get("desc_label")
            if desc_label is not None:
                desc_label.setText(
                    self._tr(meta.get("desc_key") or "", meta.get("desc_default") or "")
                )

        self._update_group_texts(self._label_group, self.LABEL_OPTIONS)
        self._update_group_texts(self._desync_group, self.DESYNC_OPTIONS)
        self._update_group_texts(self._sort_group, self.SORT_OPTIONS)
