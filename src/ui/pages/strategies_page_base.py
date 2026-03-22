# ui/pages/strategies_page_base.py
"""Базовый класс для страниц стратегий - общие методы и helper классы"""

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QComboBox, QFrame, QScrollArea, QPushButton,
                             QSizePolicy, QApplication,
                             QButtonGroup, QStackedWidget, QPlainTextEdit)

try:
    from qfluentwidgets import (
        SmoothScrollArea as _SmoothScrollArea, InfoBar,
        PushButton as _FluentPushButton,
        TitleLabel, SubtitleLabel, BodyLabel, CaptionLabel, StrongBodyLabel,
    )
    _HAS_FLUENT_LABELS = True
except ImportError:
    _SmoothScrollArea = QScrollArea
    _FluentPushButton = QPushButton  # type: ignore[assignment,misc]
    InfoBar = None
    TitleLabel = QLabel  # type: ignore[assignment,misc]
    SubtitleLabel = QLabel  # type: ignore[assignment,misc]
    BodyLabel = QLabel  # type: ignore[assignment,misc]
    CaptionLabel = QLabel  # type: ignore[assignment,misc]
    StrongBodyLabel = QLabel  # type: ignore[assignment,misc]
    _HAS_FLUENT_LABELS = False
from PyQt6.QtGui import QPainter, QColor, QPen
import qtawesome as qta
import os

from typing import List

from .base_page import BasePage, ScrollBlockingTextEdit
from ui.compat_widgets import SettingsCard, ActionButton
from ui.widgets import StrategySearchBar
from ui.text_catalog import tr as tr_catalog
from strategy_menu.filter_engine import StrategyFilterEngine, SearchQuery
from PyQt6.QtGui import QTextOption
from strategy_menu.strategy_info import StrategyInfo
from log import log

from ui.theme import get_theme_tokens, to_qcolor
from ui.theme_semantic import get_semantic_palette


class ScrollBlockingScrollArea(_SmoothScrollArea):
    """SmoothScrollArea (Fluent) который не пропускает прокрутку к родителю"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Запрещаем перетаскивание окна при взаимодействии
        self.setProperty("noDrag", True)

    def wheelEvent(self, event):
        scrollbar = self.verticalScrollBar()
        delta = event.angleDelta().y()

        # Если прокручиваем вверх и уже в начале - блокируем
        if delta > 0 and scrollbar.value() == scrollbar.minimum():
            event.accept()
            return

        # Если прокручиваем вниз и уже в конце - блокируем
        if delta < 0 and scrollbar.value() == scrollbar.maximum():
            event.accept()
            return

        super().wheelEvent(event)
        event.accept()


class Win11Spinner(QWidget):
    """Спиннер в стиле Windows 11 - кольцо с бегущей точкой"""

    def __init__(self, size=20, color: str | None = None, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._size = size
        self._color = QColor(color or get_theme_tokens().accent_hex)
        self._angle = 0
        self._arc_length = 90  # Длина дуги в градусах

        # Таймер для анимации
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)

    def start(self):
        """Запускает анимацию"""
        self._timer.start(16)  # ~60 FPS
        self.show()

    def stop(self):
        """Останавливает анимацию"""
        self._timer.stop()
        self.hide()

    def _rotate(self):
        self._angle = (self._angle + 6) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Рисуем фоновое кольцо (серое)
        try:
            tokens = get_theme_tokens()
            ring = to_qcolor(tokens.divider, QColor(220, 220, 220, 30))
        except Exception:
            ring = QColor(220, 220, 220, 30)
        pen = QPen(ring)
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        margin = 3
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        painter.drawEllipse(rect)

        # Рисуем активную дугу (голубая)
        pen.setColor(self._color)
        painter.setPen(pen)

        # Qt рисует углы против часовой стрелки, начиная с 3 часов
        # Конвертируем в формат Qt: угол * 16 (Qt использует 1/16 градуса)
        start_angle = int((90 - self._angle) * 16)  # Начинаем с 12 часов
        span_angle = int(-self._arc_length * 16)  # По часовой стрелке

        painter.drawArc(rect, start_angle, span_angle)


class StatusIndicator(QWidget):
    """Индикатор статуса: галочка или спиннер"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Стек для переключения между галочкой и спиннером
        self.stack = QStackedWidget()
        self.stack.setFixedSize(20, 20)

        # Галочка
        self.check_icon = QLabel()
        self.apply_theme()
        self.check_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.check_icon)

        # Спиннер
        try:
            spinner_color = get_theme_tokens().accent_hex
        except Exception:
            spinner_color = get_theme_tokens("Темная синяя").accent_hex
        self.spinner = Win11Spinner(20, spinner_color)
        self.stack.addWidget(self.spinner)

        layout.addWidget(self.stack)

        # По умолчанию показываем галочку
        self.stack.setCurrentWidget(self.check_icon)

    def apply_theme(self) -> None:
        semantic = get_semantic_palette()
        self.check_icon.setPixmap(qta.icon('fa5s.check-circle', color=semantic.success).pixmap(20, 20))

    def show_loading(self):
        """Показывает спиннер загрузки"""
        self.stack.setCurrentWidget(self.spinner)
        self.spinner.start()

    def show_success(self):
        """Показывает галочку успеха"""
        self.spinner.stop()
        self.stack.setCurrentWidget(self.check_icon)


class ResetActionButton(_FluentPushButton):
    """Кнопка с подтверждением через MessageBox — WinUI стиль."""

    reset_confirmed = pyqtSignal()

    def __init__(self, text: str = "Сбросить", confirm_text: str = "Подтвердить?", parent=None):
        super().__init__(parent)
        self._default_text = text
        self._confirm_text = confirm_text
        self.setText(text)
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self):
        try:
            from qfluentwidgets import MessageBox
            box = MessageBox(self._default_text, self._confirm_text, self.window())
            if box.exec():
                self.reset_confirmed.emit()
        except Exception:
            self.reset_confirmed.emit()


class StrategiesPageBase(QWidget):
    """Базовый класс для всех страниц стратегий - содержит общую логику"""

    launch_method_changed = pyqtSignal(str)
    strategy_selected = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._strategy_widget = None
        self._initialized = False
        self._current_mode = None

        # Таймер для проверки статуса процесса
        self._process_check_timer = QTimer(self)
        self._process_check_timer.timeout.connect(self._check_process_status)
        self._process_check_attempts = 0
        self._max_check_attempts = 30  # 30 попыток * 200мс = 6 секунд максимум

        # Абсолютный таймаут для защиты от зависания спиннера
        self._absolute_timeout_timer = QTimer(self)
        self._absolute_timeout_timer.setSingleShot(True)
        self._absolute_timeout_timer.timeout.connect(self._on_absolute_timeout)

        # Поисковая панель и фильтрация
        self.filter_engine = StrategyFilterEngine()
        self.search_bar = None  # Создаётся в _load_*_mode
        self._json_adapter = None

        # Кэш данных для Direct режима (для фильтрации)
        self._all_direct_strategies = {}  # {category_key: strategies_dict}
        self._all_direct_favorites = {}   # {category_key: favorites_list}
        self._all_direct_selections = {}  # {category_key: current_selection}

        from qfluentwidgets import qconfig
        qconfig.themeChanged.connect(lambda _: self._apply_theme())
        qconfig.themeColorChanged.connect(lambda _: self._apply_theme())

        self._build_ui()

        # Apply theme to local inline styles.
        self._apply_theme()

    def _build_ui(self):
        """Строит базовый UI - общий для всех режимов"""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(32, 24, 32, 0)
        self.main_layout.setSpacing(12)

        # Заголовок страницы (фиксированный, не прокручивается)
        self.title_label = TitleLabel(
            tr_catalog(
                "page.strategies_base.title",
                default="Выбор активных стратегий (и их настройка) Zapret 2",
            )
        )
        self.main_layout.addWidget(self.title_label)

        # Описание страницы
        self.subtitle_label = BodyLabel(
            tr_catalog(
                "page.strategies_base.subtitle",
                default=(
                    "Для каждой категории (доменов внутри хостлиста или айпишников внутри айпсета) "
                    "можно выбрать свою стратегию для обхода блокировок. Список всех статегий для "
                    "каждой категории одинаковый, отличается только по типу трафика (TCP, UDP, stun). "
                    "Некоторые типы дурения (например send или syndata) можно настроить более точечно "
                    "чтобы получить больше уникальных стратегий, исходя из того как работает ваше ТСПУ."
                ),
            )
        )
        self.subtitle_label.setWordWrap(True)
        self.main_layout.addWidget(self.subtitle_label)

        # Текущая стратегия (будет добавлен в scroll_area)
        self.current_widget = QWidget()
        self.current_widget.setStyleSheet("background-color: transparent;")
        current_layout = QHBoxLayout(self.current_widget)
        current_layout.setContentsMargins(0, 0, 0, 8)

        self.status_indicator = StatusIndicator()
        current_layout.addWidget(self.status_indicator)

        current_prefix = BodyLabel(
            tr_catalog("page.strategies_base.current_prefix", default="Текущая:")
        )
        self._current_prefix_label = current_prefix
        current_layout.addWidget(current_prefix)

        # Контейнер для иконок активных стратегий
        self.current_strategy_container = QWidget()
        self.current_strategy_container.setStyleSheet("background: transparent;")
        self.current_icons_layout = QHBoxLayout(self.current_strategy_container)
        self.current_icons_layout.setContentsMargins(0, 0, 0, 0)
        self.current_icons_layout.setSpacing(4)

        # Включаем отслеживание мыши для красивого тултипа
        self.current_strategy_container.setMouseTracking(True)
        self.current_strategy_container.installEventFilter(self)
        self._has_hidden_strategies = False  # Флаг для показа тултипа
        self._tooltip_strategies_data = []
        current_layout.addWidget(self.current_strategy_container)
        # current_widget будет вставлен в content_layout при загрузке контента

        # Текстовый лейбл (fallback)
        self.current_strategy_label = BodyLabel(
            tr_catalog("page.strategies_base.strategy.not_selected", default="Не выбрана")
        )
        current_layout.addWidget(self.current_strategy_label)

        current_layout.addStretch()

        # Счётчик избранных стратегий
        self.favorites_count_label = QLabel("")
        self.favorites_count_label.setStyleSheet("""
            QLabel {
                color: #ff9800;
                font-size: 13px;
                font-weight: 600;
                padding: 4px 12px;
                background: rgba(255, 152, 0, 0.15);
                border-radius: 12px;
            }
        """)
        self.favorites_count_label.hide()
        current_layout.addWidget(self.favorites_count_label)

        # current_widget не добавляется сюда, будет вставлен в content_layout

        # Прокручиваемая область для всего контента
        self.scroll_area = ScrollBlockingScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Контейнер для контента (меняется в зависимости от режима)
        self.content_container = QWidget()
        self.content_container.setStyleSheet("background-color: transparent;")
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 24)
        self.content_layout.setSpacing(12)

        # Плейсхолдер загрузки
        self.loading_label = QLabel(
            tr_catalog("page.strategies_base.loading", default="Загрузка...")
        )
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_layout.addWidget(self.loading_label)

        self.scroll_area.setWidget(self.content_container)
        self.main_layout.addWidget(self.scroll_area, 1)

        # Совместимость со старым кодом
        self.select_strategy_btn = QPushButton()
        self.select_strategy_btn.hide()

        self.category_selections = {}

        self._apply_theme()

    def _apply_theme(self) -> None:
        tokens = get_theme_tokens()

        if hasattr(self, "loading_label") and self.loading_label:
            self.loading_label.setStyleSheet(
                f"color: {tokens.fg_muted}; font-size: 13px;"
            )
        if hasattr(self, "status_indicator"):
            self.status_indicator.apply_theme()
        if hasattr(self, "favorites_count_label"):
            semantic = get_semantic_palette()
            self.favorites_count_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {semantic.warning};
                    font-size: 13px;
                    font-weight: 600;
                    padding: 4px 12px;
                    background: {semantic.warning_soft_bg};
                    border-radius: 12px;
                }}
                """
            )

        if hasattr(self, "scroll_area"):
            self.scroll_area.setStyleSheet(
                "QScrollArea { background: transparent; border: none; }"
            )

    def showEvent(self, event):
        """При показе страницы загружаем стратегии"""
        super().showEvent(event)
        if not self._initialized:
            self._initialized = True
            QTimer.singleShot(0, self._load_content)

    def _clear_content(self):
        """Очищает контент"""
        # Важно: перед удалением вкладок нужно остановить фоновые QThread,
        # иначе Qt может упасть с "QThread: Destroyed while thread is still running".
        try:
            self._stop_category_tab_loader_threads()
        except Exception as e:
            log(f"Ошибка остановки loader-потоков вкладок: {e}", "DEBUG")

        # Сохраняем current_widget (не удаляем при очистке).
        # ВАЖНО: не вызывать setParent(None) — это делает виджет top-level окном и он
        # появляется как отдельный попап. Просто скрываем и убираем из лейаута;
        # при следующей загрузке _load_*_mode добавит его обратно через addWidget.
        if hasattr(self, 'current_widget') and self.current_widget:
            self.content_layout.removeWidget(self.current_widget)
            self.current_widget.hide()

        # Удаляем все виджеты из content_layout
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._strategy_widget = None
        self.loading_label = None
        self.search_bar = None
        # Очищаем кэш Direct режима
        self._all_direct_strategies = {}
        self._all_direct_favorites = {}
        self._all_direct_selections = {}

    def _stop_category_tab_loader_threads(self) -> None:
        """Останавливает QThread, созданные для асинхронной загрузки вкладок категорий."""
        tab_container = getattr(self, "_strategy_widget", None)
        if tab_container is None:
            return

        count_fn = getattr(tab_container, "count", None)
        widget_fn = getattr(tab_container, "widget", None)
        if not callable(count_fn) or not callable(widget_fn):
            return

        for i in range(count_fn()):
            tab_widget = widget_fn(i)
            if tab_widget is None:
                continue

            loader_thread = getattr(tab_widget, "_loader_thread", None)
            if isinstance(loader_thread, QThread) and loader_thread.isRunning():
                loader_thread.quit()
                if not loader_thread.wait(1500):
                    loader_thread.terminate()
                    loader_thread.wait(500)

            if hasattr(tab_widget, "_loader"):
                tab_widget._loader = None
            if hasattr(tab_widget, "_loader_thread"):
                tab_widget._loader_thread = None

    def _load_content(self):
        """Загружает контент - ДОЛЖЕН БЫТЬ ПЕРЕОПРЕДЕЛЕН В НАСЛЕДНИКАХ"""
        raise NotImplementedError("Subclasses must implement _load_content()")

    # ==================== Общие методы для всех режимов ====================

    def _has_any_active_strategy(self, selections: dict = None) -> bool:
        """Проверяет, есть ли хотя бы одна активная стратегия (не 'none')"""
        if selections is None:
            selections = self.category_selections

        for strategy_id in selections.values():
            if strategy_id and strategy_id != "none":
                return True
        return False

    def show_loading(self):
        """Показывает спиннер загрузки при перезапуске DPI"""
        if hasattr(self, 'status_indicator'):
            self.status_indicator.show_loading()

    def show_success(self):
        """Показывает галочку после успешного запуска DPI"""
        if hasattr(self, 'status_indicator'):
            self.status_indicator.show_success()

    def _start_process_monitoring(self):
        """Запускает мониторинг статуса процесса winws/winws2"""
        self._process_check_attempts = 0
        if not self._process_check_timer.isActive():
            # Небольшая задержка перед первой проверкой - даем процессу время на инициализацию
            QTimer.singleShot(300, lambda: self._process_check_timer.start(200))
            log("Начат мониторинг запуска процесса", "DEBUG")

    def _stop_process_monitoring(self):
        """Останавливает мониторинг процесса"""
        if self._process_check_timer.isActive():
            self._process_check_timer.stop()
            log("Мониторинг запуска процесса остановлен", "DEBUG")
        self._stop_absolute_timeout()

    def _stop_absolute_timeout(self):
        """Останавливает абсолютный таймаут защиты"""
        if self._absolute_timeout_timer.isActive():
            self._absolute_timeout_timer.stop()
            log("Таймаут защиты спиннера остановлен", "DEBUG")

    def _on_absolute_timeout(self):
        """Вызывается при превышении абсолютного таймаута"""
        log("ТАЙМАУТ: Превышено время ожидания запуска (10 секунд)", "WARNING")
        log("Процесс мог зависнуть или запускается слишком долго", "WARNING")

        # Принудительно останавливаем мониторинг и показываем галочку
        self._stop_process_monitoring()
        self.show_success()

        # Показываем уведомление пользователю
        try:
            if InfoBar:
                InfoBar.warning(
                    title="Долгий запуск",
                    content="Процесс запускается дольше обычного.\n\nПроверьте логи и статус процесса.\nВозможно потребуется перезапуск.",
                    parent=self.window(),
                )
        except:
            pass

    def _check_process_status(self):
        """Проверяет реальный статус процесса winws/winws2"""
        try:
            self._process_check_attempts += 1

            # Получаем dpi_starter
            app = self.parent_app
            if not app or not hasattr(app, 'dpi_starter'):
                log("dpi_starter не найден для проверки процесса", "DEBUG")
                self._stop_process_monitoring()
                self.show_success()  # Показываем галочку по умолчанию
                return

            # Проверяем запущен ли процесс через быстрый psutil метод (~1-10ms)
            is_running = app.dpi_starter.check_process_running_wmi(silent=True)

            if is_running:
                # Процесс реально запущен - показываем галочку
                log(f"Процесс winws подтвержден как запущенный (попытка {self._process_check_attempts})", "INFO")
                self._stop_process_monitoring()  # Это автоматически остановит и абсолютный таймаут
                self.show_success()
                return

            # Проверяем лимит попыток
            if self._process_check_attempts >= self._max_check_attempts:
                log(f"Превышено максимальное время ожидания запуска процесса ({self._max_check_attempts * 0.2:.1f}с)", "WARNING")
                self._stop_process_monitoring()  # Это автоматически остановит и абсолютный таймаут
                self.show_success()  # Всё равно показываем галочку
                return

        except Exception as e:
            log(f"Ошибка проверки статуса процесса: {e}", "DEBUG")
            self._stop_process_monitoring()  # Это автоматически остановит и абсолютный таймаут
            self.show_success()

    def eventFilter(self, obj, event):
        """Обработчик событий для красивого тултипа"""
        # NOTE: During app shutdown / page teardown Qt may still dispatch events
        # while Python wrappers are already marked as deleted.
        try:
            container = self.current_strategy_container
        except RuntimeError:
            return False
        except Exception:
            return False

        if obj is container:
            try:
                from PyQt6.QtCore import QEvent

                if event.type() == QEvent.Type.Enter:
                    # При наведении показываем красивый тултип если есть стратегии
                    if self._has_hidden_strategies and hasattr(self, '_tooltip_strategies_data') and self._tooltip_strategies_data:
                        self._show_strategies_tooltip()

                elif event.type() == QEvent.Type.Leave:
                    # При уходе скрываем тултип
                    self._hide_strategies_tooltip()
            except RuntimeError:
                return False
            except Exception:
                pass

        # Do not filter the event.
        return False

    def _show_strategies_tooltip(self):
        """Показывает красивый тултип со списком стратегий"""
        try:
            from ui.widgets.strategies_tooltip import strategies_tooltip_manager

            if hasattr(self, '_tooltip_strategies_data') and self._tooltip_strategies_data:
                strategies_tooltip_manager.show(self._tooltip_strategies_data, follow=True)
        except Exception as e:
            log(f"Ошибка показа тултипа стратегий: {e}", "DEBUG")

    def _hide_strategies_tooltip(self):
        """Скрывает тултип стратегий"""
        try:
            from ui.widgets.strategies_tooltip import strategies_tooltip_manager
            strategies_tooltip_manager.hide(delay=150)
        except Exception as e:
            pass

    def update_current_strategy(self, name: str):
        """Обновляет отображение текущей стратегии - ПЕРЕОПРЕДЕЛЯЕТСЯ В НАСЛЕДНИКАХ"""
        autostart_disabled_ru = tr_catalog(
            "page.strategies_base.strategy.autostart_disabled",
            default="Автостарт DPI отключен",
            language="ru",
        )
        autostart_disabled_en = tr_catalog(
            "page.strategies_base.strategy.autostart_disabled",
            default="Autostart DPI is disabled",
            language="en",
        )

        if name and name not in {autostart_disabled_ru, autostart_disabled_en, "Автостарт DPI отключен"}:
            self.current_strategy_label.setText(name)
        else:
            self.current_strategy_label.setText(
                tr_catalog("page.strategies_base.strategy.not_selected", default="Не выбрана")
            )

    # ==================== Внешние фильтры (от StrategySortPage) ====================

    def on_external_filters_changed(self, query):
        """Обработчик изменения фильтров с внешней страницы (асинхронно)

        Args:
            query: SearchQuery объект с текущими фильтрами
        """
        # Сохраняем query для использования
        self._external_query = query
        # Запускаем асинхронное обновление через QTimer чтобы не фризить UI
        QTimer.singleShot(0, self._apply_external_filters_async)

    def on_external_sort_changed(self, sort_key: str, reverse: bool):
        """Обработчик изменения сортировки с внешней страницы (асинхронно)

        Args:
            sort_key: Ключ сортировки (default, name, rating)
            reverse: Обратный порядок
        """
        self._external_sort_key = sort_key
        self._external_sort_reverse = reverse
        QTimer.singleShot(0, self._apply_external_sort_async)

    def _apply_external_filters_async(self):
        """Асинхронно применяет внешние фильтры - ПЕРЕОПРЕДЕЛЯЕТСЯ В НАСЛЕДНИКАХ"""
        pass

    def _apply_external_sort_async(self):
        """Асинхронно применяет внешнюю сортировку - ПЕРЕОПРЕДЕЛЯЕТСЯ В НАСЛЕДНИКАХ"""
        pass

    def closeEvent(self, event):
        """Очистка ресурсов при закрытии"""
        try:
            self._stop_process_monitoring()
            self._stop_absolute_timeout()
        except Exception as e:
            log(f"Ошибка очистки ресурсов: {e}", "DEBUG")

        super().closeEvent(event)


    # ==================== Direct режим: обработчики поиска и фильтрации ====================

    def _convert_direct_dict_to_strategy_info_list(self, strategies_dict: dict, category_key: str) -> List[StrategyInfo]:
        """Конвертирует dict Direct стратегий в List[StrategyInfo] для фильтрации и сортировки."""
        result = []

        for strategy_id, strategy_data in strategies_dict.items():
            try:
                args = strategy_data.get('args', [])
                # Сохраняем аргументы в многострочном формате (один аргумент на строку)
                args_str = '\n'.join(args) if isinstance(args, list) else str(args)

                info = StrategyInfo(
                    id=strategy_id,
                    name=strategy_data.get('name', strategy_id),
                    source=f'json_{category_key}',
                    description=strategy_data.get('description', ''),
                    author=strategy_data.get('author', ''),
                    version=strategy_data.get('version', ''),
                    label=strategy_data.get('label', '') or '',
                    args=args_str,
                    is_favorite=strategy_data.get('is_favorite', False),
                )
                result.append(info)
            except Exception as e:
                log(f"Ошибка конвертации Direct стратегии {strategy_id}: {e}", "DEBUG")

        return result

    def _filter_direct_strategies(self, strategies_dict: dict, query) -> dict:
        """Фильтрует словарь стратегий по query"""
        if not query or (not query.text and not query.labels and not query.techniques):
            return strategies_dict

        filtered = {}
        search_text = query.text.lower() if query.text else ""

        for strategy_id, strategy_data in strategies_dict.items():
            # Поиск по тексту
            if search_text:
                name = str(strategy_data.get('name', '')).lower()
                description = str(strategy_data.get('description', '')).lower()
                args_str = ' '.join(strategy_data.get('args', [])).lower() if isinstance(strategy_data.get('args'), list) else str(strategy_data.get('args', '')).lower()

                if search_text not in name and search_text not in description and search_text not in args_str:
                    continue

            # Фильтрация по label
            if query.labels:
                strategy_label = str(strategy_data.get('label', '')).lower()
                if strategy_label not in [l.lower() for l in query.labels]:
                    continue

            # Фильтрация по techniques (desync методам)
            if query.techniques:
                args = strategy_data.get('args', [])
                args_str = ' '.join(args).lower() if isinstance(args, list) else str(args).lower()

                technique_found = False
                for technique in query.techniques:
                    if technique.lower() in args_str:
                        technique_found = True
                        break

                if not technique_found:
                    continue

            filtered[strategy_id] = strategy_data

        return filtered

    def _apply_direct_filter(self):
        """Применяет текущие фильтры и сортировку к Direct режиму"""
        try:
            if not self._strategy_widget:
                return

            current_index = self._strategy_widget.currentIndex()
            widget = self._strategy_widget.widget(current_index)
            if not widget:
                return

            category_key = widget.property("category_key")
            if not category_key and hasattr(self._strategy_widget, '_tab_category_keys'):
                keys = self._strategy_widget._tab_category_keys
                if 0 <= current_index < len(keys):
                    category_key = keys[current_index]

            if not category_key or category_key not in self._all_direct_strategies:
                return

            # Получаем оригинальные данные
            original_strategies = self._all_direct_strategies.get(category_key, {})
            favorites_list = self._all_direct_favorites.get(category_key, [])
            current_selection = self._all_direct_selections.get(category_key, None)

            # Применяем текстовый фильтр
            query = self.search_bar.get_query() if self.search_bar else None
            filtered_strategies = self._filter_direct_strategies(original_strategies, query)

            # Получаем параметры сортировки
            sort_key, reverse = self.search_bar.get_sort_key() if self.search_bar else ("default", False)

            # Конвертируем в List[StrategyInfo] для сортировки
            favorites_set = set(favorites_list)
            for strategy_id, strategy_data in filtered_strategies.items():
                strategy_data['is_favorite'] = strategy_id in favorites_set

            strategy_info_list = self._convert_direct_dict_to_strategy_info_list(filtered_strategies, category_key)

            # Сортируем используя filter_engine
            sorted_strategies = self.filter_engine.sort_strategies(strategy_info_list, sort_key, reverse)

            # Конвертируем обратно в dict, СОХРАНЯЯ порядок из sorted_strategies
            sorted_dict = {}
            for strategy_info in sorted_strategies:
                strategy_id = strategy_info.id
                if strategy_id in filtered_strategies:
                    sorted_dict[strategy_id] = filtered_strategies[strategy_id]

            # При сортировке по имени или рейтингу не разделяем на группы
            skip_grouping = sort_key in ("name", "rating")

            # Пересоздаём UI с отсортированными данными
            widget._loaded = False
            self._build_category_ui(widget, current_index, category_key, sorted_dict, favorites_list, current_selection, skip_grouping=skip_grouping)

            # Обновляем счётчик
            if self.search_bar:
                self.search_bar.set_result_count(len(sorted_dict))

            log(f"Direct фильтрация+сортировка {category_key}: {len(sorted_dict)} из {len(original_strategies)} (sort={sort_key}, reverse={reverse})", "DEBUG")

        except Exception as e:
            log(f"Ошибка фильтрации Direct стратегий: {e}", "ERROR")

    def _on_direct_search_changed(self, text: str):
        """Обработчик поиска для Direct режима (асинхронно)"""
        QTimer.singleShot(0, self._apply_direct_filter)

    def _on_direct_filters_changed(self, query):
        """Обработчик фильтров для Direct режима (асинхронно)"""
        QTimer.singleShot(0, self._apply_direct_filter)

    def _apply_external_filters_async(self):
        """Асинхронно применяет внешние фильтры - ПЕРЕОПРЕДЕЛЯЕТСЯ В НАСЛЕДНИКАХ"""
        try:
            query = getattr(self, '_external_query', None)
            if query is None:
                return

            if not self._initialized:
                return

            from strategy_menu import get_strategy_launch_method
            method = get_strategy_launch_method()

            if method in ("direct_zapret2", "direct_zapret2_orchestra", "direct_zapret1"):
                self._apply_direct_filter_with_query(query)

        except Exception as e:
            log(f"Ошибка применения внешних фильтров: {e}", "ERROR")

    def _apply_external_sort_async(self):
        """Асинхронно применяет внешнюю сортировку - ПЕРЕОПРЕДЕЛЯЕТСЯ В НАСЛЕДНИКАХ"""
        try:
            sort_key = getattr(self, '_external_sort_key', 'default')
            reverse = getattr(self, '_external_sort_reverse', False)

            if not self._initialized:
                return

            from strategy_menu import get_strategy_launch_method
            method = get_strategy_launch_method()

            if method in ("direct_zapret2", "direct_zapret2_orchestra", "direct_zapret1"):
                self._apply_direct_sort_with_params(sort_key, reverse)

        except Exception as e:
            log(f"Ошибка применения внешней сортировки: {e}", "ERROR")

    def _apply_direct_filter_with_query(self, query):
        """Применяет фильтр к Direct режиму с заданным query"""
        try:
            if not self._strategy_widget:
                return

            current_index = self._strategy_widget.currentIndex()
            widget = self._strategy_widget.widget(current_index)
            if not widget:
                return

            category_key = widget.property("category_key")
            if not category_key and hasattr(self._strategy_widget, '_tab_category_keys'):
                keys = self._strategy_widget._tab_category_keys
                if 0 <= current_index < len(keys):
                    category_key = keys[current_index]

            if not category_key or category_key not in self._all_direct_strategies:
                return

            original_strategies = self._all_direct_strategies.get(category_key, {})
            favorites_list = self._all_direct_favorites.get(category_key, [])
            current_selection = self._all_direct_selections.get(category_key, None)

            filtered_strategies = self._filter_direct_strategies(original_strategies, query)

            sort_key = getattr(self, '_external_sort_key', 'default')
            reverse = getattr(self, '_external_sort_reverse', False)

            favorites_set = set(favorites_list)
            for strategy_id, strategy_data in filtered_strategies.items():
                strategy_data['is_favorite'] = strategy_id in favorites_set

            strategy_info_list = self._convert_direct_dict_to_strategy_info_list(filtered_strategies, category_key)
            sorted_strategies = self.filter_engine.sort_strategies(strategy_info_list, sort_key, reverse)

            sorted_dict = {}
            for strategy_info in sorted_strategies:
                strategy_id = strategy_info.id
                if strategy_id in filtered_strategies:
                    sorted_dict[strategy_id] = filtered_strategies[strategy_id]

            skip_grouping = sort_key in ("name", "rating")
            widget._loaded = False
            self._build_category_ui(widget, current_index, category_key, sorted_dict, favorites_list, current_selection, skip_grouping=skip_grouping)

            log(f"Direct внешняя фильтрация {category_key}: {len(sorted_dict)} из {len(original_strategies)}", "DEBUG")

        except Exception as e:
            log(f"Ошибка применения внешнего фильтра Direct: {e}", "ERROR")

    def _apply_direct_sort_with_params(self, sort_key: str, reverse: bool):
        """Применяет сортировку к Direct режиму с заданными параметрами"""
        self._external_sort_key = sort_key
        self._external_sort_reverse = reverse

        query = getattr(self, '_external_query', None)
        if query is None:
            query = SearchQuery()

        self._apply_direct_filter_with_query(query)

    # ==================== Методы для Direct режима (категории, вкладки) ====================

    def _build_category_ui(self, widget, index, category_key, strategies_dict, favorites_list, current_selection, skip_grouping=False):
        """Создаёт UI элементы категории из загруженных данных - STUB, переопределяется в наследниках"""
        pass

    def _update_current_strategies_display(self):
        """Обновляет отображение списка активных стратегий - STUB, переопределяется в наследниках"""
        pass


# Для совместимости
Win11ComboBox = QComboBox
