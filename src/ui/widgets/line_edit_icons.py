"""
Helpers for consistent LineEdit icons across themes.

Primary use-case: Qt's native clear-button icon can be rendered as dark/black
even on a dark theme. We replace it with an explicit qtawesome icon.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QSize, Qt, QTimer, QEvent
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QLineEdit, QToolButton

from ui.theme import get_theme_tokens, get_cached_qta_pixmap


class _ClearButtonUpdater(QObject):
    def __init__(
        self,
        line_edit: QLineEdit,
        *,
        icon_name: str,
        color: str | None,
        size: int,
    ) -> None:
        super().__init__(line_edit)
        self._line_edit = line_edit
        self._icon_name = icon_name
        self._explicit_color = color
        self._size = size

    def update_params(self, *, icon_name: str, color: str | None, size: int) -> None:
        self._icon_name = icon_name
        self._explicit_color = color
        self._size = size

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        try:
            if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
                QTimer.singleShot(0, self.apply)
        except Exception:
            pass
        return False

    def apply(self) -> None:
        try:
            btn = self._line_edit.findChild(QToolButton, "qt_clear_button")
            if not btn:
                return

            tokens = get_theme_tokens()
            if self._explicit_color is not None:
                color = self._explicit_color
            else:
                color = tokens.icon_fg_muted

            hover_bg = tokens.surface_bg_hover
            pressed_bg = tokens.surface_bg_pressed

            pixmap = get_cached_qta_pixmap(self._icon_name, color=color, size=self._size)
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(self._size, self._size))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QToolButton#qt_clear_button {{
                    background: transparent;
                    border: none;
                    padding: 0px;
                }}
                QToolButton#qt_clear_button:hover {{
                    background: {hover_bg};
                    border-radius: 6px;
                }}
                QToolButton#qt_clear_button:pressed {{
                    background: {pressed_bg};
                    border-radius: 6px;
                }}
            """)
        except Exception:
            return


def set_line_edit_clear_button_icon(
    line_edit: QLineEdit,
    *,
    icon_name: str = "mdi.close",
    color: str | None = None,
    size: int = 14,
) -> None:
    """
    Replaces the built-in QLineEdit clear button icon with a theme-friendly one.

    Must be called after `line_edit.setClearButtonEnabled(True)`.
    """

    updater = getattr(line_edit, "_clear_button_updater", None)
    if updater is None or not isinstance(updater, _ClearButtonUpdater):
        updater = _ClearButtonUpdater(
            line_edit,
            icon_name=icon_name,
            color=color,
            size=size,
        )
        line_edit._clear_button_updater = updater  # type: ignore[attr-defined]
        try:
            line_edit.installEventFilter(updater)
        except Exception:
            pass
    else:
        updater.update_params(icon_name=icon_name, color=color, size=size)

    # The clear button can be created lazily by Qt; apply on next event loop tick.
    QTimer.singleShot(0, updater.apply)
