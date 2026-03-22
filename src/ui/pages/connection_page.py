"""Новая вкладка диагностики соединений в стиле Windows 11."""

import os
import platform
import time

from PyQt6.QtCore import Qt, QThread, QTimer, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
)

try:
    from qfluentwidgets import (
        IndeterminateProgressBar, ProgressBar, ComboBox,
        StrongBodyLabel, BodyLabel, CaptionLabel, TextEdit,
    )
    _HAS_FLUENT_WIDGETS = True
except ImportError:
    from PyQt6.QtWidgets import QProgressBar as IndeterminateProgressBar, QProgressBar as ProgressBar, QComboBox as ComboBox
    from PyQt6.QtWidgets import QTextEdit as TextEdit
    StrongBodyLabel = QLabel
    BodyLabel = QLabel
    CaptionLabel = QLabel
    _HAS_FLUENT_WIDGETS = False

from .base_page import BasePage, ScrollBlockingTextEdit
from ui.compat_widgets import SettingsCard, ActionButton
from connection_test import ConnectionTestWorker, LogSendWorker
from config import LOGS_FOLDER, APP_VERSION
from tgram.tg_log_delta import get_client_id
from ui.text_catalog import tr as tr_catalog


if _HAS_FLUENT_WIDGETS:
    class _ScrollBlockingTextBase(TextEdit):
        """TextEdit (Fluent) that stops wheel-scroll from propagating to the parent page."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setProperty("noDrag", True)

        def wheelEvent(self, event):
            scrollbar = self.verticalScrollBar()
            delta = event.angleDelta().y()
            if delta > 0 and scrollbar.value() == scrollbar.minimum():
                event.accept()
                return
            if delta < 0 and scrollbar.value() == scrollbar.maximum():
                event.accept()
                return
            super().wheelEvent(event)
            event.accept()
else:
    _ScrollBlockingTextBase = ScrollBlockingTextEdit


class StatusBadge(CaptionLabel):
    """Status label — delegates all styling to qfluentwidgets CaptionLabel."""

    def __init__(self, text: str = "", status: str = "muted", parent=None):
        super().__init__(parent)
        self.setText(text)

    def set_status(self, text: str, status: str = "muted"):
        self.setText(text)


class SupportAuthWorker(QObject):
    """Ожидает подтверждения кода авторизации (в фоне)."""

    finished = pyqtSignal(bool, str)  # ok, error_message

    def __init__(self, code: str, parent=None):
        super().__init__(parent)
        self._code = (code or "").strip()

    def run(self):
        try:
            from tgram.tg_log_bot import poll_upload_code

            ok, err = poll_upload_code(self._code)
            self.finished.emit(bool(ok), str(err or ""))
        except Exception as e:
            self.finished.emit(False, str(e))


class ConnectionTestPage(BasePage):
    """Страница теста соединений, заменяющая старое диалоговое окно."""

    def __init__(self, parent=None):
        super().__init__(
            "Диагностика соединения",
            "Автотест Discord и YouTube, проверка DNS подмены и отправка логов в поддержку",
            parent,
            title_key="page.connection.title",
            subtitle_key="page.connection.subtitle",
        )
        self.is_testing = False
        self.is_sending_log = False
        self.worker = None
        self.worker_thread = None
        self.log_send_thread = None
        self.log_send_worker = None
        self.stop_check_timer = None

        # Контейнер с ограниченной шириной, чтобы не расползалось за края
        self.container = QWidget(self.content)
        self.container.setObjectName("connectionContainer")
        self.container.setMaximumWidth(1080)
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(14)
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self._build_header()
        self._build_controls()
        self._build_log_viewer()

        # Добавляем контейнер на страницу
        self.add_widget(self.container)
        self.add_spacing(8)

    # ──────────────────────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────────────────────
    def _build_header(self):
        hero_card = SettingsCard()

        self.hero_title = StrongBodyLabel(
            tr_catalog("page.connection.hero.title", language=self._ui_language, default="Диагностика сетевых соединений")
        )
        hero_card.add_widget(self.hero_title)

        self.hero_subtitle = BodyLabel(
            tr_catalog(
                "page.connection.hero.subtitle",
                language=self._ui_language,
                default="Проверьте доступность Discord и YouTube, найдите подмену DNS и быстро отправьте лог в поддержку.",
            )
        )
        self.hero_subtitle.setWordWrap(True)
        hero_card.add_widget(self.hero_subtitle)

        badges_layout = QHBoxLayout()
        badges_layout.setSpacing(8)
        self.status_badge = StatusBadge(tr_catalog("page.connection.status.ready", language=self._ui_language, default="Готово к тестированию"), "info")
        self.progress_badge = StatusBadge(tr_catalog("page.connection.progress.waiting", language=self._ui_language, default="Ожидает запуска"), "muted")
        badges_layout.addWidget(self.status_badge)
        badges_layout.addWidget(self.progress_badge)
        badges_layout.addStretch()
        hero_card.add_layout(badges_layout)

        self.container_layout.addWidget(hero_card)

    def _build_controls(self):
        card = SettingsCard(tr_catalog("page.connection.card.testing", language=self._ui_language, default="Тестирование"))

        # Тип теста
        selector_row = QHBoxLayout()
        selector_row.setSpacing(12)
        self.test_select_label = BodyLabel(tr_catalog("page.connection.test.select", language=self._ui_language, default="Выбор теста:"))
        selector_row.addWidget(self.test_select_label)

        self.test_combo = ComboBox()
        self._refresh_test_combo_items()
        selector_row.addWidget(self.test_combo, 1)
        card.add_layout(selector_row)

        # Кнопки
        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(8)

        self.start_btn = ActionButton(tr_catalog("page.connection.button.start", language=self._ui_language, default="Запустить тест"), "fa5s.play", accent=True)
        self.start_btn.clicked.connect(self.start_test)
        buttons_row.addWidget(self.start_btn, 1)

        self.stop_btn = ActionButton(tr_catalog("page.connection.button.stop", language=self._ui_language, default="Стоп"), "fa5s.stop")
        self.stop_btn.clicked.connect(self.stop_test)
        self.stop_btn.setEnabled(False)
        buttons_row.addWidget(self.stop_btn, 1)

        self.send_log_btn = ActionButton(tr_catalog("page.connection.button.send_log", language=self._ui_language, default="Отправить лог"), "fa5s.paper-plane")
        self.send_log_btn.clicked.connect(self.send_log_to_telegram)
        self.send_log_btn.setEnabled(False)
        buttons_row.addWidget(self.send_log_btn, 1)

        card.add_layout(buttons_row)

        # Прогресс + статус
        status_layout = QHBoxLayout()
        status_layout.setSpacing(12)

        self.status_label = CaptionLabel(tr_catalog("page.connection.status.ready", language=self._ui_language, default="Готово к тестированию"))
        status_layout.addWidget(self.status_label, 1)

        self.progress_bar = IndeterminateProgressBar()
        self.progress_bar.setVisible(False)
        status_layout.addWidget(self.progress_bar, 1)

        card.add_layout(status_layout)
        self.container_layout.addWidget(card)

    def _build_log_viewer(self):
        log_card = SettingsCard(tr_catalog("page.connection.card.result", language=self._ui_language, default="Результат тестирования"))
        self.result_text = _ScrollBlockingTextBase()
        self.result_text.setReadOnly(True)
        log_card.add_widget(self.result_text)
        self.container_layout.addWidget(log_card)

    # ──────────────────────────────────────────────────────────────
    # Логика теста
    # ──────────────────────────────────────────────────────────────
    def start_test(self):
        if self.is_testing:
            self._append("ℹ️ Тест уже выполняется. Дождитесь завершения.")
            return

        selection = self.test_combo.currentText()
        test_type = "all"
        if "Discord" in selection and "YouTube" not in selection:
            test_type = "discord"
        elif "YouTube" in selection and "Discord" not in selection:
            test_type = "youtube"

        self.result_text.clear()
        self._append(f"🚀 Запуск тестирования: {selection}")
        self._append("=" * 50)

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.test_combo.setEnabled(False)
        self.send_log_btn.setEnabled(False)
        self._set_status("🔄 Тестирование в процессе...", "info")
        self.status_badge.set_status("Тест выполняется", "info")
        self.progress_badge.set_status("Идёт проверка", "info")
        self.progress_bar.setVisible(True)
        if _HAS_FLUENT_WIDGETS:
            self.progress_bar.start()

        self.worker_thread = QThread(self)
        self.worker = ConnectionTestWorker(test_type)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.update_signal.connect(self._on_worker_update)
        self.worker.finished_signal.connect(self._on_worker_finished)
        self.worker.finished_signal.connect(self.worker_thread.quit)
        self.worker.finished_signal.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.is_testing = True
        self.worker_thread.start()

    def stop_test(self):
        if not self.worker or not self.worker_thread:
            return

        self._append("\n⚠️ Остановка теста...")
        self._set_status("⏹️ Останавливаем...", "warning")
        self.worker.stop_gracefully()

        self.stop_check_timer = QTimer(self)
        self.stop_check_attempts = 0

        def check_thread():
            if not self.stop_check_timer:
                return
            self.stop_check_attempts += 1
            if not self.worker_thread or not self.worker_thread.isRunning():
                if self.stop_check_timer:
                    self.stop_check_timer.stop()
                self._append("✅ Тест остановлен")
                self._on_worker_finished()
            elif self.stop_check_attempts > 50:
                if self.stop_check_timer:
                    self.stop_check_timer.stop()
                self._append("⚠️ Принудительная остановка...")
                if self.worker_thread:
                    self.worker_thread.terminate()
                    QTimer.singleShot(800, self._finalize_stop)

        self.stop_check_timer.timeout.connect(check_thread)
        self.stop_check_timer.start(100)

    def _finalize_stop(self):
        self._on_worker_finished()

    def _on_worker_update(self, message: str):
        if "DNS" in message and "подмен" in message:
            self._append(message)
            self._append("💡 Совет: откройте вкладку «DNS подмена» для детального анализа")
        else:
            self._append(message)

        scrollbar = self.result_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_worker_finished(self):
        self.is_testing = False
        self.worker = None
        self.worker_thread = None
        self.stop_check_timer = None

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.test_combo.setEnabled(True)
        self.send_log_btn.setEnabled(True)
        if _HAS_FLUENT_WIDGETS:
            self.progress_bar.stop()
        self.progress_bar.setVisible(False)

        self.status_badge.set_status("Тест завершён", "success")
        self.progress_badge.set_status("Готово к отправке лога", "muted")
        self._set_status("✅ Тестирование завершено", "success")
        self._append("\n" + "=" * 50)
        self._append("🎉 Тестирование завершено! Лог готов к отправке.")

    # ──────────────────────────────────────────────────────────────
    # DNS и лог
    # ──────────────────────────────────────────────────────────────
    def send_log_to_telegram(self):
        if self.is_sending_log:
            self._append("ℹ️ Лог уже отправляется...")
            return

        temp_log_path = os.path.join(LOGS_FOLDER, "connection_test_temp.log")
        if not os.path.exists(temp_log_path):
            self._append("❌ Лог не найден. Сначала выполните тестирование.")
            self._set_status("Лог не найден", "error")
            return

        try:
            from tgram.tg_log_bot import get_bot_connection_info
            bot_connected, bot_error, _bot_kind = get_bot_connection_info()
            error_msg = None if bot_connected else (bot_error or "Не удалось подключиться к панели поддержки")
        except Exception as exc:  # pragma: no cover - сеть/бот
            bot_connected = False
            error_msg = str(exc)

        if not bot_connected:
            self._append(f"⚠️ {error_msg}. Сохраните лог вручную.")
            self.save_log_locally()
            return

        test_type = self.test_combo.currentText()
        caption = (
            f"📊 <b>Лог тестирования соединений</b>\n"
            f"Тип: {test_type}\n"
            f"Zapret2 v{APP_VERSION}\n"
            f"ID: <code>{get_client_id()}</code>\n"
            f"Host: {platform.node()}\n"
            f"Time: {time.strftime('%d.%m.%Y %H:%M:%S')}"
        )

        # 1) Запрашиваем одноразовый код для отправки (без хранения токена)
        try:
            from tgram.tg_log_bot import request_upload_code

            ok, code, bot_username, bot_link = request_upload_code()
            if not ok or not code:
                raise RuntimeError("Не удалось получить код авторизации")
        except Exception as exc:
            self._append(f"❌ Не удалось запросить код авторизации: {exc}")
            self.save_log_locally()
            return

        bot_line = f"@{bot_username}" if bot_username else "бот поддержки"
        self._append("🔐 Для отправки лога нужно подтвердить код в Telegram:")
        self._append(f"1) Откройте {bot_line}")
        self._append(f"2) Отправьте ему код: {code}")
        self._append(f"Ссылка: {bot_link}")

        self.send_log_btn.setEnabled(False)
        self.is_sending_log = True
        self.progress_bar.setVisible(True)
        if _HAS_FLUENT_WIDGETS:
            self.progress_bar.start()
        self._set_status("🔐 Ожидание подтверждения кода...", "info")

        # 2) Ждём подтверждения кода, затем отправляем файл
        self._auth_thread = QThread(self)
        self._auth_worker = SupportAuthWorker(code)
        self._auth_worker.moveToThread(self._auth_thread)
        self._auth_thread.started.connect(self._auth_worker.run)

        def _on_auth_done(auth_ok: bool, err: str):
            try:
                self._auth_worker.deleteLater()
            except Exception:
                pass

            if not auth_ok:
                self._on_log_sent(False, err or "Код не подтверждён")
                return

            self._set_status("📤 Отправка лога...", "info")

            self.log_send_thread = QThread(self)
            self.log_send_worker = LogSendWorker(temp_log_path, caption, auth_code=code)
            self.log_send_worker.moveToThread(self.log_send_thread)
            self.log_send_thread.started.connect(self.log_send_worker.run)
            self.log_send_worker.finished.connect(self._on_log_sent)
            self.log_send_worker.finished.connect(self.log_send_thread.quit)
            self.log_send_worker.finished.connect(self.log_send_worker.deleteLater)
            self.log_send_thread.finished.connect(self.log_send_thread.deleteLater)
            self.log_send_thread.start()

        self._auth_worker.finished.connect(_on_auth_done)
        self._auth_worker.finished.connect(self._auth_thread.quit)
        self._auth_worker.finished.connect(self._auth_worker.deleteLater)
        self._auth_thread.finished.connect(self._auth_thread.deleteLater)
        self._auth_thread.start()

    def _on_log_sent(self, success: bool, message: str):
        if _HAS_FLUENT_WIDGETS:
            self.progress_bar.stop()
        self.progress_bar.setVisible(False)
        self.is_sending_log = False
        self.send_log_btn.setEnabled(True)
        self.log_send_worker = None
        self.log_send_thread = None

        if success:
            self._set_status("✅ Лог отправлен", "success")
            self._append("✅ Лог успешно отправлен в поддержку.")
            try:
                temp_log_path = os.path.join(LOGS_FOLDER, "connection_test_temp.log")
                if os.path.exists(temp_log_path):
                    os.remove(temp_log_path)
            except Exception:
                pass
        else:
            self._set_status("❌ Ошибка отправки", "error")
            self._append(f"❌ Ошибка отправки: {message}")
            self._append("💡 Сохраняем лог локально.")
            self.save_log_locally()

    def save_log_locally(self):
        temp_log_path = os.path.join(LOGS_FOLDER, "connection_test_temp.log")
        if not os.path.exists(temp_log_path):
            self._append("❌ Файл лога не найден.")
            return

        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            save_path = os.path.join(LOGS_FOLDER, f"connection_test_{timestamp}.log")
            with open(temp_log_path, "r", encoding="utf-8-sig") as src, open(
                save_path, "w", encoding="utf-8-sig"
            ) as dest:
                dest.write(src.read())
            self._append(f"💾 Лог сохранён: {save_path}")
            os.startfile(save_path) if platform.system().lower() == "windows" else None
        except Exception as exc:
            self._append(f"❌ Не удалось сохранить лог: {exc}")

    # ──────────────────────────────────────────────────────────────
    # Вспомогательное
    # ──────────────────────────────────────────────────────────────
    def _append(self, text: str):
        self.result_text.append(text)

    def _set_status(self, text: str, status: str = "muted"):
        self.status_label.setText(text)
        self.status_badge.set_status(text, status)

    def _refresh_test_combo_items(self) -> None:
        current = self.test_combo.currentIndex() if hasattr(self, "test_combo") else 0
        items = [
            tr_catalog("page.connection.test.all", language=self._ui_language, default="🌐 Все тесты (Discord + YouTube)"),
            tr_catalog("page.connection.test.discord_only", language=self._ui_language, default="🎮 Только Discord"),
            tr_catalog("page.connection.test.youtube_only", language=self._ui_language, default="🎬 Только YouTube"),
        ]
        self.test_combo.clear()
        self.test_combo.addItems(items)
        self.test_combo.setCurrentIndex(max(0, min(current, len(items) - 1)))

    def set_ui_language(self, language: str) -> None:
        super().set_ui_language(language)

        self.hero_title.setText(tr_catalog("page.connection.hero.title", language=self._ui_language, default="Диагностика сетевых соединений"))
        self.hero_subtitle.setText(
            tr_catalog(
                "page.connection.hero.subtitle",
                language=self._ui_language,
                default="Проверьте доступность Discord и YouTube, найдите подмену DNS и быстро отправьте лог в поддержку.",
            )
        )
        self.test_select_label.setText(tr_catalog("page.connection.test.select", language=self._ui_language, default="Выбор теста:"))
        self._refresh_test_combo_items()

        self.start_btn.setText(tr_catalog("page.connection.button.start", language=self._ui_language, default="Запустить тест"))
        self.stop_btn.setText(tr_catalog("page.connection.button.stop", language=self._ui_language, default="Стоп"))
        self.send_log_btn.setText(tr_catalog("page.connection.button.send_log", language=self._ui_language, default="Отправить лог"))
    
    def cleanup(self):
        """Очистка потоков при закрытии"""
        from log import log
        try:
            if self.worker_thread and self.worker_thread.isRunning():
                log("Останавливаем connection test worker...", "DEBUG")
                if self.worker:
                    self.worker.stop_gracefully()
                self.worker_thread.quit()
                if not self.worker_thread.wait(2000):
                    log("⚠ Connection test worker не завершился, принудительно завершаем", "WARNING")
                    try:
                        self.worker_thread.terminate()
                        self.worker_thread.wait(500)
                    except:
                        pass
            
            if self.log_send_thread and self.log_send_thread.isRunning():
                log("Останавливаем log send worker...", "DEBUG")
                self.log_send_thread.quit()
                if not self.log_send_thread.wait(2000):
                    log("⚠ Log send worker не завершился, принудительно завершаем", "WARNING")
                    try:
                        self.log_send_thread.terminate()
                        self.log_send_thread.wait(500)
                    except:
                        pass
        except Exception as e:
            log(f"Ошибка при очистке connection_page: {e}", "DEBUG")
