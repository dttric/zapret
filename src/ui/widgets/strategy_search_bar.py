"""
Strategy search bar widget with search, filtering, and sorting.

Windows 11 Fluent Design style UI component for filtering strategies.
Includes registry persistence for sort settings.
"""

from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLineEdit,
    QComboBox,
    QLabel,
    QPushButton,
    QFrame,
    QAbstractItemView,
    QListView,
)
from PyQt6.QtCore import pyqtSignal, QTimer, Qt, QSize
from PyQt6.QtGui import QIcon, QAction

try:
    from qfluentwidgets import ComboBox, SearchLineEdit
    _HAS_FLUENT = True
except ImportError:
    ComboBox = QComboBox
    SearchLineEdit = QLineEdit
    _HAS_FLUENT = False

from ui.theme import get_theme_tokens, get_cached_qta_pixmap
from ui.compat_widgets import set_tooltip

from strategy_menu.filter_engine import SearchQuery
from config.reg import reg
from config import REGISTRY_PATH_GUI


class StrategySearchBar(QWidget):
    """
    Search and filter bar for strategies in Windows 11 Fluent Design style.

    Provides text search with debounce, label filtering, and sorting options.
    Emits signals when any filter criteria changes.
    Persists sort settings to Windows Registry.
    """

    # Signals
    search_changed = pyqtSignal(str)  # Text search changed
    filters_changed = pyqtSignal(object)  # SearchQuery changed
    sort_changed = pyqtSignal(str, bool)  # (sort_key, reverse)

    # Label filter options: (display_text, icon_name, value)
    LABEL_OPTIONS = [
        ("Все", "fa5s.layer-group", ""),
        ("Рекоменд.", "fa5s.star", "recommended"),
        ("Эксперим.", "fa5s.flask", "experimental"),
        ("Игровые", "fa5s.gamepad", "game"),
        ("Устаревш.", "fa5s.archive", "deprecated"),
    ]

    # Desync technique filter options: (display_text, icon_name, value)
    # Each value maps to a list of techniques in DESYNC_TECHNIQUE_MAP
    DESYNC_OPTIONS = [
        ("Все", "fa5s.layer-group", ""),
        ("Fake", "fa5s.mask", "fake"),
        ("Split", "fa5s.cut", "split"),
        ("SYN", "fa5s.bolt", "syn"),
        ("HTTP", "fa5s.globe", "http"),
        ("RST", "fa5s.ban", "rst"),
        ("WSize", "fa5s.arrows-alt-h", "wsize"),
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

    # Sort options: (display_text, icon_name, value)
    SORT_OPTIONS = [
        ("По умолчанию", "fa5s.sort", "default"),
        ("А-Я", "fa5s.sort-alpha-down", "name"),
        ("Я-А", "fa5s.sort-alpha-up", "name_desc"),
        ("Рейтинг", "fa5s.sort-amount-down", "rating"),
    ]

    # Debounce delay in milliseconds
    DEBOUNCE_MS = 300

    # Registry keys for persistence
    REG_SORT_KEY = "StrategySortKey"
    REG_SORT_REVERSE = "StrategySortReverse"

    def __init__(self, parent: QWidget = None):
        """
        Initialize the search bar.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self._tokens = get_theme_tokens()
        self._current_qss = ""
        self._applying_theme_styles = False
        self._has_active_filters = False
        self._last_theme_refresh_key: tuple[str, str, str] | None = None

        from qfluentwidgets import qconfig
        qconfig.themeChanged.connect(lambda _: self._refresh_theme())
        qconfig.themeColorChanged.connect(lambda _: self._refresh_theme())

        self._setup_ui()
        self._setup_connections()
        self._refresh_theme()
        self._load_sort_settings()

    def _configure_combo_no_scrollbar(self, combo: QComboBox, item_count: int) -> None:
        """
        Configure QComboBox dropdown to show all items without scrollbar.

        For native QComboBox: sets up a custom QListView with fixed height to ensure
        all items are visible and no scrollbar appears. Must be called AFTER
        adding all items to the combo box.

        For qfluentwidgets ComboBox: only setMaxVisibleItems is called since the
        fluent popup does not expose setView().

        Args:
            combo: QComboBox (or ComboBox) to configure
            item_count: Number of items in the combo box
        """
        combo.setMaxVisibleItems(item_count)

        # qfluentwidgets ComboBox has no setView(); skip custom list view.
        if _HAS_FLUENT and isinstance(combo, ComboBox):
            return

        # Create custom list view for dropdown (native QComboBox only)
        list_view = QListView()
        list_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Calculate height: item_height * count + padding for borders/margins
        # Each item is ~32px (min-height: 24px + padding 6px top/bottom)
        # Add extra pixels for the view's own padding (4px top + 4px bottom) and borders
        item_height = 32
        padding = 12  # 4px padding top + 4px padding bottom + borders
        total_height = (item_height * item_count) + padding

        list_view.setFixedHeight(total_height)
        list_view.setMinimumHeight(total_height)
        list_view.setMaximumHeight(total_height)

        # Set minimum width for dropdown to match ComboBox width
        # This ensures dropdown is never narrower than the button
        combo_width = combo.minimumWidth()
        if combo_width > 0:
            list_view.setMinimumWidth(combo_width + 20)  # Extra space for padding

        self._apply_combo_popup_style(list_view)

        # Set the custom view
        combo.setView(list_view)

    def _apply_combo_popup_style(self, view: QListView) -> None:
        tokens = self._tokens or get_theme_tokens("Темная синяя")

        bg = tokens.surface_bg
        border = tokens.surface_border
        text = tokens.fg
        item_hover = tokens.surface_bg_hover
        item_selected_bg = f"rgba({tokens.accent_rgb_str}, 0.20)"

        view.setStyleSheet(
            f"""
            QListView {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }}
            QListView::item {{
                background: transparent;
                color: {text};
                padding: 6px 10px;
                border-radius: 4px;
                min-height: 24px;
            }}
            QListView::item:hover {{
                background: {item_hover};
            }}
            QListView::item:selected {{
                background: {item_selected_bg};
                color: {tokens.accent_hex};
            }}
            QScrollBar:vertical, QScrollBar:horizontal {{
                width: 0px;
                height: 0px;
                background: transparent;
            }}
            """
        )

    def _get_icon_color(self, *, muted: bool = False) -> str:
        tokens = self._tokens or get_theme_tokens("Темная синяя")
        if muted:
            return tokens.icon_fg_muted
        return tokens.icon_fg

    def _refresh_icons(self) -> None:
        icon_color = self._get_icon_color(muted=True)

        try:
            search_pixmap = get_cached_qta_pixmap("fa5s.search", color=icon_color, size=16)
            self._search_action.setIcon(QIcon(search_pixmap))
        except Exception:
            pass

        try:
            clear_pixmap = get_cached_qta_pixmap("fa5s.times-circle", color=icon_color, size=14)
            self._clear_btn.setIcon(QIcon(clear_pixmap))
        except Exception:
            pass

        # Refresh combo item icons (pixmaps are not auto-recolored on theme change)
        try:
            for i, (_, icon_name, _) in enumerate(self.LABEL_OPTIONS):
                pix = get_cached_qta_pixmap(icon_name, color=icon_color, size=16)
                self._label_combo.setItemIcon(i, QIcon(pix))
            for i, (_, icon_name, _) in enumerate(self.DESYNC_OPTIONS):
                pix = get_cached_qta_pixmap(icon_name, color=icon_color, size=16)
                self._desync_combo.setItemIcon(i, QIcon(pix))
            for i, (_, icon_name, _) in enumerate(self.SORT_OPTIONS):
                pix = get_cached_qta_pixmap(icon_name, color=icon_color, size=16)
                self._sort_combo.setItemIcon(i, QIcon(pix))
        except Exception:
            pass

        # Refresh combo popup view styling (native QComboBox only; fluent ComboBox
        # manages its own popup theming and does not expose a QListView view).
        if not _HAS_FLUENT:
            for combo in (self._label_combo, self._desync_combo, self._sort_combo):
                try:
                    view = combo.view()
                    if isinstance(view, QListView):
                        self._apply_combo_popup_style(view)
                except Exception:
                    pass

    def _build_qss(self) -> str:
        tokens = self._tokens or get_theme_tokens("Темная синяя")
        fg = tokens.fg
        placeholder = tokens.fg_faint
        arrow = tokens.fg_muted
        arrow_hover = tokens.fg
        toolbtn_hover = tokens.surface_bg_hover

        clear_btn_bg = tokens.surface_bg
        clear_btn_bg_hover = tokens.surface_bg_hover
        clear_btn_bg_pressed = tokens.surface_bg_pressed
        clear_btn_border = tokens.surface_border
        clear_btn_border_hover = tokens.surface_border_hover

        # qfluentwidgets SearchLineEdit and ComboBox handle their own theming;
        # only emit QSS for native fallback widgets.
        search_input_qss = "" if _HAS_FLUENT else f"""
            /* Search Input */
            QLineEdit {{
                background: {tokens.surface_bg};
                border: 1px solid {tokens.surface_border};
                border-radius: 6px;
                padding: 8px 12px 8px 34px;
                color: {fg};
                font-size: 13px;
                font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif;
                selection-background-color: rgba({tokens.accent_rgb_str}, 0.30);
            }}
            QLineEdit:hover {{
                background: {tokens.surface_bg_hover};
                border: 1px solid {tokens.surface_border_hover};
            }}
            QLineEdit:focus {{
                background: {tokens.surface_bg_hover};
                border: 1px solid rgba({tokens.accent_rgb_str}, 0.55);
            }}
            QLineEdit::placeholder {{
                color: {placeholder};
            }}
            QLineEdit QToolButton {{
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px 4px;
            }}
            QLineEdit QToolButton:hover {{
                background: {toolbtn_hover};
                border-radius: 4px;
            }}
        """

        combo_qss = "" if _HAS_FLUENT else f"""
            /* ComboBox */
            QComboBox {{
                background: {tokens.surface_bg};
                border: 1px solid {tokens.surface_border};
                border-radius: 6px;
                padding: 6px 22px 6px 10px;
                color: {fg};
                font-size: 13px;
                font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif;
            }}
            QComboBox:hover {{
                background: {tokens.surface_bg_hover};
                border: 1px solid {tokens.surface_border_hover};
            }}
            QComboBox:focus {{
                border: 1px solid rgba({tokens.accent_rgb_str}, 0.55);
            }}
            QComboBox:on {{
                background: {tokens.accent_soft_bg};
                border: 1px solid rgba({tokens.accent_rgb_str}, 0.35);
                color: {tokens.accent_hex};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 22px;
                subcontrol-origin: padding;
                subcontrol-position: right center;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid {arrow};
                margin-right: 10px;
            }}
            QComboBox::down-arrow:hover {{
                border-top-color: {arrow_hover};
            }}
            QComboBox::down-arrow:on {{
                border-top-color: {tokens.accent_hex};
            }}
        """

        return f"""
            {search_input_qss}
            {combo_qss}

            /* Clear Button */
            QPushButton {{
                background: {clear_btn_bg};
                border: 1px solid {clear_btn_border};
                border-radius: 6px;
                padding: 0;
            }}
            QPushButton:hover {{
                background: {clear_btn_bg_hover};
                border: 1px solid {clear_btn_border_hover};
            }}
            QPushButton:pressed {{
                background: {clear_btn_bg_pressed};
            }}

            /* Result Label */
            QLabel {{
                color: {tokens.fg_muted};
                font-size: 12px;
                font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif;
            }}
        """

    def _build_theme_refresh_key(self, tokens) -> tuple[str, str, str]:
        return (str(tokens.theme_name), str(tokens.accent_hex), str(tokens.font_family_qss))

    def _refresh_theme(self) -> None:
        if self._applying_theme_styles:
            return

        refreshed_tokens = get_theme_tokens()
        theme_key = self._build_theme_refresh_key(refreshed_tokens)
        if theme_key == self._last_theme_refresh_key and self._current_qss:
            return

        self._tokens = refreshed_tokens
        self._applying_theme_styles = True
        try:
            qss = self._build_qss()
            if qss != self._current_qss:
                self._current_qss = qss
                self.setStyleSheet(qss)
            self._refresh_icons()
            self._update_clear_button_visibility()
            self._last_theme_refresh_key = theme_key
        finally:
            self._applying_theme_styles = False

    def _setup_ui(self) -> None:
        """Set up UI components in two rows."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        # === Row 1: Search input + clear button + result count ===
        row1 = QHBoxLayout()
        row1.setSpacing(12)

        # Search input with modern styling
        self._search_input = SearchLineEdit()
        self._search_input.setPlaceholderText("Поиск по названию, описанию, аргументам...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setMinimumWidth(280)
        set_tooltip(self._search_input, "Введите текст для поиска стратегий")

        # Add search icon (theme-aware).
        # qfluentwidgets SearchLineEdit.addAction() requires a QAction (not a bare QIcon),
        # because it overrides QLineEdit.addAction with its own implementation.
        search_pixmap = get_cached_qta_pixmap("fa5s.search", color=self._get_icon_color(muted=True), size=16)
        if _HAS_FLUENT:
            # Build a QAction and pass it; SearchLineEdit wraps it in a LineEditButton.
            self._search_action = QAction(QIcon(search_pixmap), "", self)
            self._search_input.addAction(self._search_action, QLineEdit.ActionPosition.LeadingPosition)
        else:
            self._search_action = self._search_input.addAction(
                QIcon(search_pixmap), QLineEdit.ActionPosition.LeadingPosition
            )

        # Debounce timer for search
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(self.DEBOUNCE_MS)

        # Clear filters button (hidden by default)
        self._clear_btn = QPushButton()
        clear_pixmap = get_cached_qta_pixmap("fa5s.times-circle", color=self._get_icon_color(muted=True), size=14)
        self._clear_btn.setIcon(QIcon(clear_pixmap))
        self._clear_btn.setIconSize(QSize(14, 14))
        self._clear_btn.setFixedSize(32, 32)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_tooltip(self._clear_btn, "Сбросить все фильтры")
        self._clear_btn.setVisible(False)

        # Result count label
        self._result_label = QLabel("Найдено: 0")
        self._result_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._result_label.setMinimumWidth(100)

        # Add widgets to row 1
        row1.addWidget(self._search_input, 2)
        row1.addWidget(self._clear_btn)
        row1.addWidget(self._result_label)

        # === Row 2: Label filter + Desync filter + Sort ===
        row2 = QHBoxLayout()
        row2.setSpacing(12)

        # Label filter combo with icon (5 items)
        self._label_combo = ComboBox()
        self._label_combo.setMinimumWidth(110)
        self._label_combo.setMaximumWidth(140)
        set_tooltip(self._label_combo, "Фильтр по типу стратегии")
        for display_text, icon_name, value in self.LABEL_OPTIONS:
            pixmap = get_cached_qta_pixmap(icon_name, color=self._get_icon_color(muted=True), size=16)
            self._label_combo.addItem(display_text, QIcon(pixmap), value)
        # Configure dropdown to show all 5 items without scrollbar
        self._configure_combo_no_scrollbar(self._label_combo, len(self.LABEL_OPTIONS))

        # Desync technique filter combo (7 items)
        self._desync_combo = ComboBox()
        self._desync_combo.setMinimumWidth(90)
        self._desync_combo.setMaximumWidth(120)
        set_tooltip(self._desync_combo, "Фильтр по технике обхода DPI")
        for display_text, icon_name, value in self.DESYNC_OPTIONS:
            pixmap = get_cached_qta_pixmap(icon_name, color=self._get_icon_color(muted=True), size=16)
            self._desync_combo.addItem(display_text, QIcon(pixmap), value)
        # Configure dropdown to show all 7 items without scrollbar
        self._configure_combo_no_scrollbar(self._desync_combo, len(self.DESYNC_OPTIONS))

        # Sort combo with icon (4 items)
        self._sort_combo = ComboBox()
        self._sort_combo.setMinimumWidth(170)
        self._sort_combo.setMaximumWidth(200)
        set_tooltip(self._sort_combo, "Сортировка списка стратегий")
        for display_text, icon_name, value in self.SORT_OPTIONS:
            pixmap = get_cached_qta_pixmap(icon_name, color=self._get_icon_color(muted=True), size=16)
            self._sort_combo.addItem(display_text, QIcon(pixmap), value)
        # Configure dropdown to show all 4 items without scrollbar
        self._configure_combo_no_scrollbar(self._sort_combo, len(self.SORT_OPTIONS))

        # Add widgets to row 2
        row2.addWidget(self._label_combo)
        row2.addWidget(self._desync_combo)
        row2.addWidget(self._sort_combo)
        row2.addStretch()

        # Add rows to main layout
        main_layout.addLayout(row1)
        main_layout.addLayout(row2)

    def _setup_connections(self) -> None:
        """Set up signal connections."""
        # Search input with debounce
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._search_timer.timeout.connect(self._emit_search_changed)

        # Filter combos
        self._label_combo.currentIndexChanged.connect(self._on_filter_changed)
        self._desync_combo.currentIndexChanged.connect(self._on_desync_changed)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)

        # Clear button
        self._clear_btn.clicked.connect(self.clear)

    def _apply_styles(self) -> None:
        # Backward compatibility: older code can still call this.
        self._refresh_theme()

    def _load_sort_settings(self) -> None:
        """Load sort settings from registry."""
        try:
            sort_key = reg(REGISTRY_PATH_GUI, self.REG_SORT_KEY)
            sort_reverse = reg(REGISTRY_PATH_GUI, self.REG_SORT_REVERSE)

            if sort_key:
                # Find and set the sort option
                sort_value = sort_key
                if sort_key == "name" and sort_reverse:
                    sort_value = "name_desc"

                for i, (_, _, value) in enumerate(self.SORT_OPTIONS):
                    if value == sort_value:
                        self._sort_combo.blockSignals(True)
                        self._sort_combo.setCurrentIndex(i)
                        self._sort_combo.blockSignals(False)
                        break
        except Exception:
            pass  # Use defaults if registry read fails

    def _save_sort_settings(self, sort_key: str, reverse: bool) -> None:
        """Save sort settings to registry."""
        try:
            reg(REGISTRY_PATH_GUI, self.REG_SORT_KEY, sort_key)
            reg(REGISTRY_PATH_GUI, self.REG_SORT_REVERSE, 1 if reverse else 0)
        except Exception:
            pass  # Silently ignore registry write failures

    def _update_clear_button_visibility(self) -> None:
        """Show/hide clear button based on active filters."""
        has_search = bool(self._search_input.text().strip())
        has_label = self._label_combo.currentIndex() > 0
        has_desync = self._desync_combo.currentIndex() > 0
        has_sort = self._sort_combo.currentIndex() > 0

        self._has_active_filters = has_search or has_label or has_desync or has_sort
        self._clear_btn.setVisible(self._has_active_filters)

        # Update result label color based on active filters
        tokens = self._tokens or get_theme_tokens("Темная синяя")
        if self._has_active_filters:
            self._result_label.setStyleSheet(
                f"color: rgba({tokens.accent_rgb_str}, 0.85); font-weight: 500;"
            )
        else:
            self._result_label.setStyleSheet(
                f"color: {tokens.fg_muted}; font-weight: normal;"
            )

    def _on_search_text_changed(self, text: str) -> None:
        """Handle search text change with debounce."""
        self._search_timer.stop()
        self._search_timer.start()
        self._update_clear_button_visibility()

    def _emit_search_changed(self) -> None:
        """Emit search_changed signal after debounce."""
        text = self._search_input.text()
        self.search_changed.emit(text)
        self._emit_filters_changed()

    def _on_filter_changed(self) -> None:
        """Handle label filter change."""
        self._update_clear_button_visibility()
        self._emit_filters_changed()

    def _on_desync_changed(self) -> None:
        """Handle desync technique filter change."""
        self._update_clear_button_visibility()
        self._emit_filters_changed()

    def _on_sort_changed(self) -> None:
        """Handle sort option change."""
        sort_value = self._sort_combo.currentData()
        reverse = sort_value == "name_desc"
        sort_key = "name" if sort_value == "name_desc" else sort_value

        # Save to registry
        self._save_sort_settings(sort_key, reverse)

        self.sort_changed.emit(sort_key, reverse)
        self._update_clear_button_visibility()
        self._emit_filters_changed()

    def _emit_filters_changed(self) -> None:
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

        # Text search
        query.text = self._search_input.text().strip()

        # Label filter
        label_value = self._label_combo.currentData()
        if label_value:
            query.labels = [label_value]

        # Desync technique filter
        desync_value = self._desync_combo.currentData()
        if desync_value:
            # Map category to actual technique names
            techniques = self.DESYNC_TECHNIQUE_MAP.get(desync_value, [])
            if techniques:
                query.techniques = techniques

        return query

    def get_sort_key(self) -> tuple[str, bool]:
        """
        Get current sort key and direction.

        Returns:
            Tuple of (sort_key, reverse)
        """
        sort_value = self._sort_combo.currentData()
        reverse = sort_value == "name_desc"
        sort_key = "name" if sort_value == "name_desc" else sort_value
        return sort_key, reverse

    def set_result_count(self, count: int) -> None:
        """
        Update the result count display.

        Args:
            count: Number of found strategies
        """
        self._result_label.setText(f"Найдено: {count}")

    def clear(self) -> None:
        """Clear all search and filter inputs to default state."""
        # Block signals to avoid multiple emissions
        self._search_input.blockSignals(True)
        self._label_combo.blockSignals(True)
        self._desync_combo.blockSignals(True)
        self._sort_combo.blockSignals(True)

        self._search_input.clear()
        self._label_combo.setCurrentIndex(0)
        self._desync_combo.setCurrentIndex(0)
        self._sort_combo.setCurrentIndex(0)

        self._search_input.blockSignals(False)
        self._label_combo.blockSignals(False)
        self._desync_combo.blockSignals(False)
        self._sort_combo.blockSignals(False)

        # Save cleared sort settings
        self._save_sort_settings("default", False)

        self._update_clear_button_visibility()

        # Emit single update
        self._emit_filters_changed()
        self.sort_changed.emit("default", False)

    def has_active_filters(self) -> bool:
        """
        Check if any filters are currently active.

        Returns:
            True if search text, label filter, or non-default sort is set
        """
        return self._has_active_filters
