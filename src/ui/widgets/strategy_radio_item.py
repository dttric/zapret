# ui/widgets/strategy_radio_item.py
"""
Карточка категории для выбора стратегии — использует CardWidget из qfluentwidgets
для нативной hover-анимации и внешнего вида Windows 11 Fluent Design.
"""

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy
from PyQt6.QtCore import pyqtSignal, Qt, QEvent
from PyQt6.QtGui import QCursor
import qtawesome as qta
from typing import Optional

from ui.theme import get_theme_tokens
from ui.compat_widgets import set_tooltip

try:
    from qfluentwidgets import CardWidget, BodyLabel, CaptionLabel, InfoBadge, InfoLevel
    _HAS_FLUENT = True
except ImportError:
    from PyQt6.QtWidgets import QFrame as CardWidget  # type: ignore[assignment]
    from PyQt6.QtWidgets import QLabel as BodyLabel   # type: ignore[assignment]
    from PyQt6.QtWidgets import QLabel as CaptionLabel  # type: ignore[assignment]
    InfoBadge = None  # type: ignore[assignment]
    InfoLevel = None  # type: ignore[assignment]
    _HAS_FLUENT = False


class StrategyRadioItem(CardWidget):
    """
    Карточка категории для выбора стратегии.

    Структура:
    ┌─────────────────────────────────────────────────────────────────┐
    │ 🎬 YouTube TCP  |  TCP 443  |  ● Default Strategy              │
    └─────────────────────────────────────────────────────────────────┘

    При клике эмитит item_activated(category_key).

    Signals:
        item_activated(str): category_key при клике
    """

    item_activated = pyqtSignal(str)

    def __init__(
        self,
        category_key: str,
        name: str,
        description: str = "",
        icon_name: Optional[str] = None,
        icon_color: str = "#2196F3",
        tooltip: str = "",
        list_type: Optional[str] = None,
        parent=None
    ):
        super().__init__(parent)
        self._category_key = category_key
        self._name = name
        self._description = description
        self._icon_name = icon_name
        self._icon_color = icon_color
        self._tooltip = tooltip
        self._list_type = list_type
        self._icon_label = None
        self._desc_label = None
        self._list_badge = None

        self._strategy_id = "none"
        self._strategy_name = "Отключено"

        self._build_ui()

        # CardWidget.clicked (no-args) → emit item_activated(str)
        self.clicked.connect(self._emit_item_activated)

        self.setProperty("clickable", True)
        self.setProperty("noDrag", True)

        if self._tooltip:
            set_tooltip(self, self._tooltip.replace('\n', '<br>'))

    def _emit_item_activated(self):
        self.item_activated.emit(self._category_key)

    @property
    def category_key(self) -> str:
        return self._category_key

    def _build_ui(self):
        self.setMinimumHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)
        self._layout = layout

        # Иконка категории (опционально)
        if self._icon_name:
            try:
                self._icon_label = QLabel()
                self._icon_label.setFixedSize(18, 18)
                self._icon_label.setStyleSheet("background: transparent;")
                layout.addWidget(self._icon_label)
                self._apply_icon_color()
            except Exception:
                pass

        # Название категории
        self._name_label = BodyLabel(self._name)
        layout.addWidget(self._name_label)

        # Описание (protocol | ports)
        if self._description:
            self._desc_label = CaptionLabel(self._description)
            layout.addWidget(self._desc_label)

        # Badge для hostlist/ipset
        if self._list_type:
            self._ensure_list_badge()

        layout.addStretch(1)

        # Статус точка
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("background: transparent; color: #888888;")
        layout.addWidget(self._status_dot)

        # Название стратегии
        self._strategy_label = CaptionLabel("Отключено")
        layout.addWidget(self._strategy_label)

        self._apply_style()

    def _ensure_list_badge(self):
        if self._list_badge is None:
            if InfoBadge is not None:
                self._list_badge = InfoBadge("", self)
            else:
                self._list_badge = QLabel()
            insert_index = max(0, self._layout.count() - 1)
            self._layout.insertWidget(insert_index, self._list_badge)
        self._apply_list_badge()

    def _apply_list_badge(self):
        if not self._list_badge:
            return
        if not self._list_type:
            self._list_badge.hide()
            return

        if InfoBadge is not None and isinstance(self._list_badge, InfoBadge):
            if self._list_type == "hostlist":
                self._list_badge.setText("Hostlist")
                # Reset any custom colour from a previous ipset state
                self._list_badge.lightBackgroundColor = None
                self._list_badge.darkBackgroundColor = None
                self._list_badge.level = InfoLevel.SUCCESS
            else:  # ipset
                self._list_badge.setText("IPset")
                self._list_badge.setCustomBackgroundColor("#8B5CF6", "#8B5CF6")
            self._list_badge.adjustSize()
            self._list_badge.update()
        else:
            # QLabel fallback (no qfluentwidgets)
            self._list_badge.setText(self._list_type)
            badge_bg = "#00B900" if self._list_type == "hostlist" else "#8B5CF6"
            self._list_badge.setStyleSheet(f"""
                QLabel {{
                    background: {badge_bg};
                    color: rgba(245, 245, 245, 0.95);
                    border-radius: 8px;
                    padding: 1px 6px;
                    font-size: 9px;
                    font-weight: 600;
                }}
            """)

        self._list_badge.show()

    def _apply_style(self):
        """Обновляет цвет статус-точки по активности."""
        if self.is_active():
            self._status_dot.setStyleSheet("background: transparent; color: #6ccb5f;")
        else:
            try:
                tokens = get_theme_tokens()
                self._status_dot.setStyleSheet(
                    f"background: transparent; color: {tokens.fg_faint};"
                )
            except Exception:
                self._status_dot.setStyleSheet("background: transparent; color: #888888;")

    def _apply_icon_color(self):
        if not self._icon_name or self._icon_label is None:
            return
        try:
            tokens = get_theme_tokens()
            color = self._icon_color if self.is_active() else (
                "#808080" if tokens.is_light else "#BFC5CF"
            )
            self._icon_label.setPixmap(
                qta.icon(self._icon_name, color=color).pixmap(18, 18)
            )
        except Exception:
            pass

    def set_strategy(self, strategy_id: str, strategy_name: str):
        self._strategy_id = strategy_id
        self._strategy_name = strategy_name
        self._strategy_label.setText(strategy_name)
        self._apply_icon_color()
        self._apply_style()

    def set_list_type(self, list_type: str | None):
        self._list_type = list_type
        if self._list_type:
            self._ensure_list_badge()
        elif self._list_badge:
            self._apply_list_badge()

    def get_strategy_id(self) -> str:
        return self._strategy_id

    def is_active(self) -> bool:
        return self._strategy_id != "none"

    def changeEvent(self, event):  # noqa: N802
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self._apply_style()
            self._apply_icon_color()
        super().changeEvent(event)

    def set_visible_by_filter(self, visible: bool):
        self.setVisible(visible)
