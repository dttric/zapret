# ui/compat_widgets.py
"""
Compatibility widgets: re-exports old custom widgets or their qfluentwidgets replacements.
All pages should import SettingsCard, ActionButton, StatusIndicator, SettingsRow, PulsingDot
from here.

New in this version:
  - PrimaryActionButton  — proper PrimaryPushButton-based accent button
  - Re-exports: SwitchButton, LineEdit, ComboBox, CheckBox, IndeterminateProgressBar
  - InfoBarHelper        — one-liner InfoBar.success/warning/error/info
"""
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QEvent, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QSizePolicy, QPushButton,
)
from PyQt6.QtGui import QIcon, QFont, QColor, QPainter

try:
    from qfluentwidgets import (
        CardWidget, SimpleCardWidget, PrimaryPushButton, PushButton,
        TransparentPushButton, BodyLabel, StrongBodyLabel, CaptionLabel,
        SubtitleLabel, TitleLabel, IndeterminateProgressBar, FluentIcon,
        ProgressBar, InfoBar, InfoBarPosition, SwitchButton, isDarkTheme, themeColor,
        LineEdit, ComboBox, CheckBox,
        ToolTipFilter, ToolTipPosition,
    )
    HAS_FLUENT = True
except ImportError:
    HAS_FLUENT = False
    ToolTipFilter = None    # type: ignore[assignment,misc]
    ToolTipPosition = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Re-export native qfluentwidgets inputs so pages can import from one place
# ---------------------------------------------------------------------------
if not HAS_FLUENT:
    # Fallbacks when qfluentwidgets is not installed
    from PyQt6.QtWidgets import QLineEdit as LineEdit       # type: ignore[assignment]
    from PyQt6.QtWidgets import QComboBox as ComboBox       # type: ignore[assignment]
    from PyQt6.QtWidgets import QCheckBox as CheckBox       # type: ignore[assignment]
    SwitchButton = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# set_tooltip — installs qfluentwidgets ToolTipFilter + sets tooltip text
# ---------------------------------------------------------------------------

def set_tooltip(widget, text: str, *, position=None, delay: int = 300) -> None:
    """Set a Fluent-styled tooltip on *widget*.

    Installs ``ToolTipFilter`` exactly once per widget (safe to call multiple
    times — subsequent calls only update the text). Falls back to the native
    Qt tooltip when qfluentwidgets is not available.

    Args:
        widget:   Any QWidget.
        text:     Tooltip text (empty string hides the tooltip).
        position: ``ToolTipPosition`` value; defaults to ``TOP``.
        delay:    Hover-to-show delay in milliseconds (default 300).
    """
    widget.setToolTip(text)
    if ToolTipFilter is None:
        return
    # Install only once — skip if already done for this widget.
    if getattr(widget, "_fluent_tooltip_filter", None) is None:
        pos = position if position is not None else ToolTipPosition.TOP
        f = ToolTipFilter(widget, showDelay=delay, position=pos)
        widget.installEventFilter(f)
        widget._fluent_tooltip_filter = f  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# SettingsCard — wraps qfluentwidgets CardWidget (or falls back to QFrame)
# ---------------------------------------------------------------------------

class SettingsCard(CardWidget if HAS_FLUENT else QFrame):
    """Card container for settings rows, matching the old SettingsCard API."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("settingsCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._title_label = None

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(16, 16, 16, 16)
        self.main_layout.setSpacing(12)

        if title:
            title_lbl = StrongBodyLabel(title, self) if HAS_FLUENT else QLabel(title)
            if not HAS_FLUENT:
                title_lbl.setStyleSheet("font-size: 14px; font-weight: 600;")
            self._title_label = title_lbl
            self.main_layout.addWidget(title_lbl)

    def add_widget(self, widget: QWidget):
        self.main_layout.addWidget(widget)

    def add_layout(self, layout):
        self.main_layout.addLayout(layout)

    def set_title(self, text: str) -> None:
        try:
            if self._title_label is None:
                title_lbl = StrongBodyLabel(text, self) if HAS_FLUENT else QLabel(text)
                if not HAS_FLUENT:
                    title_lbl.setStyleSheet("font-size: 14px; font-weight: 600;")
                self._title_label = title_lbl
                self.main_layout.insertWidget(0, title_lbl)
            else:
                self._title_label.setText(text)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# ActionButton — non-accent PushButton (use PrimaryActionButton for accent)
# ---------------------------------------------------------------------------

class ActionButton(PushButton if HAS_FLUENT else QPushButton):
    """Non-accent action button using qfluentwidgets PushButton.

    For accent (primary) buttons, use PrimaryActionButton instead.
    Note: PushButton.__init__ takes (parent=None) only — text is set via setText().
    Subclasses (StopButton etc.) rely on this being a real class.
    """

    def __init__(self, text: str, icon_name: str | None = None, accent: bool = False, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.accent = accent
        self._icon_name = icon_name
        self._theme_refresh_scheduled = False
        self._last_icon_color = None
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if icon_name:
            self.setIconSize(QSize(16, 16))
            # Avoid virtual dispatch to subclass _update_style() while base __init__ runs.
            ActionButton._update_style(self)

    def _update_style(self):
        """Update icon tint when theme changes."""
        if self._icon_name:
            try:
                import qtawesome as qta
                from qfluentwidgets import isDarkTheme as _idt
                _color = "#cccccc" if _idt() else "#555555"
                if _color == self._last_icon_color:
                    return
                self.setIcon(qta.icon(self._icon_name, color=_color))
                self._last_icon_color = _color
            except Exception:
                pass

    def changeEvent(self, event):  # noqa: N802 (Qt override)
        try:
            if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
                if not self._icon_name:
                    return super().changeEvent(event)
                if not self._theme_refresh_scheduled:
                    self._theme_refresh_scheduled = True
                    QTimer.singleShot(16, self._on_debounced_theme_change)
        except Exception:
            pass
        return super().changeEvent(event)

    def _on_debounced_theme_change(self) -> None:
        try:
            self._update_style()
        finally:
            self._theme_refresh_scheduled = False


# ---------------------------------------------------------------------------
# RefreshButton — ActionButton with WinUI-style spinning animation
# ---------------------------------------------------------------------------

class RefreshButton(ActionButton):
    """Refresh / reload button with WinUI-style icon spin during loading.

    Usage:
        btn = RefreshButton()          # default "Обновить" + sync icon
        btn = RefreshButton("Обновить статус")
        btn.set_loading(True)          # start spin, disable button
        btn.set_loading(False)         # stop spin, re-enable button
    """

    def __init__(self, text: str = "Обновить", icon_name: str = "fa5s.sync-alt", parent=None):
        self._loading = False
        self._spin_angle = 0.0
        self._spin_timer = None
        super().__init__(text, icon_name, parent=parent)
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(40)  # ~25 fps
        self._spin_timer.timeout.connect(self._spin_tick)

    def set_loading(self, loading: bool) -> None:
        """Start or stop the spinning loading animation."""
        if self._loading == loading:
            return
        self._loading = loading
        self.setEnabled(not loading)
        timer = self._spin_timer
        if loading:
            self._spin_angle = 0.0
            if timer is not None:
                timer.start()
        else:
            if timer is not None:
                timer.stop()
            self._set_icon_at(0.0)

    def _spin_tick(self) -> None:
        self._spin_angle = (self._spin_angle + 12) % 360  # ~1 rotation/sec
        self._set_icon_at(self._spin_angle)

    def _set_icon_at(self, angle: float) -> None:
        if not self._icon_name:
            return
        try:
            import qtawesome as qta
            from qfluentwidgets import isDarkTheme as _idt
            color = "#cccccc" if _idt() else "#555555"
            self.setIcon(qta.icon(self._icon_name, color=color, rotated=angle))
        except Exception:
            timer = getattr(self, "_spin_timer", None)
            if timer is not None:
                timer.stop()

    def _update_style(self) -> None:
        """Update icon tint when theme changes (only when not spinning)."""
        if not getattr(self, "_loading", False):
            self._set_icon_at(0.0)


# ---------------------------------------------------------------------------
# PrimaryActionButton — accent PrimaryPushButton (start/confirm actions)
# ---------------------------------------------------------------------------

class PrimaryActionButton(PrimaryPushButton if HAS_FLUENT else QPushButton):
    """Accent action button using qfluentwidgets PrimaryPushButton.

    Use this for primary / confirm actions (e.g. «Запустить», «Применить»).
    PrimaryPushButton.__init__ takes (parent=None) only — text is set via setText().
    """

    def __init__(self, text: str, icon_name: str | None = None, parent=None):
        super().__init__(parent)
        self.setText(text)
        self._icon_name = icon_name
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if icon_name:
            self.setIconSize(QSize(16, 16))
            try:
                import qtawesome as qta
                self.setIcon(qta.icon(icon_name, color="#ffffff"))
            except Exception:
                pass

    def _update_style(self):
        """No-op: qfluentwidgets handles styling."""
        pass


# ---------------------------------------------------------------------------
# SettingsRow — icon + title/description left, control right
# ---------------------------------------------------------------------------

class SettingsRow(QWidget):
    """Settings row (icon + text on the left, control widget on the right)."""

    def __init__(self, icon_name: str, title: str, description: str = "", parent=None):
        super().__init__(parent)

        self._icon_name = icon_name
        self._icon_label = None
        self._icon_update_scheduled = False
        self._title_label = None
        self._desc_label = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)

        # Icon
        icon_label = QLabel()
        self._icon_label = icon_label
        self._refresh_icon()
        icon_label.setFixedSize(24, 24)
        layout.addWidget(icon_label)

        # Text
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        if HAS_FLUENT:
            title_label = BodyLabel(title)
        else:
            title_label = QLabel(title)
            title_label.setStyleSheet("font-size: 13px; font-weight: 500;")
        self._title_label = title_label
        text_layout.addWidget(title_label)

        if description:
            if HAS_FLUENT:
                desc_label = CaptionLabel(description)
            else:
                desc_label = QLabel(description)
                desc_label.setStyleSheet("font-size: 11px;")
            desc_label.setWordWrap(True)
            self._desc_label = desc_label
            text_layout.addWidget(desc_label)

        layout.addLayout(text_layout, 1)

        # Control container (populated externally via set_control)
        self.control_container = QHBoxLayout()
        self.control_container.setSpacing(8)
        layout.addLayout(self.control_container)

    def changeEvent(self, event):  # noqa: N802 (Qt override)
        try:
            if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
                if not self._icon_update_scheduled:
                    self._icon_update_scheduled = True
                    QTimer.singleShot(0, self._on_debounced_theme_change)
        except Exception:
            pass
        return super().changeEvent(event)

    def _on_debounced_theme_change(self) -> None:
        self._icon_update_scheduled = False
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        if self._icon_label is None:
            return
        try:
            import qtawesome as qta
            color = themeColor().name() if HAS_FLUENT else "#5fcffe"
            self._icon_label.setPixmap(qta.icon(self._icon_name, color=color).pixmap(20, 20))
        except Exception:
            pass

    def set_control(self, widget: QWidget):
        """Adds a control widget on the right side."""
        self.control_container.addWidget(widget)

    def set_title(self, text: str) -> None:
        try:
            if self._title_label is not None:
                self._title_label.setText(text)
        except Exception:
            pass

    def set_description(self, text: str) -> None:
        try:
            if self._desc_label is not None:
                self._desc_label.setText(text)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# PulsingDot — animated status indicator dot with glow effect
# ---------------------------------------------------------------------------

class PulsingDot(QWidget):
    """Pulsing dot indicator — QTimer at 100 ms (10 FPS).

    QPropertyAnimation was intentionally avoided: it runs at the display
    refresh rate (~60 FPS), tripling paint calls vs a fixed interval timer.
    Lifecycle: timer stops when the widget is hidden and resumes on show,
    so there is zero CPU cost while the user is on a different page.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = QColor("#aeb5c1")
        self._pulse_phase = 0.0
        self._is_pulsing = False

        self.setFixedSize(28, 28)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._timer = QTimer(self)
        self._timer.setInterval(100)         # 10 FPS — smooth enough, half the CPU vs 50 ms
        self._timer.timeout.connect(self._tick)

    # --- Public API -------------------------------------------------------

    def set_color(self, color: str) -> None:
        c = QColor(color)
        if c.isValid():
            self._color = c
        self.update()

    def start_pulse(self) -> None:
        if not self._is_pulsing:
            self._is_pulsing = True
            self._pulse_phase = 0.0
            if self.isVisible():
                self._timer.start()

    def stop_pulse(self) -> None:
        self._is_pulsing = False
        self._timer.stop()
        self._pulse_phase = 0.0
        self.update()

    # --- Lifecycle: stop timer when hidden, restart when shown -----------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._is_pulsing and not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()   # zero CPU while page is not visible

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            window = self.window()
            if window and window.isMinimized():
                self._timer.stop()
            elif self._is_pulsing and not self._timer.isActive():
                self._timer.start()

    # --- Animation tick ---------------------------------------------------

    def _tick(self) -> None:
        self._pulse_phase = (self._pulse_phase + 0.08) % 1.0  # ~0.8 cycles/sec at 10 FPS
        self.update()

    # --- Paint ------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2
        cy = self.height() / 2
        base_r = 5

        # Pulsing rings (two offset by 0.5 phase for continuous ripple)
        if self._is_pulsing:
            for phase_offset in (0.0, 0.5):
                phase = (self._pulse_phase + phase_offset) % 1.0
                opacity = max(0.0, 0.5 * (1.0 - phase))
                radius = base_r + 10 * phase
                c = QColor(self._color)
                c.setAlphaF(opacity)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(c)
                r = int(radius)
                painter.drawEllipse(int(cx - r), int(cy - r), r * 2, r * 2)

        # Static outer glow
        glow = QColor(self._color)
        glow.setAlphaF(0.3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(
            int(cx - base_r - 2), int(cy - base_r - 2),
            (base_r + 2) * 2, (base_r + 2) * 2,
        )

        # Main dot
        painter.setBrush(self._color)
        painter.drawEllipse(int(cx - base_r), int(cy - base_r), base_r * 2, base_r * 2)

        # Highlight
        painter.setBrush(QColor(255, 255, 255, 90))
        painter.drawEllipse(int(cx - 2), int(cy - 3), 3, 3)


# ---------------------------------------------------------------------------
# StatusIndicator — PulsingDot + label, theme-aware status colors
# ---------------------------------------------------------------------------

class StatusIndicator(QWidget):
    """Status indicator (pulsing dot + text) with theme-aware colors."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_status = "neutral"
        self._theme_refresh_scheduled = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.dot = PulsingDot()
        layout.addWidget(self.dot)

        if HAS_FLUENT:
            self.text = BodyLabel("...")
        else:
            self.text = QLabel("...")
            self.text.setStyleSheet("font-size: 13px;")
        layout.addWidget(self.text)
        layout.addStretch()

    def set_status(self, text: str, status: str = "neutral"):
        """Sets status. status: 'running', 'stopped', 'warning', 'neutral'"""
        self.text.setText(text)
        self._current_status = status

        colors = self._get_status_colors()
        color = colors.get(status, colors["neutral"])
        self.dot.set_color(color)

        if status == "running":
            self.dot.start_pulse()
        else:
            self.dot.stop_pulse()

    def _get_status_colors(self) -> dict[str, str]:
        """Returns status->color mapping using semantic palette if available."""
        try:
            from ui.theme_semantic import get_semantic_palette
            palette = get_semantic_palette()
            return {
                "running": palette.success,
                "stopped": palette.error,
                "warning": palette.warning,
                "neutral": themeColor().name() if HAS_FLUENT else "#5fcffe",
            }
        except Exception:
            return {
                "running": "#52c477",
                "stopped": "#e05454",
                "warning": "#e0a854",
                "neutral": "#5fcffe",
            }

    def changeEvent(self, event):  # noqa: N802 (Qt override)
        try:
            if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
                if not self._theme_refresh_scheduled:
                    self._theme_refresh_scheduled = True
                    QTimer.singleShot(0, self._on_debounced_theme_change)
        except Exception:
            pass
        return super().changeEvent(event)

    def _on_debounced_theme_change(self) -> None:
        self._theme_refresh_scheduled = False
        self.set_status(self.text.text(), self._current_status)


# ---------------------------------------------------------------------------
# InfoBarHelper — one-liner InfoBar notifications
# ---------------------------------------------------------------------------

class InfoBarHelper:
    """Convenience wrapper for qfluentwidgets InfoBar notifications."""

    @staticmethod
    def success(parent: QWidget, title: str, content: str = "", duration: int = 3000):
        if HAS_FLUENT:
            InfoBar.success(title, content, duration=duration,
                            position=InfoBarPosition.TOP_RIGHT, parent=parent)

    @staticmethod
    def warning(parent: QWidget, title: str, content: str = "", duration: int = 4000):
        if HAS_FLUENT:
            InfoBar.warning(title, content, duration=duration,
                            position=InfoBarPosition.TOP_RIGHT, parent=parent)

    @staticmethod
    def error(parent: QWidget, title: str, content: str = "", duration: int = 5000):
        if HAS_FLUENT:
            InfoBar.error(title, content, duration=duration,
                          position=InfoBarPosition.TOP_RIGHT, parent=parent)

    @staticmethod
    def info(parent: QWidget, title: str, content: str = "", duration: int = 3000):
        if HAS_FLUENT:
            InfoBar.info(title, content, duration=duration,
                         position=InfoBarPosition.TOP_RIGHT, parent=parent)
